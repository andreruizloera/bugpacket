#!/usr/bin/env bash
# Demo, in three parts.
#
# Part 1: introduce a realistic bug in the example Python shop app, run its
# tests through bugpacket, and show the packet that comes out.
#
# Part 2: the same thing for Rust, Go, and the JVM, whose traces name files in
# ways that cannot simply be opened. Each example runs in a throwaway git repo
# so the packet is about the example and not about this repository's own
# working tree.
#
# Part 3: the same three projects with an edit that stops them compiling. A
# build failure produces no stack trace at all, only compiler diagnostics, so
# this is a different parse from every trace in part 2.
#
# Every line this script prints that the README also pastes is checked here.
# If the tool's output drifts from the documentation, this exits nonzero and
# CI goes red.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  uv venv --python 3.13 >/dev/null
fi
uv sync --quiet

FAILURES=0
check() {
  # check <file> <literal string that must appear>
  if ! grep -qF -- "$2" "$1"; then
    echo "DEMO CHECK FAILED: expected in $1:" >&2
    echo "  $2" >&2
    FAILURES=$((FAILURES + 1))
  fi
}

check_order() {
  # check_order <file> <string that must come first> <string that must follow>
  #
  # `check` only asks whether a line exists, which is why the README's pasted
  # JVM stack could go stale without CI noticing: every line in it was still
  # present, in the wrong order. Ordering is the claim here, so it gets its
  # own assertion.
  local first last
  first=$(grep -nF -- "$2" "$1" | head -1 | cut -d: -f1)
  last=$(grep -nF -- "$3" "$1" | head -1 | cut -d: -f1)
  if [ -z "$first" ] || [ -z "$last" ] || [ "$first" -ge "$last" ]; then
    echo "DEMO CHECK FAILED: in $1, expected this line first:" >&2
    echo "  $2 (line ${first:-missing})" >&2
    echo "to come before:" >&2
    echo "  $3 (line ${last:-missing})" >&2
    FAILURES=$((FAILURES + 1))
  fi
}

# ---------------------------------------------------------------- part 1 ---

TARGET="examples/shopapp/shop/payment.py"
BACKUP="$(mktemp)"
cp "$TARGET" "$BACKUP"
restore() { cp "$BACKUP" "$TARGET"; rm -f "$BACKUP"; }
trap restore EXIT

# The bug: the coupon field gets read under the wrong name.
python3 - "$TARGET" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
p.write_text(p.read_text().replace('coupon["percent"]', 'coupon["percentage"]'))
PY

echo "=============================================================="
echo "part 1: Python"
echo "=============================================================="
echo '$ cd examples/shopapp'
echo '$ bugpacket run -- python -m pytest tests/test_payment.py'
echo
(
  cd examples/shopapp
  uv run --project ../.. bugpacket run -- python -m pytest tests/test_payment.py
)

echo
echo "Packet preview (bugpacket show | head -40):"
echo
(
  cd examples/shopapp
  uv run --project ../.. bugpacket show | head -40
)

PY_PACKET="examples/shopapp/.bugpacket/packet.md"
check "$PY_PACKET" "KeyError: 'percentage'"
check "$PY_PACKET" "examples/shopapp/shop/payment.py:15"
check "$PY_PACKET" "examples/shopapp/shop/cart.py:30 in checkout"
check "$PY_PACKET" "rank 1: stack trace"
check "$PY_PACKET" "- tests/test_payment.py::test_total_with_percent_coupon"
# Two failing tests are two stacks, each led by the line that raised. Flattened
# and cross-deduplicated, this section used to end on the SECOND test's top
# frame, directly under the first test's innermost one.
check "$PY_PACKET" "2 stacks, each printed innermost frame first"
check "$PY_PACKET" "test_bigger_coupon_never_increases_total:"
check_order "$PY_PACKET" \
  "examples/shopapp/shop/payment.py:15" \
  "examples/shopapp/tests/test_payment.py:19"

# The token numbers the README pastes are only reproducible from a clean
# checkout: an uncommitted diff legitimately belongs in the packet, so a dirty
# tree makes the packet bigger. Only that one file is expected to differ here,
# because this script edits it on purpose and restores it on exit.
#
# The file count is a property of the tool's behaviour on this failure and is
# the same everywhere, so it is checked. The token numbers are not: a packet
# embeds the environment it was built in (platform, interpreter versions), so
# its size differs between macOS and a Linux runner, and "Repository source
# size" moves on any commit that changes any file's size. The README reports
# those as one real run's output rather than as invariants.
DIRTY="$(git status --porcelain | grep -v "$TARGET" || true)"
if [ -z "$DIRTY" ]; then
  (
    cd examples/shopapp
    uv run --project ../.. bugpacket run -- python -m pytest tests/test_payment.py
  ) > /tmp/bugpacket-demo-part1.txt 2>&1
  check /tmp/bugpacket-demo-part1.txt "files/       (4 relevant files)"
else
  echo "(working tree is dirty, so the README's token numbers are not checked)"
fi

# ---------------------------------------------------------------- part 2 ---

WORK="$(mktemp -d)"
cleanup() { restore; rm -rf "$WORK"; }
trap cleanup EXIT

REPO_ROOT="$(pwd)"

# Each example becomes its own git repository, the way a real Rust, Go, or
# JVM project is, so the packet's paths are that project's paths.
setup_repo() {
  # setup_repo <destination name> [source example, default the same name]
  local name="$1" lang="${2:-$1}"
  cp -R "examples/multilang/$lang" "$WORK/$name"
  cp examples/multilang/replay.sh "$WORK/$name/replay.sh"
  mkdir -p "$WORK/$name/traces"
  cp examples/multilang/traces/*.txt "$WORK/$name/traces/"
  (
    cd "$WORK/$name"
    git init -q
    git add -A
    git -c user.email=demo@example.com -c user.name=demo commit -qm "example project"
  )
}
setup_repo java
setup_repo go
setup_repo rust
setup_repo python

# Run the real toolchain when this machine has it, and replay the recorded
# output of a real run when it does not. The recordings in
# examples/multilang/traces/ are captures from real runs (see
# record-traces.sh), so both paths feed bugpacket the same bytes.
build_example() {
  case "$1" in
    java)
      command -v javac >/dev/null 2>&1 || return 0
      (cd "$WORK/java" && javac -d out $(find src -name '*.java')) || return 1
      ;;
  esac
  return 0
}

run_example() {
  # run_example <dir> <trace name> <exit code> <real command...>
  local dir="$1" trace="$2" code="$3"
  shift 3
  local tool="$1"
  if command -v "$tool" >/dev/null 2>&1 && build_example "$dir"; then
    echo "\$ $*   (real $tool on this machine)"
    (
      cd "$WORK/$dir"
      RUST_BACKTRACE=1 uv run --project "$REPO_ROOT" bugpacket run -- "$@" >/dev/null 2>&1
    ) || true
  else
    echo "\$ $*   (no $tool here; replaying the recorded output of that command)"
    (cd "$WORK/$dir" && uv run --project "$REPO_ROOT" bugpacket run -- \
      ./replay.sh "$trace" "$code" >/dev/null 2>&1) || true
  fi
}

section() {
  echo
  echo "=============================================================="
  echo "$1"
  echo "=============================================================="
}

show_packet() {
  local dir="$1"
  sed -n '/## Failure/,/## Current diff/p' "$WORK/$dir/.bugpacket/packet.md" |
    grep -vE '^\s*$' | grep -vE '^```' | sed -e 's/^/  /'
}

section "part 2a: JVM. The trace names Pricing.java and no directory at all."
run_example java java-exception 1 java -cp out com.example.shop.Main
show_packet java
JVM_PACKET="$WORK/java/.bugpacket/packet.md"
check "$JVM_PACKET" "java.lang.NullPointerException"
check "$JVM_PACKET" "That is the root cause of a chain of 2 exceptions."
check "$JVM_PACKET" "java.lang.IllegalStateException: checkout failed for 1 item(s)"
check "$JVM_PACKET" "src/main/java/com/example/shop/Pricing.java:8 in com.example.shop.Pricing.applyCoupon (jvm)"
check "$JVM_PACKET" "[matched by file name; the trace gave no usable path]"
check "$JVM_PACKET" "### src/main/java/com/example/shop/Pricing.java (rank 1: stack trace)"
# The root cause's stack must lead. The JVM prints the rethrow at the top, and
# printing it that way contradicted the packet's own Failure section.
check "$JVM_PACKET" "2 stacks, each printed innermost frame first"
check_order "$JVM_PACKET" \
  "src/main/java/com/example/shop/Pricing.java:8 in com.example.shop.Pricing.applyCoupon (jvm)" \
  "src/main/java/com/example/shop/Checkout.java:11 in com.example.shop.Checkout.run (jvm)"

section "part 2b: Go panic. The trace names the path the binary was BUILT at."
run_example go go-panic 1 go run .
show_packet go
GO_PACKET="$WORK/go/.bugpacket/packet.md"
check "$GO_PACKET" "panic: runtime error: index out of range [2] with length 1"
check "$GO_PACKET" "cart/cart.go:21 in github.com/example/shop/cart.Receipt (go)"
check "$GO_PACKET" "### cart/cart.go (rank 1: stack trace)"

section "part 2c: go test. The failure names a file relative to its package."
run_example go go-test 1 go test ./...
show_packet go
check "$GO_PACKET" "ApplyCoupon(1200, 10%) = 1200, want 1080"
check "$GO_PACKET" "TestApplyCouponPercentOff"
check "$GO_PACKET" "### pricing/pricing_test.go (rank 1: stack trace)"
check "$GO_PACKET" "### pricing/pricing.go (rank 3: imported by, or in the same package as, a relevant file)"

section "part 2d: Rust panic. Standard-library frames are not repository files."
run_example rust rust-panic 101 cargo run --quiet
show_packet rust
RUST_PACKET="$WORK/rust/.bugpacket/packet.md"
check "$RUST_PACKET" "no entry found for key"
check "$RUST_PACKET" "src/pricing.rs:5 (rust)"
check "$RUST_PACKET" "src/cart.rs:12 in shop::cart::checkout (rust)"
check "$RUST_PACKET" "### src/pricing.rs (rank 1: stack trace)"
# The std frames in the backtrace must not appear as repository files.
if grep -qE '^### .*(option|function)\.rs' "$RUST_PACKET"; then
  echo "DEMO CHECK FAILED: a Rust standard-library file was ranked into the packet" >&2
  FAILURES=$((FAILURES + 1))
fi

section "part 2e: CPython chains. Two separators that look alike and are not."
# `raise X from Y`. CPython prints Y first, so the ORDER is already right and
# the failure is the thing that was wrong: the last line of the output is the
# rethrow, and reporting it sends a reader to the handler.
run_example python python-cause-chain 1 python3 chained.py cause
show_packet python
PY_CHAIN_PACKET="$WORK/python/.bugpacket/packet.md"
check "$PY_CHAIN_PACKET" "KeyError: 'GBP'"
check "$PY_CHAIN_PACKET" "That is the root cause of a chain of 2 exceptions."
check "$PY_CHAIN_PACKET" "LookupError: no exchange rate for GBP"
check_order "$PY_CHAIN_PACKET" \
  "shop/pricing.py:14 in rate_for" \
  "shop/pricing.py:32 in convert_cents"

# An exception raised while handling another. CPython prints the same way and
# means the opposite: here the LAST traceback is the failure, so the FAILURE is
# already right and the order is what was wrong.
run_example python python-context-chain 1 python3 chained.py context
show_packet python
check "$PY_CHAIN_PACKET" 'TypeError: can only concatenate str (not "NoneType") to str'
check "$PY_CHAIN_PACKET" "2 stacks, each printed innermost frame first"
check_order "$PY_CHAIN_PACKET" \
  "shop/pricing.py:19 in fallback_line" \
  "shop/pricing.py:14 in rate_for"
# A `During handling` run is not a cause chain, so the packet must not claim
# one. Reporting the KeyError here would answer a question nobody asked.
if grep -qF "That is the root cause of a chain" "$PY_CHAIN_PACKET"; then
  echo "DEMO CHECK FAILED: a 'During handling' run was reported as a cause chain" >&2
  FAILURES=$((FAILURES + 1))
fi


# ---------------------------------------------------------------- part 3 ---

break_source() {
  # break_source <file> <old text> <new text>
  python3 - "$@" <<'PY'
import sys
from pathlib import Path

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
target = Path(path)
text = target.read_text()
if old not in text:
    raise SystemExit(f"break_source: {old!r} is not in {path}")
target.write_text(text.replace(old, new))
PY
}

# The pristine project is committed first and broken after, so the edit that
# stopped it compiling is in the packet's "Current diff" where an agent can see
# it, which is the whole point of running a build failure through bugpacket.
setup_broken_repo() {
  local lang="$1"
  setup_repo "$lang-broken" "$lang"
}

section "part 3a: rustc. A type error, so there is no stack trace at all."
setup_broken_repo rust
break_source "$WORK/rust-broken/src/main.rs" \
  'coupon.insert("percent".to_string(), 10u32);' \
  'coupon.insert("percent".to_string(), 10.0);'
run_example rust-broken rust-compile-error 101 cargo build
show_packet rust-broken
RUSTC_PACKET="$WORK/rust-broken/.bugpacket/packet.md"
check "$RUSTC_PACKET" "error[E0308]: mismatched types: expected \`&HashMap<String, u32>\`, found \`&HashMap<String, {float}>\`"
check "$RUSTC_PACKET" "## Reported locations"
check "$RUSTC_PACKET" "src/main.rs:10 (rust)"
check "$RUSTC_PACKET" "src/cart.rs:10 (rust)"
check "$RUSTC_PACKET" "### src/cart.rs (rank 1: compiler diagnostic)"

section "part 3b: go build. One line, no stack, and the file it names."
setup_broken_repo go
break_source "$WORK/go-broken/main.go" \
  'coupon := map[string]int{"percent": 10}' \
  'coupon := map[string]float64{"percent": 10}'
run_example go-broken go-build-error 1 go build ./...
show_packet go-broken
GOBUILD_PACKET="$WORK/go-broken/.bugpacket/packet.md"
check "$GOBUILD_PACKET" "cannot use coupon (variable of type map[string]float64) as map[string]int value"
check "$GOBUILD_PACKET" "main.go:12 (go)"
check "$GOBUILD_PACKET" "### main.go (rank 1: compiler diagnostic)"

section "part 3c: javac. Two errors, and the first one is the one to fix."
setup_broken_repo java
break_source "$WORK/java-broken/src/main/java/com/example/shop/Pricing.java" \
  'int percent = coupon.get("percentage");' \
  'String percent = coupon.get("percentage");'
run_example java-broken javac-error 1 javac -d out src/main/java/com/example/shop/Pricing.java
show_packet java-broken
JAVAC_PACKET="$WORK/java-broken/.bugpacket/packet.md"
check "$JAVAC_PACKET" "incompatible types: Integer cannot be converted to String"
check "$JAVAC_PACKET" "The compiler reported 2 errors."
check "$JAVAC_PACKET" "src/main/java/com/example/shop/Pricing.java:8 (jvm)"
check "$JAVAC_PACKET" "src/main/java/com/example/shop/Pricing.java:9 (jvm)"

echo
if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES demo check(s) failed: the README and the tool disagree." >&2
  exit 1
fi
echo "All demo checks passed; every line the README pastes was found in a real packet."
