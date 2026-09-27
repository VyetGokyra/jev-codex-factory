#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

from typesafe_sdk import TypeSafeClient


def load_dotenv(path=".env"):
    p = Path(path)
    if not p.exists():
        return

    for line in p.read_text().splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


load_dotenv()

if len(sys.argv) < 5:
    raise SystemExit(
        "usage: jev_after_run.py TASK WORKER VERIFY_EXIT ATTEMPTS"
    )


task = sys.argv[1]
worker = sys.argv[2]
verify_exit = int(sys.argv[3])
attempts = int(sys.argv[4])


client = TypeSafeClient(
    api_key=os.environ["TYPESAFE_API_KEY"]
)


result = client.system_one(
    model="jev-latest",
    state={
        "task": task,
        "worker": worker,
        "verification_exit_code": verify_exit,
        "repair_attempts": attempts,
    },
    questions={
        "next_action": {
            "type": "choice",
            "criteria": {
                "RETRY_LUNA": (
                    "The verification failure looks local, straightforward, "
                    "and suitable for one more inexpensive coding attempt."
                ),
                "ESCALATE_SOL": (
                    "The failure likely needs deeper debugging, architecture "
                    "analysis, difficult reasoning, or a stronger model."
                ),
                "STOP_AND_REPORT": (
                    "Further autonomous attempts are unlikely to be reliable "
                    "or repair attempts are exhausted."
                ),
            },
            "instructions": (
                "Choose the safest next action after a failed verification."
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
