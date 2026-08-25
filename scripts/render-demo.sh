#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
asset_dir="$repo_dir/docs/assets"
pages_dir="${MUSE_OPENROUTER_PAGES_DIR:-$repo_dir/../xhluca.github.io/muse-code-openrouter}"

if [[ ! -f "$pages_dir/index.html" ]]; then
  echo "Muse OpenRouter Pages checkout not found at $pages_dir." >&2
  echo "Set MUSE_OPENROUTER_PAGES_DIR and rerun." >&2
  exit 2
fi

mkdir -p "$asset_dir" "$pages_dir/assets"
uv run --script "$script_dir/render-demo.py" "$pages_dir" "$asset_dir"
install -m 0644 "$asset_dir/demo.gif" "$pages_dir/assets/demo.gif"
install -m 0644 "$asset_dir/demo.mp4" "$pages_dir/assets/demo.mp4"

echo "Rendered docs/assets/demo.gif and docs/assets/demo.mp4."
