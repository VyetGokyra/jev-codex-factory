#!/usr/bin/env bash
set -euo pipefail

DEMO=/tmp/jev-codex-factory-demo

cd "$DEMO"

jfactory \
  "Do two independent tasks:
   1) add subtract(a,b) to src/math.py with tests;
   2) implement src/auth.py using docs/auth-api.yaml.
   Do not invent the authentication contract if it is missing."
