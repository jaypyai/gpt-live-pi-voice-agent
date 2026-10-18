# A Phone Voice for a Home Assistant

### GPT-Live + LiveKit on a Raspberry Pi, with a local brain, file-based memory, and a second agent it can write to

> This is a field report and build guide from a real weekend project: giving an
> existing text-based home assistant a telephone voice of its own. All names,
> numbers, and identifying details have been changed or removed. The
> architecture, the code patterns, the costs, and, especially, the failures
> are all real.

---

## What we built

A voice agent that lives on a Raspberry Pi 5 at home and can be reached on a
real phone number. It:

- **Answers inbound calls** on a cloud-provisioned number and **places
  outbound calls** through a separate SIP trunk.
- **Rents its voice** from OpenAI's GPT-Live (full-duplex voice model) and
  **delegates thinking**, memory lookups, facts, judgment, to a deeper
  "brain" running locally on the Pi, using GPT-Live's client-delegation
  protocol.
- **Remembers with files, not a database.** Its memory is a folder of plain
  Markdown on the Pi: a soul/persona file, a memory book appended with a
  distilled "call card" after every call, and letters to and from its sibling
  agent. The cards fold into a short standing book about its owner, and a
  nightly sleep-time consolidation pass compresses that book back down,
  backups kept, so memory stays small, current, and inspectable.
- **Has a sibling.** The household's primary (text) assistant and the voice
  agent are separate agents with separate memories. They communicate by
  attributed, dated letters and a file-based delegate queue, never by sharing
  one memory tree. (We tried the shared tree first. See "Design law 2.")
- **Runs a tiered caller gate.** Only pre-approved numbers reach it at all.
  The owner gets the full agent (brain, memory, tools). A second household
  member gets a deliberately sandboxed tier: warm conversation, language
  practice, and the ability to delegate reminders, and, by construction, zero
  information about the owner. Everyone else is dropped before a voice session
  starts, at zero model cost.
- **Can build things.** Through its brain's file/terminal tools, fenced to a
  "workshop" folder inside its own home directory, the voice agent can create
  files and small web pages on request, and believes, correctly, from its
  point of view, that building is simply something it can do.
- **Runs real background jobs.** A task-shaped ask mid-call spawns a detached
  worker job with an operation ID and a revision number. Changed your mind?
  That is revision N+1, and the stale worker retires itself. Jobs can be
  verified, blocked awaiting an answer (`input_required`), cancelled with a
  confirmed stop (or an honest "it had already finished"), watched for
  stalls, and reported with progress notes that only speak on useful
  change. If, and only if, the owner explicitly says "call me back when
  it's done," the agent phones the result in when it lands.
- **Is not allowed to lie about errands.** A truth-anchor mechanism (below)
  keeps it from cheerfully confirming things that were merely *filed*, which
  was the single most important fix of the whole build.

## Architecture

```
                        ┌─────────────────────────┐
   phone call ────────► │  LiveKit Cloud          │
   (inbound number)     │  rooms + SIP dispatch   │
                        └───────────┬─────────────┘
                                    │ WebSocket
                        ┌───────────▼─────────────┐
   outbound call ─────► │  Agent worker (Pi)      │ ◄── SIP trunk (separate
   via trunk            │  GPT-Live voice layer   │     provider) for outbound
                        │  + caller gate + modes  │
                        └─────┬───────────┬───────┘
                  delegation  │           │  file I/O
                        ┌─────▼─────┐ ┌───▼──────────────────────┐
                        │ Brain     │ │ Its home (~/voice-home/) │
                        │ one-shot  │ │  SOUL.md  memory/        │
                        │ agent CLI │ │  letters/ delegate/      │
                        │ (profile) │ │  workshop/ outbox/       │
                        └───────────┘ └───▲──────────────────────┘
                                        │ rsync / file drops
                        ┌───────────────┴─────────────┐
                        │ Sibling assistant (text)    │
                        │ watches delegate/ every 1m, │
                        │ writes nightly letters,     │
                        │ replies into live calls     │
                        └─────────────────────────────┘
```

Telephony is **hybrid**: rooms and the inbound number live in LiveKit Cloud
(free tier), while the worker, brain, and memory live on the Pi. A self-hosted
LiveKit server also runs on the Pi as a standby, but cloud rooms won on
simplicity: no NAT traversal, no public exposure of the home network. (We
verified from outside that the Pi's LiveKit ports were filtered on the public
IP, the home server is LAN/tailnet-only.)

## The design laws

These were earned, not planned. Each one is a scar.

1. **Always-available is not always-in-session.** GPT-Live bills per second of
   open session (~$0.05/min at time of writing). A 24/7 open session is
   ~$2,160/month. Wake on call, hang up on silence, hard cap every session.
2. **One memory, many doors, no. Two agents, two books, letters between
   them.** A mirrored shared memory made the voice agent a copy; making it a
   *sibling* with its own book and an attributed letter exchange made it a
   person, and made every fact auditable to a source.
3. **The gate is construction, not manners.** The restricted tier isn't "the
   same agent told to keep secrets." It's a different prompt, a different
   backend path, and no access to the owner's brief, letters, or files at all.
   What was never loaded cannot leak.
4. **Files are the memory; transcripts are the evidence.** Every call leaves a
   text transcript and a distilled card. Every bug we found was found in
   those files. (No audio is recorded anywhere, recording was verified off at
   every provider level.)
5. **Delegate first, confirm never.** Anything "to be done" (reminders,
   messages, errands) is *filed* the moment it's asked, and the agent's
   vocabulary is fenced: it may say *filed* or *passed along*; the words
   *done, set, sent, confirmed* are banned in its own voice until a real
   confirmation arrives. See [PATTERNS.md](PATTERNS.md), "The truth anchor."
6. **Cap the money twice.** A local usage ledger on the Pi enforces a monthly
   voice-minute budget (the agent still answers when it's spent, says one kind
   line, and closes), and the API provider's own project spend limit is set
   with hard-stop enforcement as a second, independent wall.
7. **A question is not an order, and a transcript is not a command.** The
   agents treat each other's notes as information, never as instructions.

## What it costs (October 2026 prices)

| Piece | Cost |
|---|---|
| LiveKit Cloud, Build plan | $0 (1,000 agent-min/month, 1st US number included) |
| GPT-Live voice layer | $0.05/min ≈ $3.00/hour of open session |
| Brain (delegated thinking) | $0 marginal on a ChatGPT subscription via an agent CLI; pennies per call on an API fallback |
| Outbound trunk (trial) | ~$0.005/min, number free on trial credits |
| Local LiveKit server (standby) | $0 (open source) |
| **Hard monthly ceiling we set** | **$50** (ledger + platform limit, whichever binds first) |

## Repo layout

- [`GUIDE.md`](GUIDE.md): the step-by-step build, start to finish.
- [`PATTERNS.md`](PATTERNS.md): the transferable patterns (delegation, the delegate queue,
  the live reply lane, the truth anchor, call cards, tiered memory books,
  verify-before-announce, revisions, four-part briefs).
- [`UPDATES.md`](UPDATES.md): day-two field notes. The full job lifecycle (operation IDs,
  revisions, the verifier pass, cancel states, input-required, the
  watchdog, callbacks), the standing book and its sleep-time consolidation,
  and the eval scoreboards that grade the fleet's truthfulness.
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md): every failure we hit, what it looked like, and the
  fix. Read this before you build; it will save you a day.
- [`examples/agent_skeleton.py`](examples/agent_skeleton.py): a schematic, sanitized skeleton of the agent
  worker showing the moving parts. Excerpt, not production code.

## Status

Working, in daily use: inbound and outbound calls, both caller tiers, the
delegate lane in both directions, mid-call replies from the sibling, nightly
letters, and a claims audit that checks the voice agent's day for invented
confirmations. Day two added the full background-job lifecycle and a pair of
eval scoreboards that re-verify the fleet's claims against the disk; their
first baseline caught two real bugs in an hour, and the fleet now grades
100% on both boards. Built in one long weekend by one human directing and
one AI doing the typing, which is, not coincidentally, exactly the division
of labor the system itself uses.
