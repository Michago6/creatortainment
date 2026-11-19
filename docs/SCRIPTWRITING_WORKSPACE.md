# Scriptwriting workspace

Creatortainment has a separate, local-only `scriptwriting/` workspace for
script authors. It is intentionally gitignored so writing context, curated
asset copies, sidecars, storyboard drafts, and learned preferences do not
become implementation repository history.

The workspace contains authoring docs, `scripts/drafts/`, `scripts/archive/`,
curated assets, and `agent_knowledge/`. The canonical
production asset root is `scriptwriting/assets/`; scripts retain the
project-relative `assets/...` registry namespace. Curated asset metadata and
indexes support discovery and
their sidecars record the production source; scripts still use production
`assets/...` registry paths.

Start the separate scriptwriting agent with `scriptwriting/` as its intended
working context:

```bash
cd scriptwriting
copilot
```

This is a workflow/context boundary, not a security boundary. The agent still
has shell access, so it should prefer files inside `scriptwriting/` and should
not inspect `creatortainment/`, production assets, `projects/`, `testing/`, or
unrelated repository files unless the user explicitly asks.

From the repository root, use the normal CLI directly:

```bash
.venv/bin/python -m creatortainment validate scriptwriting/scripts/drafts/my_script.json
.venv/bin/python -m creatortainment storyboard scriptwriting/scripts/drafts/my_script.json
```

Always validate before considering a script complete. Storyboards may write to
`projects/`; the agent does not need to inspect that directory unless
explicitly asked. Do not perform a full video render unless explicitly
requested.

Populate or refresh the curated library offline with:

```bash
.venv/bin/python tools/bootstrap_scriptwriting_assets.py --inspect-frames
```

The bootstrap copies production assets, records dimensions/media metadata,
extracts representative local frames for GIF/video files, writes sidecars and
indexes, and stores fingerprints so later runs skip unchanged assets.
