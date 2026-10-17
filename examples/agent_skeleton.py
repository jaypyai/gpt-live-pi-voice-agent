"""Schematic skeleton of the voice-agent worker (sanitized excerpt).

Shows the moving parts from GUIDE.md: caller gate keyed off the room name,
GPT-Live duplex session with client delegation, human fillers, mechanical
delegate filing, call-card write-back, and a monthly budget ledger.

NOT production code: error handling, the reply-lane poller, the truth
anchor, and the outbound greeter are described in GUIDE.md / PATTERNS.md
and only sketched here. Requires the PINNED pair:
    livekit-agents==1.8.8, livekit-plugins-openai==1.8.8
"""
import asyncio
import json
import os
import random
import time
from pathlib import Path

from livekit import agents
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.plugins import silero
from livekit.plugins.openai.realtime import GPTLiveModel

HOME = Path.home() / "voice-home"          # the agent's world: soul, books, queues
AGENT_DIR = Path.home() / "voice-agent"
VOICE = os.environ.get("VOICE_NAME", "marin")
OWNER = os.environ.get("OWNER_NUMBER", "")
HOUSEHOLD = os.environ.get("HOUSEHOLD_NUMBER", "")
MONTHLY_CAP_S = int(os.environ.get("MONTHLY_VOICE_CAP_SECONDS", "60000"))

FILLERS = ["Hmm, let me check on that.", "One sec, let me look into that.",
           "Give me a second.", "Hang on just a moment."]
STILL_CHECKING = [12, 12, 24, 48]          # seconds between extra fillers

OWNER_INSTRUCTIONS = """You are <NAME>, a phone companion. ... (persona,
warmth, and the honesty law: for anything to be done you may say only that
it is filed or passed along; never done/set/sent/confirmed.)"""
HOUSEHOLD_INSTRUCTIONS = """You are <NAME>, a friendly voice for a
household member. Chat, language practice, reminders via delegation.
You hold NO information about the owner and never discuss relationships."""
BRAIN_INSTRUCTIONS = """You are <NAME>'s deeper self. Answer from the
context brief and the files in your home. Return ONLY words to be spoken:
1-3 short sentences, no markdown, no lists."""
HOUSEHOLD_BRAIN_INSTRUCTIONS = """... same, minus any owner context ..."""


# ---------- budget ledger ----------
def budget_left() -> int:
    p = AGENT_DIR / "usage.json"
    now = time.localtime()
    data = {"month": f"{now.tm_year}-{now.tm_mon:02d}", "seconds": 0}
    if p.exists():
        data = json.loads(p.read_text())
        if data["month"] != f"{now.tm_year}-{now.tm_mon:02d}":
            data = {"month": f"{now.tm_year}-{now.tm_mon:02d}", "seconds": 0}
    return max(0, MONTHLY_CAP_S - data["seconds"])


def budget_add(seconds: int) -> None:
    p = AGENT_DIR / "usage.json"
    now = time.localtime()
    data = {"month": f"{now.tm_year}-{now.tm_mon:02d}", "seconds": seconds}
    if p.exists():
        old = json.loads(p.read_text())
        if old["month"] == data["month"]:
            data["seconds"] += old["seconds"]
    p.write_text(json.dumps(data))


# ---------- gate ----------
def mode_for(room_name: str) -> tuple[str, str]:
    """Room names carry the peer: call-_<caller>_<rand> inbound,
    call-out_<callee>_<rand> outbound. Suffix match on the last 10 digits."""
    digits = "".join(c for c in room_name if c.isdigit())
    if OWNER and digits.endswith(OWNER[-10:]):
        return "owner", OWNER
    if HOUSEHOLD and digits.endswith(HOUSEHOLD[-10:]):
        return "household", HOUSEHOLD
    return "blocked", digits


def file_delegate(source: str, who_said: str, agent_said: str) -> Path:
    """Mechanical filing: code does this, the moment it happens, whether
    or not the model remembered to use its own note path."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = HOME / "delegate" / f"{stamp}-{source}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{who_said} said: {agent_said}\n")
    return path


# ---------- brain (any one-shot CLI works; API fallback omitted) ----------
async def brain_answer(prompt: str, mode: str, tools: bool) -> str:
    args = ["hermes", "-t", "file,terminal,code_execution" if tools else "",
            "-z", prompt]
    env = {**os.environ, "AGENT_PROFILE": "voice"}
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        cwd=str(HOME), env=env)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=240 if tools else 20)
    return out.decode().strip()


class Companion(Agent):
    def __init__(self, mode: str, digest: str):
        base = OWNER_INSTRUCTIONS if mode == "owner" else HOUSEHOLD_INSTRUCTIONS
        if digest and mode in ("owner", "household"):
            base += "\n\n" + digest
        super().__init__(
            instructions=base,
            realtime=GPTLiveModel(voice={"id": VOICE}, instructions=base),
        )
        self.mode = mode

    async def on_enter(self):
        # Outbound: wait for the callee, then open from a *reason* file.
        # Inbound owner: greet warmly. Inbound household: greet by name.
        ...  # see GUIDE.md §3.3 / PATTERNS.md §9


async def entrypoint(ctx: agents.JobContext):
    mode, peer = mode_for(ctx.room.name)
    if mode == "blocked":
        (HOME / "outbox").mkdir(parents=True, exist_ok=True)
        (HOME / "outbox" / f"blocked-{int(time.time())}.md").write_text(
            f"Blocked call from {peer} at {time.strftime('%H:%M')}\n")
        await ctx.room.delete_room(ctx.room.name)   # pre-session, zero cost
        return

    left = budget_left()
    session_cap = min(3600, left)                   # 60 min or what's left
    digest = compose_digest(mode)                    # GUIDE.md §3.3 (elided)
    agent = Companion(mode, digest)
    session = AgentSession(vad=silero.VAD.load())
    started = time.time()

    @ctx.add_shutdown_callback
    async def write_back():
        budget_add(int(time.time() - started))
        note = HOME / "outbox" / f"voice-{time.strftime('%Y%m%d-%H%M%S')}.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(render_transcript(ctx))      # your transcript store
        if mode == "owner":
            card = await brain_answer(card_prompt(ctx), mode, tools=False)
            with open(HOME / "memory" / f"{time.strftime('%Y-%m-%d')}.md", "a") as fh:
                fh.write(f"\n## Call card {time.strftime('%H:%M')}\n{card}\n")

    await session.start(agent, room=ctx.room,
                        room_input_options=RoomInputOptions())
    # ... delegation handling, fillers, reply-lane poller, truth anchor:
    # PATTERNS.md §§1-4. Session closes on room disconnect / cap.


def compose_digest(mode: str) -> str: ...
def render_transcript(ctx) -> str: ...
def card_prompt(ctx) -> str: ...

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(
        entrypoint_fnc=entrypoint, agent_name="voice"))
