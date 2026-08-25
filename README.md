# Muse Code OpenRouter

Use an OpenRouter API key and model directly inside Meta Muse Code. After setup,
the normal `muse` command uses `meta/muse-spark-1.2` through OpenRouter; no Codex
configuration is involved.

## Why an adapter is needed

Muse Code 0.2.1 exposes a `--base-url` option but the shipped binary only enables
its `meta` and `echo` providers. Pointing that Meta provider straight at
OpenRouter fails before inference because Muse first requests the proprietary
`/muse-code/models` catalog. Muse also requires a `sequence_number` on each
Responses API stream event, which compatible providers do not always emit.

The local adapter fixes those protocol differences:

- translates OpenRouter's public model record into Muse's local model catalog;
- replaces Muse's endpoint with a loopback-only Responses API adapter;
- supplies the OpenRouter credential without putting it in Muse's Meta auth store;
- adds missing stream sequence numbers; and
- shortens and restores provider-incompatible function names when necessary.

## Install

```bash
curl -LsSf https://xhluca.github.io/muse-code-openrouter/install.sh | sh
```

The installer installs Meta's official Muse Code launcher if `muse` is missing,
installs this package for the current user, and prompts for the OpenRouter key
without echoing it. Afterwards, use Muse Code normally:

```bash
muse
```

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
- Preserves Muse's other settings while updating `provider`, `model`,
  `endpoint_transport`, and `model_catalog` in `~/.config/muse/settings.json`.
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
