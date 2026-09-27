#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

from typesafe_sdk import TypeSafeClient


ENGINE_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path=None):
    if path is None:
        path = ENGINE_ROOT / ".env"

    path = Path(path)

    if not path.exists():
        return

    for line in path.read_text().splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


def tail(path, limit=6000):
    path = Path(path)

    if not path.exists():
        return ""

    text = path.read_text(
        errors="replace"
    )

    return text[-limit:]


load_dotenv()

if len(sys.argv) < 5:
    raise SystemExit(
        "usage: jev_after_run.py "
        "TASK WORKER VERIFY_EXIT ATTEMPTS"
    )


task = sys.argv[1]
worker = sys.argv[2]
verify_exit = int(sys.argv[3])
attempts = int(sys.argv[4])

verify_log = tail(
    ENGINE_ROOT / "logs" / "verify_last.log"
)

codex_log = tail(
    ENGINE_ROOT / "state" / "codex_last.txt"
)


client = TypeSafeClient(
    api_key=os.environ["TYPESAFE_API_KEY"]
)


result = client.system_one(
    model="jev-latest",
    state={
        "task": task,
        "current_worker": worker,
        "verification_exit_code": verify_exit,
        "attempts_so_far": attempts,
        "verification_log_tail": verify_log,
        "worker_output_tail": codex_log,
    },
    questions={
        "next_action": {
            "type": "choice",
            "criteria": {
                "RETRY_SAME": (
                    "The failure appears local or transient and the current "
                    "worker lane is still appropriate. Retry once without "
                    "changing the model lane."
                ),
                "RETRY_HIGHER_EFFORT": (
                    "The same model family is appropriate, but the failure "
                    "needs more reasoning effort."
                ),
                "ESCALATE_MODEL": (
                    "The current model lane is insufficient. A stronger "
                    "model family is justified by the debugging or reasoning "
                    "difficulty."
                ),
                "BLOCKED_RESOURCE": (
                    "Execution cannot continue because a required file, "
                    "credential, service, contract, external resource, "
                    "or other prerequisite is missing."
                ),
                "BLOCKED_DEPENDENCY": (
                    "Execution depends on another task, code change, API, "
                    "module, or prerequisite implementation that is not yet "
                    "available."
                ),
                "NEEDS_HUMAN": (
                    "The failure requires a human decision because the "
                    "requirements are ambiguous, mutually incompatible, "
                    "or require an explicit choice."
                ),
                "STOP": (
                    "Further autonomous retries are unlikely to improve the "
                    "result, or the failure is not safely recoverable."
                ),
            },
            "instructions": (
                "Choose exactly one next action after this failed coding "
                "attempt. Prefer the cheapest reliable action. Do not "
                "escalate merely because verification failed. Treat missing "
                "resources and dependencies as blockers rather than model "
                "weakness. Avoid repeated retries when evidence indicates "
                "the task cannot progress."
            ),
        }
    },
)


answer = result.choices["next_action"]

print(
    json.dumps(
        {
            "decision": answer.choice,
            "probabilities": answer.probabilities,
            "confidence": answer.confidence,
        }
    )
)
