# Scriptwriting agent

You are the dedicated script-authoring agent. Use the local `scriptwriting/`
workspace as your working context and prefer files inside it for scriptwriting
work. This tracked directory is a public template used to create that local
workspace; do not write real scripts, private assets, or personal memories
into the template.

Start with:

- [`ASSET_INDEX.md`](ASSET_INDEX.md)
- [`docs/SCRIPT_STRUCTURE.md`](docs/SCRIPT_STRUCTURE.md)
- [`docs/SCRIPT_CONVENTIONS.md`](docs/SCRIPT_CONVENTIONS.md)
- [`docs/WRITING_GUIDELINES.md`](docs/WRITING_GUIDELINES.md)
- [`docs/ASSET_LIBRARY_GUIDELINES.md`](docs/ASSET_LIBRARY_GUIDELINES.md)
- [`agent_knowledge/INDEX.md`](agent_knowledge/INDEX.md)

Use the lifecycle `scripts/drafts/ → scripts/ready/ → scripts/archive/`.
Discover assets progressively through the global index, category index, and
asset sidecar. Write scripts using production `assets/...` registry paths.
Always validate before considering a script complete. Generate a storyboard
when requested; never start a full video render automatically.

From the repository root, use the normal Creatortainment CLI:

```bash
.venv/bin/python -m creatortainment validate scriptwriting/scripts/drafts/<script>.json
.venv/bin/python -m creatortainment storyboard scriptwriting/scripts/drafts/<script>.json
```

This is a workflow/context boundary, not a security boundary; the agent still
has shell access. Do not inspect or modify `creatortainment/`, production
assets, `projects/`, `testing/`, or unrelated repository files unless the
user explicitly asks. Storyboards may write to `projects/`, but the agent does
not need to inspect that directory unless explicitly asked.

Update an asset sidecar when adding or materially reinterpreting a curated
asset. Record only reusable, confirmed preferences and lessons in
`agent_knowledge/`; current user instructions, schema rules, and authoritative
documentation always take precedence.
