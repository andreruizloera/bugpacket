# BugPacket

Turn a software failure into the smallest useful debugging context for an AI coding agent.

[![CI](https://github.com/andreruizloera/bugpacket/actions/workflows/ci.yml/badge.svg)](https://github.com/andreruizloera/bugpacket/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

You run your failing command through `bugpacket run`. It captures the output,
parses the stack trace, figures out which files actually matter, and writes a
single `packet.md` you can paste into any AI coding agent. Instead of dumping
your whole repository into a context window, you hand over just the failure,
the reproduction, the implicated files, and your current diff.

**BugPacket is strictly local. It never uploads anything anywhere.** There is
no network code in the source tree at all, and a test
(`tests/test_no_network.py`) fails the build if any ever appears. No
telemetry, no version checks, no accounts. Your code stays on your machine
until you decide where to paste the packet.

## Quickstart

```sh
git clone https://github.com/andreruizloera/bugpacket
cd bugpacket
./demo.sh
```

The demo introduces a realistic bug into the example shop app under
`examples/`, runs its test suite through bugpacket, and shows the packet.
Real output from that demo:

```
$ cd examples/shopapp
$ bugpacket run -- python -m pytest tests/test_payment.py

.FF                                                                      [100%]
=================================== FAILURES ===================================
________________________ test_total_with_percent_coupon ________________________
...
E       KeyError: 'percentage'

shop/payment.py:15: KeyError
...
2 failed, 1 passed in 0.03s

BugPacket written to .bugpacket/
  packet.md    (paste into your AI coding agent, or: bugpacket copy)
  packet.json  (structured)
  files/       (4 relevant files)

Repository source size: 21,207 tokens estimated
BugPacket size: 1,257 tokens estimated
Context reduction: 94.1%
```

Token counts use a chars/4 heuristic and are always labeled as estimates.

The generated `packet.md` from that same run, abridged:

````markdown
# BugPacket

## Failure

```
KeyError: 'percentage'
```

Failing tests:
- tests/test_payment.py::test_total_with_percent_coupon
- tests/test_payment.py::test_bigger_coupon_never_increases_total

## Reproduction

```
$ python -m pytest tests/test_payment.py
exit code: 1
```

## Relevant stack

```
examples/shopapp/tests/test_payment.py:19
examples/shopapp/shop/cart.py:30 in checkout
examples/shopapp/shop/payment.py:25 in total_cents
examples/shopapp/shop/payment.py:15
```

## Relevant files

### examples/shopapp/shop/payment.py (rank 1: stack trace)

```python
def apply_coupon(amount_cents: int, coupon: dict) -> int:
    """Apply a percent-off coupon to an amount, rounding down."""
    percent = coupon["percentage"]
    ...
```

## Current diff

```diff
 def apply_coupon(amount_cents: int, coupon: dict) -> int:
     """Apply a percent-off coupon to an amount, rounding down."""
-    percent = coupon["percent"]
+    percent = coupon["percentage"]
```

## Environment

- python: 3.13.14 (CPython)
- node: v24.10.0
- platform: macOS-15.7.1-arm64-arm-64bit-Mach-O
- environment variable names (values are never captured; secret-looking
  names removed): HOME, LANG, PATH, ...
````

The full packet includes the whole files, the porcelain git status, and the
complete diff. The shop app has eight modules and three test files; only the
two modules and one test tied to the failure, plus the manifest, made it into
the packet.

## Why?

Pasting a raw test failure into an AI agent usually goes one of two ways:
either the agent gets the traceback with no code and guesses, or it gets the
whole repository and burns most of its context window on files that have
nothing to do with the bug. The useful middle is small and mechanical to
compute: the trace, the files the trace names, the failing test, what those
import, and what you changed. BugPacket computes exactly that, the same way
every time, and shows you how much context it saved.

The local-only constraint is the other half of the point. Debugging context
is some of the most sensitive data a tool can touch: source code, diffs of
unreleased work, environment details. A tool that packages all of that should
be verifiably incapable of sending it anywhere.

## Installation

Requires Python 3.12 or newer. Zero runtime dependencies.

```sh
uv tool install git+https://github.com/andreruizloera/bugpacket
```

or, from a clone:

```sh
uv tool install .
```

or with pip:

```sh
pip install git+https://github.com/andreruizloera/bugpacket
```

## Usage

Run any failing command after `--`:

```sh
bugpacket run -- pytest tests/test_payment.py
bugpacket run -- npm test
bugpacket run -- python scripts/repro.py
```

Then:

```sh
bugpacket show    # render the latest packet.md to the terminal
bugpacket copy    # copy packet.md to the clipboard (pbcopy, wl-copy, xclip, or xsel)
bugpacket run --json -- pytest   # print packet.json to stdout instead of the summary
bugpacket run --budget 4000 -- pytest   # tighter token budget for included files
```

Output lands in `.bugpacket/` in the directory you ran from:

```
.bugpacket/
  packet.md      optimized for pasting into an AI coding agent
  packet.json    the same information, structured
  files/         copies of the relevant files
```

Add `.bugpacket/` to your `.gitignore`.

## What gets captured

- the command, its stdout, stderr, and exit code
- parsed stack traces: CPython tracebacks, pytest-style traces, and Node/V8 frames
- the source files implicated by the trace, whole, with a token budget
- the failing test file and the local modules those files import
- `git status`, the current diff against HEAD, and branch/commit
- the dependency manifest (pyproject.toml, package.json, and similar)
- environment metadata: interpreter and node versions, OS, and environment
  variable names only. Values are never captured, for any variable, and
  names matching a secret denylist (KEY, TOKEN, SECRET, PASSWORD, ...) are
  dropped too.

## Architecture

Plain Python 3.12+, standard library only, in `src/bugpacket/`:

- `stacktrace.py` parses Python, pytest, and Node/V8 traces with regexes
  and a small state machine.
- `ranking.py` assigns each candidate file a deterministic relevance rank:
  1 stack-trace files, 2 the failing test, 3 local modules imported by those,
  4 files in the git diff, 5 the dependency manifest. Ties sort by path, so
  the same failure always produces the same packet.
- `packet.py` fills a token budget with whole files in rank order, trims the
  first file that does not fit down to windows around the referenced lines,
  and lists whatever had to be omitted.
- `tokens.py` estimates tokens (chars/4, labeled as an estimate) for the
  repository versus the packet and produces the reduction line.
- `environment.py`, `gitcapture.py`, `clipboard.py` do what their names say,
  through local subprocesses only.

## Limitations

- Token counts are estimates from a chars/4 heuristic, not tokenizer output.
- Stack-trace parsing covers CPython, pytest, and Node/V8 formats. Rust, Go,
  JVM, and Ruby traces are not parsed yet (see ROADMAP.md).
- Import following is one level deep and intentionally simple; dynamic
  imports and package `__init__` re-exports are not chased.
- Windows paths in stack traces are not handled yet.
- If your program prints secrets into its own output, they will appear in the
  captured output. BugPacket filters its environment capture, but it cannot
  know what is secret inside arbitrary program text. Read the packet before
  pasting it anywhere.

## Roadmap

See [ROADMAP.md](ROADMAP.md). Highlights: more trace dialects (Rust, Go,
JVM), jest/vitest summaries, a configurable secret denylist, and function-
boundary trimming.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The two hard rules: no network code,
ever, and no runtime dependencies.

## License

MIT. See [LICENSE](LICENSE).

GitHub topics: `debugging`, `ai-agents`, `developer-tools`, `llm`, `code-intelligence`
