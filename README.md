# Muse Code OpenRouter

Use an OpenRouter API key and any `meta/muse*` model directly inside Meta Muse
Code. After setup, the normal `muse` command uses `meta/muse-spark-1.2` through
OpenRouter by default; no Codex configuration is involved.

## Why an adapter is needed

Muse Code 0.2.1 exposes a `--base-url` option but the shipped binary only enables
its `meta` and `echo` providers. Pointing that Meta provider straight at
OpenRouter fails before inference because Muse first requests the proprietary
`/muse-code/models` catalog. Muse also requires a `sequence_number` on each
Responses API stream event, which compatible providers do not always emit.

The local adapter fixes those protocol differences:

- translates OpenRouter's live `meta/muse*` catalog into Muse's model catalog;
- replaces Muse's endpoint with a loopback-only Responses API adapter;
- supplies the OpenRouter credential without putting it in Muse's Meta auth store;
- preserves the requested `meta/muse*` model instead of pinning one model;
- clamps Muse's output budget to each advertised model limit;
- adds missing stream sequence numbers; and
- shortens and restores provider-incompatible function names when necessary.

## Install

```bash
curl -LsSf https://xhluca.github.io/muse-code-openrouter/install.sh | sh
```

The installer installs Meta's official Muse Code launcher if `muse` is missing,
installs this package for the current user, prompts for the OpenRouter key
without echoing it, and then presents a numbered default-model chooser.
Afterwards, use Muse Code normally:

```bash
muse
```

List every currently available Meta Muse model and mark the configured default:

```bash
muse-openrouter models
```

Open the chooser again to change the default and refresh Muse's visible picker:

```bash
muse-openrouter select
```

Or select directly:

```bash
muse-openrouter select meta/muse-glimmer-30b
```

Select any listed model for only one run without changing the default:

```bash
muse --model meta/muse-glimmer-30b
muse --model meta/muse-spark-1.1
muse --model meta/muse-spark-1.2
muse --model meta/muse-spark-1.2-contributor
```

Remove the adapter, credential, service, and OpenRouter-owned Muse settings,
restoring the settings saved before setup:

```bash
muse-openrouter uninstall
```

This keeps the command installed so setup can be run again. To also uninstall
the `uv` tool package:

```bash
muse-openrouter uninstall --remove-package
```

Setup and `select` fetch the live catalog and write every current `meta/muse*`
model as a visible Muse picker entry. Run `muse-openrouter select` again to pick
up newly released models. OpenRouter account privacy settings and provider
availability still apply.

Contributor models are clearly marked wherever they are listed or selected.
OpenRouter's official disclosure says: **Your prompts and outputs may be used to
improve Meta's products.** They may also be blocked by restrictive OpenRouter
data policies.

Manual installation is also supported:

```bash
uv tool install muse-code-openrouter
muse-openrouter setup
muse-openrouter doctor --live
```

For automation, supply the key on standard input so it does not appear in shell
history or the process list:

```bash
printf '%s\n' "$OPENROUTER_API_KEY" | muse-openrouter setup --key-stdin
```

## What setup changes

- Stores the key at
  `${XDG_CONFIG_HOME:-~/.config}/muse-code-openrouter/credential`, mode `0600`.
- Preserves Muse's other settings while updating `provider`, `model`, and
  `endpoint_transport` in `~/.config/muse/settings.json`.
- Writes every current `meta/muse*` model into Muse's undocumented
  `model_catalog` as a visible picker row, including context/output limits and
  Contributor warnings.
- Saves the original Muse settings under
  `${XDG_STATE_HOME:-~/.local/state}/muse-code-openrouter/`.
- Starts a loopback-only adapter on `127.0.0.1:8817`, normally as a systemd user
  service on Linux.

The adapter never logs API keys, authorization headers, prompts, request bodies,
or model responses. Muse session logging remains controlled by Muse itself.

## Development

```bash
uv run --with pytest pytest
uv run --with ruff ruff check .
uv build
```

The adapter is dependency-free Python and supports Linux and macOS. The service
installer uses systemd when available and otherwise launches a detached process.
