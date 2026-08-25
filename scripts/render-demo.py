#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.55.0"]
# ///
"""Render the website's interactive terminal demo as MP4 and GIF."""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

FPS = 10
DURATION_SECONDS = 6


def browser_executable() -> Path:
    cache = Path.home() / ".cache" / "ms-playwright"
    candidates = sorted(
        [
            *cache.glob("chromium-*/chrome-linux64/chrome"),
            *cache.glob("chromium-*/chrome-linux/chrome"),
        ],
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("no Playwright Chromium executable found")
    return candidates[0]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextlib.contextmanager
def static_server(root: Path):
    port = free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def encode(frames: Path, mp4: Path, gif: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            str(frames / "frame-%04d.png"),
            "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
    )
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(mp4),
            "-vf",
            "fps=10,split[s0][s1];"
            "[s0]palettegen=max_colors=96[p];[s1][p]paletteuse=dither=bayer",
            "-loop",
            "0",
            str(gif),
        ],
        check=True,
    )


def render(site_root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="muse-openrouter-demo-") as temporary:
        frames = Path(temporary)
        with static_server(site_root) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(browser_executable()),
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            page = browser.new_page(viewport={"width": 1000, "height": 760})
            page.goto(url, wait_until="networkidle")
            demo = page.locator(".demo")
            demo.scroll_into_view_if_needed()
            for index in range(DURATION_SECONDS * FPS):
                time_value = index / FPS
                page.evaluate(
                    """timeValue => {
                      document.querySelectorAll('.demo-line').forEach((line) => {
                        const delay = Number.parseFloat(
                          getComputedStyle(line).getPropertyValue('--delay')
                        );
                        const progress = Math.max(0, Math.min(1, (timeValue - delay) / 0.25));
                        line.style.animation = 'none';
                        line.style.opacity = String(progress);
                        line.style.transform = `translateY(${4 * (1 - progress)}px)`;
                      });
                    }""",
                    time_value,
                )
                demo.screenshot(path=str(frames / f"frame-{index:04d}.png"))
            browser.close()
        encode(frames, output / "demo.mp4", output / "demo.gif")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.site_root.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
