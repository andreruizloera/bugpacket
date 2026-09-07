# Roadmap

Honest future work, in rough priority order. Nothing below is implemented;
where a shipped feature is named, it is named only to say what is left of it.

- **The remaining compiler diagnostics.** rustc, `go build`, and javac ship;
  `tsc` (`src/app.ts(10,5): error TS2322: ...`), clang and gcc
  (`main.c:10:5: error: ...`), and MSBuild are the ones left. Each is one line
  format and a recorded capture, in `diagnostics.py` beside the three that
  exist, but none of them should be written from memory: the recordings in
  `examples/multilang/traces/` are what keeps the parsers honest, and a
  toolchain has to be installed to make one.
- **A second independent compiler error.** Only the first is reported as the
  failure, because the errors after it are usually consequences of it. Two
  genuinely unrelated errors in one build are not distinguishable from that
  today; nothing short of reading the messages would tell them apart.
- **The remaining stack-trace dialects.** Ruby, and browser-flavored JS
  traces. Rust, Go, and JVM shipped; each new dialect is a contained addition
  to `dialects.py` with a recorded fixture.
- **Stack-frame ordering.** Frames are kept in the order the runtime printed
  them, which means Python reads outermost-first and Rust, Go, and the JVM read
  innermost-first. Normalising to one direction, and saying which, would make
  the "Relevant stack" section read the same way for every language.
- **Import following for Rust and the JVM.** Both are handled today by the
  trace naming every frame's file, which is usually enough. A Rust `mod`/`use`
  graph and a JVM `import` reader would add the collaborator that the trace
  passed through without failing in.
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
