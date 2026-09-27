#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

from typesafe_sdk import TypeSafeClient


def load_dotenv(path):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


ENGINE_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ENGINE_ROOT / ".env")

if len(sys.argv) < 2:
    raise SystemExit('usage: jev_shape.py "task"')

task = " ".join(sys.argv[1:])

client = TypeSafeClient(api_key=os.environ["TYPESAFE_API_KEY"])

result = client.system_one(
    model="jev-latest",
    state={
        "task": task,
        "purpose": "Choose execution topology for a software engineering task.",
    },
    questions={
        "execution_shape": {
            "type": "choice",
            "criteria": {
                "SINGLE_AGENT": (
                    "The task is bounded and cohesive. Even if difficult, it is best "
                    "handled by one agent because the reasoning or implementation is "
                    "tightly coupled, mostly sequential, or centered on one invariant."
                ),
                "DECOMPOSE": (
                    "The task contains at least two meaningful independent or semi-independent "
                    "workstreams with clear deliverables that can be delegated separately. "
                    "Examples include separate modules, tests, docs, benchmarking, frontend/backend, "
                    "or independent investigations."
                ),
                "NEEDS_HUMAN": (
                    "The request lacks critical requirements or contains ambiguity that prevents "
                    "reliable planning even before implementation begins."
                ),
            },
            "instructions": (
                "Choose execution topology, not model strength. "
                "Difficulty alone is NOT a reason to decompose. "
                "Choose DECOMPOSE only when delegation creates useful independent workstreams."
            ),
        }
    },
)

a = result.choices["execution_shape"]

print(json.dumps({
    "decision": a.choice,
    "probabilities": a.probabilities,
    "confidence": a.confidence,
}))
