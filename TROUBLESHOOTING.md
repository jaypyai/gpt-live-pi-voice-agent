# Troubleshooting

Every entry here cost real time. Format: **symptom → what it actually was →
fix**.

## SDK / imports

**`GPTLiveModel` can't be imported; the realtime module doesn't have it.**
You installed the 2.0 beta line of `livekit-agents`. GPT-Live lives in the
stable pair `livekit-agents==1.8.8` + `livekit-plugins-openai==1.8.8`,
import path `livekit.plugins.openai.realtime`. Pin both, together.

**Crash in `session.start` around room options.**
Version/shape mismatch in how duplex session options are passed on the
stable line. Keep the session construction minimal, pass room options the
way the 1.8.x examples do, and upgrade the pair in lockstep only.

**`RoomAgentDispatch` import fails from `livekit.room`.**
It lives in `livekit.protocol.agent_dispatch`. (You need it for explicit
dispatch in the outbound dialer.)

## Telephony

**Inbound calls connect but the agent greets nobody / wrong mode.**
The gate read room participants at connect time and raced the join. Put
the caller number in the **room name** via the dispatch rule
(`call-_<caller>_<random>`) and parse it from there. For outbound, the
callee number plays the same role.

**Outbound calls fail: `403 Account is disabled … D17`.**
Trial trunk account with no billing. Add a payment method/balance; then
*wait*, release lags minutes behind the balance appearing. Retrying
instantly just collects more 403s.

**Outbound call "answered" in seconds but nobody's there.**
Voicemail answers count as answered (and phones with silence-unknown-
callers send new numbers straight there). Your agent should handle a
greeting gracefully, ours improvised a proper voicemail message, which
was honestly fine, but your *telemetry* must never read `ANSWERED` as "a
human is talking." Verify with participants/transcript, not the dialer.

**Audio pops and clicks on outbound only; inbound is clean.**
Codec negotiation. The far end kept answering **G.722** (offered first by
the cloud side) regardless of the trunk's codec checkboxes, and G.722's
8 kHz RTP clock through a PSTN transcode pops. Fix on the *invitation*:
have the dialer send `SIPMediaConfig(only_listed_codecs=True,
codecs=[PCMU, PCMA])` so only G.711 is offered. Narrowband, but clean.
Things that did **not** fix it: pinning codecs in the trunk portal,
anchor-site selection, jitter buffer toggles, comfort noise.

**Wideband experiments fail: AMR-WB gets `488 Not Acceptable`.**
The provider's PSTN egress speaks G.711/G.722/G.729 only. Enabling the
codec on the connection doesn't create an egress path. Dead end; G.711 is
the production answer.

## The voice model

**First reply never starts; log says "the model did not start speaking
when asked"; transcript is empty.**
Transient GPT-Live stall. Redial; it's not your config. If it recurs at
the same instruction revision, shorten the opening generation request.

**The agent introduces itself by the voice's name.**
Your scripted opening mentioned the voice ("it is still Marin") and the
model adopted it as its name. Two fixes: reasons-not-scripts for openings,
and a standing identity guard: its name is always its own; voice names are
outfits, never names.

**The agent confirms things that haven't happened / invents the sibling's
replies.**
The central boss fight. See PATTERNS §4 (truth anchor). Prompt-only fixes
("never invent") decay within a day of calls. The mechanical filing +
banned vocabulary + `append_thinking` ground-truth injections are what
held.

**The agent misses "tell her …" requests (pronouns).**
Trigger lists written for exact phrases ("tell <Name>", "ask <Name>") miss
natural speech entirely, and the model then *pretends* it filed the
message. Widen triggers to include pronoun forms ("tell her", "let her
know", "send her"), and treat any "pass this along" intent as a delegate
regardless of wording.

**A name is pronounced wrong.**
Voice layers read names phonetically. Respell in voice-facing text, pick a
different voice, or, as happened here organically, rename the persona in
the voice layer to something the voice says correctly.

**Brain answers take 30 s+ and callers sit in silence.**
Any tools-path call through an agent CLI is slow. Fillers at delegation
time + still-checking fillers at 12/12/24/48 s. Also: precompute the digest
(GUIDE §3.3) so the common questions never delegate at all.

## The brain

**The brain "remembers" things its files don't say.**
Its built-in memory is on. Turn off both the memory store and the
user-profile feature in its profile, and verify empirically, send a probe
in one invocation and check a later, separate one.

**Brain-built files land in the wrong directory.**
The CLI's working directory pulls output toward the process cwd. Set the
subprocess `cwd` to the agent's home *and* name the absolute workshop path
in its instructions. One of the two alone wasn't enough.

**`hermes -z` eats the prompt / argparse errors.**
Argument order matters: the one-shot flag must come *after* the toolset
flag (`hermes -t <toolsets> -z <prompt>`), or the prompt is consumed as a
toolset value.

**Per-profile invocations leak into the default profile.**
Pin the profile per invocation via the profile env var, never by switching
the CLI's sticky default, especially on a machine that hosts other
agents.

## Pi / browser automations (for the sibling's other arms)

**Chromium "loads forever"; every tab wedged; looks like DNS failure.**
The login-keyring modal on an autologin desktop freezes the *entire*
browser. Unlock/dismiss once, or set `--password-store=basic` in a
user-level desktop override and fully quit Chromium before relaunching.

**Playwright sends fail with `Page.content: Target crashed`.**
The paired-browser profile/session is wedged (in our case, after the
keyring saga). Check for zombie Chromium processes and profile locks,
restart the desktop browser cleanly, and re-verify pairing before assuming
the account is broken. Witness `SENT_OK` (or your equivalent) before
reporting any message as sent, workers *will* claim sends that never
happened.

**Killing browser processes kills your own SSH session.**
`pkill -f` with a literal pattern matches your remote shell's command
line. Match precise binary paths and exclude ancestor PIDs.

## Queues / watchers

**A handled delegate gets processed again.**
A watcher rewrote the seen-watermark from state read at run start,
clobbering a concurrent append. Watermarks should be merged (read fresh,
append, write) as late as possible, or accept idempotence: make handling
check for the created artifact ("does the reminder already exist?") before
creating it again.

**Confirmation arrives but there's no call to speak it in.**
Live replies are written for a call that already ended. Harmless by
design: files older than an hour retire at the next call start. Don't
"fix" this by widening the mtime window, stale news spoken as fresh is
worse than silence.

**The logs don't show the fact you injected.**
Our anchor log line truncated the injected text at 80 chars, cutting off
the very phrase we grepped for. We "proved" a fix missing that was
actually working. Verify behavior from **transcripts**, and make log lines
carry the whole payload hash or a short marker instead of a truncated
prefix.

## Money

**"Free" tier surprise.**
The telephony cloud's free plan caps *agent minutes* (1,000/mo) while the
voice model bills per *second of open session*. The two meters are
different; either can bind first. Set the local ledger cap to whichever is
lower (ours: 60,000 s ≈ 1,000 min ≈ $50) and the platform spend limit as
the hard wall behind it.

**API key expiry sneaks up.**
Keys with expiries power production voice paths. Put the expiry date in
your runbook and calendar when you create the key, not when it dies.
