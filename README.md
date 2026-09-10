# Creatortainment scene generator

This terminal app turns a scene script into per-project text, image, and narration files.
It uses ElevenLabs for image generation and text-to-speech. Image generation is asynchronous,
so the app polls until each image is ready.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
printf '%s\n' 'your-elevenlabs-api-key' > api_keys.txt
```

`api_keys.txt` is ignored by git. Keep the key on its first non-empty, non-comment line.

## Run

```bash
python app.py script.txt \
  --name cookie-explainer \
  --voice-id YOUR_ELEVENLABS_VOICE_ID \
  --reference MrMouse-reference-sheet.png
```

Repeat `--reference` to provide more reference images. The default image model is
`gemini-3.1-flash-lite-image`, with a forced `9:16` aspect ratio and `1K` resolution.
Use `--image-model MODEL_ID` if the model available to your ElevenLabs workspace differs.
The default TTS model is `eleven_multilingual_v2`.

Generated files are written below `projects/<project-name>/`:

```text
script.txt
script_visual_only.txt
script_speak_only.txt
scenes/scene_01.png
audio/scene_01.mp3
```

`script.txt` is the original user-provided script, unchanged. The visual and speak files
contain only their respective extracted sections.

The parser expects each scene to have this shape:

```text
SCENE 1

[VISUAL] A vertical scene description.

[SPEAK] The narration for this scene.
```

For a local parsing-only run:

```bash
python app.py script.txt --name cookie-explainer --skip-images --skip-audio
```
