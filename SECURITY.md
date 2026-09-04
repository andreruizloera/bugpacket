# Security

## Model

BugPacket runs commands you give it, reads files in your repository, and
writes a packet to a local `.bugpacket/` directory. It is strictly local:

- There is no network code in the source tree. Nothing is uploaded, no
  telemetry, no version checks. `tests/test_no_network.py` fails the build if
  networking modules ever appear in `src/`.
- Environment variable values are never captured. Variable names are captured
  but filtered against a denylist (KEY, TOKEN, SECRET, PASSWORD, and similar),
  so even a suspicious name never reaches the packet.

## What you should still review

The packet contains your source files, your git diff, and your command
output. If your code or test output itself prints secrets, those will be in
the packet, because BugPacket cannot know what is secret inside arbitrary
program output. Read `packet.md` before pasting it anywhere.

BugPacket executes the command you pass after `--` exactly as given. It does
not sandbox it. Do not point it at commands you would not run yourself.

## Reporting

Open a GitHub issue for anything that does not expose sensitive data. For a
report that does, email andre.x.ruizloera@gmail.com.
