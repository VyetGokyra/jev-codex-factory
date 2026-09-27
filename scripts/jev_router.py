#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

from typesafe_sdk import Choice, TypeSafeClient


def load_dotenv(path: str = ".env"):
    env_path = Path(path)

    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


load_dotenv()

api_key = os.environ.get("TYPESAFE_API_KEY")

if not api_key:
    print(
        json.dumps(
            {
                "decision": "STOP",
                "confidence": 0.0,
                "reason": "TYPESAFE_API_KEY is missing",
            }
        )
    )
    sys.exit(1)


if len(sys.argv) < 2:
    print(
        json.dumps(
            {
                "decision": "STOP",
                "confidence": 0.0,
                "reason": "No task supplied",
            }
        )
    )
    sys.exit(1)


task = " ".join(sys.argv[1:])


client = TypeSafeClient(
    api_key=api_key,
)


state = {
    "task": task,
    "repository_role": "software engineering repository",
    "available_actions": [
        "LUNA_LOW",
        "LUNA_HIGH",
        "TERRA_HIGH",
        "SOL_MEDIUM",
        "SOL_HIGH",
        "SOL_XHIGH",
        "ASTRA_HIGH",
        "VERIFY_ONLY",
        "STOP_AND_REPORT",
    ],
}


result = client.system_one(
    model="jev-latest",
    state=state,
    questions={
        "next_action": {
            "type": "choice",
            "criteria": {
                "LUNA_LOW": "Very small, mechanical, or read-only work: repository inspection, typo fixes, formatting, documentation edits, tiny local fixes, simple test updates.",
                "LUNA_HIGH": "Clearly scoped implementation, bounded refactoring, normal feature work, straightforward debugging, or multi-file work with clear requirements.",
                "TERRA_HIGH": "Tasks needing stronger judgment than Luna but still bounded: code review, design tradeoffs, medium-complexity reasoning, or uncertain local architecture decisions.",
                "SOL_MEDIUM": "Nontrivial implementation, difficult debugging, integration work, performance investigation, concurrency, or changes requiring broader repository understanding.",
                "SOL_HIGH": "Hard architecture, unclear root cause, CUDA or kernel issues, subtle numerical problems, difficult concurrency, security-sensitive work, or research-heavy implementation.",
                "SOL_XHIGH": "Very difficult bounded engineering requiring deep investigation, repeated failed attempts, broad verification, or complex cross-module reasoning.",
                "ASTRA_HIGH": "Exceptional tasks requiring the strongest planning or reasoning: large ambiguous redesigns, research-grade investigation, extremely difficult root-cause analysis, or tasks where lower tiers have already failed.",
                "VERIFY_ONLY": "Choose this ONLY when the user explicitly asks to run or check existing tests, build, lint, type checking, benchmarks, or verification commands. Reading or inspecting a repository is NOT VERIFY_ONLY.",
                "STOP_AND_REPORT": "The task cannot be executed reliably because critical information, credentials, resources, requirements, or dependencies are missing.",
            },
            "instructions": (
                "Choose the cheapest model and reasoning tier that can reliably complete the task. "
                "For resumed tasks, treat references to old or previous blockers as historical context. "\
                "If the prompt says the repository has been synchronized or the dependency should be re-checked, do not choose STOP_AND_REPORT solely because the old blocker is mentioned. "
                "Prefer lower-cost tiers when capability is sufficient. "
                "Use stronger tiers only when task complexity, ambiguity, risk, or required reasoning justifies them."
            ),
        }
    },
)


answer = result.choices["next_action"]


output = {
    "decision": answer.choice,
    "probabilities": answer.probabilities,
    "confidence": answer.confidence,
}


print(json.dumps(output))
