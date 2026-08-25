<h1 align="center">Muse Code OpenRouter</h1>

<p align="center"><strong>Use your OpenRouter key inside Meta Muse Code.</strong></p>

<p align="center">
  <a href="https://pypi.org/project/muse-code-openrouter/"><img src="https://img.shields.io/pypi/v/muse-code-openrouter?style=flat-square&color=b9f227&label=PyPI" alt="PyPI version"></a>
  <a href="https://pypi.org/project/muse-code-openrouter/"><img src="https://img.shields.io/pypi/pyversions/muse-code-openrouter?style=flat-square" alt="Python versions"></a>
  <a href="https://github.com/xhluca/muse-code-openrouter/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-8dbdff?style=flat-square" alt="MIT license"></a>
  <a href="https://xhluca.github.io/muse-code-openrouter/"><img src="https://img.shields.io/badge/demo-live-b9f227?style=flat-square" alt="Interactive demo"></a>
</p>

<p align="center">
  A small local adapter for using any available <code>meta/muse*</code> model
  through OpenRouter without replacing the Muse Code harness.
</p>

## Install

```bash
curl -LsSf https://xhluca.github.io/muse-code-openrouter/install.sh | sh
```

The installer prompts for your OpenRouter key without echoing it and lets you
choose a default model. It installs for the current user on Linux or macOS.

Already have `uv`?

```bash
uv tool install muse-code-openrouter
muse-openrouter setup
```

## Use

Start Muse normally:

```bash
muse
```

Switch models during a session with `/models`, or choose one for a new run:

```bash
muse --model meta/muse-glimmer-30b
```

Refresh the live model list and change the default:

```bash
muse-openrouter select
```

The adapter safely drops model-bound encrypted reasoning when you switch
models, while keeping normal conversation and tool history. This prevents the
OpenRouter cross-model 404.

## Commands

| Command | Purpose |
| --- | --- |
| `muse-openrouter setup` | Configure the key, model catalog, and local service |
| `muse-openrouter models` | List available Meta Muse models |
| `muse-openrouter select` | Change the default model |
| `muse-openrouter doctor --live` | Check the local adapter and OpenRouter access |
| `muse-openrouter uninstall` | Restore Muse Code's previous settings |

## What it changes

- Stores the key in `~/.config/muse-code-openrouter/credential` with mode `0600`.
- Runs a loopback-only adapter on `127.0.0.1:8817`.
- Adds OpenRouter's live `meta/muse*` catalog to Muse's model picker.
- Translates the small catalog and streaming differences between Muse and OpenRouter.

The adapter does not log API keys, prompts, request bodies, or model responses.

> **Contributor model warning:** Your prompts and outputs may be used to
> improve Meta's products.

## Uninstall

```bash
muse-openrouter uninstall
```

To also remove this package:

```bash
muse-openrouter uninstall --remove-package
```

## Development

```bash
uv run --with pytest pytest
uv run --with ruff ruff check .
```

[Interactive demo](https://xhluca.github.io/muse-code-openrouter/) ·
[PyPI](https://pypi.org/project/muse-code-openrouter/) ·
[MIT license](LICENSE)
