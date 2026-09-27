#!/usr/bin/env python3

import json
import sys
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ENGINE_ROOT / "state"


def resolve_state(arg=None):
    if arg:
        p = Path(arg)
        if not p.exists():
            p = STATE_DIR / arg
        if not p.exists():
            raise SystemExit(f"State file not found: {arg}")
        return p.resolve()

    preferred = sorted(
        STATE_DIR.glob("run-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if preferred:
        return preferred[0]

    candidates = sorted(
        [
            *STATE_DIR.glob("blocked-*.json"),
            *STATE_DIR.glob("verify-fail-*.json"),
            *STATE_DIR.glob("conflict-*.json"),
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not candidates:
        raise SystemExit("No run state files found.")

    return candidates[0]


def short(s, n=28):
    s = str(s or "")
    return s if len(s) <= n else s[: n - 3] + "..."


def normalize(data):
    # legacy blocked-state format: list of worker results
    if isinstance(data, list):
        return {
            "run_id": None,
            "target_root": None,
            "results": data,
        }

    # future structured run-state format
    if isinstance(data, dict):
        if "results" in data:
            return data

        if "tasks" in data:
            return {
                "run_id": data.get("run_id"),
                "target_root": data.get("target_root"),
                "results": data["tasks"],
            }

    raise SystemExit("Unsupported state format.")


def status_icon(status):
    return {
        "MERGED": "✓",
        "COMPLETED": "✓",
        "READY_TO_MERGE": "→",
        "RUNNING": "…",
        "VERIFYING": "?",
        "BLOCKED": "!",
        "CONFLICTED": "!",
        "FAILED": "✗",
        "NEEDS_HUMAN": "?",
        "PENDING": "·",
    }.get(status, "-")


def main():
    state_file = resolve_state(
        sys.argv[1] if len(sys.argv) > 1 else None
    )

    raw = json.loads(state_file.read_text())
    state = normalize(raw)

    results = state.get("results", [])

    print()
    print("JEV CODEX FACTORY STATUS")
    print("=" * 90)
    print("State :", state_file)

    if state.get("run_id"):
        print("Run   :", state["run_id"])

    if state.get("target_root"):
        print("Target:", state["target_root"])

    print()
    print(
        f"{'':2} "
        f"{'TASK':22} "
        f"{'STATUS':16} "
        f"{'MODEL':16} "
        f"{'EFFORT':8} "
        f"{'CONF':6} "
        f"{'TRY':4} "
        f"{'VERIFY':10} "
        f"{'REASON'}"
    )
    print("-" * 90)

    counts = {}

    for r in results:
        task = r.get("task", {})
        task_id = (
            task.get("id")
            or r.get("task_id")
            or r.get("id")
            or "unknown"
        )

        status = r.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1

        model = (
            r.get("model")
            or r.get("worker")
            or r.get("decision")
            or "-"
        )

        effort = r.get("effort") or "-"

        confidence = r.get("jev_confidence")
        if isinstance(confidence, (int, float)):
            confidence = f"{confidence:.2f}"
        else:
            confidence = "-"

        attempts = r.get("attempts", "-")

        verify = (
            r.get("verify")
            or r.get("verify_result")
            or "-"
        )

        reason = r.get("reason") or ""

        print(
            f"{status_icon(status):2} "
            f"{short(task_id, 22):22} "
            f"{status:16} "
            f"{short(model, 16):16} "
            f"{short(effort, 8):8} "
            f"{confidence:6} "
            f"{str(attempts):4} "
            f"{short(verify, 10):10} "
            f"{short(reason, 30)}"
        )

    print()
    print("SUMMARY")
    print("-" * 90)

    if not counts:
        print("No task results.")
    else:
        print(
            "  ".join(
                f"{k}={v}"
                for k, v in sorted(counts.items())
            )
        )

    blocked = [
        r for r in results
        if r.get("status") in {
            "BLOCKED",
            "CONFLICTED",
            "FAILED",
            "NEEDS_HUMAN",
        }
    ]

    if blocked:
        print()
        print("ATTENTION")
        print("-" * 90)

        for r in blocked:
            task = r.get("task", {})
            tid = task.get("id") or r.get("task_id") or "unknown"

            print(f"- {tid}")
            print(f"  status : {r.get('status')}")
            print(f"  reason : {r.get('reason') or '-'}")

            if r.get("worktree"):
                print(f"  worktree: {r['worktree']}")

    print()


if __name__ == "__main__":
    main()
