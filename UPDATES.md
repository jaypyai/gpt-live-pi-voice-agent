# Updates: Day Two

### The job lifecycle release: background work the voice agent can talk about truthfully

> Field notes from the second day of the build described in `README.md`.
> The first version answered calls, delegated questions, and filed errands.
> This release gives it real background work: tasks it can start mid-call,
> revise, verify, block on, cancel, and report, without ever claiming
> something the disk doesn't agree with. Same rules as the main guide: all
> names and numbers removed, every failure real.
>
> An afternoon session follows the job release: callbacks for the delegate
> lane, a push bus between the siblings, and the adversarial security
> review that bus had to survive the day it shipped.

---

## A standing book, consolidated in its sleep

Day one, the agent's memory was call cards: one distilled note per call,
read back as recent history. Day two it got a **standing book** about its
owner: one short file (standing facts / open threads / lately), capped at a
few hundred words, loaded into every call's context brief alongside the
most recent cards.

- After each call, the card is queued, and a **detached worker** folds it
  into the book: reads the book plus pending cards, rewrites in place,
  validates the shape (header, the three sections, sane length), then
  swaps atomically under a lock. The call never waits on bookkeeping.
- Nightly, a **sleep-time consolidation** pass runs (03:17 local) that
  compresses the book back down: merges duplicates, drops what's stale,
  keeps what's load-bearing. It is itself spawned through the job
  machinery below as a silent internal job, so no announcement lane ever
  talks about it. The previous book is backed up first (last 14 kept);
  a draft that fails shape validation is never swapped in.
- Two flaws showed up on the first live test call and were fixed the same
  morning: the digest opened without the current time (the agent greeted
  the evening like the morning), and folding inline made calls end slowly.
  Both are the same lesson: precompute everything the first minute needs,
  and never let a call block on its own paperwork.

## A subscription fast path for the brain

The brain's quick-answer lane now tries a **subscription-backed endpoint
first**: the same agent CLI's OAuth credential the household already pays
for, read from its credential store **read-only** (this code never
refreshes or rotates the token; if it fails, it fails). Any error silently
falls back to the pay-per-token API key. Facts and lookups got noticeably
faster; the voice path and the web-search lane stay on API keys, where
their tooling lives. Rule of thumb: spend subscription where it's flat,
spend API where it's metered by capability.

## Voice-started background jobs

"Build me a small web page about X" used to be something the agent could
only fake. Now a task-shaped ask spawns a **detached background job**:

- A spawner creates a job folder (brief, status file, progress file,
  result file) and launches the worker detached, so the call continues.
- The spawner prints a receipt line naming the job. **The agent may only
  claim a job exists when a receipt printed.** Before this rule, the agent
  once announced a background job that did not exist, then honestly
  retracted it when pressed. The receipt made the lie structurally
  impossible instead of merely discouraged.
- Every brief is written in **four parts: OBJECTIVE / OUTPUT FORMAT /
  TOOLS AND SOURCES / BOUNDARIES.** The day we switched, worker output
  quality jumped more than any model change had. (Independent research
  agrees: in multi-agent failure studies, underspecified task briefs are
  the single largest failure class, ahead of model capability.)

## Operation IDs and task revisions

Each job carries an **operation ID** and a **revision number**, an idea
borrowed from the GPT-Live delegation guide and A2A-style task systems:

- A change of mind mid-flight ("no, make it green instead") is detected
  deterministically, by change phrases or by content overlap with a
  running job's name, and spawns **revision N+1** of the same operation.
- The old revision is marked superseded and a flag file lands in its
  folder; its wrapper polls for the flag every few seconds and retires
  the stale worker (a dedicated exit code, so "superseded" is a recorded
  state, not a mystery death).
- Superseded jobs are invisible to every reporting lane: never announced,
  never counted, never phoned in. A late-arriving result for an outdated
  request is discarded by construction.

## The verifier pass

Nothing gets announced on the worker's word anymore. Before either
announcement lane (in-call, or the out-of-call reporter) may speak a
result, a **verifier** re-checks it against the disk:

- the result file exists and its first line, the speakable summary, is
  non-empty;
- a "done" job's wrapper exit code is actually 0;
- every file the result claims to have made, by path, **exists**.

Failure doesn't kill the news; it changes the sentence. The agent says the
job finished but it could not verify the claim, and quotes the claim as a
claim. Verification stamps are written back into the job's status, first
writer wins, so both lanes grade from the same record.

## Cancel is a state machine, not a shrug

Interrupting speech never cancels backend work (true of every delegation
protocol we studied), so cancellation is explicit machinery:

- Strong phrases ("cancel that job") act alone. Weak phrases ("never
  mind", "forget it") act **only** with a job referent in the same
  breath. Small talk cannot kill work.
- A cancel drops a flag the wrapper polls. If the worker stops:
  `cancelled`, with `cancel_confirmed: true`. If the worker already
  finished on its own: state stays `done`, with
  `cancel_requested: true, cancel_confirmed: false,
  finished_before_cancel: true`, and every announcement says so.
- The agent's spoken line at cancel time claims only the *request*
  ("Stopping it now; I'll tell you when the stop is confirmed, or if it
  had already finished"). Confirmation arrives later, from the record.

## Input-required: blocked is a first-class state

Workers hit questions only the owner can answer. Guessing is how you get
a blue poster that should have been green, so the worker contract says:
don't guess, don't write a result. Write the question (one or two plain
sentences) to a dedicated file and stop. The job parks in
**`input_required`** with the question in its status; both lanes announce
it once, question included. The answer resumes the work as a **new
revision** with the answer folded into the brief. The parked job is never
edited; it is superseded, like everything else.

## The watchdog and the progress note

- A watcher flags any running job with **no progress for 30 minutes**,
  exactly once (a stamp in its status prevents repeats), with its age and
  its last progress line. It wakes a human-facing report offering three
  options: leave it, cancel it, inspect it. It takes no action itself.
- In-call, a running job earns a spoken progress note only on **useful
  change**: a genuinely new progress line, spaced out (job old enough,
  enough time since the last note, capped per call). A job with no
  milestones earns exactly one "still working" note, late. Silence about
  progress is its own kind of lie; chatter is worse.

## Callback when done, but only when armed

The owner can say "call me back when it's done," and the agent will: the
job is **armed** in its status, and when the verified result lands, the
reporter dials out through the outbound trunk and the agent delivers the
result live, before any chat message is sent. The arming words are a
fixed phrase list ("call me back", "ring me when", ...), and nothing
else arms it, ever. No explicit words, no call. An unarmed job reports
by message like always. Proven live the same morning it was built.

## The artifact guard

Asked to "make" something non-verbal (ASCII art was the case that bit
us), the voice model once read the art aloud, character by character,
for a full minute. Instruction fixes failed their offline proof, so the
fix is mechanical: for make-shaped asks, any reply longer than a couple
of lines is intercepted, saved verbatim to the workshop as a file, and
replaced with a short spoken report of what was made and where it lives.
The agent cannot read a picture aloud because the picture never reaches
the voice lane. (See design law 3 in `README.md`: construction, not
manners.)

## Eval scoreboards

Trust, graded. A small runner scores the whole job fleet on two boards:

- **Task truth.** Every done job is re-verified against the disk.
  Superseded-result jobs must never have been announced. Cancelled jobs
  must carry their confirmation.
- **Conversation truth.** Every announced job must carry its verification
  stamp; every announced input-required job must carry its question; the
  delivery record is checked for duplicates.

The first baseline run scored 100% on task truth and 50% on conversation
truth, and both failures were real: results announced by the out-of-call
reporter had been verified but never *stamped*, because that lane checked
without writing back. (Fixed: first-writer-wins stamping in both lanes.)
The fix run then surfaced a verifier false positive: a job's result named
its own progress file, and the path-matching regex matched a folder name
inside the job's own slug. (Fixed with a boundary-aware pattern, in both
implementations.) Final baseline: **10/10 and 4/4.** The scoreboards
found two genuine bugs in their first hour. Write the eval before you
trust the system; it will pay for itself immediately.

---

## Part two: the afternoon session

The morning's system worked, and two things about it itched. Errands
filed through the voice agent reported back by message only, even when
the owner had asked to be phoned. And every hop between the siblings was
a poll: the delegate wake could take ten seconds plus stalls, replies
rode a two-second file poll, and the measured round trip for "ask her,
wait, hear the answer" ran 25 to 60 seconds. The afternoon fixed both,
then spent its last hour defending what it had built.

## Callbacks for delegates, not just jobs

Job callbacks (above) armed on the owner's words. Delegate notes now
carry the same trick. When the owner files an errand through the voice
agent and asks, in his own words, for a callback (a fixed phrase list:
"call me back", "ring me when", and kin), the note is stamped with a
callback marker before it ever leaves the Pi.

The discipline is all in who can arm it and what happens after:

- Only the caller's own segment of the note is scanned for arming
  phrases. The voice agent's summary of the conversation sits in the
  same file, and her words can never arm a call.
- When the sibling finishes the errand, it writes the usual reply, then
  checks whether a call with the owner is live right now. If one is,
  no dial: a callback never interrupts a call.
- Otherwise it dials first and reports in chat second, so the human
  hears the outcome from the agent's voice before any message lands.
- Never for the restricted tier, never twice, and the chat report always
  says which of the three happened: delivered, failed, or skipped
  because he was already on a call.

## Filler, on a three-second threshold

Day one banned holding phrases outright, because the voice model
narrated its own machinery ("let me check with my other self") and the
narration leaked the architecture. The ban held, but it made genuine
handoffs feel dead: a real question goes to the brain, the brain takes
seconds, and silence reads as a dropped call.

The rule is now a threshold instead of a ban. A holding phrase is
allowed only when the handoff will genuinely take more than about
three seconds: one short phrase, once. Anything quicker gets an
instant answer with no filler at all. The same tuning pass fixed a
truth bug in the backend instructions: the agent had been telling
callers a filed reminder "would be set when the other agent sees it,"
which undersold the machinery. A filed reminder reaches the owner as a
real text. The instructions now say exactly that.

## The push bus: a doorbell, not a mailbox

The polls were the round trip. Replacing them took one small server:
NATS, running on the Pi, in a sandboxed service unit. Topology was
forced by the house: the sibling's machine accepts no inbound
connections at all, so the bus could not live there. It lives on the
Pi, every sibling connection is outbound from the sibling's side
through a local forwarder, and the server listens only on the Pi's
tailnet address.

Three subjects carry the whole protocol:

- a delegate event, whose payload is only a filename;
- a job-completion event, whose payload is only a job folder name;
- a reply channel per caller, whose payload is one sentence.

That minimalism is the point. **The bus carries names, not content.**
Files remain the journal and the fallback on every path: a delegate
event wakes the watcher, which reads the actual note from disk; a reply
event is woven into the call through the same consume-and-dedupe path
as the file lane, so a reply arriving by both routes is spoken once.
Kill the sibling's bridge and the watcher falls back to its old
polling path on its own; restart the bridge and push resumes in about
a second. Both directions of that degradation were tested, not assumed.

Results: delegate filed to watcher awake in about two seconds, replies
in a live call in a few. One lane deliberately did not get faster: the
job-completion reporter kept its slower verified scan, because its
in-call announcement grace period is a semantic floor, not a transport
delay. Making the transport instant does not make a one-minute grace
period wrong.

## Attacked within the hour

The bus shipped, and within the hour it was handed to a separate
security-focused agent on the same Pi with permission to attack it.
Verdict on the afternoon's first configuration: **HIGH**. The findings,
all real:

- One shared credential with unrestricted permissions, including the
  messaging system's admin API surface, most of which the bus never
  uses.
- The server listened on every interface, in plaintext.
- Any holder of the credential could publish on the reply channel, and
  the voice agent would weave the message in as a fact from its
  sibling. The duplicate filter is not authentication, and the report
  said so in those words.
- The delegate and job subjects were equally forgeable by any
  credential holder, whatever the downstream consequences.
- Publish failures were swallowed silently by design, so a dead bus
  would have looked exactly like a quiet one.

One finding the reviewer could not settle from his sandbox (no root),
so the operator verified it directly: the Pi's firewall defaults to
deny and admits only the tailnet interface, so the LAN was never
actually able to reach the port. His successful connects were same-host
delivery, not firewall crossings. Same-host and LAN are different
threat models, and confusing them cuts both ways.

Hardening, same day, each item verified after the change:

- The server binds only the tailnet address. Connects aimed at its LAN
  and loopback addresses are refused, proven, not just configured.
- The shared credential is retired. Two per-role users with
  least-privilege ACLs replaced it: the voice side may publish its own
  events and subscribe to replies; the sibling side the mirror image.
  Out-of-ACL attempts are refused and logged by the server, by user and
  subject.
- The persistence layer (JetStream) is disabled entirely. The bus
  needs no store; files are the journal.
- The service unit is sandboxed (no new privileges, private temp,
  read-only home, empty capability set, a memory cap), and its
  directories were tightened from world-readable defaults.
- Publish failures now count somewhere visible, with sparse warnings,
  instead of vanishing.
- End to end re-proven under the new credentials: delegate filed,
  watcher awake, reply delivered, about two seconds.

Two traps surfaced by the testing itself are in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md): a refused publish that
reported success, and a retry setting that means the opposite of what
it says.

## Signed replies

ACLs narrow who can forge a reply. They do not prove a message is
genuine, and the reviewer's deepest point was that the voice agent
treats replies as facts. So the reply channel got cryptography:

- Every reply payload is now a version line carrying an HMAC-SHA256
  over the reply text, keyed by a secret that is deliberately separate
  from the bus credentials and held only by the two machines that
  produce and consume replies.
- The voice agent verifies before weaving anything in. Unsigned or
  badly signed messages are dropped and logged, never spoken.
- The publisher fails closed: no key, no send. A missing key produces
  an error the worker sees, not a silent unsigned message the agent
  would drop downstream anyway.
- Proven against the production verifier in three cases: a properly
  signed reply verified verbatim; an unsigned publish was dropped; a
  forgery signed with the wrong key was dropped.

Scope, stated plainly: signing covers the reply lane, the one whose
messages get spoken as fact. Delegate and job events stay behind the
ACL split, and their consumer only ever acts on real files, so a
forged event there can cause a wasted wake, not a false statement.
And the limit that was put to the owner before he chose this fix still
stands: signing defeats a leaked bus credential. It does not defeat an
attacker who already owns the publisher's machine, because the key
lives there too.

## New scars, collected

- **A claim is not a fact until the disk agrees.** Verify at the point of
  announcement, in every lane that can announce.
- **Interrupted is not cancelled, and requested is not confirmed.** Any
  system with detached work needs the vocabulary, and the states, for the
  gaps between those words.
- **Blocked beats guessing.** A parked question costs a minute. A
  confident wrong answer costs trust.
- **Revisions, not edits.** Work that changes gets a new revision and a
  retired predecessor, never a quiet rewrite. The record stays honest
  about what was asked, in what order, and what was discarded.
- **A doorbell is not a mailbox.** Push for latency, files for truth.
  Every fast path we built keeps a slow, verifiable journal underneath
  it, and a fallback that engages on its own when the fast path dies.
- **Ship, then red-team your own glue.** The riskiest artifact of the
  afternoon was not a model. It was a small server config written in
  twenty minutes. It was attacked within the hour and fixed the same
  day, which is the only reason it is safe to describe here.
- **A refused publish can report success.** Async clients deliver
  permission errors after the flush returns. If your helper does not
  wait and check, your tooling will lie to you politely, in writing,
  with exit code 0.
- **Access control is not authenticity.** ACLs decide who may speak on
  a channel. A signature decides whether this message is real. A
  channel whose contents an agent treats as fact deserves both.
