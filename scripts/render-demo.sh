#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
asset_dir="$repo_dir/docs/assets"
pages_dir="${MUSE_OPENROUTER_PAGES_DIR:-$repo_dir/../xhluca.github.io/muse-code-openrouter}"
cast_file="$asset_dir/demo.cast"

if [[ ! -f "$pages_dir/index.html" ]]; then
  echo "Muse OpenRouter Pages checkout not found at $pages_dir." >&2
  echo "Set MUSE_OPENROUTER_PAGES_DIR and rerun." >&2
  exit 2
fi
if [[ ! -f "$cast_file" ]]; then
  echo "Real terminal recording not found at $cast_file." >&2
  echo "Capture it with scripts/capture-live-demo.sh first." >&2
  exit 2
fi
for command in agg ffmpeg; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "$command is required" >&2
    exit 2
  }
done

mkdir -p "$asset_dir" "$pages_dir/assets"
agg --quiet --theme dracula --font-size 35 --cols 90 --rows 28 \
  --idle-time-limit 3600 --fps-cap 20 --last-frame-duration 3 \
  "$cast_file" "$asset_dir/demo.gif"
ffmpeg -hide_banner -loglevel error -y -i "$asset_dir/demo.gif" \
  -vf "pad=ceil(iw/2)*2:ceil(ih/2)*2" \
  -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -movflags +faststart \
  "$asset_dir/demo.mp4"
install -m 0644 "$cast_file" "$pages_dir/assets/demo.cast"
install -m 0644 "$asset_dir/demo.gif" "$pages_dir/assets/demo.gif"
install -m 0644 "$asset_dir/demo.mp4" "$pages_dir/assets/demo.mp4"

echo "Rendered demo.cast as docs/assets/demo.gif and docs/assets/demo.mp4."
