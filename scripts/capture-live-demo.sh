#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
key_file="${1:-}"
cast_file="${2:-$repo_dir/docs/assets/demo.cast}"
demo_home="${MUSE_OPENROUTER_DEMO_HOME:-}"
demo_port="${MUSE_OPENROUTER_DEMO_PORT:-}"

if [[ -z "$key_file" || ! -f "$key_file" ]]; then
  echo "usage: scripts/capture-live-demo.sh TEMPORARY_OPENROUTER_KEY_FILE [CAST_FILE]" >&2
  exit 2
fi
if [[ ! -x "$script_dir/capture-live-demo.exp" ]]; then
  echo "capture-live-demo.exp is not executable" >&2
  exit 2
fi
for command in asciinema expect muse python3 uv; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "$command is required" >&2
    exit 2
  }
done
if [[ -z "$demo_port" ]]; then
  demo_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
fi
if [[ ! "$demo_port" =~ ^[0-9]+$ ]] || ((demo_port < 1 || demo_port > 65535)); then
  echo "MUSE_OPENROUTER_DEMO_PORT must be a valid TCP port" >&2
  exit 2
fi
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
  pid_file="$demo_home/.local/state/muse-code-openrouter/proxy.pid"
  if [[ -f "$pid_file" ]]; then
    read -r demo_pid <"$pid_file" || demo_pid=""
    if [[ "$demo_pid" =~ ^[0-9]+$ ]]; then
      kill "$demo_pid" >/dev/null 2>&1 || true
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$demo_pid" >/dev/null 2>&1 || break
        sleep 0.1
      done
      kill -KILL "$demo_pid" >/dev/null 2>&1 || true
    fi
  fi
  if [[ -d "$demo_home" && ! -L "$demo_home" ]]; then
    rm -rf -- "$demo_home"
  fi
}
trap cleanup EXIT

asciinema rec --quiet --overwrite --cols 110 --rows 30 \
  --title "Muse Code OpenRouter — real install and model switch" \
  --command "$script_dir/capture-live-demo.exp '$key_file' '$demo_home' '$demo_port'" \
  "$cast_file"

# The terminal does not echo the key and asciinema does not capture stdin.
# Fail closed anyway if a credential-shaped string made it into stdout.
if LC_ALL=C grep -aEq 'sk-or-v1-[A-Za-z0-9_-]{20,}' "$cast_file"; then
  echo "refusing to keep a recording containing an OpenRouter key" >&2
  exit 1
fi

# Avoid publishing workstation paths and add terminal-native semantic colors.
python3 "$script_dir/process-demo-cast.py" \
  "$cast_file" "$(id -un)" "$demo_home" "$repo_dir"

for marker in \
  "Live Muse Code request through OpenRouter: accepted" \
  "SPARK_READY" \
  "GLIMMER_READY"; do
  grep -aFq "$marker" "$cast_file" || {
    echo "recording is incomplete; missing: $marker" >&2
    exit 1
  }
done

echo "Recorded real workflow to $cast_file"
