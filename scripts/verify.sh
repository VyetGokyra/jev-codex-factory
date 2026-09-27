#!/usr/bin/env bash
set -uo pipefail

FAILED=0
RAN_ANY=0

echo
echo "========== VERIFY =========="

# Project-specific verifier takes priority.
if [ -x "./scripts/verify.sh" ] && \
   [ "$(readlink -f ./scripts/verify.sh)" != "$(readlink -f "$0")" ]; then
    echo "[project verify]"
    ./scripts/verify.sh
    exit $?
fi

# -------------------------------------------------
# Python
# -------------------------------------------------
if [ -d tests ] && find tests -type f -name 'test_*.py' | grep -q .; then

    # Prefer pytest when Python can import it.
    if python -c 'import pytest' >/dev/null 2>&1; then
        echo "[pytest]"
        RAN_ANY=1

        PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
        PYTHONDONTWRITEBYTECODE=1 \
        python -m pytest \
            -q \
            -p no:cacheprovider \
            || FAILED=1

    else
        echo "[unittest discovery check]"

        TEST_COUNT="$(
            PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
import unittest

suite = unittest.defaultTestLoader.discover("tests")
print(suite.countTestCases())
PY
        )"

        echo "Discovered unittest cases: $TEST_COUNT"

        if [ "$TEST_COUNT" -gt 0 ]; then
            RAN_ANY=1
            PYTHONDONTWRITEBYTECODE=1 \
                python -m unittest discover -s tests \
                || FAILED=1
        else
            echo "Python tests exist but no runnable test framework was found."
        fi
    fi
fi

# -------------------------------------------------
# Node
# -------------------------------------------------
if [ -f package.json ]; then
    RAN_ANY=1

    if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1; then
        echo "[pnpm test]"
        pnpm test || FAILED=1
    elif [ -f yarn.lock ] && command -v yarn >/dev/null 2>&1; then
        echo "[yarn test]"
        yarn test || FAILED=1
    elif command -v npm >/dev/null 2>&1; then
        echo "[npm test]"
        npm test || FAILED=1
    else
        FAILED=1
    fi
fi

# -------------------------------------------------
# Rust
# -------------------------------------------------
if [ -f Cargo.toml ]; then
    RAN_ANY=1
    command -v cargo >/dev/null 2>&1 && cargo test || FAILED=1
fi

# -------------------------------------------------
# Go
# -------------------------------------------------
if [ -f go.mod ]; then
    RAN_ANY=1
    command -v go >/dev/null 2>&1 && go test ./... || FAILED=1
fi

echo
echo "========== RESULT =========="

if [ "$FAILED" -ne 0 ]; then
    echo "VERIFY_FAIL"
    exit 1
fi

if [ "$RAN_ANY" -eq 0 ]; then
    echo "VERIFY_INCONCLUSIVE"
    exit 2
fi

echo "VERIFY_PASS"
exit 0
