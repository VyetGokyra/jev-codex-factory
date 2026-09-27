#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"

mkdir -p "$BIN_DIR"

link_cmd() {
    local name="$1"
    local target="$2"

    ln -sfn "$ROOT/$target" "$BIN_DIR/$name"
    echo "installed: $BIN_DIR/$name -> $ROOT/$target"
}

link_cmd jcodex scripts/run.sh
link_cmd jfactory scripts/factory.py
link_cmd jresume scripts/resume.py
link_cmd jstatus scripts/status.py

chmod +x \
    "$ROOT/scripts/run.sh" \
    "$ROOT/scripts/factory.py" \
    "$ROOT/scripts/resume.py" \
    "$ROOT/scripts/status.py" \
    "$ROOT/scripts/jev_router.py" \
    "$ROOT/scripts/jev_shape.py" \
    "$ROOT/scripts/jev_after_run.py"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo
    echo "NOTE: $BIN_DIR is not currently in PATH."
    echo 'Add this to your shell profile:'
    echo 'export PATH="$HOME/.local/bin:$PATH"'
fi

echo
echo "Jev Codex Factory installed."
echo
echo "Commands:"
echo "  jcodex   - single routed coding task"
echo "  jfactory - decomposed multi-agent task"
echo "  jresume  - resume blocked/incomplete runs"
echo "  jstatus  - inspect canonical run state"
