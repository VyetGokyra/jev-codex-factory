#!/usr/bin/env python3

import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parent.parent
TARGET_ROOT = Path.cwd().resolve()

STATE_ROOT = ENGINE_ROOT / "state"
LOG_ROOT = ENGINE_ROOT / "logs"

STATE_ROOT.mkdir(exist_ok=True)
LOG_ROOT.mkdir(exist_ok=True)

# Git worktree/ref creation mutates shared repository metadata.
# Serialize only this short critical section; workers still execute in parallel.
GIT_WORKTREE_LOCK = threading.Lock()


def run(cmd, cwd=None, capture=False, check=False, env=None):
    print("+", " ".join(str(x) for x in cmd))

    merged_env = os.environ.copy()
    if env:
        merged_env.update({
            str(k): str(v)
            for k, v in env.items()
        })

    return subprocess.run(
        [str(x) for x in cmd],
        cwd=cwd,
        text=True,
        capture_output=capture,
        check=check,
        env=merged_env,
    )


def output(cmd, cwd=None):
    r = run(cmd, cwd=cwd, capture=True, check=True)
    return r.stdout.strip()


def sanitize(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-").lower()


def verify(repo):
    custom = repo / "scripts" / "verify.sh"

    if custom.exists() and os.access(custom, os.X_OK):
        cmd = [str(custom)]
    else:
        cmd = [str(ENGINE_ROOT / "scripts" / "verify.sh")]

    print()
    print("========== VERIFY ==========")
    r = run(cmd, cwd=repo)

    if r.returncode == 0:
        return "PASS"

    if r.returncode == 2:
        return "INCONCLUSIVE"

    return "FAIL"


def get_shape(task):
    r = run(
        [
            sys.executable,
            ENGINE_ROOT / "scripts" / "jev_shape.py",
            task,
        ],
        cwd=ENGINE_ROOT,
        capture=True,
    )

    if r.returncode != 0:
        print(r.stderr)
        raise RuntimeError("Jev shape routing failed")

    result = json.loads(r.stdout)
    print("JEV #0:", json.dumps(result, indent=2))
    return result


def run_single(task):
    print()
    print("=====================================")
    print(" SINGLE AGENT")
    print("=====================================")

    run_id = time.strftime("%Y%m%d-%H%M%S")

    telemetry_dir = STATE_ROOT / "workers" / run_id
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    telemetry_path = telemetry_dir / "single-agent.json"
    state_file = STATE_ROOT / f"run-{run_id}.json"

    if telemetry_path.exists():
        telemetry_path.unlink()

    started_at = time.time()

    r = run(
        [ENGINE_ROOT / "scripts" / "run.sh", task],
        cwd=TARGET_ROOT,
        env={
            "JEV_TELEMETRY_FILE": telemetry_path,
            "JEV_RUN_ID": run_id,
            "JEV_TASK_ID": "single-agent",
        },
    )

    telemetry = load_worker_telemetry(telemetry_path)

    worker_status = telemetry.get("worker_status")

    if r.returncode == 0:
        status = "COMPLETED"
        reason = None
    elif worker_status == "FAILED":
        status = "FAILED"
        reason = f"WORKER_EXIT_{r.returncode}"
    else:
        status = "BLOCKED"
        reason = f"WORKER_EXIT_{r.returncode}"

    result = {
        "task": {
            "id": "single-agent",
            "title": task,
            "prompt": task,
            "files": [],
            "depends_on": [],
            "acceptance": [],
        },
        "status": status,
        "reason": reason,
    }

    result.update(telemetry)

    state = {
        "version": 1,
        "run_id": run_id,
        "execution_shape": "SINGLE_AGENT",
        "target_root": str(TARGET_ROOT),
        "original_task": task,
        "started_at": started_at,
        "finished_at": time.time(),
        "results": [result],
    }

    state_file.write_text(
        json.dumps(state, indent=2) + "\n"
    )

    print()
    print("=====================================")
    print(" RUN STATE")
    print("=====================================")
    print("Run   :", run_id)
    print("State :", state_file)

    raise SystemExit(r.returncode)


def make_plan(task, plan_file):
    prompt = f"""
You are the parent software-engineering orchestrator.

Goal:
{task}

Inspect the repository before planning.

Decompose the goal into the smallest useful set of substantial subtasks.

Rules:
- Only create multiple subtasks when they represent meaningful work.
- Every subtask must have a clear deliverable.
- Assign explicit file ownership to each subtask.
- Parallel-ready subtasks must not own overlapping files.
- If two tasks require the same files, express the dependency so they run sequentially.
- Reserve genuinely shared integration files for the parent in shared_integration_files.
- Do not implement anything.
- Do not modify the repository.
- Produce only the requested structured plan.
"""

    cmd = [
        "codex",
        "exec",
        "-m",
        "gpt-5.6-sol",
        "-c",
        'model_reasoning_effort="high"',
        "-C",
        TARGET_ROOT,
        "--output-schema",
        ENGINE_ROOT / "schemas" / "plan.schema.json",
        "-o",
        plan_file,
        prompt,
    ]

    r = run(cmd, cwd=TARGET_ROOT)

    if r.returncode != 0:
        raise RuntimeError("Parent planning failed")

    return json.loads(plan_file.read_text())


def validate_plan(plan):
    tasks = plan["tasks"]

    ids = [t["id"] for t in tasks]

    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate task IDs in plan")

    valid = set(ids)

    for task in tasks:
        unknown = set(task["depends_on"]) - valid
        if unknown:
            raise RuntimeError(
                f'{task["id"]} has unknown dependencies: {unknown}'
            )

        if task["id"] in task["depends_on"]:
            raise RuntimeError(f'{task["id"]} depends on itself')


def calculate_waves(tasks):
    pending = {t["id"]: t for t in tasks}
    completed = set()
    waves = []

    while pending:
        ready = [
            t
            for t in pending.values()
            if set(t["depends_on"]).issubset(completed)
        ]

        if not ready:
            raise RuntimeError("Dependency cycle detected")

        waves.append(ready)

        for task in ready:
            completed.add(task["id"])
            del pending[task["id"]]

    return waves


def check_wave_file_overlap(wave):
    ownership = {}

    for task in wave:
        for filename in task["files"]:
            key = filename.rstrip("/")

            if key in ownership:
                raise RuntimeError(
                    f"Parallel ownership conflict: "
                    f'{task["id"]} and {ownership[key]} both own {filename}'
                )

            ownership[key] = task["id"]


def worker_prompt(task):
    owned = "\n".join(f"- {x}" for x in task["files"])
    acceptance = "\n".join(f"- {x}" for x in task["acceptance"])

    return f"""
You are an isolated implementation worker.

SUBTASK:
{task["title"]}

INSTRUCTIONS:
{task["prompt"]}

Generated artifacts must never be committed. Ignore or remove:
- __pycache__/
- *.pyc
- .pytest_cache/
- .mypy_cache/
- .ruff_cache/

FILE OWNERSHIP:
{owned}

ACCEPTANCE CRITERIA:
{acceptance}

Rules:
- Work only on this subtask.
- Modify only files inside the declared ownership scope.
- Do not perform unrelated refactors.
- If completing the task requires modifying files outside ownership,
  do not silently expand scope. Report the blocker instead.
- Run relevant targeted verification before finishing.
"""


def load_worker_telemetry(path):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as exc:
        print(f"Warning: telemetry read failed: {exc}")

    return {}


def with_telemetry(result, telemetry_path):
    result.update(load_worker_telemetry(telemetry_path))
    return result


def run_worker(run_id, task, base_commit):
    tid = sanitize(task["id"])
    branch = f"jev/{run_id}/{tid}"

    wt_root = Path("/tmp/jev-codex-factory") / run_id
    wt_root.mkdir(parents=True, exist_ok=True)

    wt = wt_root / tid

    telemetry_dir = STATE_ROOT / "workers" / run_id
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    telemetry_path = telemetry_dir / f"{tid}.json"

    if telemetry_path.exists():
        telemetry_path.unlink()

    if wt.exists():
        shutil.rmtree(wt)

    with GIT_WORKTREE_LOCK:
        # Clear stale administrative entries before creating a new worktree.
        run(
            ["git", "worktree", "prune"],
            cwd=TARGET_ROOT,
        )

        create = run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                branch,
                wt,
                base_commit,
            ],
            cwd=TARGET_ROOT,
        )

    if create.returncode != 0:
        print(f"Retrying worktree creation for {tid}...")

        time.sleep(0.25)

        with GIT_WORKTREE_LOCK:
            run(
                ["git", "worktree", "prune"],
                cwd=TARGET_ROOT,
            )

            # Remove a partially-created branch only if it exists and
            # is not checked out anywhere.
            branch_exists = subprocess.run(
                [
                    "git",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch}",
                ],
                cwd=TARGET_ROOT,
            ).returncode == 0

            if branch_exists:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    cwd=TARGET_ROOT,
                )

            create = run(
                [
                    "git",
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    wt,
                    base_commit,
                ],
                cwd=TARGET_ROOT,
            )

    if create.returncode != 0:
        return {
            "task": task,
            "status": "BLOCKED",
            "reason": "WORKTREE_CREATE_FAILED",
            "branch": branch,
            "worktree": str(wt),
        }

    prompt = worker_prompt(task)

    worker = run(
        [
            ENGINE_ROOT / "scripts" / "run.sh",
            prompt,
        ],
        cwd=wt,
        env={
            "JEV_TELEMETRY_FILE": telemetry_path,
            "JEV_RUN_ID": run_id,
            "JEV_TASK_ID": tid,
        },
    )

    if worker.returncode != 0:
        return with_telemetry({
            "task": task,
            "status": "BLOCKED",
            "reason": f"WORKER_EXIT_{worker.returncode}",
            "branch": branch,
            "worktree": str(wt),
        }, telemetry_path)

    status = output(["git", "status", "--porcelain"], cwd=wt)

    if not status:
        return with_telemetry({
            "task": task,
            "status": "BLOCKED",
            "reason": "NO_CHANGES_PRODUCED",
            "branch": branch,
            "worktree": str(wt),
        }, telemetry_path)

    if status:
        run(["git", "add", "-A"], cwd=wt, check=True)

        commit = run(
            [
                "git",
                "commit",
                "-m",
                f'agent({task["id"]}): {task["title"]}',
            ],
            cwd=wt,
        )

        if commit.returncode != 0:
            return with_telemetry({
                "task": task,
                "status": "BLOCKED",
                "reason": "COMMIT_FAILED",
                "branch": branch,
                "worktree": str(wt),
            }, telemetry_path)

    commit_sha = output(["git", "rev-parse", "HEAD"], cwd=wt)

    return with_telemetry({
        "task": task,
        "status": "READY_TO_MERGE",
        "branch": branch,
        "commit": commit_sha,
        "worktree": str(wt),
    }, telemetry_path)


def merge_worker(result):
    branch = result["branch"]
    tid = result["task"]["id"]

    print()
    print(f"========== MERGE GATE {tid} ==========")

    merged = run(
        [
            "git",
            "merge",
            "--no-ff",
            "--no-commit",
            branch,
        ],
        cwd=TARGET_ROOT,
        capture=True,
    )

    if merged.returncode != 0:
        print(merged.stdout)
        print(merged.stderr)

        run(
            ["git", "merge", "--abort"],
            cwd=TARGET_ROOT,
        )

        result["status"] = "CONFLICTED"
        result["reason"] = "MERGE_CONFLICT"
        return False

    committed = run(
        [
            "git",
            "commit",
            "-m",
            f"merge agent task {tid}",
        ],
        cwd=TARGET_ROOT,
    )

    if committed.returncode != 0:
        run(
            ["git", "merge", "--abort"],
            cwd=TARGET_ROOT,
        )

        result["status"] = "CONFLICTED"
        result["reason"] = "MERGE_COMMIT_FAILED"
        return False

    result["status"] = "MERGED"
    return True


def cleanup_worker(result):
    wt = result.get("worktree")
    branch = result.get("branch")

    if wt:
        run(
            ["git", "worktree", "remove", "--force", wt],
            cwd=TARGET_ROOT,
        )

    if branch:
        run(
            ["git", "branch", "-D", branch],
            cwd=TARGET_ROOT,
        )


def save_run_state(
    path,
    *,
    run_id,
    original_task,
    started_at,
    results,
    status,
    plan_file=None,
    reason=None,
):
    terminal = {
        "COMPLETED",
        "BLOCKED",
        "FAILED",
        "CONFLICTED",
        "NEEDS_HUMAN",
    }

    payload = {
        "version": 1,
        "run_id": run_id,
        "execution_shape": "DECOMPOSE",
        "status": status,
        "reason": reason,
        "target_root": str(TARGET_ROOT),
        "original_task": original_task,
        "plan_file": str(plan_file) if plan_file else None,
        "started_at": started_at,
        "updated_at": time.time(),
        "finished_at": time.time() if status in terminal else None,
        "results": results,
    }

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)



def execute_task_waves(
    run_id,
    tasks,
    *,
    completed_ids=None,
    max_workers=3,
    on_update=None,
):
    """
    Shared DAG executor used by both initial plans and post-resume replans.

    Returns:
        {
            "status": "COMPLETED" | "BLOCKED" | "FAILED" | "CONFLICTED",
            "reason": str | None,
            "results": [...],
        }
    """
    completed = set(completed_ids or [])
    pending = {task["id"]: task for task in tasks}
    task_ids = set(pending)

    # Validate IDs.
    if len(task_ids) != len(tasks):
        raise RuntimeError("Duplicate task IDs")

    # Validate dependencies. Dependencies may point either to another task
    # in this execution or to an already-completed task from a previous run.
    valid_dependencies = task_ids | completed

    for task in tasks:
        deps = set(task.get("depends_on", []))

        unknown = deps - valid_dependencies
        if unknown:
            raise RuntimeError(
                f'{task["id"]} has unknown dependencies: {unknown}'
            )

        if task["id"] in deps:
            raise RuntimeError(
                f'{task["id"]} depends on itself'
            )

    results = []

    def notify(status="RUNNING", reason=None):
        if on_update:
            on_update(
                results,
                status=status,
                reason=reason,
            )

    notify()

    wave_index = 0

    while pending:
        wave_index += 1

        ready_tasks = [
            task
            for task in pending.values()
            if set(task.get("depends_on", [])).issubset(completed)
        ]

        if not ready_tasks:
            raise RuntimeError(
                "Dependency cycle or unresolved dependency detected"
            )

        print()
        print("=====================================")
        print(f" SHARED WAVE {wave_index}")
        print("=====================================")

        check_wave_file_overlap(ready_tasks)

        base_commit = output(
            ["git", "rev-parse", "HEAD"],
            cwd=TARGET_ROOT,
        )

        wave_results = []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(max_workers, len(ready_tasks))
        ) as pool:
            futures = [
                pool.submit(
                    run_worker,
                    run_id,
                    task,
                    base_commit,
                )
                for task in ready_tasks
            ]

            for future in futures:
                wave_results.append(future.result())

        results.extend(wave_results)
        notify()

        ready_to_merge = [
            result
            for result in wave_results
            if result.get("status") == "READY_TO_MERGE"
        ]

        blocked = [
            result
            for result in wave_results
            if result.get("status") != "READY_TO_MERGE"
        ]

        if blocked:
            print()
            print("========== PARTIAL BLOCK ==========")

            for result in blocked:
                print(
                    result["task"]["id"],
                    result.get("status"),
                    result.get("reason"),
                    result.get("worktree"),
                )

        # Merge successful workers even when another independent worker
        # in the same wave is blocked.
        for result in ready_to_merge:
            if not merge_worker(result):
                notify(
                    status="CONFLICTED",
                    reason=result.get("reason") or "MERGE_CONFLICT",
                )

                return {
                    "status": "CONFLICTED",
                    "reason": result.get("reason") or "MERGE_CONFLICT",
                    "results": results,
                }

            integration_verify = verify(TARGET_ROOT)

            if integration_verify != "PASS":
                result["status"] = "FAILED"
                result["reason"] = (
                    f"INTEGRATION_VERIFY_{integration_verify}"
                )

                notify(
                    status="FAILED",
                    reason=result["reason"],
                )

                return {
                    "status": "FAILED",
                    "reason": result["reason"],
                    "results": results,
                }

            cleanup_worker(result)

            completed.add(result["task"]["id"])
            pending.pop(result["task"]["id"], None)

            notify()

        if blocked:
            notify(
                status="BLOCKED",
                reason="WAVE_PARTIALLY_BLOCKED",
            )

            return {
                "status": "BLOCKED",
                "reason": "WAVE_PARTIALLY_BLOCKED",
                "results": results,
            }

    notify(status="COMPLETED")

    return {
        "status": "COMPLETED",
        "reason": None,
        "results": results,
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: jfactory "large task"')

    task = " ".join(sys.argv[1:])

    if not (TARGET_ROOT / ".git").exists():
        raise SystemExit(
            "jfactory requires the current directory to be a Git repository."
        )

    shape = get_shape(task)

    if shape["decision"] == "SINGLE_AGENT":
        run_single(task)

    if shape["decision"] == "NEEDS_HUMAN":
        raise SystemExit("Jev requested human clarification.")

    if shape["decision"] != "DECOMPOSE":
        raise SystemExit(
            f'Unknown shape decision: {shape["decision"]}'
        )

    dirty = output(["git", "status", "--porcelain"], cwd=TARGET_ROOT)

    if dirty:
        raise SystemExit(
            "DECOMPOSE requires a clean working tree. "
            "Commit or stash current changes first."
        )

    run_id = time.strftime("%Y%m%d-%H%M%S")
    started_at = time.time()
    plan_file = STATE_ROOT / f"plan-{run_id}.json"
    run_state_file = STATE_ROOT / f"run-{run_id}.json"

    print()
    print("=====================================")
    print(" CODEX PARENT: DECOMPOSE")
    print("=====================================")

    plan = make_plan(task, plan_file)
    validate_plan(plan)

    print()
    print(json.dumps(plan, indent=2))

    all_results = []

    def update_factory_state(
        current_results,
        *,
        status="RUNNING",
        reason=None,
    ):
        nonlocal all_results

        all_results = current_results

        save_run_state(
            run_state_file,
            run_id=run_id,
            original_task=task,
            started_at=started_at,
            results=all_results,
            status=status,
            plan_file=plan_file,
            reason=reason,
        )

    outcome = execute_task_waves(
        run_id,
        plan["tasks"],
        on_update=update_factory_state,
    )

    all_results = outcome["results"]

    if outcome["status"] != "COMPLETED":
        legacy_prefix = {
            "BLOCKED": "blocked",
            "CONFLICTED": "conflict",
            "FAILED": "verify-fail",
        }.get(outcome["status"], "blocked")

        state_file = (
            STATE_ROOT
            / f"{legacy_prefix}-{run_id}.json"
        )

        state_file.write_text(
            json.dumps(all_results, indent=2) + "\n"
        )

        print()
        print("=====================================")
        print(f" FACTORY {outcome['status']}")
        print("=====================================")
        print("Reason:", outcome.get("reason"))
        print("State :", run_state_file)

        exit_code = {
            "BLOCKED": 2,
            "CONFLICTED": 3,
            "FAILED": 4,
        }.get(outcome["status"], 2)

        raise SystemExit(exit_code)

    print()
    print("=====================================")
    print(" FINAL VERIFY")
    print("=====================================")

    if verify(TARGET_ROOT) != "PASS":
        save_run_state(
            run_state_file,
            run_id=run_id,
            original_task=task,
            started_at=started_at,
            results=all_results,
            status="FAILED",
            plan_file=plan_file,
            reason="FINAL_VERIFY_FAILED",
        )
        raise SystemExit("Final verification failed.")

    save_run_state(
        run_state_file,
        run_id=run_id,
        original_task=task,
        started_at=started_at,
        results=all_results,
        status="COMPLETED",
        plan_file=plan_file,
    )

    print()
    print("=====================================")
    print(" FACTORY COMPLETE")
    print("=====================================")
    print(f"Plan : {plan_file}")
    print(f"State: {run_state_file}")
    print(f"Tasks completed: {len(all_results)}")


if __name__ == "__main__":
    main()
