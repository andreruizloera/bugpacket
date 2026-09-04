# Roadmap

Honest future work, in rough priority order. None of this exists yet.

- **More stack-trace dialects.** Rust panics and backtraces, Go panics, Java
  and JVM stack traces, Ruby, and browser-flavored JS traces. The parser is
  regex-based and each dialect is a contained addition with fixtures.
- **Jest and vitest awareness.** Parse their failure summaries the way pytest
  summaries are parsed today, so the failing spec file ranks at 2 even when
  the trace is noisy.
- **Configurable secret-name denylist.** A `[tool.bugpacket]` section in
  pyproject.toml to extend the built-in pattern for company-specific naming
  conventions.
- **Recent-log capture.** Opt-in inclusion of an application log file tail
  (path given explicitly by the user) with the same budget accounting.
- **Smarter trimming.** Trim within a file by function boundaries instead of
  fixed line windows, so a trimmed file still parses.
- **`bugpacket diff` mode.** Build a packet for a failure that only reproduces
  against a dirty tree, comparing against the last green commit.
- **Watch mode.** `bugpacket watch -- pytest` reruns on file change and keeps
  the packet fresh, so the latest failure is always one `bugpacket copy` away.
- **Real tokenizer adapters.** Optional exact token counts when a tokenizer
  library is installed; the chars/4 estimate stays the zero-dependency default.
- **Windows support.** Path handling for drive-letter stack frames and a
  clip.exe clipboard backend.
