# Creatortainment

Creatortainment turns an authored JSON script into a project folder. Shared
assets live at the repository level and are referenced by the script's
`asset_registry`.

## First test

Add the files below to `assets/` using the paths in
`scripts/example_scripts/example_script.json`:

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

Generate narration and alignment first:

```bash
python3 -m creatortainment align \
  scripts/example_scripts/example_script.json
```

Then render a fast first MP4 preview:

```bash
python3 -m creatortainment render \
  scripts/example_scripts/example_script.json \
  --preview
```

## Running tests

Install the development/test dependencies, then run the complete offline test
suite:

```bash
.venv/bin/python -m pip install -e '.[full]'
.venv/bin/python -m pytest
```

The tests do not call ElevenLabs or spend API credits. They cover tokenization,
alignment, project identity, narration hash caching, response parsing, and
asset/script validation.

To generate real narration and alignment, install the full dependencies:

```bash
pip install -e '.[full]'
python3 -m creatortainment align scripts/example_scripts/example_script.json
```

The program reads the API key automatically from the repository-root file
`elevenlabs_api_key.txt`. The ElevenLabs voice ID is configured in the script's
`project.voice_id` field.

For detailed ElevenLabs diagnostics, add `--debug`:

```bash
python3 -m creatortainment align \
  scripts/example_scripts/example_script.json \
  --debug
```

Diagnostics are written to `projects/<slug>/debug.log`. The log records request
metadata, response type and fields, encoded-audio size, alignment shape, and
parsing exceptions; it never records the API key.

Projects use a stable title-based folder under `projects/`. Narrations are
stored permanently under that project's `narrations/` folder, each with a
sidecar alignment JSON file. Re-running the same narration prompts for
confirmation and does not create another audio file; changed narration creates
a new file after confirmation. Use `--force-audio` to skip confirmation and
always create a new take.

## CLI commands and flags

### `validate`

```bash
python3 -m creatortainment validate <script.json>
```

Validates the script structure, asset registry, referenced asset files, word
indexes, resolution, anchors, element sizing, TTS model, and voice ID.

Flags:

- `-h`, `--help` — show command help.

### `render`

```bash
python3 -m creatortainment render <script.json>
```

Builds all scenes with their static layouts, captions, and narration audio,
then writes one MP4 with hard cuts between scenes. Run `align` for the same
script first so its build manifest and active narration are available.

Flags:

- `--out <path>` — choose the output MP4 path relative to the project
  directory. The default is `output/video.mp4`.
- `--preview` — render at quarter resolution with a reduced frame rate and
  faster encoding for quick checks.
- `-h`, `--help` — show command help.

### `align`

```bash
python3 -m creatortainment align <script.json>
```

Generates the real ElevenLabs narration, word alignment, narration sidecar,
and `build_manifest.json`.

Flags:

- `--force-audio` — skip the existing-project confirmation and always generate
  a new narration file. Existing narration files are never overwritten.
- `--debug` — write detailed request, response, and parsing diagnostics to
  `projects/<slug>/debug.log`.
- `-h`, `--help` — show command help.

For help on any command:

```bash
python3 -m creatortainment --help
python3 -m creatortainment validate --help
python3 -m creatortainment render --help
python3 -m creatortainment align --help
```

Each project uses a stable folder like:

```text
projects/understanding_gpu_architecture/
├── script.json
├── build_manifest.json
├── build_manifests/
└── output/video.mp4
```

Use the script-specific manifest under `build_manifests/` when available;
rendering falls back to the legacy project-level manifest for older projects.
The current MoviePy renderer uses static first-keyframe layouts, static
captions, and narration audio. Animated timelines, word highlighting, and
mixed music/SFX audio are still upcoming phases.
