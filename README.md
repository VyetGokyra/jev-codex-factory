<div align="center">

# ⚡ Jev Codex Factory

<p align="center">
  <a href="https://github.com/VyetGokyra/jev-codex-factory/actions/workflows/ci.yml">
    <img src="https://github.com/VyetGokyra/jev-codex-factory/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="https://github.com/VyetGokyra/jev-codex-factory/releases/tag/v0.1.0">
    <img src="https://img.shields.io/github/v/release/VyetGokyra/jev-codex-factory" alt="Release">
  </a>
  <a href="https://github.com/VyetGokyra/jev-codex-factory/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/VyetGokyra/jev-codex-factory" alt="License">
  </a>
  <img src="https://img.shields.io/badge/Jev-powered-7c3aed" alt="Jev powered">
  <img src="https://img.shields.io/badge/Codex-multi--agent-111827" alt="Codex multi-agent">
</p>

### Route smarter. Code in parallel. Resume what breaks.

**A Jev-powered multi-agent coding factory for OpenAI Codex.**

Turn one engineering request into a routed, parallel, verified, resumable swarm of coding agents.

```text
One task
   ↓
Jev decides how to execute it
   ↓
Codex agents work in parallel
   ↓
Verification gates every change
   ↓
Failures get classified, not blindly retried
   ↓
Blocked work can resume later
```

</div>

---

## Why this exists

Most coding-agent workflows still look roughly like this:

```text
prompt
  ↓
one big model
  ↓
hope it understands everything
  ↓
hope tests pass
  ↓
hope the repo is still clean
```

That works for small tasks.

It gets messy when the job contains independent subtasks, different reasoning difficulty, missing dependencies, flaky verification, parallel file edits, partial failures, or interrupted sessions.

**Jev Codex Factory turns coding into an execution system instead of a single model call.**

---

# The idea

Jev does not write the code.

Jev decides **how the code should be written**.

```text
                    ┌───────────────────────┐
                    │      USER TASK        │
                    └───────────┬───────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │  JEV SHAPE #0   │
                       │ single or DAG?  │
                       └───────┬─────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
       SINGLE AGENT                         DECOMPOSE
              │                                 │
              ▼                                 ▼
       JEV ROUTER #1                        TASK DAG
       model + effort                          │
              │                        ┌────────┼────────┐
              ▼                        ▼        ▼        ▼
          CODEX                    worker A worker B worker C
              │                        │        │        │
              │                        └────────┼────────┘
              │                                 │
              └────────────────┬────────────────┘
                               ▼
                         VERIFICATION
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
                 ▼                           ▼
               PASS                         FAIL
                 │                           │
                 ▼                           ▼
               MERGE                    JEV #2
                                      post-failure
                                          │
                    ┌─────────┬────────────┼────────────┐
                    ▼         ▼            ▼            ▼
                  RETRY    ESCALATE      BLOCK      NEEDS HUMAN
```

---

# What makes it different

| Typical coding agent | Jev Codex Factory |
|---|---|
| One model for everything | Routes each task to a model/effort lane |
| Sequential execution | Parallel DAG execution |
| Agents share one working tree | Isolated Git worktrees |
| Test failure = retry | Jev classifies the failure |
| Missing resource = model keeps trying | `BLOCKED_RESOURCE` |
| Missing code dependency = confusion | `BLOCKED_DEPENDENCY` |
| Agent exit = success | Verification is the actual completion gate |
| Interrupted task = lost context | Canonical resumable run state |
| Resume old task blindly | Re-evaluate the original goal |
| Bad merge may stay in repo | Automatic rollback |
| Parallel agents may overwrite files | File ownership conflict detection |

---

# A real example

Suppose you ask:

```bash
jfactory \
  "Add subtraction support, implement authentication from the API contract, \
  add tests, and document the new API."
```

The factory may produce:

```text
JEV SHAPE
└── DECOMPOSE

WAVE 1
├── math-subtract
│   ├── route: SOL_MEDIUM
│   ├── verify: PASS
│   └── MERGED
│
└── auth-contract
    ├── contract missing
    └── BLOCKED_RESOURCE
```

Instead of hallucinating an API contract or repeatedly escalating to a stronger model, the run stops safely.

Later you provide the missing contract:

```bash
jresume
```

The system re-checks the **original user goal**:

```text
POST-RESUME REPLAN

✓ subtraction already complete
✓ auth contract now exists
✗ auth implementation still missing

NEW TASK
└── implement-auth-client
    ├── route: LUNA_HIGH
    ├── verify: PASS
    └── MERGED
```

Final state:

```text
JEV CODEX FACTORY STATUS

TASK                   STATUS             MODEL
--------------------------------------------------------
math-subtract          MERGED             gpt-5.6-sol
restore-auth-contract  MERGED             gpt-5.6-sol
implement-auth-client  MERGED             gpt-5.6-luna

Status: COMPLETED
```

> **Don't retry harder when the real problem is that something is missing.**

---

# Jev as the decision layer

Jev is used in three places.

## 1. Execution shape

```text
SINGLE_AGENT
DECOMPOSE
NEEDS_HUMAN
```

A difficult task is not automatically decomposed. A task is decomposed when decomposition actually creates useful independent work.

## 2. Model routing

Workers can be routed into lanes such as:

```text
LUNA_LOW
LUNA_HIGH
TERRA_HIGH
SOL_MEDIUM
SOL_HIGH
SOL_XHIGH
ASTRA_HIGH
VERIFY_ONLY
STOP_AND_REPORT
```

Example:

```text
small local edit
      ↓
LUNA_LOW

hard bounded debugging
      ↓
SOL_HIGH

deep cross-module investigation
      ↓
SOL_XHIGH
```

Low-confidence routing can fall back to a safer lane.

## 3. Post-failure decisions

After verification fails, Jev can choose:

```text
RETRY_SAME
RETRY_HIGHER_EFFORT
ESCALATE_MODEL
BLOCKED_RESOURCE
BLOCKED_DEPENDENCY
NEEDS_HUMAN
STOP
```

That gives the factory a useful distinction between:

```text
"The model needs to think harder"

and

"The model literally cannot proceed."
```

---

# Parallel coding without agent chaos

Large tasks are converted into a dependency DAG:

```text
          ┌── backend-api ──┐
          │                 │
START ────┤                 ├── integration-tests
          │                 │
          └── frontend-ui ──┘
```

Independent tasks execute in parallel:

```text
Wave 1
├── backend-api
└── frontend-ui

Wave 2
└── integration-tests
```

Each worker receives:

- its own Git worktree
- its own branch
- explicit file ownership
- task-specific acceptance criteria
- independent model routing
- isolated telemetry
- verification before merge

---

# Verification is the merge gate

A successful Codex process is not considered task success.

```text
Codex exits 0
      ↓
verification
      ↓
PASS?
```

Only then is the worker allowed through the merge gate.

```text
worker branch
      ↓
merge
      ↓
integration verify
      ↓
PASS → keep merge
FAIL → rollback to pre-merge HEAD
```

---

# Resume instead of restart

Blocked runs preserve run ID, original user goal, completed tasks, blocked tasks, worktrees, model route, reasoning effort, Jev confidence, attempts, and verification result.

Then:

```bash
jresume
```

can continue the same run.

More importantly, the system performs a **post-resume replan**.

It does not assume:

```text
old plan finished
=
original goal finished
```

---

# Canonical run state

```bash
jstatus
```

Example:

```text
JEV CODEX FACTORY STATUS
================================================================================
Run   : 20260927-183706
Shape : DECOMPOSE
Status: COMPLETED

   TASK                   STATUS           MODEL            EFFORT   CONF
--------------------------------------------------------------------------------
✓  math-subtract          MERGED           gpt-5.6-sol      medium   0.54
✓  restore-auth-contract  MERGED           gpt-5.6-sol      medium   0.57
✓  implement-auth-client  MERGED           gpt-5.6-luna     high     0.96
```

---

# Install

## Requirements

- Git
- Python 3.10+
- OpenAI Codex CLI
- TypeSafe Jev access

Clone:

```bash
git clone https://github.com/VyetGokyra/jev-codex-factory.git
cd jev-codex-factory
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Configure Jev:

```bash
cp .env.example .env
```

Then add:

```bash
TYPESAFE_API_KEY=your_key_here
```

Install the commands:

```bash
./install.sh
```

Check your environment:

```bash
./scripts/doctor.sh
```

Expected:

```text
Jev Codex Factory Doctor
========================
✓ git
✓ python
✓ codex
✓ typesafe_sdk
✓ TYPESAFE_API_KEY

Environment looks ready.
```

---

# Four commands

## `jcodex`

One coding task with Jev routing.

```bash
jcodex "Fix the parser edge cases and update tests."
```

## `jfactory`

Multi-agent execution.

```bash
jfactory \
  "Implement authentication, validation, tests and documentation."
```

## `jstatus`

Inspect the latest run.

```bash
jstatus
```

## `jresume`

Continue blocked work.

```bash
jresume
```

or:

```bash
jresume state/run-20260927-183706.json
```

---

# Safety mechanisms

```text
✓ clean-target merge gate
✓ isolated Git worktrees
✓ path-prefix file ownership checks
✓ verification before merge
✓ integration verification
✓ pre-merge HEAD capture
✓ failed-integration rollback
✓ generated artifact cleanup
✓ stale worktree cleanup
✓ stale branch cleanup
✓ maximum retry budget
✓ semantic blocker classification
```

---

# Project structure

```text
jev-codex-factory/
│
├── schemas/
│   ├── plan.schema.json
│   └── replan.schema.json
│
├── scripts/
│   ├── factory.py
│   ├── resume.py
│   ├── run.sh
│   ├── status.py
│   ├── jev_shape.py
│   ├── jev_router.py
│   ├── jev_after_run.py
│   ├── states.py
│   ├── verify.sh
│   └── doctor.sh
│
├── install.sh
├── requirements.txt
└── .env.example
```

---

# Design philosophy

### Jev decides. Codex executes.

Use Jev where a fast decision is more useful than another long generation.

### Use the cheapest reliable model.

Not every edit needs the strongest model.

### Parallelism must be explicit.

Agents only run concurrently when dependencies and file ownership allow it.

### Verification beats confidence.

A model saying “done” does not mean the task is done.

### Blockers are information.

Missing resources should not trigger increasingly expensive hallucination.

### Resume the goal, not merely the task.

The original user request remains the source of truth.

---

# Roadmap

### v0.1

- [x] Jev execution-shape routing
- [x] model/effort routing
- [x] low-confidence fallback
- [x] DAG decomposition
- [x] parallel worktrees
- [x] verification gates
- [x] adaptive retry/escalation
- [x] semantic blocker states
- [x] canonical run state
- [x] resume
- [x] post-resume replanning
- [x] integration rollback
- [x] stale worktree recovery

### Next

- [ ] token / latency / cost telemetry
- [ ] richer run history
- [ ] interactive `jstatus --watch`
- [ ] configurable routing policies
- [ ] worker concurrency limits
- [ ] policy benchmarks
- [ ] Web UI
- [ ] provider-independent agent backends

---

# Research question

> **Can a small, fast decision model orchestrating stronger coding models outperform always calling the strongest model?**

Interesting dimensions include:

```text
cost
latency
success rate
retry count
verification pass rate
model escalation frequency
parallel speedup
```

If you're experimenting with Jev, coding agents, model routing, or agent orchestration, contributions and benchmark results are welcome.

---

# Contributing

Issues, experiments, routing ideas, failure cases, and strange agent behavior are welcome.

Especially useful:

- tasks where Jev routing clearly saves compute
- cases where model escalation helps
- false-positive blockers
- resume/replan edge cases
- multi-agent merge failures
- alternative routing policies

---

# License

Apache License 2.0.

---

<div align="center">

### If this idea is useful, star the repo and try breaking it.

The interesting part of agent systems is not when everything works.

**It's what they do when something doesn't.**

</div>
