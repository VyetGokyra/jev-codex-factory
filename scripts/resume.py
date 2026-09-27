#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = ENGINE_ROOT / "state"
TARGET_ROOT = Path.cwd().resolve()


def run(cmd, cwd=None, capture=False):
    cmd = [str(x) for x in cmd]
    print("+", " ".join(cmd))

    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=capture,
    )


def output(cmd, cwd=None):
    r = run(cmd, cwd=cwd, capture=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "command failed")
    return r.stdout.strip()


def worker_prompt(task):
    owned = "\n".join(f"- {x}" for x in task.get("files", []))
    acceptance = "\n".join(
        f"- {x}" for x in task.get("acceptance", [])
    )

    return f"""
You are resuming a previously blocked isolated implementation worker.

SUBTASK:
{task["title"]}

RESUME CONTEXT:
- This task was previously blocked.
- The parent repository has now been synchronized into this worktree.
- Re-check the filesystem and current repository state.
- Do NOT assume the old blocker still exists merely because it is mentioned in the original instructions.
- If the previously missing dependency is now present, continue implementation normally.

ORIGINAL INSTRUCTIONS:
{task["prompt"]}

FILE OWNERSHIP:
{owned}

ACCEPTANCE CRITERIA:
{acceptance}

Rules:
- Resume only this subtask.
- Inspect whether the previous blocker has been resolved.
- Modify only files inside the declared ownership scope.
- Do not perform unrelated refactors.
- Do not silently expand scope.
- Run relevant targeted verification before finishing.
- If the blocker still exists, report it clearly and stop.
"""


def verify(repo):
    custom = repo / "scripts" / "verify.sh"

    if custom.exists() and os.access(custom, os.X_OK):
        cmd = [custom]
    else:
        cmd = [ENGINE_ROOT / "scripts" / "verify.sh"]

    r = run(cmd, cwd=repo)

    if r.returncode == 0:
        return "PASS"

    if r.returncode == 2:
        return "INCONCLUSIVE"

    return "FAIL"


def resolve_state(arg=None):
    if arg:
        p = Path(arg)

        if not p.exists():
            p = STATE_ROOT / arg

        if not p.exists():
            raise SystemExit(f"State file not found: {arg}")

        return p.resolve()

    candidates = sorted(
        STATE_ROOT.glob("blocked-*.json"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )

    if not candidates:
        raise SystemExit("No blocked state files found.")

    return candidates[0]


def save_state(path, data):
    path.write_text(json.dumps(data, indent=2))


def main():
    state_file = resolve_state(
        sys.argv[1] if len(sys.argv) > 1 else None
    )

    if not (TARGET_ROOT / ".git").exists():
        raise SystemExit(
            "Run jresume from the target Git repository."
        )

    dirty = output(
        ["git", "status", "--porcelain"],
        cwd=TARGET_ROOT,
    )

    if dirty:
        raise SystemExit(
            "Target repository must be clean. "
            "Commit or stash changes before resume."
        )

    data = json.loads(state_file.read_text())

    if not isinstance(data, list):
        raise SystemExit("Unsupported state format.")

    blocked = [
        r for r in data
        if r.get("status") in {
            "BLOCKED",
            "CONFLICTED",
        }
    ]

    if not blocked:
        print("No blocked tasks remain.")
        return

    print()
    print("=====================================")
    print(" RESUME")
    print("=====================================")
    print("State :", state_file)
    print("Target:", TARGET_ROOT)
    print("Tasks :", len(blocked))

    for result in blocked:
        task = result["task"]
        tid = task["id"]

        wt = Path(result["worktree"])
        branch = result["branch"]

        print()
        print("=====================================")
        print(f" RESUME TASK: {tid}")
        print("=====================================")

        if not wt.exists():
            result["status"] = "BLOCKED"
            result["reason"] = "WORKTREE_MISSING"
            save_state(state_file, data)
            print("Blocked worktree no longer exists:", wt)
            continue

        # Sync successful work merged after this worker was created.
        target_head = output(
            ["git", "rev-parse", "HEAD"],
            cwd=TARGET_ROOT,
        )

        print()
        print("Sync blocked worktree with current target HEAD")

        sync = run(
            [
                "git",
                "merge",
                "--no-edit",
                target_head,
            ],
            cwd=wt,
        )

        if sync.returncode != 0:
            result["status"] = "CONFLICTED"
            result["reason"] = "RESUME_SYNC_CONFLICT"
            save_state(state_file, data)

            print()
            print("Resume sync conflict.")
            print("Worktree preserved:", wt)
            continue

        prompt = worker_prompt(task)

        worker = run(
            [
                ENGINE_ROOT / "scripts" / "run.sh",
                prompt,
            ],
            cwd=wt,
        )

        if worker.returncode != 0:
            result["status"] = "BLOCKED"
            result["reason"] = f"WORKER_EXIT_{worker.returncode}"
            save_state(state_file, data)

            print()
            print("Task remains blocked:", tid)
            print("Worktree preserved:", wt)
            continue

        status = output(
            ["git", "status", "--porcelain"],
            cwd=wt,
        )

        if status:
            run(["git", "add", "-A"], cwd=wt)

            commit = run(
                [
                    "git",
                    "commit",
                    "-m",
                    f"agent({tid}): resume {task['title']}",
                ],
                cwd=wt,
            )

            if commit.returncode != 0:
                result["status"] = "BLOCKED"
                result["reason"] = "RESUME_COMMIT_FAILED"
                save_state(state_file, data)
                continue

        worker_head = output(
            ["git", "rev-parse", "HEAD"],
            cwd=wt,
        )

        print()
        print(f"========== RESUME MERGE GATE {tid} ==========")

        merge = run(
            [
                "git",
                "merge",
                "--no-ff",
                "--no-commit",
                branch,
            ],
            cwd=TARGET_ROOT,
        )

        if merge.returncode != 0:
            run(
                ["git", "merge", "--abort"],
                cwd=TARGET_ROOT,
            )

            result["status"] = "CONFLICTED"
            result["reason"] = "RESUME_MERGE_CONFLICT"
            save_state(state_file, data)
            continue

        verify_result = verify(TARGET_ROOT)

        print("Integration verify:", verify_result)

        if verify_result != "PASS":
            run(
                ["git", "merge", "--abort"],
                cwd=TARGET_ROOT,
            )

            result["status"] = "BLOCKED"
            result["reason"] = (
                f"RESUME_VERIFY_{verify_result}"
            )
            save_state(state_file, data)
            continue

        commit = run(
            [
                "git",
                "commit",
                "-m",
                f"merge resumed agent task {tid}",
            ],
            cwd=TARGET_ROOT,
        )

        if commit.returncode != 0:
            run(
                ["git", "merge", "--abort"],
                cwd=TARGET_ROOT,
            )

            result["status"] = "BLOCKED"
            result["reason"] = "RESUME_MERGE_COMMIT_FAILED"
            save_state(state_file, data)
            continue

        result["status"] = "MERGED"
        result["reason"] = None
        result["commit"] = worker_head

        save_state(state_file, data)

        run(
            [
                "git",
                "worktree",
                "remove",
                "--force",
                wt,
            ],
            cwd=TARGET_ROOT,
        )

        run(
            [
                "git",
                "branch",
                "-D",
                branch,
            ],
            cwd=TARGET_ROOT,
        )

        print()
        print("RESUMED + MERGED:", tid)

    remaining = [
        r for r in data
        if r.get("status") in {
            "BLOCKED",
            "CONFLICTED",
        }
    ]

    print()
    print("=====================================")

    if remaining:
        print(" RESUME PARTIALLY COMPLETE")
        print("=====================================")
        print("Remaining blocked:", len(remaining))

        for r in remaining:
            print(
                "-",
                r["task"]["id"],
                r.get("reason"),
                r.get("worktree"),
            )

        raise SystemExit(2)

    print(" FINAL VERIFY")
    print("=====================================")

    final = verify(TARGET_ROOT)

    if final != "PASS":
        raise SystemExit(
            f"Final verification: {final}"
        )

    print()
    print("=====================================")
    print(" RESUME COMPLETE")
    print("=====================================")
    print("State:", state_file)


if __name__ == "__main__":
    main()
