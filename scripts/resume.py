#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path

import factory


ENGINE_ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = ENGINE_ROOT / "state"
TARGET_ROOT = Path.cwd().resolve()


def run(cmd, cwd=None, capture=False, env=None):
    cmd = [str(x) for x in cmd]
    print("+", " ".join(cmd))

    merged_env = os.environ.copy()

    if env:
        merged_env.update({
            str(k): str(v)
            for k, v in env.items()
        })

    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=capture,
        env=merged_env,
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
    path.write_text(json.dumps(data, indent=2) + "\n")


def extract_results(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]

    raise SystemExit("Unsupported state format.")


def infer_run_id(path, data):
    if isinstance(data, dict) and data.get("run_id"):
        return str(data["run_id"])

    stem = path.stem

    for prefix in (
        "blocked-",
        "conflict-",
        "verify-fail-",
        "run-",
    ):
        if stem.startswith(prefix):
            return stem[len(prefix):]

    return None


def resolve_canonical_state(state_file, data):
    run_id = infer_run_id(state_file, data)

    if not run_id:
        return None

    candidate = STATE_ROOT / f"run-{run_id}.json"

    if candidate.exists():
        return candidate

    return None


def update_run_state(
    canonical_path,
    results,
    *,
    status=None,
    reason=None,
):
    if canonical_path is None or not canonical_path.exists():
        return

    data = json.loads(canonical_path.read_text())

    if not isinstance(data, dict):
        return

    data["results"] = results

    if status is not None:
        data["status"] = status

    data["reason"] = reason

    import time
    data["updated_at"] = time.time()

    if status in {
        "COMPLETED",
        "BLOCKED",
        "FAILED",
        "CONFLICTED",
        "NEEDS_HUMAN",
    }:
        data["finished_at"] = time.time()

    save_state(canonical_path, data)



def replan_after_resume(run_state):
    original_task = run_state.get("original_task")

    if not original_task:
        return {
            "goal_complete": True,
            "summary": "No original goal is available for replanning.",
            "shared_integration_files": [],
            "tasks": [],
        }

    completed = []

    for result in run_state.get("results", []):
        if result.get("status") not in {
            "MERGED",
            "COMPLETED",
        }:
            continue

        task = result.get("task", {})

        completed.append({
            "id": task.get("id"),
            "title": task.get("title"),
            "acceptance": task.get("acceptance", []),
            "status": result.get("status"),
        })

    run_id = str(run_state.get("run_id") or "resume")
    replan_file = STATE_ROOT / f"replan-{run_id}.json"

    completed_json = json.dumps(
        completed,
        indent=2,
    )

    prompt = f"""
You are the parent software-engineering orchestrator performing a
post-resume completion check.

ORIGINAL USER GOAL:
{original_task}

TASKS ALREADY COMPLETED OR MERGED:
{completed_json}

The repository has changed since the original plan. Inspect the CURRENT
repository state before deciding anything.

Determine whether the ORIGINAL USER GOAL is now fully satisfied.

Important rules:
- Judge completion against the original user goal, not merely the old plan.
- Previously blocked prerequisites may now exist.
- Do not recreate work that is already complete.
- Do not create a task merely to restore a prerequisite if that prerequisite
  already exists in the repository.
- If implementation work remains after a prerequisite was restored, create
  the implementation task.
- Create only the smallest remaining substantive tasks.
- A single remaining task is valid.
- Zero remaining tasks is valid.
- Parallel tasks must not own overlapping files.
- Do not modify the repository.
- Do not implement anything.
- Never search above the repository root.
- Restrict inspection to the current repository.
- Ignore .git, .venv, node_modules, build directories, caches and generated
  artifacts unless directly relevant.

Set goal_complete=true only when the current repository already satisfies
the original user goal.

If goal_complete=true, tasks MUST be empty.

Return only the requested structured result.
"""

    cmd = [
        "codex",
        "exec",
        "-s",
        "read-only",
        "-m",
        "gpt-5.6-sol",
        "-c",
        'model_reasoning_effort="medium"',
        "-C",
        TARGET_ROOT,
        "--output-schema",
        ENGINE_ROOT / "schemas" / "replan.schema.json",
        "-o",
        replan_file,
        prompt,
    ]

    r = run(cmd, cwd=TARGET_ROOT)

    if r.returncode != 0:
        raise RuntimeError(
            f"Replan failed with exit code {r.returncode}"
        )

    result = json.loads(replan_file.read_text())

    if result["goal_complete"] and result["tasks"]:
        raise RuntimeError(
            "Invalid replan: goal_complete=true but tasks are present."
        )

    if not result["goal_complete"] and not result["tasks"]:
        raise RuntimeError(
            "Invalid replan: goal incomplete but no remaining tasks."
        )

    print()
    print("=====================================")
    print(" POST-RESUME REPLAN")
    print("=====================================")
    print(json.dumps(result, indent=2))

    return result



def execute_replan_tasks(run_state, replan):
    tasks = replan.get("tasks", [])

    if not tasks:
        return []

    run_id = str(run_state.get("run_id") or "resume")

    print()
    print("=====================================")
    print(" EXECUTE REPLAN TASKS")
    print("=====================================")

    completed_ids = {
        r.get("task", {}).get("id")
        for r in run_state.get("results", [])
        if r.get("status") in {"MERGED", "COMPLETED"}
    }

    pending = []

    for task in tasks:
        deps = task.get("depends_on", [])

        unknown = [
            dep for dep in deps
            if dep not in completed_ids
            and dep not in {t["id"] for t in tasks}
        ]

        if unknown:
            raise RuntimeError(
                f"Replan task {task['id']} has unknown dependencies: "
                f"{unknown}"
            )

        pending.append(task)

    new_results = []

    while pending:
        ready = [
            task for task in pending
            if all(
                dep in completed_ids
                for dep in task.get("depends_on", [])
            )
        ]

        if not ready:
            raise RuntimeError(
                "Replan dependency cycle or unresolved dependency."
            )

        base_commit = output(
            ["git", "rev-parse", "HEAD"],
            cwd=TARGET_ROOT,
        )

        for task in ready:
            result = factory.run_worker(
                run_id,
                task,
                base_commit,
            )

            new_results.append(result)

            if result.get("status") != "READY_TO_MERGE":
                return new_results

            if not factory.merge_worker(result):
                return new_results

            verification = verify(TARGET_ROOT)

            if verification != "PASS":
                result["status"] = "FAILED"
                result["reason"] = (
                    f"REPLAN_INTEGRATION_VERIFY_{verification}"
                )
                return new_results

            factory.cleanup_worker(result)

            completed_ids.add(task["id"])

        ready_ids = {task["id"] for task in ready}
        pending = [
            task for task in pending
            if task["id"] not in ready_ids
        ]

    return new_results


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
    results = extract_results(data)

    canonical_state = resolve_canonical_state(
        state_file,
        data,
    )

    blocked = [
        r for r in results
        if r.get("status") in {
            "BLOCKED",
            "CONFLICTED",
        }
    ]

    if not blocked:
        print("No blocked tasks remain.")

        if canonical_state is None or not canonical_state.exists():
            return

        canonical_data = json.loads(
            canonical_state.read_text()
        )

        replan = replan_after_resume(
            canonical_data
        )

        if replan["goal_complete"]:
            update_run_state(
                canonical_state,
                results,
                status="COMPLETED",
                reason=None,
            )

            print()
            print("Original goal is already complete.")
            return

        new_results = execute_replan_tasks(
            canonical_data,
            replan,
        )

        results.extend(new_results)

        failed_replan = [
            r for r in new_results
            if r.get("status") != "MERGED"
        ]

        if failed_replan:
            update_run_state(
                canonical_state,
                results,
                status="BLOCKED",
                reason="REPLAN_TASK_FAILED",
            )

            raise SystemExit(2)

        final_after_replan = verify(
            TARGET_ROOT
        )

        if final_after_replan != "PASS":
            update_run_state(
                canonical_state,
                results,
                status="FAILED",
                reason=(
                    "POST_REPLAN_FINAL_VERIFY_"
                    f"{final_after_replan}"
                ),
            )

            raise SystemExit(
                f"Post-replan final verification: "
                f"{final_after_replan}"
            )

        update_run_state(
            canonical_state,
            results,
            status="COMPLETED",
            reason=None,
        )

        print()
        print("=====================================")
        print(" REPLAN COMPLETE")
        print("=====================================")
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

            update_run_state(
                canonical_state,
                results,
                status="BLOCKED",
                reason=result.get("reason"),
            )
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

            update_run_state(
                canonical_state,
                results,
                status="BLOCKED",
                reason=result.get("reason"),
            )

            print()
            print("Resume sync conflict.")
            print("Worktree preserved:", wt)
            continue

        prompt = worker_prompt(task)

        resume_run_id = infer_run_id(state_file, data) or "resume"

        telemetry_dir = STATE_ROOT / "workers" / resume_run_id
        telemetry_dir.mkdir(parents=True, exist_ok=True)

        telemetry_path = telemetry_dir / f"{tid}.json"

        worker = run(
            [
                ENGINE_ROOT / "scripts" / "run.sh",
                prompt,
            ],
            cwd=wt,
            env={
                "JEV_TELEMETRY_FILE": telemetry_path,
                "JEV_RUN_ID": resume_run_id,
                "JEV_TASK_ID": tid,
            },
        )

        if telemetry_path.exists():
            try:
                result.update(
                    json.loads(telemetry_path.read_text())
                )
            except Exception as exc:
                print("Warning: resume telemetry read failed:", exc)

        if worker.returncode != 0:
            result["status"] = "BLOCKED"
            result["reason"] = f"WORKER_EXIT_{worker.returncode}"
            save_state(state_file, data)

            update_run_state(
                canonical_state,
                results,
                status="BLOCKED",
                reason=result.get("reason"),
            )

            print()
            print("Task remains blocked:", tid)
            print("Worktree preserved:", wt)
            continue

        status = output(
            ["git", "status", "--porcelain"],
            cwd=wt,
        )

        if not status:
            print()
            print(
                f"Resume task {tid} is already satisfied "
                "after synchronization; no worker changes required."
            )

            final_check = verify(TARGET_ROOT)

            if final_check != "PASS":
                result["status"] = "BLOCKED"
                result["reason"] = (
                    f"RESUME_NO_CHANGE_VERIFY_{final_check}"
                )

                save_state(state_file, data)

                update_run_state(
                    canonical_state,
                    results,
                    status="BLOCKED",
                    reason=result["reason"],
                )
                continue

            target_head = output(
                ["git", "rev-parse", "HEAD"],
                cwd=TARGET_ROOT,
            )

            result["status"] = "MERGED"
            result["reason"] = None
            result["commit"] = target_head
            result["verify_result"] = "PASS"

            save_state(state_file, data)

            update_run_state(
                canonical_state,
                results,
                status="RUNNING",
                reason=None,
            )

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

            print("RESUMED + SATISFIED:", tid)
            continue

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

                update_run_state(
                    canonical_state,
                    results,
                    status="BLOCKED",
                    reason=result.get("reason"),
                )
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

            update_run_state(
                canonical_state,
                results,
                status="CONFLICTED",
                reason=result.get("reason"),
            )
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

            update_run_state(
                canonical_state,
                results,
                status="BLOCKED",
                reason=result.get("reason"),
            )
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

            update_run_state(
                canonical_state,
                results,
                status="BLOCKED",
                reason=result.get("reason"),
            )
            continue

        result["status"] = "MERGED"
        result["reason"] = None
        result["commit"] = worker_head

        save_state(state_file, data)

        update_run_state(
            canonical_state,
            results,
            status="RUNNING",
            reason=None,
        )

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
        r for r in results
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

        update_run_state(
            canonical_state,
            results,
            status="BLOCKED",
            reason="RESUME_PARTIALLY_BLOCKED",
        )

        raise SystemExit(2)

    print(" FINAL VERIFY")
    print("=====================================")

    final = verify(TARGET_ROOT)

    if final != "PASS":
        update_run_state(
            canonical_state,
            results,
            status="FAILED",
            reason=f"FINAL_VERIFY_{final}",
        )

        raise SystemExit(
            f"Final verification: {final}"
        )

    if canonical_state is not None and canonical_state.exists():
        canonical_data = json.loads(
            canonical_state.read_text()
        )

        replan = replan_after_resume(
            canonical_data
        )

        if not replan["goal_complete"]:
            new_results = execute_replan_tasks(
                canonical_data,
                replan,
            )

            results.extend(new_results)

            failed_replan = [
                r for r in new_results
                if r.get("status") != "MERGED"
            ]

            if failed_replan:
                update_run_state(
                    canonical_state,
                    results,
                    status="BLOCKED",
                    reason="REPLAN_TASK_FAILED",
                )

                raise SystemExit(2)

            final_after_replan = verify(
                TARGET_ROOT
            )

            if final_after_replan != "PASS":
                update_run_state(
                    canonical_state,
                    results,
                    status="FAILED",
                    reason=(
                        "POST_REPLAN_FINAL_VERIFY_"
                        f"{final_after_replan}"
                    ),
                )

                raise SystemExit(
                    f"Post-replan final verification: "
                    f"{final_after_replan}"
                )

    update_run_state(
        canonical_state,
        results,
        status="COMPLETED",
        reason=None,
    )

    print()
    print("=====================================")
    print(" RESUME COMPLETE")
    print("=====================================")
    print("State:", state_file)


if __name__ == "__main__":
    main()
