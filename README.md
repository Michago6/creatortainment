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

Then validate the script:

```bash
python3 -m creatortainment validate example_script.json
```

Create the first dependency-light storyboard mock:

```bash
python3 -m creatortainment render example_script.json
```

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
