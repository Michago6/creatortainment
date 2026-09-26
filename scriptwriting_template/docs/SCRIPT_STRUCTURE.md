# Script structure for authors

This document is an author-oriented overview. `SCRIPT_CONVENTIONS.md` and the
application's validation command provide the detailed rules; the application's
schema remains authoritative for validity.

Creatortainment scripts are JSON objects with three required top-level
sections:

```json
{
  "project": {},
  "asset_registry": {},
  "scenes": []
}
```

- `project` contains video-wide settings and defaults.
- `asset_registry` maps stable asset keys to production asset paths and
  optional generation metadata.
- `scenes` describe the video in order, including narration, backgrounds,
  elements, captions, transitions, music, and sound cues.

Scene references use asset-registry keys, not raw filesystem paths. Registry
paths normally point into the production `assets/` directory.

## Authoring workflow

1. Read the relevant authoritative conventions and asset indexes.
2. Create or edit the script in `scripts/drafts/`.
3. Use existing reusable assets when appropriate.
4. Validate from the repository root:

   ```bash
   .venv/bin/python -m creatortainment validate scriptwriting/scripts/drafts/<script>.json
   ```

5. Generate a storyboard when visual review is requested:

   ```bash
   .venv/bin/python -m creatortainment storyboard scriptwriting/scripts/drafts/<script>.json
   ```

6. Fix validation or storyboard issues, validate again, and move the finished
   script to `scripts/ready/`.
7. Move completed or superseded scripts to `scripts/archive/` when appropriate.

Do not perform a full video render automatically. Rendering remains an
explicit user operation.
