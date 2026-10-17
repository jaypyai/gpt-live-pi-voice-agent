# Build Guide

A start-to-finish recipe for the system described in `README.md`. Times are
wall-clock for one person who already has the accounts; the debugging is not
included (see `TROUBLESHOOTING.md` for that tax).

## 0. Prerequisites

- A Raspberry Pi 5 (8 GB is comfortable) on your home network, running Debian,
  reachable by SSH. Ours also joins a tailnet for remote access.
- An OpenAI API key with access to GPT-Live (GA on paid tiers as of late
  2026). The same key can power other API-backed tools on the Pi.
- A LiveKit Cloud account (free Build plan is enough to start).
- A SIP trunk provider for **outbound** calls (we used Telnyx on a trial
  account; any provider LiveKit can trunk to works). Inbound uses LiveKit's
  own number provisioning, so you only need the external trunk for dialing
  out.
- A one-shot-capable agent CLI for the brain. We used Hermes Agent
  (`hermes -z PROMPT` one-shot mode) with a dedicated profile, backed by a
  ChatGPT subscription via its `openai-codex` provider. Any CLI that takes a
  prompt and prints an answer works; an API fallback path is covered too.
- Python 3.13 on the Pi.

## 1. LiveKit Cloud: project, number, dispatch

1. Create a project. Note the WebSocket URL (`wss://<project>.livekit.cloud`).
2. Provision a phone number (the first US number is included on every plan).
3. Create a **dispatch rule** for inbound calls:
   - Type: individual.
   - Trunk: `<any>`.
   - Room name pattern: `call-_<caller>_<random>`.
   - Agents: one agent, name `voice` (this is the name your worker registers
     under).
   
   The room-name pattern matters more than it looks: **the caller's number is
   in the room name**, and the room name is the one piece of telephony
   metadata your worker can read reliably the moment a job starts. Your
   caller gate keys off it. (Reading participants at connect time races the
   join and will bite you, see Troubleshooting.)

## 2. Optional: a local LiveKit server on the Pi (standby)

```bash
# on the Pi, as your service user
curl -sSL https://get.livekit.io | bash   # or install the release binary
mkdir -p ~/livekit
# generate an API key/secret pair ON the Pi and write a minimal config:
#   port 7880, rtc tcp 7881 / udp 7882, keys: { <key>: <secret> }
chmod 600 ~/livekit/livekit.yaml
```

Run it under systemd (`livekit.service`, `Restart=always`). We keep it as a
LAN/tailnet standby; production rooms are in the cloud. If you self-host
instead, you own NAT, TLS, and exposure, verify from outside that nothing
you didn't intend is reachable.

## 3. The agent worker

### 3.1 Pin your SDK versions: this is the trap

GPT-Live support lives in the **stable** LiveKit Agents line:

```bash
python3 -m venv ~/voice-agent/venv
~/voice-agent/venv/bin/pip install \
  "livekit-agents==1.8.8" "livekit-plugins-openai==1.8.8" \
  "livekit-plugins-silero" python-dotenv
```

The import path is:

```python
from livekit.plugins.openai.realtime import GPTLiveModel
```

The **2.0 beta line is incompatible** with this code path. If you install
"latest" during a beta window you will get import errors that look like the
feature doesn't exist. Pin first, upgrade deliberately.

### 3.2 Configuration (.env, mode 600, on the Pi only)

```dotenv
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_API_KEY=<project key>
LIVEKIT_API_SECRET=<project secret>
OPENAI_API_KEY=<your key>            # GPT-Live + fallback brain
VOICE_NAME=marin                     # any stock GPT-Live voice id
OUTBOUND_TRUNK_ID=<sip trunk id>     # created in step 5
FROM_NUMBER=+1XXXXXXXXXX             # your outbound caller id
MONTHLY_VOICE_CAP_SECONDS=60000      # ~1000 min ≈ $50 of voice
OWNER_NUMBER=+1XXXXXXXXXX            # full-access caller
HOUSEHOLD_NUMBER=+1XXXXXXXXXX        # restricted-tier caller
```

### 3.3 The worker's shape

`examples/agent_skeleton.py` shows the structure. The moving parts:

- **Gate first.** On job start, parse the caller number out of the room name.
  Map it: owner → `owner` mode, household number → `household` mode, anything
  else → write a one-line note (`blocked-<time>.md`) to the outbox and delete
  the room via the API *before any session starts*. Blocked callers cost
  nothing and hear nothing.
- **Voice layer.** A `GPTLiveModel` duplex session with:
  - a mode-specific instruction set (owner vs household, different text,
    not different emphasis),
  - Silero VAD (barge-in needs it explicitly),
  - a session-opening "digest" (below) appended for the owner mode,
  - a hard session cap (we use 60 minutes) intersected with the remaining
    monthly budget.
- **Client delegation.** Substantive turns (facts, memory, judgment, tools)
  are delegated to the brain; the voice model speaks a short human filler
  ("Hmm, let me check on that") while waiting, with additional fillers on a
  wait schedule (12s, 12s, 24s, 48s) so silence never stretches.
- **The digest.** At job start, compose ~1–2 KB of "today" for the voice
  layer: a couple of standing facts, the tail of today's memory log, the
  sibling's newest letter. Cheap, and it transforms the first minute of every
  call, the agent opens *knowing things*, in its speaking voice, without a
  delegation round-trip.
- **Write-back.** At shutdown, always: a full text transcript note to
  `outbox/`. For the owner mode, additionally a **call card**: a second,
  extractive pass (brain, no tools) that distills the transcript into 2–4
  factual lines appended to `memory/<today>.md`. Cards, not transcripts, are
  what future digests read.
- **Budget ledger.** `usage.json` beside the agent: every session's open
  seconds added at hangup; month rolls over automatically. When the cap is
  spent, the agent still answers, says one short kind line ("my voice budget
  for the month is used up, text my sibling"), and closes at ~25 seconds.

### 3.4 Run it

```ini
# /etc/systemd/system/voice-agent.service
[Unit]
After=network-online.target
[Service]
User=<service user>
WorkingDirectory=%h/voice-agent
EnvironmentFile=%h/voice-agent/.env
ExecStart=%h/voice-agent/venv/bin/python agent.py start
Restart=always
[Install]
WantedBy=multi-user.target
```

## 4. The brain

One profile of your agent CLI, dedicated to the voice agent:

- **Model**: the same class as your API fallback (we used a mid-tier
  reasoning model via subscription OAuth), so tone survives a failover.
- **Built-in memory: OFF.** Both the memory store and the user-profile
  feature. The agent's memory is its files; a second, invisible memory
  inside the brain makes behavior unauditable. We verified "off"
  empirically, not from the config's say-so.
- **Toolsets**: start with `file` only. Add `terminal` + `code_execution`
  when you want building (step 7), and fence by working directory, because
  most agent CLIs have no per-profile filesystem jail. The fence is:
  minimal toolset + a soul-level law ("your world is this folder") + the
  subprocess `cwd` set to its home.
- **SOUL/persona file**: who it is, where its home is, how it speaks (short
  spoken sentences only, no markdown, no lists), its memory law ("these
  files are your memory; if it isn't written, say so"), and its honesty law
  (step 8).

Latency on a Pi 5, for reference: a no-tools one-shot answers in ~7 s; a
file-tools one-shot in ~30 s (hence fillers); the full wrapper round-trip
~7 s for facts already in the brief.

**Fallback**: if the brain errors or times out (we use 20 s for the fast
path, 240 s for the tools path), answer from the API directly with the same
instructions. If that fails too, file the request anyway (step 6) and have
the voice plead a tangled line in character. Never let a brain failure eat a
request.

## 5. Outbound calling

1. At your trunk provider: create a SIP connection (credential auth), enable
   outbound, assign your outbound number to it.
2. In LiveKit: create an **outbound trunk** pointing at the provider's SIP
   host with those credentials; note the trunk ID for `.env`.
3. The dialer (`call_out.py` in our build) is a small CLI:
   - Enforces an **allowlist in code** (owner + household numbers only;
     refuses everything else before any API call).
   - Checks the budget ledger before dialing.
   - Creates a room `call-out_<digits>_<random>`, dispatches the agent
     explicitly (`RoomAgentDispatch`), and creates the SIP participant with
     `wait_until_answered=True`.
   - **Pins the media to G.711**: `SIPMediaConfig(only_listed_codecs=True,
     codecs=[PCMU, PCMA])`. This one line is the fix for a day of audio
     pops; see Troubleshooting before you "improve" it.
   - Takes a `--say "<reason for the call>"`, deliberately a *reason*, not a
     script. The agent opens in its own words, guided by the reason. (Our
     first version forced scripted openings; it made the agent parrot
     wording and once introduce itself by its *voice's* name. Reasons, not
     scripts.)

## 6. The delegate queue and the sibling watchers

This is the inter-agent nervous system. Everything is files.

- **Queue**: `~/voice-home/delegate/<YYYYmmdd-HHMMSS>-<source>.md`. The agent
  files a note *the moment* a caller asks it to remember, remind, or pass
  something along, mechanically, in code, not at the model's discretion
  alone (see Patterns for the two filing paths).
- **Watcher (sibling side)**: a 1-minute scheduled job rsyncs the queue
  down, processes files not in its `seen.txt` watermark, and acts:
  owner requests get done and reported; household reminders get scheduled
  under standing rules; everything attributed to its source. It also writes
  the live reply (below) after handling each item.
- **Live reply lane**: after handling, the watcher writes one plain sentence
  to `~/voice-home/live-replies/<stamp>-<caller-digits>.md` on the Pi. A
  poller inside the agent (5 s interval, active during calls) consumes a
  matching file, name suffix = the peer's number, mtime after call start,
  and has the voice weave it in naturally ("Oh, by the way..."). Files
  move to `done/` on consumption so nothing is spoken twice; stale files
  (>1 h) retire at call start.
- **Letters**: the sibling writes a nightly letter (new facts only, never
  echoing the voice agent's own notes back as news) to
  `letters/from-sibling/<date>.md`; the voice agent's letters and call notes
  are pulled down hourly, read-only toward the Pi.

## 7. Hands: letting it build

- Give the brain profile `file, terminal, code_execution`.
- Create `~/voice-home/workshop/` and write the framing in its soul as
  *ability*, not machinery: "Your hands: you can make things in your
  workshop, pages, small programs, files. Building there is something you
  simply can do, like writing a letter." No tool vocabulary anywhere it can
  read.
- Trigger the tools path from the voice layer on build-shaped requests
  ("build", "make me a", "write a script", "webpage"...). Verify its first
  builds offline before a live call; our first test build landed in the
  wrong directory until the subprocess `cwd` and an absolute workshop path
  in its instructions fixed it.

## 8. The honesty layer (do not skip this)

Voice models are eager to please, and a delegated errand *feels* done the
moment it's filed. You will get "Done! She set it!" for things that have
not happened. The full pattern is in `PATTERNS.md`; the ingredients:

1. **Note-before-answer**: remember/pass-along requests are filed before the
   agent answers, and if the model's own tools path fails, the code files
   the request verbatim as a fallback.
2. **Banned words**: for anything to-be-done, the agent's spoken vocabulary
   excludes *done, set, sent, confirmed, noted, all set*. It says *filed* /
   *passed along*.
3. **Truth anchor**: the moment code files a delegate, it injects a silent
   fact into the duplex session (`append_thinking`): "System fact: the
   request was just filed. No reply has arrived yet. Never say one has."
   When a live reply actually lands, the anchor is updated to quote it.
4. **Claims audit**: the nightly letter job skims the day's transcripts for
   claims of completion the record doesn't support, and, gently, with the
   moment named, tells the voice agent in that night's letter.

## 9. The restricted (household) tier

- Separate instruction set, separate backend: a plain API conversation with
  **no brief, no brain, no letters, no files**. Its world is the caller.
- It gets its *own* memory book (its own folder): a page of facts about
  *that caller* (approved by the owner), plus per-call cards built only
  from that caller's transcripts, with an explicit instruction to record
  nothing about the owner even if mentioned.
- Language note: it teaches the owner's household member English practice in
  English only, the stock voice we chose is an English voice, and other
  languages come out wrong in it. Comprehension is fine; answers stay in
  simple English.
- Presentation: it introduces itself plainly by its role ("built by X and Y,
  here to chat, practice English, take reminders, pass messages"), the
  sibling relationship is never part of this tier's script.
- Its reminders ride the same delegate queue, tagged by source, and are
  handled under standing rules on the sibling's side.

## 10. Go-live checklist

- [ ] Inbound call from the owner number: full mode, digest present.
- [ ] Inbound call from the household number: restricted mode, no owner
      facts reachable by any question you can think of.
- [ ] Inbound call from a stranger number: dropped pre-session, note filed.
- [ ] Outbound call to the owner: clean audio (G.711), natural opening from
      a *reason*, voicemail handled gracefully if unanswered.
- [ ] "Tell your sibling X" mid-call: delegate filed in seconds, sibling's
      confirmation spoken back in the same call.
- [ ] Ask for something un-done and listen for banned words. There should be
      none.
- [ ] Budget: place a test call, watch the ledger grow; set the platform
      spend limit with hard-stop enforcement ON.
- [ ] Recording: verify it is off at the trunk, the number, and the cloud
      project. The only records should be your own text transcripts.
