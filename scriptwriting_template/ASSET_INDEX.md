# Curated asset index

This file is the entry point for the local scriptwriting asset library.
Production `assets/` is authoritative; the local `scriptwriting/assets/`
directory is a curated, agent-facing copy with one sidecar beside each asset.

Use progressive discovery instead of scanning every sidecar:

```text
global ASSET_INDEX.md
    ↓
category/INDEX.md
    ↓
individual-asset.ext.md
```

The template intentionally contains no real assets. When setting up a local
workspace, add categories that emerge from the actual reusable library, then
link each category index here. A conceptual example is:

```text
assets/
├── backgrounds/
│   ├── INDEX.md
│   └── reusable_background.ext
│       └── reusable_background.ext.md
└── audio/
    └── sfx/
        ├── INDEX.md
        └── reusable_sound.ext
            └── reusable_sound.ext.md
```

Assets have one primary physical location, but an asset can be conceptually
useful in multiple categories. Follow related-category links before deciding
that a suitable asset does not exist.
