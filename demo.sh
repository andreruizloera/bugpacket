#!/usr/bin/env bash
# Demo, in two parts.
#
# Part 1: introduce a realistic bug in the example Python shop app, run its
# tests through bugpacket, and show the packet that comes out.
#
# Part 2: the same thing for Rust, Go, and the JVM, whose traces name files in
# ways that cannot simply be opened. Each example runs in a throwaway git repo
# so the packet is about the example and not about this repository's own
# working tree.
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

# The token numbers the README pastes are only reproducible from a clean
# checkout: an uncommitted diff legitimately belongs in the packet, so a dirty
# tree makes the packet bigger. Only that one file is expected to differ here,
# because this script edits it on purpose and restores it on exit.
#
# The packet size and the file count are properties of the tool's behaviour on
# this failure, so they are checked. "Repository source size" and the reduction
# derived from it are properties of how large this repository happens to be
# today, and would move on any commit that changes the size of any file,
# including this one; the README says so rather than freezing them here.
DIRTY="$(git status --porcelain | grep -v "$TARGET" || true)"
if [ -z "$DIRTY" ]; then
  (
    cd examples/shopapp
    uv run --project ../.. bugpacket run -- python -m pytest tests/test_payment.py
  ) > /tmp/bugpacket-demo-part1.txt 2>&1
  check /tmp/bugpacket-demo-part1.txt "files/       (4 relevant files)"
  check /tmp/bugpacket-demo-part1.txt "BugPacket size: 1,221 tokens estimated"
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
  local lang="$1"
  cp -R "examples/multilang/$lang" "$WORK/$lang"
  cp examples/multilang/replay.sh "$WORK/$lang/replay.sh"
  mkdir -p "$WORK/$lang/traces"
  cp examples/multilang/traces/*.txt "$WORK/$lang/traces/"
  (
    cd "$WORK/$lang"
    git init -q
    git add -A
    git -c user.email=demo@example.com -c user.name=demo commit -qm "example project"
  )
}
setup_repo java
setup_repo go
setup_repo rust

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

echo
if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES demo check(s) failed: the README and the tool disagree." >&2
  exit 1
fi
echo "All demo checks passed; every line the README pastes was found in a real packet."
