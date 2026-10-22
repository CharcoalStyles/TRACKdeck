"""Phase B step 2: CPU latency benchmark for pydecide's laya backend on this
i7 (no GPU, no MLX). Standalone, run with the scratch venv's python."""
import time

from decide import Choice, Client, Noul

client = Client.from_env()
print("Backends in chain:", [b.name for b in client.backends])

# Warm-up call: this is where the ~1GB HF weights download + model load happens.
t0 = time.perf_counter()
resp = client.decide(
    "remind me to pick up meds at 5pm",
    {
        "category": Choice(
            instructions="Which category of tool does this request need?",
            criteria=["reminders", "calendar", "weather", "notes", "general"],
        )
    },
)
warm_ms = (time.perf_counter() - t0) * 1000
print(f"First call (incl. model load): {warm_ms:.1f} ms -> {resp['category']}")
print("Meta:", resp.meta)

# Now time steady-state single-call latency.
samples = []
test_messages = [
    "remind me to pick up meds at 5pm",
    "what's the weather this weekend",
    "what do I have on my calendar today",
    "add a note about my meeting",
    "search the web for the best pizza place",
    "log that I went for a 20 minute run",
    "cancel my 3pm reminder",
    "what's on my schedule this week",
    "set a timer for 10 minutes",
    "tell me a joke",
]
for msg in test_messages:
    t0 = time.perf_counter()
    resp = client.decide(
        msg,
        {
            "category": Choice(
                instructions="Which category of tool does this request need?",
                criteria=["reminders", "calendar", "weather", "notes", "general", "activity_log", "web", "planning"],
            )
        },
    )
    dt = (time.perf_counter() - t0) * 1000
    samples.append(dt)
    print(f"{dt:7.1f} ms  {msg!r:55s} -> {resp['category'].choice}")

print()
print(f"n={len(samples)} mean={sum(samples)/len(samples):.1f}ms min={min(samples):.1f}ms max={max(samples):.1f}ms")

# Also test a Noul gate call ("needs a tool at all?"), same as Phase C's proposed first gate.
t0 = time.perf_counter()
resp = client.decide(
    "thanks, that's all for now",
    {"needs_tool": Noul(instructions="Does responding to this message require calling any tool?")},
)
dt = (time.perf_counter() - t0) * 1000
print(f"\nNoul gate call: {dt:.1f} ms -> needs_tool={resp['needs_tool'].noul:.3f}")
