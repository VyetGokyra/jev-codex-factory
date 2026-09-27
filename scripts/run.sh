#!/usr/bin/env bash

set -euo pipefail

TASK="${*:-}"

if [ -z "$TASK" ]; then
    echo 'Usage: ./scripts/run.sh "your task"'
    exit 1
fi

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
ENGINE_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
TARGET_ROOT="$(pwd)"
cd "$ENGINE_ROOT"

if [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"
fi

mkdir -p state logs

echo
echo "====================================="
echo " JEV #1 - PRE ROUTE"
echo "====================================="

RESULT="$(python scripts/jev_router.py "$TASK")"
echo "$RESULT"

DECISION="$(
python -c '
import json,sys
x=json.load(sys.stdin)
print(x["decision"])
' <<< "$RESULT"
)"

CONFIDENCE="$(
python -c '
import json,sys
x=json.load(sys.stdin)
print(x["confidence"])
' <<< "$RESULT"
)"

ROUTE_DECISION="$DECISION"

write_telemetry() {
    local status="${1:-UNKNOWN}"
    local verify_result="${2:-NOT_RUN}"
    local codex_exit="${3:-}"
    local attempts="${4:-0}"

    [ -z "${JEV_TELEMETRY_FILE:-}" ] && return 0

    mkdir -p "$(dirname "$JEV_TELEMETRY_FILE")"

    TELEMETRY_STATUS="$status" \
    TELEMETRY_VERIFY="$verify_result" \
    TELEMETRY_CODEX_EXIT="$codex_exit" \
    TELEMETRY_ATTEMPTS="$attempts" \
    TELEMETRY_ROUTE_DECISION="${ROUTE_DECISION:-}" \
    TELEMETRY_WORKER="${WORKER:-${DECISION:-}}" \
    TELEMETRY_MODEL="${MODEL:-}" \
    TELEMETRY_EFFORT="${EFFORT:-}" \
    TELEMETRY_CONFIDENCE="${CONFIDENCE:-}" \
    TELEMETRY_RUN_ID="${JEV_RUN_ID:-}" \
    TELEMETRY_TASK_ID="${JEV_TASK_ID:-}" \
    python - "$JEV_TELEMETRY_FILE" <<'PYTELEMETRY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])

def maybe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def maybe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

data = {
    "run_id": os.environ.get("TELEMETRY_RUN_ID") or None,
    "task_id": os.environ.get("TELEMETRY_TASK_ID") or None,
    "route_decision": os.environ.get("TELEMETRY_ROUTE_DECISION") or None,
    "worker": os.environ.get("TELEMETRY_WORKER") or None,
    "model": os.environ.get("TELEMETRY_MODEL") or None,
    "effort": os.environ.get("TELEMETRY_EFFORT") or None,
    "jev_confidence": maybe_float(
        os.environ.get("TELEMETRY_CONFIDENCE")
    ),
    "attempts": maybe_int(
        os.environ.get("TELEMETRY_ATTEMPTS")
    ),
    "codex_exit": maybe_int(
        os.environ.get("TELEMETRY_CODEX_EXIT")
    ),
    "verify_result": os.environ.get("TELEMETRY_VERIFY") or None,
    "worker_status": os.environ.get("TELEMETRY_STATUS") or None,
}

tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
tmp.replace(path)
PYTELEMETRY
}

echo
echo "Decision   : $DECISION"
echo "Confidence : $CONFIDENCE"

LOW_CONF="$(
python -c '
import sys
print("yes" if float(sys.argv[1]) < 0.60 else "no")
' "$CONFIDENCE"
)"

if [ "$LOW_CONF" = "yes" ]; then
    echo "Jev confidence < 0.60"

    if [ "$DECISION" = "STOP_AND_REPORT" ]; then
        echo "STOP_AND_REPORT"
        write_telemetry "BLOCKED_RESOURCE" "NOT_RUN" "" "0"
        exit 2
    fi

    if [ "$DECISION" != "VERIFY_ONLY" ]; then
        echo "Low-confidence routing: fallback -> SOL_MEDIUM"
        DECISION="SOL_MEDIUM"
    fi
fi

run_codex() {
    local worker="$1"
    local task="$2"

    case "$worker" in
        LUNA_LOW)
            MODEL="gpt-5.6-luna"
            EFFORT="low"
            ;;
        LUNA_HIGH)
            MODEL="gpt-5.6-luna"
            EFFORT="high"
            ;;
        TERRA_HIGH)
            MODEL="gpt-5.6-terra"
            EFFORT="high"
            ;;
        SOL_MEDIUM)
            MODEL="gpt-5.6-sol"
            EFFORT="medium"
            ;;
        SOL_HIGH)
            MODEL="gpt-5.6-sol"
            EFFORT="high"
            ;;
        SOL_XHIGH)
            MODEL="gpt-5.6-sol"
            EFFORT="xhigh"
            ;;
        ASTRA_HIGH)
            MODEL="gpt-6-astra"
            EFFORT="high"
            ;;
        *)
            echo "Unknown worker: $worker"
            return 3
            ;;
    esac

    echo
    echo "====================================="
    echo " CODEX WORKER: $worker"
    echo " MODEL: $MODEL"
    echo "====================================="

    codex exec \
        -s workspace-write \
        -m "$MODEL" \
        -c model_reasoning_effort="\"$EFFORT\"" \
        -C "$TARGET_ROOT" \
        -o "$ENGINE_ROOT/state/codex_last.txt" \
        "$task"
}

run_verify() {
    echo
    echo "====================================="
    echo " VERIFY: $TARGET_ROOT"
    echo "====================================="

    local verify_exit

    if [ -x "$TARGET_ROOT/scripts/verify.sh" ]; then
        (cd "$TARGET_ROOT" && ./scripts/verify.sh) | tee "$ENGINE_ROOT/logs/verify_last.log"
        verify_exit=${PIPESTATUS[0]}
    else
        (cd "$TARGET_ROOT" && "$ENGINE_ROOT/scripts/verify.sh") | tee "$ENGINE_ROOT/logs/verify_last.log"
        verify_exit=${PIPESTATUS[0]}
    fi

    return "$verify_exit"
}

case "$DECISION" in
    LUNA_LOW|LUNA_HIGH|TERRA_HIGH|SOL_MEDIUM|SOL_HIGH|SOL_XHIGH|ASTRA_HIGH)
        WORKER="$DECISION"
        ;;

    VERIFY_ONLY)
        WORKER="VERIFY_ONLY"
        MODEL=""
        EFFORT=""

        if run_verify; then
            echo
            echo "DONE: verification passed."
            write_telemetry "COMPLETED" "PASS" "" "0"
            exit 0
        else
            VERIFY_EXIT=$?
            echo
            echo "Verification failed."
            write_telemetry "FAILED" "FAIL" "" "0"
            exit "$VERIFY_EXIT"
        fi
        ;;

    STOP_AND_REPORT)
        WORKER="STOP_AND_REPORT"
        echo "Jev requested STOP_AND_REPORT."
        write_telemetry "BLOCKED_RESOURCE" "NOT_RUN" "" "0"
        exit 2
        ;;

    *)
        echo "Unknown Jev decision: $DECISION"
        exit 3
        ;;
esac

next_higher_effort_lane() {
    case "$1" in
        LUNA_LOW)
            echo "LUNA_HIGH"
            ;;
        SOL_MEDIUM)
            echo "SOL_HIGH"
            ;;
        SOL_HIGH)
            echo "SOL_XHIGH"
            ;;
        *)
            echo "$1"
            ;;
    esac
}

next_stronger_model_lane() {
    case "$1" in
        LUNA_LOW|LUNA_HIGH)
            echo "TERRA_HIGH"
            ;;
        TERRA_HIGH)
            echo "SOL_MEDIUM"
            ;;
        SOL_MEDIUM)
            echo "SOL_HIGH"
            ;;
        SOL_HIGH)
            echo "SOL_XHIGH"
            ;;
        SOL_XHIGH)
            echo "ASTRA_HIGH"
            ;;
        ASTRA_HIGH)
            echo "ASTRA_HIGH"
            ;;
        *)
            echo "SOL_MEDIUM"
            ;;
    esac
}

ATTEMPTS=0
MAX_ATTEMPTS=3

while true; do
    ATTEMPTS=$((ATTEMPTS + 1))

    set +e
    run_codex "$WORKER" "$TASK"
    CODEX_EXIT=$?
    set -e

    echo
    echo "Codex exit code: $CODEX_EXIT"

    set +e
    run_verify
    VERIFY_EXIT=$?
    set -e

    if [ "$VERIFY_EXIT" -eq 0 ]; then
        echo
        echo "====================================="
        echo " DONE"
        echo "====================================="
        echo "Worker   : $WORKER"
        echo "Attempts : $ATTEMPTS"
        echo "Verify   : PASS"
        write_telemetry "COMPLETED" "PASS" "$CODEX_EXIT" "$ATTEMPTS"
        exit 0
    fi

    if [ "$VERIFY_EXIT" -eq 2 ]; then
        VERIFY_RESULT="INCONCLUSIVE"
    else
        VERIFY_RESULT="FAIL"
    fi

    echo
    echo "Verification failed with exit code: $VERIFY_EXIT"

    echo
    echo "====================================="
    echo " JEV #2 - POST FAILURE"
    echo "====================================="

    POST_RESULT="$(
        python scripts/jev_after_run.py \
            "$TASK" \
            "$WORKER" \
            "$VERIFY_EXIT" \
            "$ATTEMPTS"
    )"

    echo "$POST_RESULT"

    POST_DECISION="$(
    python -c '
import json,sys
x=json.load(sys.stdin)
print(x["decision"])
' <<< "$POST_RESULT"
    )"

    POST_CONFIDENCE="$(
    python -c '
import json,sys
x=json.load(sys.stdin)
print(x["confidence"])
' <<< "$POST_RESULT"
    )"

    echo
    echo "Post decision   : $POST_DECISION"
    echo "Post confidence : $POST_CONFIDENCE"

    LOW_POST_CONF="$(
    python -c '
import sys
print("yes" if float(sys.argv[1]) < 0.60 else "no")
' "$POST_CONFIDENCE"
    )"

    if [ "$LOW_POST_CONF" = "yes" ]; then
        echo "Post-run Jev confidence < 0.60"
        echo "NEEDS_HUMAN"

        write_telemetry             "NEEDS_HUMAN"             "$VERIFY_RESULT"             "$CODEX_EXIT"             "$ATTEMPTS"

        exit 2
    fi

    case "$POST_DECISION" in
        RETRY_SAME)
            if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
                echo "Maximum attempts reached; retry denied."
                write_telemetry                     "FAILED"                     "$VERIFY_RESULT"                     "$CODEX_EXIT"                     "$ATTEMPTS"
                exit 2
            fi

            echo "Retrying same lane: $WORKER"
            ;;

        RETRY_HIGHER_EFFORT)
            if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
                echo "Maximum attempts reached; RETRY_HIGHER_EFFORT denied."
                write_telemetry \
                    "FAILED" \
                    "$VERIFY_RESULT" \
                    "$CODEX_EXIT" \
                    "$ATTEMPTS"
                exit 2
            fi
            OLD_WORKER="$WORKER"
            WORKER="$(next_higher_effort_lane "$WORKER")"

            echo "Higher-effort retry:"
            echo "  $OLD_WORKER -> $WORKER"

            if [ "$WORKER" = "$OLD_WORKER" ]; then
                echo "No higher-effort lane available."
            fi
            ;;

        ESCALATE_MODEL)
            if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
                echo "Maximum attempts reached; ESCALATE_MODEL denied."
                write_telemetry \
                    "FAILED" \
                    "$VERIFY_RESULT" \
                    "$CODEX_EXIT" \
                    "$ATTEMPTS"
                exit 2
            fi
            OLD_WORKER="$WORKER"
            WORKER="$(next_stronger_model_lane "$WORKER")"

            echo "Model escalation:"
            echo "  $OLD_WORKER -> $WORKER"

            if [ "$WORKER" = "$OLD_WORKER" ]; then
                echo "Already at strongest available lane."
            fi
            ;;

        BLOCKED_RESOURCE)
            echo "Jev classified failure as BLOCKED_RESOURCE."
            write_telemetry                 "BLOCKED_RESOURCE"                 "$VERIFY_RESULT"                 "$CODEX_EXIT"                 "$ATTEMPTS"
            exit 2
            ;;

        BLOCKED_DEPENDENCY)
            echo "Jev classified failure as BLOCKED_DEPENDENCY."
            write_telemetry                 "BLOCKED_DEPENDENCY"                 "$VERIFY_RESULT"                 "$CODEX_EXIT"                 "$ATTEMPTS"
            exit 2
            ;;

        NEEDS_HUMAN)
            echo "Jev classified failure as NEEDS_HUMAN."
            write_telemetry                 "NEEDS_HUMAN"                 "$VERIFY_RESULT"                 "$CODEX_EXIT"                 "$ATTEMPTS"
            exit 2
            ;;

        STOP)
            echo "Jev requested autonomous stop."
            write_telemetry                 "FAILED"                 "$VERIFY_RESULT"                 "$CODEX_EXIT"                 "$ATTEMPTS"
            exit 2
            ;;

        *)
            echo "Unknown post-run decision: $POST_DECISION"
            write_telemetry                 "FAILED"                 "$VERIFY_RESULT"                 "$CODEX_EXIT"                 "$ATTEMPTS"
            exit 3
            ;;
    esac
done
