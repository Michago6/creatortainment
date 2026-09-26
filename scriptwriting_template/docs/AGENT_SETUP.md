# Scriptwriting agent setup

The real local workspace is `scriptwriting/`. It is gitignored because it
contains local drafts, curated asset copies, sidecars, and learned knowledge.
This tracked `scriptwriting_template/` directory is the clean public starting
point users copy from. It is not the live workspace and scripts should not be
run directly from it; it is not a production asset registry.

## Create a local workspace

When creating a new local workspace, first confirm that `scriptwriting/` does
not already contain real work. From the repository root, copy the tracked
template into `scriptwriting/`:

```bash
cp -a scriptwriting_template/. scriptwriting/
```

`scriptwriting/` is the actual local workspace used by the scriptwriting
agent. It is gitignored and is where drafts, curated assets, sidecars, and
agent knowledge belong.

Then populate `scriptwriting/assets/` only with curated copies or links
appropriate for the local project. Keep `scriptwriting/assets/` as the
canonical production asset root.
The repository's asset-bootstrap tooling can inventory production assets and
create curated sidecars and indexes when that workflow is used.

## Start the agent

Start a separate Copilot CLI session with the local workspace as its intended
context:

```bash
cd scriptwriting
copilot --agent scriptwriter
```

Changing directories provides workflow context, not filesystem security. The
agent still has shell access. It should prefer files inside `scriptwriting/`
and should not inspect `creatortainment/`, production assets, `projects/`,
`testing/`, or unrelated repository files unless the user explicitly asks.

## Direct CLI workflow

From the repository root:

```bash
.venv/bin/python -m creatortainment validate scriptwriting/scripts/drafts/<script>.json
.venv/bin/python -m creatortainment storyboard scriptwriting/scripts/drafts/<script>.json
```

These commands intentionally use paths under the real `scriptwriting/`
workspace, not under `scriptwriting_template/`.

Always validate before considering a script complete. Storyboards may write to
`projects/`; do not inspect that directory unless explicitly requested. Do not
perform a full video render unless explicitly requested.

## Session and knowledge workflow

For a genuinely new video, prefer a fresh scriptwriter session so unnecessary
conversation history is not carried forward. Reuse `agent_knowledge/` only for
confirmed reusable preferences and lessons. Current user instructions,
validation/schema rules, authoritative docs, and setup instructions take
precedence over learned knowledge.
