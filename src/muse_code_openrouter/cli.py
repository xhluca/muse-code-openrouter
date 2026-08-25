"""Command-line interface for Muse Code OpenRouter support."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from . import __version__
from .install import (
    DEFAULT_MODEL,
    DEFAULT_PORT,
    doctor,
    list_models,
    select_default_model,
    setup,
)
from .proxy import DEFAULT_UPSTREAM, proxy_main


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="muse-openrouter")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the Muse Code protocol adapter")
    serve.add_argument("--host", default=os.environ.get("MUSE_OPENROUTER_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--model", default=DEFAULT_MODEL)
    serve.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    serve.add_argument("--log-level", default="INFO")

    configure = commands.add_parser("setup", help="store the key and configure Muse Code")
    configure.add_argument("--key-stdin", action="store_true", help="read the key from stdin")
    configure.add_argument("--no-validate", action="store_true")
    configure.add_argument("--no-systemd", action="store_true")
    model_choice = configure.add_mutually_exclusive_group()
    model_choice.add_argument("--model", default=DEFAULT_MODEL)
    model_choice.add_argument(
        "--choose-model",
        action="store_true",
        help="choose the default from the live OpenRouter Meta Muse catalog",
    )
    configure.add_argument("--port", type=int, default=DEFAULT_PORT)

    check = commands.add_parser("doctor", help="check the key, adapter, and Muse Code")
    check.add_argument("--live", action="store_true", help="send a small paid model request")
    check.add_argument("--model", help="model to test (default: current Muse setting)")
    check.add_argument("--port", type=int, default=DEFAULT_PORT)

    commands.add_parser("models", help="list available OpenRouter meta/muse* models")

    select = commands.add_parser("select", help="select a default and refresh Muse's picker")
    select.add_argument("model", nargs="?", help="meta/muse* id (omit for a chooser)")
    select.add_argument("--port", type=int, default=DEFAULT_PORT)
    select.add_argument("--no-systemd", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            return proxy_main(
                [
                    "--host",
                    args.host,
                    "--port",
                    str(args.port),
                    "--model",
                    args.model,
                    "--upstream",
                    args.upstream,
                    "--log-level",
                    args.log_level,
                ]
            )
        if args.command == "setup":
            setup(
                key_stdin=args.key_stdin,
                no_validate=args.no_validate,
                no_systemd=args.no_systemd,
                choose_model=args.choose_model,
                model=args.model,
                port=args.port,
            )
            return 0
        if args.command == "doctor":
            return doctor(port=args.port, model=args.model, live=args.live)
        if args.command == "models":
            return list_models()
        if args.command == "select":
            return select_default_model(
                model=args.model,
                port=args.port,
                no_systemd=args.no_systemd,
            )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2
