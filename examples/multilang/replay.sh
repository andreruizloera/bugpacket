#!/usr/bin/env bash
# Print a recorded trace and exit the way the real command exited.
#
# This exists so the demo runs on a machine with no Rust, Go, or JVM
# toolchain. BugPacket reads a command's output; it does not care whether the
# process that produced that output was a compiler or a `cat`. The files in
# traces/ are real captures (see record-traces.sh), so what BugPacket parses
# here is exactly what it would parse from the live command.
set -euo pipefail
cd "$(dirname "$0")"

if [ $# -ne 2 ]; then
  echo "usage: replay.sh <trace-name> <exit-code>" >&2
  exit 2
fi

trace="traces/$1.txt"
if [ ! -f "$trace" ]; then
  echo "replay.sh: no recorded trace at $trace" >&2
  exit 2
fi

cat "$trace"
exit "$2"
