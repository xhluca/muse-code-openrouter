#!/usr/bin/env python3
"""Sanitize a real asciicast and add terminal-native semantic colors."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def styled(text: str, code: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"


def main() -> int:
    if len(sys.argv) != 5:
        print(
            "usage: process-demo-cast.py CAST ACCOUNT DEMO_HOME REPO_DIR",
            file=sys.stderr,
        )
        return 2

    path = Path(sys.argv[1])
    account, demo_home, repo_dir = sys.argv[2:]
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    processed: list[str] = []

    highlights = [
        ("Choose the default Meta Muse model:", "1;35"),
        ("[Contributor: data-use warning]", "1;33"),
        ("OpenRouter API key:", "1;35"),
        ("Live Muse Code request through OpenRouter: accepted", "1;32"),
        ("Muse Code adapter: healthy", "1;32"),
        ("Muse Code is ready. Run: muse", "1;32"),
        ("Hello from Spark.", "1;32"),
        ("Hello from Glimmer.", "1;32"),
        ("meta/muse-glimmer-30b", "1;36"),
        ("meta/muse-spark-1.2-contributor", "1;36"),
        ("meta/muse-spark-1.2", "1;36"),
        ("meta/muse-spark-1.1", "1;36"),
    ]

    for line in raw_lines:
        entry = json.loads(line)
        if isinstance(entry, list) and len(entry) == 3 and entry[1] == "o":
            output = entry[2]
            # The public demo ends on the stable Muse TUI. Do not publish the
            # tmux alternate-screen teardown that follows the actual session.
            if "To continue this session, run muse resume" in output:
                break
            output = output.replace(repo_dir, "~/muse-code-openrouter")
            output = output.replace(account, "demo").replace(demo_home, "~")
            # Muse draws this environment-specific notice in three cursor-
            # positioned fragments before drawing the complete line. Remove
            # all three fragments so no workstation-specific skill count is
            # left behind in a full-screen TUI recording.
            output = re.sub(
                r"\x1b\[23;3HIncluding.*?(?=\x1b\[20;1H)",
                "",
                output,
                flags=re.DOTALL,
            )
            output = re.sub(
                r"\x1b\[23;45Hmanage.*?(?=\x1b\[21;3H)",
                "",
                output,
                flags=re.DOTALL,
            )
            output = re.sub(
                r"\x1b\[23;1H  Including.*?(?=\x1b\[24;1H)",
                "",
                output,
                flags=re.DOTALL,
            )
            output = re.sub(
                r"muse: Including your \d+ Codex personal skills — manage with "
                r"/settings\.\r?\r?\n",
                "",
                output,
            )
            for phrase, code in highlights:
                colored_phrase = styled(phrase, code)
                if colored_phrase not in output:
                    output = output.replace(phrase, colored_phrase)
            entry[2] = output
        processed.append(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))

    path.write_text("\n".join(processed) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
