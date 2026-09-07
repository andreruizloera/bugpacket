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

echo "Recorded:"
ls -1 "$OUT"
