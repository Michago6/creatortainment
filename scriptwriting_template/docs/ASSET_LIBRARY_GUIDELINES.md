# Asset library guidelines

The local `scriptwriting/assets/` directory is a curated creative library.
The `scriptwriting/assets/` directory is the canonical production asset root.
The scriptwriting agent must not silently modify production assets.

## Organization

Organize assets by what they are and how they can be reused, not by the video
that first used them. Begin with concrete concepts supported by the actual
library, such as backgrounds, characters, diagrams, textures, music, or sound
effects. Do not create a large taxonomy in advance.

Categories are dynamic. Create a category when several assets share a useful
recurring concept and the category materially improves discovery. Categories
may be split, merged, renamed, or reorganized as the library grows.

- One level is normal.
- Two levels are allowed when useful.
- Three levels is the maximum.
- Avoid arbitrary deep nesting and one-off categories.

## One physical location and sidecars

Each curated asset has one primary physical location. Do not duplicate an
asset merely because it fits multiple concepts. Use indexes and cross-links
for alternate discovery.

Place one Markdown sidecar beside each asset:

```text
assets/<category>/example.ext
assets/<category>/example.ext.md
```

Sidecars should describe what the asset is, visual or audio characteristics,
good and future uses, useful pairings, limitations, and provenance or model
information when known.

## Index-first discovery

Use:

```text
ASSET_INDEX.md → category/INDEX.md → asset sidecar
```

The global index should remain compact. Each category `INDEX.md` should
describe what the category contains, useful scene/video purposes,
characteristics, its assets, related categories, and alternative discovery
paths. Do not make indexes a dump of every sidecar.

If concepts overlap, prefer cross-links for occasional overlap. Merge
categories when a distinction stops being useful, split categories that
become too broad, and move an asset when another primary location is clearly
better. Update every affected index. Never conclude that an asset is absent
without checking related categories.
