# Creatortainment

Creatortainment turns an authored JSON script into a project folder. Shared
assets live at the repository level and are referenced by the script's
`asset_registry`.

## First test

Add the files below to `assets/` using the paths in `example_script.json`:

```text
assets/backgrounds/default_studio.jpg
assets/backgrounds/cyberpunk_room.jpg
assets/sprites/mrmouse_relaxed.png
assets/sprites/mrmouse_pointing.png
assets/sprites/mrmouse_laptop.png
assets/sprites/mrmouse_excited.png
assets/images/gpu_core_diagram.jpg
assets/images/gpu_core_grid.jpg
assets/audio/sfx/pop.mp3
assets/audio/sfx/whoosh.mp3
assets/audio/monkeys_spinning_monkeys.mp3
```

The example scripts are stored under `scripts/example_scripts/`. Validate one
of them with:

```bash
python3 -m creatortainment validate scripts/example_scripts/example_script.json
```

Create the first dependency-light storyboard mock:

```bash
python3 -m creatortainment render scripts/example_scripts/example_script.json
```

To exercise the offline narration alignment pipeline without API credentials:

```bash
python3 -m creatortainment align \
  scripts/example_scripts/example_script.json \
  --mock-response tests/fixtures/mock_elevenlabs_response.json
```

This creates a project folder containing `script.json`, `build_manifest.json`,
and the cached `narration.mp3` bytes returned by the mock client. A repeated
alignment with the same narration uses the manifest cache. Changing any
scene's `narration_text` causes one new full-video synthesis.

Each render creates a folder like:

```text
projects/understanding-gpu-architecture-20260916-132445/
├── script.json
├── build_manifest.json
└── output/storyboard.png
```

The current mock renderer creates a storyboard PNG and manifest. ElevenLabs,
audio alignment, MoviePy video rendering, and API integrations will be added
after the asset-backed mock passes.
