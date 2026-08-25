#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
key_file="${1:-}"
cast_file="${2:-$repo_dir/docs/assets/demo.cast}"
demo_home="${MUSE_OPENROUTER_DEMO_HOME:-}"

if [[ -z "$key_file" || ! -f "$key_file" ]]; then
  echo "usage: scripts/capture-live-demo.sh TEMPORARY_OPENROUTER_KEY_FILE [CAST_FILE]" >&2
  exit 2
fi
if [[ ! -x "$script_dir/capture-live-demo.exp" ]]; then
  echo "capture-live-demo.exp is not executable" >&2
  exit 2
fi
for command in asciinema expect muse uv; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "$command is required" >&2
    exit 2
  }
done
if [[ -n "$demo_home" ]]; then
  if [[ -e "$demo_home" ]]; then
    echo "refusing to overwrite existing demo home: $demo_home" >&2
    exit 2
  fi
  mkdir -m 0700 -p "$demo_home"
else
  demo_home="$(mktemp -d "${TMPDIR:-/tmp}/muse-openrouter-demo-home.XXXXXXXX")"
fi

mkdir -p "$(dirname "$cast_file")"
cleanup() {
  if [[ -x "$demo_home/.local/bin/muse-openrouter" ]]; then
    HOME="$demo_home" \
      XDG_CONFIG_HOME="$demo_home/.config" \
      XDG_STATE_HOME="$demo_home/.local/state" \
      XDG_DATA_HOME="$demo_home/.local/share" \
      "$demo_home/.local/bin/muse-openrouter" uninstall >/dev/null 2>&1 || true
  fi
  if [[ -d "$demo_home" && ! -L "$demo_home" ]]; then
    rm -rf -- "$demo_home"
  fi
}
trap cleanup EXIT

asciinema rec --quiet --overwrite --cols 110 --rows 30 --idle-time-limit 2 \
  --title "Muse Code OpenRouter — real install and model switch" \
  --command "$script_dir/capture-live-demo.exp '$key_file' '$demo_home'" \
  "$cast_file"

# The terminal does not echo the key and asciinema does not capture stdin.
# Fail closed anyway if a credential-shaped string made it into stdout.
if LC_ALL=C grep -aEq 'sk-or-v1-[A-Za-z0-9_-]{20,}' "$cast_file"; then
  echo "refusing to keep a recording containing an OpenRouter key" >&2
  exit 1
fi

# Avoid publishing the workstation account name while preserving real output.
python3 - "$cast_file" "$(id -un)" "$demo_home" "$repo_dir" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
account = sys.argv[2]
demo_home = sys.argv[3]
repo_dir = sys.argv[4]
content = path.read_text(encoding="utf-8")
path.write_text(
    content.replace(repo_dir, "~/muse-code-openrouter")
    .replace(account, "demo")
    .replace(demo_home, "~"),
    encoding="utf-8",
)
PY

for marker in \
  "Live Muse Code request through OpenRouter: accepted" \
  "SPARK_READY" \
  "GLIMMER_READY" \
  "Muse Code OpenRouter integration removed"; do
  grep -aFq "$marker" "$cast_file" || {
    echo "recording is incomplete; missing: $marker" >&2
    exit 1
  }
done

echo "Recorded real workflow to $cast_file"
