#!/usr/bin/env bash
set -euo pipefail

fail=0

check_cmd() {
    if command -v "$1" >/dev/null 2>&1; then
        echo "✓ $1"
    else
        echo "✗ $1 missing"
        fail=1
    fi
}

echo "Jev Codex Factory Doctor"
echo "========================"

check_cmd git
check_cmd python
check_cmd codex

python - <<'PY' || fail=1
try:
    import typesafe_sdk
    print("✓ typesafe_sdk")
except Exception:
    print("✗ typesafe_sdk missing")
    raise SystemExit(1)
PY

if [ -n "${TYPESAFE_API_KEY:-}" ]; then
    echo "✓ TYPESAFE_API_KEY"
elif [ -f .env ] && grep -q '^TYPESAFE_API_KEY=' .env; then
    echo "✓ TYPESAFE_API_KEY in .env"
else
    echo "✗ TYPESAFE_API_KEY missing"
    fail=1
fi

if [ "$fail" -ne 0 ]; then
    echo
    echo "Doctor found setup problems."
    exit 1
fi

echo
echo "Environment looks ready."
