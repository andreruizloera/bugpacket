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

The demo runs in two parts. Part 1 introduces a realistic bug into the example
Python shop app under `examples/shopapp`, runs its test suite through
bugpacket, and shows the packet. Part 2 does the same for Rust, Go, and the
JVM (see [Rust, Go, and the JVM](#rust-go-and-the-jvm) below). Real output from
part 1:

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

Repository source size: 41,093 tokens estimated
BugPacket size: 1,221 tokens estimated
Context reduction: 97.0%
```

Token counts use a chars/4 heuristic and are always labeled as estimates.

That block is the output of one real run, from a clean checkout on a macOS
laptop. The four relevant files are checked by `./demo.sh` on every CI run,
because which files BugPacket picks is what the tool decides and is the same
everywhere. The token numbers are not checked and will not match yours exactly:
a packet embeds the environment it was built in, so its size differs between
machines, and "Repository source size" is the total over every source file in
this repository, so it moves whenever any file here changes. Your packet also
grows when your working tree has uncommitted changes, because your diff and the
files in it are part of the context an agent needs.

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

## Rust, Go, and the JVM

A Python traceback names a file you can open. A Rust, Go, or JVM trace usually
does not, which is the actual work in supporting them:

- A JVM frame is `at com.example.shop.Pricing.applyCoupon(Pricing.java:8)`. It
  carries a file name and no directory at all.
- A Go panic frame carries the absolute path the binary was **built** at, so a
  binary built in a container or on CI names a directory that does not exist on
  the machine reading the trace. A `go test` failure names a file relative to
  its package, which is not the directory the command ran in.
- A Rust backtrace mixes your crate's paths with standard-library paths inside
  the toolchain.

BugPacket resolves a frame by opening the path when that works, and otherwise
searching the repository for a file whose path ends with the frame's path, the
longest match first. Real output from `./demo.sh`, part 2a, run against the
example JVM project:

```
$ java -cp out com.example.shop.Main   (real java on this machine)
  ## Failure
  java.lang.NullPointerException: Cannot invoke "java.lang.Integer.intValue()" because the return value of "java.util.Map.get(Object)" is null
  That is the root cause of a chain of 2 exceptions. The outermost, which is where the trace starts and usually not where the bug is:
  java.lang.IllegalStateException: checkout failed for 1 item(s)
  ## Relevant stack
  src/main/java/com/example/shop/Checkout.java:11 in com.example.shop.Checkout.run (jvm)  [matched by file name; the trace gave no usable path]
  src/main/java/com/example/shop/Main.java:10 in com.example.shop.Main.main (jvm)  [matched by file name; the trace gave no usable path]
  src/main/java/com/example/shop/Pricing.java:8 in com.example.shop.Pricing.applyCoupon (jvm)  [matched by file name; the trace gave no usable path]
  src/main/java/com/example/shop/Cart.java:13 in com.example.shop.Cart.checkout (jvm)  [matched by file name; the trace gave no usable path]
  src/main/java/com/example/shop/Checkout.java:9 in com.example.shop.Checkout.run (jvm)  [matched by file name; the trace gave no usable path]
  ## Relevant files
  ### src/main/java/com/example/shop/Pricing.java (rank 1: stack trace)
```

Three decisions in there are worth stating, because each of them is a place
the tool could have been confidently wrong instead:

**The root cause is reported, not the wrapper.** A wrapped JVM failure prints
the outermost exception first, and that one is almost never where the bug is:
`IllegalStateException: checkout failed` is a rethrow in a catch block, and the
`NullPointerException` under it is the thing to fix. BugPacket reports the
deepest `Caused by:` and names the outermost separately, so the agent reading
the packet starts at the defect rather than at the handler.

**A name match that is not unique resolves to nothing.** If two files in the
repository could be the `Pricing.java` in the trace, BugPacket includes
neither, and the packet says so and names the candidates. A missing file costs
the agent a question; the wrong file gets edited with confidence. Where a JVM
frame's package is available it is used first (`com/example/shop/Pricing.java`
rather than `Pricing.java`), because a package-qualified path is much harder to
match by accident.

**Frames resolved by search are labeled as such.** `[matched by file name; the
trace gave no usable path]` marks an inference, so a reader can tell it apart
from a path the runtime actually gave.

Toolchain and dependency frames are never searched for. A Rust backtrace that
passes through `std`'s `HashMap` names `.../rustlib/.../map.rs`; a project with
its own `map.rs` must not have it pulled into the packet on that basis. The
same applies to `java.base` frames, the Go module cache, `node_modules`, and
`site-packages`.

For Go, a `go test` failure names only the test file, and a Go package is its
directory, so the other non-test `.go` files in that directory are included at
rank 3. That is how `pricing/pricing.go` reaches the packet in part 2c of the
demo when the trace named only `pricing/pricing_test.go`.

The example projects under `examples/multilang/` are real, compilable Rust, Go,
and Java. `examples/multilang/traces/` holds output captured from actually
running them (`record-traces.sh` is how, and CI re-runs the live toolchains on
every push). `./demo.sh` runs the real compilers when the machine has them and
replays those recordings when it does not, so the demo works from a clean clone
with no Rust, Go, or JVM installed.

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
bugpacket run -- cargo test
bugpacket run -- go test ./...
bugpacket run -- ./gradlew test
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
- parsed stack traces: CPython tracebacks, pytest-style traces, Node/V8 frames,
  Rust panics and backtraces, Go panics and `go test` failures, and JVM
  exceptions including `Caused by:` chains
- the source files implicated by the trace, whole, with a token budget
- the failing test file and the local modules those files import (for Go, the
  rest of the failing test's package)
- `git status`, the current diff against HEAD, and branch/commit
- the dependency manifest (pyproject.toml, package.json, and similar)
- environment metadata: interpreter and node versions, OS, and environment
  variable names only. Values are never captured, for any variable, and
  names matching a secret denylist (KEY, TOKEN, SECRET, PASSWORD, ...) are
  dropped too.

## Architecture

Plain Python 3.12+, standard library only, in `src/bugpacket/`:

- `stacktrace.py` owns the single pass over the output and the order the
  dialects are offered each line, which is the only place their regexes could
  collide. It parses Python, pytest, and Node/V8 directly.
- `dialects.py` holds the Rust, Go, and JVM state machines. They are pure:
  text in, frames out, no filesystem.
- `resolve.py` maps a frame's path onto a real repository file, and is the
  single place both the ranking and the rendered stack ask, so the two cannot
  disagree about where a frame lives. It is also where the refusal to guess
  lives.
- `ranking.py` assigns each candidate file a deterministic relevance rank:
  1 stack-trace files, 2 the failing test, 3 local modules imported by those
  (or, in Go, the rest of the package), 4 files in the git diff, 5 the
  dependency manifest. Ties sort by path, so the same failure always produces
  the same packet.
- `packet.py` fills a token budget with whole files in rank order, trims the
  first file that does not fit down to windows around the referenced lines,
  and lists whatever had to be omitted.
- `tokens.py` estimates tokens (chars/4, labeled as an estimate) for the
  repository versus the packet and produces the reduction line.
- `environment.py`, `gitcapture.py`, `clipboard.py` do what their names say,
  through local subprocesses only.

## Limitations

- Token counts are estimates from a chars/4 heuristic, not tokenizer output.
- Stack-trace parsing covers CPython, pytest, Node/V8, Rust, Go, and JVM
  formats. Ruby and browser-flavored JS traces are not parsed yet (see
  ROADMAP.md).
- **Compiler and build errors are not parsed.** A `cargo build` that fails to
  compile, a `javac` error, or a `go build` failure produces diagnostics, not a
  stack trace, and BugPacket reads none of them today. The three new dialects
  cover things that failed at run time.
- **A frame matched by file name is an inference, and an unlucky repository
  can make it a wrong one.** If exactly one file matches, it is used, and a
  single match can still be the wrong file in a repository that vendors a copy
  of someone else's source outside the directories BugPacket skips. Frames
  resolved this way are labeled in the packet so the inference is visible.
- **A JVM package hint assumes the package matches the directory.** It is only
  a convention, though a near-universal one; a project that does not follow it
  falls back to matching on the bare file name.
- Import following is one level deep and intentionally simple; dynamic
  imports and package `__init__` re-exports are not chased. For Rust and the
  JVM there is no import following at all, because their traces already name
  every frame's file. Go gets package siblings rather than import following.
- Windows paths inside a trace are folded to forward slashes for matching, but
  BugPacket is not otherwise tested on Windows.
- If your program prints secrets into its own output, they will appear in the
  captured output. BugPacket filters its environment capture, but it cannot
  know what is secret inside arbitrary program text. Read the packet before
  pasting it anywhere.

## Roadmap

See [ROADMAP.md](ROADMAP.md). Highlights: compiler and build-error
diagnostics, Ruby traces, jest/vitest summaries, a configurable secret
denylist, and function-boundary trimming.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The two hard rules: no network code,
ever, and no runtime dependencies.

## License

MIT. See [LICENSE](LICENSE).

GitHub topics: `debugging`, `ai-agents`, `developer-tools`, `llm`, `code-intelligence`
