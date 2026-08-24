#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${XAI_API_KEY:-}" ]]; then
  for candidate in "$repo_dir"/../*/.env; do
    [[ -f "$candidate" ]] || continue
    key_line="$(sed -n 's/^XAI_API_KEY=//p' "$candidate" | head -n 1)"
    if [[ -n "$key_line" ]]; then export XAI_API_KEY="$key_line"; break; fi
  done
fi
cd "$repo_dir"
exec .venv/bin/python -m fastbot.main
