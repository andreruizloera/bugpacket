# Contributing

Thanks for considering a contribution.

## Setup

```sh
git clone https://github.com/andreruizloera/bugpacket
cd bugpacket
uv venv --python 3.13
uv sync
```

## Before opening a pull request

```sh
uv run ruff format .
uv run ruff check .
uv run pytest
```

All three must pass. New behavior needs a test.

## Ground rules

- BugPacket is strictly local. Pull requests that add any network code
  (uploads, telemetry, version checks, anything) will not be merged. The test
  suite enforces this and the check must stay.
- Zero runtime dependencies. The standard library has what we need.
- Keep output deterministic: same failure in, same packet out.
- Environment variable values must never be captured, and secret-looking
  variable names must stay filtered.

## Good first contributions

See ROADMAP.md for concrete ideas, or improve the stack-trace parsers with
fixtures from real tools (new test frameworks, new languages).
