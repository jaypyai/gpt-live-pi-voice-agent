# Patterns

The transferable ideas from this build, in descending order of how much
they'd hurt to learn the hard way.

## 1. Rent the voice, own the mind

GPT-Live's client delegation is the architectural center: the voice model
handles turn-taking, interruption, and speech, and hands substantive turns
to your backend as *delegations* (`{id, pending_transcript}`). You answer
with `append_commentary(text, delegation_id=...)` (≤500 tokens per append;
chunk long answers) and can inject silent knowledge with `append_thinking`.

Why it matters: the expensive, metered component (the voice session) stays
dumb and replaceable, while everything that makes the agent *yours*, model
choice, memory, tools, persona, lives in a backend you control, on your
hardware, at subscription (not per-token) prices.

Corollary: because a backend answer takes seconds, **teach the voice to
stall like a human**: a rotating set of short checking phrases at delegation
time, plus scheduled still-checking phrases while it waits. Silence is the
only unforgivable latency.

## 2. The delegate queue (files as an inter-agent API)

Two agents that need to coordinate under latency and trust constraints
don't need a message bus. They need a folder.

- Producer drops `<timestamp>-<source>.md` files, atomically enough, the
  moment an event happens.
- A watcher on a short interval (1 minute) syncs, diffs against a
  `seen.txt` watermark, acts, and appends.
- Every note is attributed (who said it, through whom, when) and carries the
  *request verbatim* plus what the agent answered.

Failure modes we actually hit: a watcher run rewriting the watermark from a
stale in-memory copy and clobbering a manual append (the file got processed
twice); and a worker "completing" a run whose side effects (a reminder) had
been created by a *concurrent* run, dedupe by checking for the artifact,
not by trusting the queue state.

## 3. The live reply lane

Delegates are one-way and asynchronous, useless mid-call, when the human
is *right there* asking "did she reply yet?" The lane closes the loop:

- The watcher, after handling an item, writes one plain sentence to a
  replies folder on the agent's machine, filename ending in the caller's
  digits.
- The in-call agent polls every 5 s; a file is live if its suffix matches
  the current peer and its mtime is after the call started.
- It is consumed (moved to `done/`) *before* being spoken, so it can never
  be spoken twice, and injected as a generation request that lets the voice
  phrase it naturally.

Real-world loop time, delegate filed → confirmation spoken: under a minute.

## 4. The truth anchor (anti-confabulation)

The failure: a voice agent with a warm personality will *invent* the other
agent's replies ("She says thanks, and it all looks good!") and announce
errands as completed the instant they're filed. It is not lying; it is
completing a pattern. You cannot prompt your way out of it with "don't make
things up", we tried; it helps for a day.

The fix that held has four parts (Guide §8): file mechanically before
answering; ban completion vocabulary in the agent's own voice; inject a
**silent ground-truth fact** into the session at the exact moment of filing
and again when a real reply arrives (`append_thinking` is perfect for
this, the model *knows* without being told to say it); and audit the
day's transcripts nightly for unsupported claims, naming the moment back
to the agent in its nightly letter.

Behavioral proof after the fix, on a test call: "I've passed it along,
it's on its way." … "That part's filed with her." … (unprompted) "Did she
say anything back yet, or should we give it a minute?" Then, when the real
reply landed, it was delivered as an aside and, when pressed, repeated
*verbatim in substance* with zero embellishment.

## 5. Call cards, not transcripts

Raw transcripts are evidence; they are terrible memory (long, noisy, full
of STT errors). After every call, run one extractive pass, facts only,
nothing invented, 2–4 lines, and append it, dated, to a memory book. The
next call's digest reads the *cards*. The agent's continuity becomes
curated by construction, and because each card names its date, the agent
can say "last Tuesday you told me…" and be right.

Each caller tier gets its own book. The restricted tier's card-writer is
instructed to record the caller's side only, topics, practice, their own
requests, and nothing about the owner, even if the owner was mentioned.

## 6. Memory books beat brain memory

Agent frameworks ship built-in memory (curated notes injected into the
prompt, session search). We evaluated it against the file book and kept it
**off**, for one reason: auditability. Every failure in this project was
diagnosed because the agent's entire world, soul, brief, cards, letters,
was plain files one `grep` could search. A second, opaque memory inside
the brain would have made the agent's beliefs uninspectable, and in a
one-shot-per-turn brain it only reaches half the agent anyway. If it isn't
written in the book, the agent is instructed to say it doesn't know, and
mostly, it does.

## 7. Digests: precompute the first minute

A voice agent that delegates everything starts every call ignorant and
slow. Composing a small digest at job start (standing facts, today's
memory tail, the newest letter; ~1.5 KB) and appending it to the voice
instructions makes the agent open warm and informed, reserving delegation
for genuinely new questions. Per-caller digests, obviously: the restricted
tier's digest is built only from that caller's own page and cards.

## 8. Tiers by construction

Don't build one agent with secrets and rules. Build:

- a gate that runs before any model session,
- per-tier instruction sets,
- per-tier backends (the restricted tier literally has no code path that
  loads the owner's context),
- per-tier memory books,
- and drops for everyone else, pre-session, at zero model cost.

Caller ID is spoofable, so this is a good lock, not a vault, a DTMF PIN is
the known hardening we haven't needed yet. Say so in your own docs, the way
we're saying it here.

## 9. Reasons, not scripts, for outbound openings

Passing the dialer a full opening script made the agent parrot it,
including, once, introducing itself by its *voice's* name ("Hi, I'm
Marin") because the script mentioned the voice. Passing a *reason* ("this
is a first introduction; tell her what you can do for her; invite her to
practice a word") produces a natural opening in the agent's own words, in
character, every time. Guard the identity separately, in standing
instructions: "Your name is always X. Voice names are outfits you wear,
never your name."

## 10. Two caps or none

A budget enforced in one place is a budget that fails in one place. We run
a local ledger in the agent (monthly seconds cap ≈ the free telephony
tier's minute ceiling ≈ $50) *and* the provider platform's spend limit
with alerting at 80% and hard-stop enforcement on. The agent's ledger gives
grace (a kind line and a short call when spent); the platform limit gives
certainty.
