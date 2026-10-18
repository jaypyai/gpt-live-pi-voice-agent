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

*Update, day two afternoon:* the lane gained a push transport (§14). The
reply is also published to a per-caller channel on the bus, the in-call
agent subscribes for the length of the call, and the message is woven in
through this same consumption path, same dedupe, same consume-before-speak
rule, so a reply arriving by both file and bus is spoken once. The file
remains the journal and the fallback when the bus is down. Loop time on
the push path: a few seconds end to end. And because the lane's messages
are spoken as facts, the channel itself is signed (§15).

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

## 11. Verify before you announce

A finished worker is a claimant, not a witness. Before any lane speaks a
result, re-check it against the ground truth it claims about: the result
file exists and is non-empty, the wrapper's exit code is really 0, and
every artifact the result names is present on disk. Stamp the verdict
into the job's record, first writer wins, so every lane grades from the
same page. When verification fails, the announcement doesn't die, it
changes tense: "it finished, but I could not verify X" is a sentence an
agent is allowed to say. "X is done," unverified, is not.

## 12. Revisions, not edits

Give every unit of delegated work an operation ID and a revision number.
A changed request spawns revision N+1 and retires the old worker with a
flag it polls for; the old revision is marked superseded and becomes
invisible to every reporting path. Late results for outdated requests
are then discarded by construction, not by vigilance. The same move
handles blocked work: a job parked in `input_required` is never edited
when the answer arrives; it is superseded by a revision whose brief
carries the answer. The record ends up showing what was asked, in what
order, what was replaced, and what was thrown away, which is exactly
what you need the first time an agent and its owner disagree about what
happened.

## 13. Four-part briefs

Every delegated task gets a brief in four parts: OBJECTIVE, OUTPUT
FORMAT, TOOLS AND SOURCES, BOUNDARIES. Underspecified briefs are the
largest single failure class in multi-agent systems, ahead of model
capability, and the fix is embarrassingly cheap: a template. Boundaries
does the most work of the four. It is where "don't guess, park a
question" and "write only inside this folder" live, in writing, where
the worker can be graded against them later.

## 14. Doorbell, not mailbox

Polls made the sibling round trip 25 to 60 seconds, and most of that was
interval, not work. The fix was a small message bus (we run NATS on the
voice agent's machine; the sibling's host accepts no inbound connections,
so every sibling connection is initiated from its side). But the bus
carries almost nothing:

- An event's payload is a *name*: this file exists, this job finished.
- The content of record stays in the file journal (§2, §3), and consumers
  read and verify it exactly as they did when they were polling.
- Replies cross the bus too, but they are woven in through the same
  dedupe and consume-before-speak path as the file lane.

Latency collapses (delegate filed to watcher awake in about two
seconds) while the audit story is untouched, because nothing the bus
says is believed on its own. When the bus or its bridge dies, the
watchers fall back to polling the journal on their own; when it returns,
push resumes. Test both directions of that degradation before you need
them. One deliberate exception: a lane whose timing is governed by a
semantic rule (our job reporter's announcement grace period) does not
get faster just because the transport did. The grace is the floor, not
the poll.

## 15. Sign the channel your agent treats as fact

The reply lane (§3) injects the sibling's sentences into the live call
as ground truth, an `append_thinking` fact the voice model is told to
believe. That makes the lane part of the trusted computing base, and it
should be built like it:

- Least-privilege credentials per role on the transport: each side can
  publish only its own subjects and subscribe only to the other's. One
  shared all-powerful token is how a doorbell becomes a master key.
- An HMAC over every payload, keyed by a secret kept *separate* from
  the transport credential, held only by the producer and the consumer.
- Verification before injection. Unsigned or badly signed messages are
  dropped and logged, never woven in, never spoken.
- Publishers fail closed: no key, no send, with an error the caller
  sees.

Know the limit and write it down: signing defeats a leaked transport
credential, not an attacker who already owns the publisher's machine,
since the key lives there too. Access control decides who may knock.
The signature decides whether the voice at the door is really your
sibling's.
