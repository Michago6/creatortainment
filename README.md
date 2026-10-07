# Creatortainment

Creatortainment turns an authored JSON script into a finished short-form
video. You provide the scenes, narration, backgrounds, reusable characters,
captions, music, sound effects, and timing; Creatortainment assembles the
storyboard, narration alignment, animated visuals, and final MP4.

The project is designed for an enjoyable **iterate → preview → render** loop:
make a small change, check it quickly, and only spend time on a full render
when everything looks right. ☕🎬

## Quick start: script to final video

This walkthrough uses the archived example script:

```text
scriptwriting/scripts/archive/pac_man_ghosts_were_never_smart.json
```

### 1. Install the full dependencies

From the repository root:

```bash
.venv/bin/python -m pip install -e '.[full]'
```

If the virtual environment does not exist yet, create it first:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[full]'
```

### 2. Check the shared assets

Every asset referenced by `asset_registry` must exist under
`scriptwriting/assets/`.
Validation catches missing files, invalid word indexes, invalid element
keyframes, invalid transitions, and other script errors before rendering.
Registry entries use an object with a project-relative `assets/...` path:

```json
"bg_studio": {
  "path": "assets/backgrounds/default_studio.jpg",
  "generate": null
}
```

The optional `generate` field may contain complete generation metadata for a
pending asset. A missing `generate` field is equivalent to `generate: null`,
so the file must already exist. All generated and reusable assets stay in the
canonical `scriptwriting/assets/` directory; project folders never contain
their own assets directory.

```bash
.venv/bin/python -m creatortainment validate \
  scriptwriting/scripts/archive/pac_man_ghosts_were_never_smart.json
```

## API keys / environment setup

Create the local environment file from the committed template:

```bash
cp .env.example .env
```

Set `FAL_KEY` to your fal.ai API key and `ELEVENLABS_API_KEY` to your
ElevenLabs API key in `.env`. Never commit `.env`; it is ignored by Git and
must remain local.

For ElevenLabs voice validation, the API key needs the `voices_read`
permission. If you use a shared or community voice, add it to **My Voices**
on the ElevenLabs Voices page before validating the script.

Validation also performs read-only provider lookups for the ElevenLabs
`project.tts_model` and `project.voice_id`, plus the effective fal.ai models
required by generated assets. These checks verify metadata only; they do not
generate audio or images and do not spend generation credits.

If validation reports a missing asset, add that file at the path declared in
the script's `asset_registry`, then run validation again. Shared assets live
once at repository level and can be reused by every project.

For the current Pac-Man script, the audio assets still needed in
`assets/audio/` are:

```text
assets/audio/sfx/arcade_beep.mp3
assets/audio/sfx/digital_glitch.mp3
assets/audio/sfx/retro_error.mp3
assets/audio/sfx/arcade_level_transition.mp3
assets/audio/sfx/dramatic_reveal.mp3
assets/audio/retro_arcade_mystery.mp3
```

The storyboard can still be generated while you are collecting or creating
those audio files, because it only needs the visual assets. Validation must
pass before alignment and video rendering can begin.

### 3. Generate a storyboard

A storyboard is the fastest way to inspect scene backgrounds, character
placement, element sizing, and rough caption layout before spending time on
audio or video rendering.

Run the dedicated storyboard command:

```bash
.venv/bin/python -m creatortainment storyboard \
  scriptwriting/scripts/archive/pac_man_ghosts_were_never_smart.json
```

By default, this creates the project folder if needed and writes:

```text
projects/pac-man-ghosts-were-never-smart/storyboard_YYYYMMDD_HHMMSS.png
```

To choose another output path inside the project folder:

```bash
.venv/bin/python -m creatortainment storyboard \
  scriptwriting/scripts/archive/pac_man_ghosts_were_never_smart.json \
  --out storyboard/iteration-02.png
```

This is the perfect stage for iteration. Open the JSON script, adjust scene
backgrounds, element `pos` values, sizes, anchors, captions, or timing, and
run the storyboard command again. Repeat until the visual plan feels good.
The storyboard requires only a valid script and its visual assets; it does not
call ElevenLabs or spend ElevenLabs credits. This is the fastest way to get a
visual overview of the project before generating narration. ✨

### 4. Generate or reuse narration alignment

Once the storyboard is in a good place, create the narration and word timing
manifest:

```bash
.venv/bin/python -m creatortainment align \
  scriptwriting/scripts/archive/pac_man_ghosts_were_never_smart.json
```

The script's `project.voice_id` selects the default voice. Scenes may use
ordered `narration_segments` for dialogue: each segment can inherit that
default or specify its own `voice_id`, and local `start_at_word` anchors plus
signed `start_offset_sec` values can create intentional overlap. Narration
files and alignment sidecars are kept permanently in the stable project
folder. If the same narration is already available, Creatortainment reuses it
instead of making another API call. If the project already exists and the
narration needs to change, the command asks for confirmation.

For detailed diagnostics:

```bash
.venv/bin/python -m creatortainment align \
  scriptwriting/scripts/archive/pac_man_ghosts_were_never_smart.json \
  --debug
```

### 5. Make a fast preview video

Preview rendering uses quarter resolution and faster encoding, making it ideal
for checking:

- scene order and timing
- caption legibility and word highlighting
- animated elements
- pauses and narration alignment
- music and sound-effect placement
- transitions and overall pacing

```bash
.venv/bin/python -m creatortainment render \
  scriptwriting/scripts/archive/pac_man_ghosts_were_never_smart.json \
  --preview \
  --out output/preview.mp4
```

The output is written relative to the project folder:

```text
projects/pac-man-ghosts-were-never-smart/output/render_YYYYMMDD_HHMMSS_preview.mp4
```

Watch the preview before starting a full render. If something feels off,
edit the script, regenerate the storyboard if the layout changed, re-run
`align` if narration text changed, and render another preview. This is where
most creative decisions are cheapest to fix. 🎨

### 6. Render the final full-resolution video

When the storyboard and preview look right, render at the script's actual
`project.resolution`:

```bash
.venv/bin/python -m creatortainment render \
  scriptwriting/scripts/archive/pac_man_ghosts_were_never_smart.json \
  --out output/final.mp4
```

Final output:

```text
projects/pac-man-ghosts-were-never-smart/output/render_YYYYMMDD_HHMMSS.mp4
```

Full-resolution rendering can take a while, especially for portrait videos
with animated elements and audio mixing. Start the command, watch the progress
bar, and make yourself a cup of coffee while MoviePy does its thing. ☕

For a more descriptive filename:

```bash
.venv/bin/python -m creatortainment render \
  scriptwriting/scripts/archive/pac_man_ghosts_were_never_smart.json \
  --out output/pac-man-ghosts-were-never-smart-final.mp4
```

That file will be written to:

```text
projects/pac-man-ghosts-were-never-smart/output/render_YYYYMMDD_HHMMSS.mp4
```

## What gets created

Projects use a stable title-based folder under `projects/`:

```text
projects/pac-man-ghosts-were-never-smart/
├── script.json
├── project_state.json
├── build_manifest.json
├── build_manifests/
├── narrations/
├── storyboard_YYYYMMDD_HHMMSS.png
├── output/
│   ├── render_YYYYMMDD_HHMMSS_preview.mp4
│   └── render_YYYYMMDD_HHMMSS.mp4
```

The script-specific manifest under `build_manifests/` is used when available.
Older projects may still use the project-level `build_manifest.json`.

## Editing guide

The main authoring file is the JSON script. Useful fields include:

- `project.resolution` and `project.fps` for output format
- `project.caption_style` for video-wide caption defaults
- `scene.caption_style` for scene-level caption overrides
- `scene.elements` and their keyframes for animated visual placement
- `scene.pause_before_sec` for intentional silent gaps
- `scene.transition_in` for transition settings
- `scene.bg_music` for music change, stop, and restart events
- `scene.sfx` for one-shot sound effects
- `project.duck_to_narration_pct` and scene overrides for music loudness

Use asset keys from `asset_registry`, not raw filesystem paths. Keep reusable
images and audio in `assets/`; generated project files belong in
`projects/<project-slug>/`.

## CLI commands

### Scriptwriting workspace

The local `scriptwriting/` workspace provides a separate, gitignored context
for writing scripts. Production `assets/` remains authoritative; the
scriptwriting asset library is a curated discovery copy with sidecars and
indexes. Setup, lifecycle, direct CLI workflow, and bootstrap details are in
[`docs/SCRIPTWRITING_WORKSPACE.md`](docs/SCRIPTWRITING_WORKSPACE.md).

The tracked [`scriptwriting_template/`](scriptwriting_template/) directory is
the clean public starting point for creating a local `scriptwriting/`
workspace. Do not run scripts directly from the template. Copy or use its
structure to initialize `scriptwriting/`, which is the actual local,
gitignored workspace used by the scriptwriting agent. It contains generic
documentation and empty directory placeholders only.

### Validate

```bash
.venv/bin/python -m creatortainment validate <script.json>
```

Validates the typed script model, referenced assets, word indexes, element
keyframes, caption values, music cues, and transition shapes.

Invalid scripts are reported with JSON paths and readable explanations instead
of repeated raw Pydantic messages. Repeated identical schema errors are grouped
by path. For example, legacy string-valued asset entries are identified with a
hint to use the current object format:

```text
✗ asset_registry.white_portrait.jpg
  Expected an asset object, but got a string ('assets/backgrounds/white_portrait.jpg').
Hint: asset_registry entries must use the current object format.
This script appears to use the legacy string format.
```

For generated assets, the effective fal.ai model is resolved from the
asset-level `generate.model` first, then
`project.generation_defaults[generation_method]`. Only generation methods
actually used by generated assets require a valid model. If several assets
share the same missing model configuration, validation groups the errors by
method instead of printing one error per asset:

```text
Asset generation:
- No model configured for image_to_image (11 assets)
- No model configured for text_to_image (17 assets)
```

Use `--asset-gen-info` to print the detailed generation plan for every
generated asset, including its asset key, generation method, effective model,
and source asset when applicable:

```bash
.venv/bin/python -m creatortainment validate \
  <script.json> \
  --asset-gen-info
```

Static assets are omitted from this report. An unresolved effective model is
shown as `<unresolved>`, even when validation fails, so the report can be
used to identify the missing configuration. Provider failures are reported
with concise status or configuration details; raw HTTP headers, trace IDs,
and full API response bodies are not printed.

### Generate assets

Generate all missing assets with a non-null `generate` block in a current-format
script:

```bash
.venv/bin/python -m creatortainment generate-assets <script.json>
```

The command resolves each asset's model from `generate.model`, then
`project.generation_defaults[generation_method]`, creates destination
directories, and processes source-asset dependencies before their consumers.
Existing files are skipped by default. Use `--force` to regenerate them:

```bash
.venv/bin/python -m creatortainment generate-assets <script.json> --force
```

Image generation uses the project's explicit `project.resolution`; it does not
infer dimensions from prompt text. FAL credentials are loaded from `FAL_KEY`
in the repository `.env` setup described above.

### Storyboard

Once you have all the assets for your video, you can generate a storyboard to
see what the project will look like:

```bash
.venv/bin/python -m creatortainment storyboard <script.json>
```

This is the fastest way to get an overview of the project's scenes, asset
placement, composition, and captions before spending time on narration
alignment or a video render. The storyboard is written to the project's
`storyboard_YYYYMMDD_HHMMSS.png` file. Use `--out <path>` to choose another
output path inside the project folder. Existing storyboard and render files are
never overwritten; a timestamped alternative name is selected when needed.

### Align

```bash
.venv/bin/python -m creatortainment align <script.json>
```

Generates or reuses the full-video ElevenLabs narration, word alignment, and
build manifest.

Useful flags:

- `--force-audio` — skip confirmation and create a new narration take
- `--debug` — write request and response diagnostics to
  `projects/<slug>/debug.log` without recording the API key

### Render

```bash
.venv/bin/python -m creatortainment render <script.json>
```

Useful flags:

- `--preview` — quarter-resolution, faster render
- `--out <path>` — output path relative to the project directory

For command help:

```bash
.venv/bin/python -m creatortainment --help
.venv/bin/python -m creatortainment validate --help
.venv/bin/python -m creatortainment generate-assets --help
.venv/bin/python -m creatortainment align --help
.venv/bin/python -m creatortainment render --help
.venv/bin/python -m creatortainment storyboard --help
```

## Running tests

The test suite is offline and mocks provider lookups, so it does not call
ElevenLabs or fal.ai or spend API credits:

```bash
.venv/bin/python -m pytest
```

The tests cover schema validation, asset checks, tokenization, narration
caching, alignment, caption rendering, animated elements, timeline mapping,
music/SFX mixing, and final audio attachment.

## A small piece of advice

Do not wait for the full render to discover that an element is slightly too
far left or a caption is too low. The storyboard catches composition issues;
the preview catches timing and audio issues; the final render is for producing
the polished result. That workflow keeps the creative process quick,
repeatable, and much less stressful. 🚀
