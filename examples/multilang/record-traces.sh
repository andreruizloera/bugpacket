#!/usr/bin/env bash
# Re-record the trace fixtures in traces/ by actually running each example.
#
# The files in traces/ are captured output from real toolchain runs, not text
# written by hand. This script is how they were produced and how they are
# refreshed; CI runs it on a machine that has all three toolchains, so a
# fixture that stopped matching what the toolchain prints fails the build
# instead of quietly becoming fiction.
#
# The Go example is built in a throwaway directory on purpose. A Go panic
# records the absolute path the binary was BUILT at, so recording from a
# directory that is then deleted produces the ordinary real-world case: a
# trace naming a path that does not exist on the machine reading it.
set -euo pipefail
cd "$(dirname "$0")"

HERE="$(pwd)"
OUT="$HERE/traces"
BUILD="$(mktemp -d)/bugpacket-build"
mkdir -p "$BUILD"
trap 'rm -rf "$(dirname "$BUILD")"' EXIT

mkdir -p "$OUT"

cp -R go "$BUILD/shop"
(cd "$BUILD/shop" && go run . > "$OUT/go-panic.txt" 2>&1) || true
(cd "$BUILD/shop" && go test ./... > "$OUT/go-test.txt" 2>&1) || true

cp -R java "$BUILD/javabuild"
(
  cd "$BUILD/javabuild"
  javac -d out $(find src -name '*.java')
  java -cp out com.example.shop.Main > "$OUT/java-exception.txt" 2>&1
) || true

cp -R rust "$BUILD/rustbuild"
(cd "$BUILD/rustbuild" && RUST_BACKTRACE=1 cargo run --quiet > "$OUT/rust-panic.txt" 2>&1) || true

# The compile-error recordings. Each is the same example with one edit that
# stops it compiling, which is a different parse from every capture above: a
# build that fails to compile prints no stack trace at all, only diagnostics.
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

cp -R rust "$BUILD/rustbroken"
break_source "$BUILD/rustbroken/src/main.rs" \
  'coupon.insert("percent".to_string(), 10u32);' \
  'coupon.insert("percent".to_string(), 10.0);'
(cd "$BUILD/rustbroken" && cargo build > "$OUT/rust-compile-error.txt" 2>&1) || true

cp -R go "$BUILD/gobroken"
break_source "$BUILD/gobroken/main.go" \
  'coupon := map[string]int{"percent": 10}' \
  'coupon := map[string]float64{"percent": 10}'
(cd "$BUILD/gobroken" && go build ./... > "$OUT/go-build-error.txt" 2>&1) || true

cp -R java "$BUILD/javabroken"
break_source "$BUILD/javabroken/src/main/java/com/example/shop/Pricing.java" \
  'int percent = coupon.get("percentage");' \
  'String percent = coupon.get("percentage");'
# Only the one file, because javac pulls its dependencies in through the
# source path and the demo has to be able to name the same command.
(
  cd "$BUILD/javabroken"
  javac -d out src/main/java/com/example/shop/Pricing.java > "$OUT/javac-error.txt" 2>&1
) || true

echo "Recorded:"
ls -1 "$OUT"
