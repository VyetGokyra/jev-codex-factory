#!/usr/bin/env bash
set -euo pipefail

DEMO=/tmp/jev-codex-factory-demo

rm -rf "$DEMO"
mkdir -p "$DEMO/src" "$DEMO/tests"

cd "$DEMO"

git init -b main >/dev/null

cat > src/math.py <<'PY'
def add(a, b):
    return a + b
PY

touch src/__init__.py

cat > tests/test_math.py <<'PY'
from src.math import add

def test_add():
    assert add(2, 3) == 5
PY

git add .
git commit -m "demo baseline" >/dev/null

echo
echo "===================================================="
echo " JEV CODEX FACTORY DEMO"
echo "===================================================="
echo
echo "Goal:"
echo "  1. Add subtract(a, b)"
echo "  2. Implement auth from docs/auth-api.yaml"
echo
echo "The auth contract intentionally does not exist."
echo
echo "Expected behavior:"
echo
echo "  math-subtract → MERGED"
echo "  auth          → BLOCKED_RESOURCE"
echo
echo "Then provide the contract and run:"
echo
echo "  jresume"
echo
echo "The factory should replan the original goal."
echo
