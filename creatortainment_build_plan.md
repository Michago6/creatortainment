# creatortainment — Build Plan

## What this is

`creatortainment` is a Python program that takes a JSON "video script" (schema
below) describing a short-form tech-education video — narration, background,
on-screen character/diagram animations, captions, music, and sound effects —
and renders it to a final video file using MoviePy. Narration audio and
word-level timing come from a single ElevenLabs TTS call covering the whole
video. All timing in the script (music cues, sfx cues, animation keyframes,
caption highlighting) is expressed as a *word index* into that scene's
narration text, not as raw seconds — the build pipeline resolves word index →
real timestamp using the ElevenLabs alignment.

Reference schema + fully worked example: `example_script.json` (attached).

## Guiding principles for implementation

- **Authored script vs. generated build artifacts are separate files.**
  `script.json` (hand/LLM-authored, no timestamps) never gets timestamps
  written back into it. All generated data (audio file, word timestamps,
  resolved scene durations) lives in a separate `build_manifest.json`.
- **Validate before rendering, always.** A full pass that checks every
  `asset_registry` reference resolves, every `trigger_word_index` is within
  bounds for its scene's narration word count, and the schema is otherwise
  well-formed — before any TTS call or MoviePy work happens. Fail loud and
  early, not halfway through a render.
- **Cache aggressively at two independent granularities.** Audio (TTS +
  alignment) is cached keyed on the hash of *all* narration_text concatenated
  across the whole script — editing any scene's wording invalidates the whole
  audio cache. Each scene's *visual* render is cached independently, keyed on
  the hash of that scene's non-narration fields (bg, elements, sfx, transitions,
  caption style) — so a wording tweak in scene 4 does not force a re-render of
  scene 1's visuals.
- **Word tokenization must be implemented exactly once** (split narration_text
  on whitespace, no punctuation splitting) and reused everywhere an index is
  resolved — captions, sfx, bg_music, element keyframes. Do not duplicate this
  logic.

## Suggested repo structure

```
creatortainment/
  creatortainment/
    __init__.py
    schema/
      models.py          # Pydantic models mirroring example_script.json
      validate.py         # asset-ref checks, index-bounds checks, schema load
    audio/
      tokenize.py          # canonical whitespace tokenizer (single source of truth)
      elevenlabs_client.py  # full-video TTS call + word-timestamp retrieval
      alignment.py          # global word-timestamp array -> per-scene slices
      manifest.py            # build_manifest.json read/write + audio cache hashing
    render/
      timeline.py           # word_index (local) -> absolute seconds, per scene
      keyframes.py           # easing functions + interpolation between keyframes
      scene_builder.py       # one scene -> a MoviePy CompositeVideoClip
      captions.py             # word-highlight caption rendering (TextClip/PIL)
      audio_mix.py            # bg_music (fade/volume) + sfx placement + ducking
      transitions.py           # crossfade etc. between adjacent scene clips
      cache.py                  # per-scene visual render cache
    cli.py                       # entry point: validate / render / preview commands
  tests/
    fixtures/
      example_script.json        # copy of the attached example
      mock_elevenlabs_response.json
    test_tokenize.py
    test_validate.py
    test_alignment.py
    test_keyframes.py
  pyproject.toml
  README.md
```

## Dependencies

- `moviepy`
- `pydantic` (schema models + validation)
- `elevenlabs` (official SDK) — wrap all calls behind `elevenlabs_client.py` so
  tests can mock it; never hit the real API in unit tests.
- `click` or `typer` for the CLI
- `pytest` for tests

## Build phases

Work through these roughly in order. Each phase should end with something
runnable/testable — don't let phases blur together.

### Phase 0 — Scaffolding
- Repo structure above, `pyproject.toml`, dependency install, empty CLI with
  `--help` working.
- Acceptance: `python -m creatortainment --help` runs.

### Phase 1 — Schema + validation
- Pydantic models for the full `example_script.json` shape (project,
  asset_registry, scenes, elements, keyframes, sfx, bg_music, caption_style,
  the `_conventions` block can just be an ignored/passthrough field).
- `validate.py`: load a script, check every asset reference resolves against
  `asset_registry`, check every `trigger_word_index` is within bounds for its
  scene's tokenized narration_text word count, report all errors found (not
  just the first).
- CLI command: `creatortainment validate script.json`.
- Acceptance: validating `example_script.json` passes cleanly; a deliberately
  broken copy (bad asset key, out-of-range index) reports the specific errors.

### Phase 2 — Tokenizer
- `tokenize.py`: canonical whitespace-only tokenizer per the `_conventions`
  rule in the schema. This is used by both validation (Phase 1) and alignment
  (Phase 3) — implement once, import everywhere.
- Acceptance: unit tests covering punctuation-attached words, contractions,
  hyphenated words, multiple spaces.

### Phase 3 — ElevenLabs integration + alignment slicing
- `elevenlabs_client.py`: given the full script, concatenate all scenes'
  `narration_text` (respecting `pause_before_sec` via SSML breaks if
  supported, else track pause durations separately for later silence
  splicing), make one TTS call, return audio bytes + word-level timestamps.
- `alignment.py`: given the global timestamp array and each scene's word
  count (from the tokenizer), slice out per-scene timestamp ranges and
  compute each scene's `start_time_sec` / `end_time_sec` / `duration_sec`.
- `manifest.py`: write/read `build_manifest.json` in the shape discussed
  earlier (global audio path + timestamps + per-scene offsets/durations);
  hash-based cache check to skip the API call if narration text is unchanged.
- Mock the ElevenLabs client in tests with a fixture response — no live API
  calls in the test suite.
- Acceptance: running against `example_script.json` (with a mocked client)
  produces a `build_manifest.json` with correct per-scene word offsets and
  durations.

### Phase 4 — Timeline resolution
- `timeline.py`: given a scene, its local `trigger_word_index`, and the
  manifest, return an absolute second within that scene's clip (i.e. relative
  to the scene's own start, ready to hand to MoviePy's `.set_start()` /
  keyframe timing) — not the global video time.
- Acceptance: unit tests resolving known indices from the fixture manifest to
  expected seconds.

### Phase 5 — Static scene compositing
- `scene_builder.py`: for one scene, build background clip + element clips at
  their *first* keyframe position/scale/opacity only (no interpolation yet),
  sized/cropped to `project.aspect_ratio`, duration from the manifest.
- Acceptance: rendering `example_script.json` produces a rough video with
  correct scene lengths, backgrounds, and static character/diagram placement,
  no captions/audio/animation yet.

### Phase 6 — Keyframe interpolation
- `keyframes.py`: implement the `easing_values` set (instant, linear, ease_in,
  ease_out, ease_in_out, bounce) as functions of `t \u2208 [0,1]`, and interpolate
  pos/scale/opacity between consecutive keyframes resolved via Phase 4's
  timeline. Opacity via mask-based fading (MoviePy has no native alpha tween).
- Acceptance: elements in the example script visibly move/scale/fade per
  their keyframes at the right times.

### Phase 7 — Word-highlight captions
- `captions.py`: render narration_text (or static caption_text per the
  word-count-mismatch fallback rule) with the current word highlighted per
  the ElevenLabs timing, styled per `caption_style` (project default merged
  with any scene override).
- Acceptance: captions appear, are readable at the configured position/size,
  and the highlighted word changes in sync with narration audio.

### Phase 8 — Audio mixing
- `audio_mix.py`: place the global narration track, layer `bg_music` with
  volume/fade_in resolved via Phase 4 timing, layer `sfx` cues the same way,
  duck music under narration (simple volume drop while narration audio is
  present, restore after).
- Acceptance: final audio mix has narration clearly audible over ducked
  music, sfx land on the correct words.

### Phase 9 — Transitions
- `transitions.py`: crossfade (and any other `transition_in.type` values you
  add later) applied between adjacent scene clips before final concatenation.
- Acceptance: scene boundaries in `example_script.json` show a crossfade
  where specified and a hard cut where `transition_in` is null.

### Phase 10 — Caching + CLI polish
- `cache.py`: per-scene visual cache keyed on a hash of that scene's
  non-narration fields; skip re-rendering unchanged scenes on repeat runs.
- CLI: `creatortainment render script.json --out video.mp4`,
  `creatortainment render script.json --preview` (quarter-res, faster encode,
  for quick iteration).
- Acceptance: editing one scene's caption_style and re-rendering only
  rebuilds that scene's clip, not the whole video (verify via log output or
  timing).

### Phase 11 — End-to-end + nice-to-haves (pick up after core works)
- Full pipeline test: `example_script.json` → validate → TTS+alignment →
  render → final mp4, asserted against expected duration/resolution.
- Nice-to-haves, roughly in priority order: Ken Burns pan/zoom on backgrounds,
  scene templates/macros for recurring choreography patterns, simple
  amplitude-driven mouth-flap animation for the mascot, fixed intro/outro
  template applied outside the per-video script.

## Notes for whoever (or whatever) implements this

- Don't let MoviePy's default `TextClip` be the caption renderer if it can't
  do per-word color highlighting cleanly — compositing individual word
  `TextClip`s per frame, or dropping to PIL/Pillow for direct frame drawing,
  is likely necessary for the highlight effect and should be decided early in
  Phase 7, not discovered late.
- Keep `elevenlabs_client.py` as the *only* file that imports the ElevenLabs
  SDK, so the rest of the codebase — and all tests — depend on a plain
  Python interface you control.
- `_conventions` in the script JSON is documentation only; the schema loader
  should accept and ignore it, never validate against it.
