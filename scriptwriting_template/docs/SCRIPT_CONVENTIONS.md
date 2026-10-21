# Creatortainment Script Conventions

This is the **single canonical authoring guide for creatortainment JSON scripts**
from the scriptwriter agent's perspective.

It exists primarily so humans and LLMs have one consistent description of how
scripts are supposed to be written. For the scriptwriter agent, this document
and `SCRIPT_STRUCTURE.md` are the normal authoring references. The actual
Pydantic schema remains authoritative for the software itself, but the
scriptwriter agent should rely on the maintained scriptwriting documentation
when authoring scripts rather than inspecting `creatortainment/` source code,
tests, or implementation details unless the user explicitly asks.

This document does **not** itself enforce the rules. The software's Pydantic
schema and validation code are the authoritative enforcement mechanism for the
application itself.

## Rule precedence

When information conflicts, use this order:

1. **Current maintained scriptwriting documentation (`SCRIPT_STRUCTURE.md` and `SCRIPT_CONVENTIONS.md`)** — the normal authoring references for the scriptwriter agent.
2. **Current Pydantic schema and validation code** — authoritative for software validity.
3. **Individual JSON scripts** — content only. Any `_conventions` object found inside an individual script is legacy documentation and is not a separate source of truth.

New scripts should **not** duplicate the conventions document inside `_conventions`.

Existing scripts may still contain `_conventions` for historical reasons. Do not copy those blocks forward when creating a new script. When an old script conflicts with this document, treat the old block as stale unless the current schema/code proves otherwise.

---

# 1. Script structure

Every script is a single JSON object with these top-level sections:

```json
{
  "project": {},
  "asset_registry": {},
  "scenes": []
}
```

A script must contain at least one scene.

The three sections have different responsibilities:

- `project` contains video-wide configuration and defaults.
- `asset_registry` defines every asset and its real file path.
- `scenes` describe the video in order.

Do not put raw filesystem paths into scene references. Scenes reference asset-registry keys.

---

# 2. Project identity and naming

## 2.1 `project.title`

New script titles must be:

- lowercase
- words separated with underscores
- stable
- free of dates and timestamps

Examples:

```text
minecraft_is_a_horror_game
pac_man_ghosts_were_never_smart
asset_generation_test
```

The title is the stable project identity and corresponds to the project directory name.

Do not create titles such as:

```text
Minecraft Is a Horror Game
minecraft-is-a-horror-game
minecraft_is_a_horror_game_2026_09_22
```

The project folder must not acquire a date or timestamp.

Existing legacy scripts may have older human-readable titles. They are legacy data, not the convention for new scripts.

## 2.2 `project.date`

`date` is metadata only.

It does not participate in project identity matching or narration-cache identity.

Use:

```text
YYYY-MM-DD
```

---

# 3. Project configuration

The project section contains the video-wide defaults:

```json
{
  "title": "minecraft_is_a_horror_game",
  "date": "2026-09-22",
  "tts_model": "eleven_v3",
  "voice_id": "...",
  "duck_to_narration_pct": 0.4,
  "aspect_ratio": "9:16",
  "resolution": [1080, 1920],
  "fps": 30,
  "generation_defaults": {
    "text_to_image": null,
    "image_to_image": null,
    "text_to_audio": null,
    "audio_to_audio": null
  },
  "caption_style": {}
}
```

## 3.1 TTS model

`project.tts_model` selects the ElevenLabs model used for the **single full-video narration generation call**.

The production default is:

```text
eleven_v3
```

`eleven_flash_v2_5` is reserved for testing. A script may explicitly choose
another valid model only when there is a deliberate reason or the user
requests it.

A more expensive model is an explicit override, not the default convention.

## 3.2 Voice

`project.voice_id` is the ElevenLabs voice ID for the narration call.

Every script that contains narration must provide a voice ID.

The voice ID affects which voice is used, not the basic project structure.

## 3.3 Narration speed

`project.speed` optionally controls the speed used by ElevenLabs during TTS
generation. It accepts values from `0.7` through `1.2`, inclusive, and defaults
to `1.0` when omitted:

```json
"project": {
  "voice_id": "VOICE_ID",
  "speed": 1.1
}
```

Speed changes the generated narration and its returned alignment timestamps. It
does not change MoviePy playback speed and is never applied as post-processing.
The setting applies to legacy narration and every multi-voice segment. Changing
it creates a different narration cache identity.

Model capabilities constrain these options: Eleven v3, Eleven v3 Conversational,
Eleven v4, and Eleven v4 Turbo support expressive audio tags but do not provide
speed control, so they require the default `speed` of `1.0`. Models with
documented speed control accept the full `0.7`-`1.2` range. Models without
audio-tag support must not be used with recognized directive-shaped tags.

## 3.3 Aspect ratio and resolution

`aspect_ratio` is a human-readable label.

`resolution` is the **canonical pixel canvas** used by the renderer.

For example:

```json
"aspect_ratio": "9:16",
"resolution": [1080, 1920]
```

The actual rendered dimensions come from `resolution`.

When generating images, use the project resolution as the requested output dimensions where the provider supports explicit dimensions. Do not depend on a natural-language prompt containing `"9:16"` or `"1080x1920"`.

---

# 4. Narration and timing

## 4.1 One narration generation call

All scenes' `narration_text` are concatenated in scene order and sent to ElevenLabs as **one narration request** for the whole video.

The result is:

- one continuous narration audio file
- one global word-timestamp/alignment array

The pipeline maps the global alignment back to individual scenes.

Do not design scripts around one API call per scene.

## 4.2 Narration caching

Narration identity is based on the concatenated scene narration together with the selected TTS model.

Changing any scene's `narration_text` changes the narration identity and invalidates the existing matching narration cache.

The project directory can retain multiple historical narration files. Old narration files are not overwritten.

When the requested narration already exists in the project's narration history, it should be reused rather than regenerated.

If a new narration would need to be generated, the normal workflow requires explicit confirmation before the API generation occurs, unless a force option intentionally bypasses that confirmation.

## 4.3 TTS text, spoken words, and audio tags

`narration_text` is the exact text sent to ElevenLabs. It may contain supported
v4 audio tags such as `[whispers]`, `[laughs]`, `[sighs]`, `[beat]`, or
multi-word directives such as `[nervous laugh]`. Keep these tags in the
narration text because they control delivery and may add pauses.

The pipeline derives the spoken-word sequence from that same text. Recognized
audio-tag directives are not spoken words: they never appear in captions and
never consume word indexes. Tag-induced timing gaps remain in the returned
word timestamps. Do not add a second authored `read_narration` field.

Write tags adjacent to the narration they affect, for example:

```text
[whispers] Something is wrong. [beat] Did you hear that?
```

Only directive-shaped supported tag syntax is treated this way; ordinary
narration text is preserved.

## 4.4 Word tokenization

Word indexing is **0-based**.

For spoken-word indexing, tokenize the narration after excluding recognized
audio-tag directives, then:

1. stripping leading/trailing whitespace
2. collapsing repeated whitespace
3. splitting on whitespace only

Do **not** split on punctuation.

Examples:

```text
"GPU,"                  -> one token
"state-of-the-art"      -> one token
"we're"                 -> one token
```

`trigger_word_index` always refers to the local spoken-word index inside that
scene's narration. Audio tags do not count.

The script author never computes the global word offset.

The pipeline computes global offsets from the local scene indices.

A `trigger_word_index` must be less than the local word count of its scene's narration.

---

# 5. Scene structure

A scene follows this conceptual shape:

```json
{
  "id": "scene_1",
  "bg": "<asset_registry_key>",
  "narration_text": "...",
  "caption_style": null,
  "duration_sec": null,
  "extra_duration_sec": 0.0,
  "pause_before_sec": 0.3,
  "transition_in": null,
  "duck_to_narration_pct": null,
  "bg_music": null,
  "sfx": [],
  "elements": []
}
```

## 5.1 Scene order

The `scenes` array is the authoritative playback order.

Scene IDs should be unique and descriptive.

## 5.2 `duration_sec`

Authored scripts must always use:

```json
"duration_sec": null
```

The duration is calculated by the pipeline from the real ElevenLabs alignment.

Do not manually author scene duration based on an estimated reading time.

Computed duration belongs in the build output/manifest, not back in the authored script.

## 5.3 `extra_duration_sec`

`extra_duration_sec` is optional and defaults to `0.0`. A positive value keeps
the scene's final visual state active for that many seconds after the scene's
narration finishes. The final caption chunk and visual layers remain active;
no additional narration is generated.

For example:

```json
"extra_duration_sec": 2.0
```

keeps the scene on screen for two seconds after narration ends. The authored
`duration_sec` must remain `null`; the pipeline computes narration duration
from alignment and adds this hold when building the final timeline.

Zero or omitted `extra_duration_sec` preserves the normal narration-length
behavior. Values must not be negative.

## 5.4 `pause_before_sec`

`pause_before_sec` **adds** time immediately before the scene's narration.

Default:

```text
0.3 seconds
```

Use:

```json
"pause_before_sec": 0
```

when the scene should continue directly across the boundary without an inserted pause.

A pause is different from a transition overlap:

- pause = adds time
- transition = consumes/overlaps time

Do not treat them as two names for the same mechanism.

---

# 6. Captions

Captions are derived from narration.

## 6.1 No separate caption text

There is no separate caption-text field.

Captions display the derived spoken narration, not non-spoken audio tags.

Do not create a second manually-maintained caption string.

This intentionally keeps spoken words and displayed words identical.

## 6.2 Project caption defaults

Typical project-level caption settings are:

```json
{
  "font": "Montserrat-Bold",
  "font_size": 64,
  "color": "#FFFFFF",
  "stroke_color": "#000000",
  "stroke_width": 3,
  "position": "bottom_center",
  "max_chars_per_line": 28,
  "highlight_color": "#FFD700",
  "highlight_scale": 1.15,
  "words_per_chunk": 3
}
```

Do not assume every script must use these exact visual values. They are defaults/examples; the schema determines which values are valid.

## 6.3 Chunking

`words_per_chunk` is the primary caption chunking control.

For example:

```json
"words_per_chunk": 3
```

means up to three words are shown together before the chunk advances.

`max_chars_per_line` is a secondary overflow safety cap. It is not the primary chunking mechanism.

Captions are intended to behave like short-form video captions, not like a full paragraph or full-sentence subtitle block.

## 6.4 Caption timing

Before the first spoken word of a scene:

```text
blank
```

After the final word finishes:

```text
the final chunk remains visible indefinitely
```

The final word remains highlighted.

Do not fade the caption away merely because the scene ended.

This behavior is independent of `pause_before_sec`.

## 6.5 Active-word highlighting

The active word is highlighted with `highlight_color`.

`highlight_scale` is optional and defaults to `1.0`.

Scaling is an optional enhancement; the fundamental highlighting mechanism is the color change.

## 6.6 Caption vertical placement

`caption_style.vertical_position_frac` is optional.

When present, it represents the vertical position of the **bottom edge of the caption block**, expressed as a fraction of canvas height:

```text
0.0 = top edge of the canvas
0.5 = canvas vertical center
1.0 = bottom edge of the canvas
```

For example:

```json
"vertical_position_frac": 0.5
```

places the bottom edge at the vertical center of the frame.

When omitted, use the renderer's existing resolution-aware bottom-margin behavior.

## 6.7 Scene caption overrides

`scene.caption_style` normally has one of two meanings:

```json
"caption_style": null
```

means inherit the project default.

A non-null object is **merged over** the project default.

Only fields that need to change should be supplied.

Example:

```json
"caption_style": {
  "font_size": 76,
  "highlight_color": "#FF3333"
}
```

Do not replace the entire project caption style just to change one property.

---

# 7. Asset registry

The `asset_registry` is the only place where the actual asset file path is declared.

Example:

```json
"asset_registry": {
  "main_character": {
    "path": "assets/sprites/narrator_character.png",
    "generate": null
  }
}
```

## 7.1 Asset paths

Paths are relative to the shared repository-level `assets/` directory.

Examples:

```text
assets/backgrounds/...
assets/sprites/...
assets/images/...
assets/audio/...
assets/audio/sfx/...
```

The declared path must remain inside `assets/`.

Music files live directly under:

```text
assets/audio/
```

There is no required `assets/audio/music/` directory.

## 7.2 Scene asset references

Scene asset references must use the registry key:

```json
"bg": "bg_cyberpunk_room"
```

not:

```json
"bg": "assets/backgrounds/cyberpunk_room.jpg"
```

The same applies to:

- backgrounds
- element assets
- SFX
- background music

Do not use `"default"` as a sentinel asset.

## 7.3 Existing vs generated assets

An entry with:

```json
"generate": null
```

means the referenced file is expected to already exist.

The validation layer should reject the script if that required file is missing.

An entry with a non-null `generate` block may refer to a file that does not exist yet. That represents a pending/generated asset.

---

# 8. Asset generation conventions

Generated assets use a structured `generate` block:

```json
"generate": {
  "asset_type": "sprite",
  "generation_method": "image_to_image",
  "model": null,
  "description": "Generation prompt...",
  "source_asset": "narrator_reference",
  "transparent_background": true
}
```

## 8.1 Asset types

Valid conceptual asset types are:

```text
background
sprite
sfx
music
```

Use the type that describes the intended role of the generated output.

## 8.2 Generation methods

Supported generation methods are:

```text
text_to_image
image_to_image
text_to_audio
audio_to_audio
```

## 8.3 Model resolution

The effective fal.ai model is resolved in this order:

```text
generate.model
    ↓ if null/missing
project.generation_defaults[generation_method]
```

An asset-level model override wins over the project default.

Missing and explicit-null generation defaults have the same semantic meaning: no default is configured.

Only generation methods actually used by generated assets need an effective model.

Do not require unrelated unused generation methods to have valid models merely because they exist as configuration keys.

## 8.4 Generation defaults

The project may provide one default model per generation method:

```json
"generation_defaults": {
  "text_to_image": "...",
  "image_to_image": "...",
  "text_to_audio": "...",
  "audio_to_audio": "..."
}
```

Keep all four method keys conceptually available.

Model IDs are provider-specific and can change over time. The canonical rule is:

> Use a current, explicitly verified model ID appropriate to the method and cost/quality requirements; do not invent model IDs based on naming guesses.

A script may override a default on a specific asset when that asset genuinely requires a different model.

## 8.5 Image generation

For image generation:

- use the project's actual resolution when the provider supports explicit dimensions
- do not rely on aspect-ratio words in the prompt to determine output dimensions
- backgrounds should normally use `transparent_background: false`
- composited sprites normally use `transparent_background: true`

The generation description is the semantic prompt, not a place to encode renderer implementation details that the API can receive as structured parameters.

## 8.6 Image-to-image

`source_asset` is required.

It must reference another **asset-registry key**, not a raw filesystem path.

Example:

```json
"source_asset": "bg_house_interior"
```

The generated result should preserve the source composition/identity unless the description explicitly requests a change.

Do not redesign unrelated parts of the source image.

## 8.7 Audio-to-audio

`source_asset` is also required for audio-to-audio.

It must reference a registry key containing an actual audio file.

Choose source audio that meaningfully exercises transformation. A source should have enough content and structure for the transformation to be observable; avoid tiny incidental clicks when the test is meant to evaluate transformation of richer audio.

The description should clearly state both:

- what characteristics to preserve
- what characteristics to transform

## 8.8 Text-to-audio

Text-to-audio does not have a source asset.

The description is the generation prompt.

Use `asset_type: "sfx"` for short sound effects and `asset_type: "music"` for music beds.

## 8.9 `transparent_background`

This field is meaningful for image-generation methods.

For generated image assets it is explicitly boolean:

```json
true
```

or:

```json
false
```

Use:

```text
true
```

for a sprite intended to be composited over a background.

Use:

```text
false
```

for a full-frame background.

For audio methods it is not meaningful.

---

# 9. Generation dependency order

Generated assets can depend on other registry entries.

Example:

```text
bg_house_interior
        ↓
bg_second_bed
        ↓
bg_empty_doorway
        ↓
bg_herobrine_doorway
```

A generated asset must not be produced until its `source_asset` exists.

Generation order must therefore be determined from the dependency graph, using a topological ordering.

Never assume JSON registry iteration order is safe.

If a dependency cycle exists, generation must fail rather than guessing an order.

---

## Video assets

Assets may be video files such as MP4 in addition to still images.

A video asset can be referenced anywhere the schema permits that asset type.
For background video, the video fills the project canvas using the same
cover-fit behavior as a background image.

Video assets are time-based media rather than static images. The renderer
should preserve their temporal playback rather than treating them as a
single still frame.

If a video asset is shorter than the scene duration, the renderer should
follow the project's defined video-loop/repeat behavior. If no such behavior
is defined by the schema or renderer, the script author must not assume
looping.

# 10. Elements

Elements are scene-local visual objects layered over a background.

Conceptually:

```json
{
  "id": "main_character",
  "asset": "narrator_character",
  "z_index": 10,
  "anchor": "bottom_center",
  "keyframes": []
}
```

## 10.1 Scene scoping

Elements do **not** persist automatically across scenes.

Every scene redeclares its own `elements` array.

If an element should visually continue into the next scene, redeclare it there with its own opening keyframe.

Do not assume an element from the previous scene remains available.

## 10.2 Layering

`z_index` controls the element's visual layer.

Use higher values for content that should render above lower values.

---

# 11. Element sizing and anchoring

Elements use **canvas-relative sizing**, not native-pixel sizing.

## 11.1 Size fields

Each keyframe uses exactly one of:

```text
target_height_frac
```

or:

```text
target_width_frac
```

These are fractions of the current project's canvas height or width.

Examples:

```json
"target_height_frac": 0.32
```

or:

```json
"target_width_frac": 0.55
```

Do not author native pixel dimensions for the element itself.

The pipeline reads the source asset's real dimensions and derives the rendered size.

## 11.2 Aspect ratio

Element scaling preserves the source asset's aspect ratio.

Do not specify both width- and height-based fractional sizing for a normal element.

## 11.3 Anchors

Allowed anchors are:

```text
top_left
center
bottom_center
```

`pos` is the canvas-pixel position of the declared anchor point.

It is **not** automatically the image's top-left corner.

Use:

- `bottom_center` for grounded characters
- `center` for floating diagrams/icons
- `top_left` when positioning should be tied to the top-left anchor

Because the anchor remains fixed, an element can change size without the intended anchor point drifting.

---

# 12. Keyframes and easing

A keyframe describes the state of an element at a narration-relative trigger word.

Example:

```json
{
  "trigger_word_index": 6,
  "pos": [300, 1750],
  "target_height_frac": 0.32,
  "opacity": 1.0,
  "easing": "ease_in_out"
}
```

## 12.1 Easing values

Allowed values:

```text
instant
linear
ease_in
ease_out
ease_in_out
bounce
```

## 12.2 Easing meaning

The easing value belongs to the **destination keyframe**.

It controls the interpolation **into that keyframe from the previous keyframe**.

Therefore:

- the first keyframe normally uses `instant`
- `instant` means hold the previous state until the destination time, then snap
- between two consecutive keyframes, shared state values interpolate from A to B
- after the final keyframe, hold the final state

Before the first keyframe, hold the first keyframe's values.

The renderer resolves an element state from the already-resolved absolute time.

The element state resolution itself should remain conceptually deterministic and independent of MoviePy.

---

# 13. Backgrounds

Backgrounds fill the entire project canvas.

They do not have an element-style size field.

Background images are cover-fitted to the project's `resolution`:

1. scale until the canvas is fully covered
2. center-crop the excess

This is equivalent to the conceptual behavior of:

```text
background-size: cover
```

The script author should not manually size a background asset.

---

# 14. Background music

`bg_music` is a **change event**, not persistent per-scene state.

## 14.1 No change

```json
"bg_music": null
```

means:

> make no music change.

Whatever is already playing continues unchanged, including through the scene's pause.

## 14.2 Start or change music

```json
"bg_music": {
  "asset": "music_dark",
  "trigger_word_index": 0,
  "fade_in_sec": 0.8
}
```

If the same asset is already playing, it continues from its current phase.

Do not restart the same music asset merely because a new scene contains a cue for the same asset.

If a different asset is selected, the pipeline crossfades from the old asset to the new asset.

## 14.3 Stop music

```json
"bg_music": {
  "stop": true,
  "trigger_word_index": 0,
  "fade_in_sec": 1.5
}
```

stops the currently playing music by fading it to silence.

The field is named `fade_in_sec` by schema convention even for a stop event; in that case it represents the fade-out duration.

A later start cue can legitimately restart music after a real stop.

## 14.4 Music has no volume field

Do **not** add:

```json
"volume": ...
```

to `bg_music`.

There is deliberately only one music-loudness control:

```text
duck_to_narration_pct
```

Keeping both would create overlapping mechanisms.

## 14.5 Music ducking

`duck_to_narration_pct` is a loudness-relative ratio, not a raw amplitude multiplier.

It controls background music relative to narration loudness.

The project-level value is the default:

```json
"duck_to_narration_pct": 0.4
```

A scene may override it:

```json
"duck_to_narration_pct": 0.5
```

A scene value of `null` inherits the project default.

The ducked gain remains continuous through:

- narration
- pauses between scenes

Do not make the music louder during pauses and then duck it again when narration resumes.

That older behavior caused audible pumping and is considered a regression.

Background music loops seamlessly as needed to cover the required timeline.

---

# 15. Sound effects

`sfx` contains one-shot audio cues.

Example:

```json
"sfx": [
  {
    "asset": "sfx_whoosh",
    "trigger_word_index": 0,
    "volume": 0.6
  }
]
```

Each SFX cue has its own:

```text
volume
```

in the range:

```text
0.0–1.0
```

SFX volume is independent of background-music ducking.

SFX are layered at their cue time and do not become persistent scene state.

---

# 16. Cue timing and pauses

`bg_music` and `sfx` trigger indices refer to the narration timeline.

The raw narration alignment describes the narration audio itself and does not include scene pauses.

The final rendered video timeline may contain extra `pause_before_sec` silence.

Therefore the pipeline must translate raw narration-relative cue times into final video times using the same scene-offset calculation used by scene assembly.

There must be one shared timing calculation, not separate duplicated math for:

- video scene placement
- music cue placement
- SFX cue placement

Separate implementations can drift apart and create synchronization bugs.

---

# 17. Transitions

`transition_in` describes how a scene enters.

The first scene must always have:

```json
"transition_in": null
```

`null` means a hard cut.

Supported transition types:

```text
crossfade
zoom_out
push
```

`push` additionally uses:

```text
direction: left | right
style: hard | soft
```

## 17.1 Transition timing

Every transition is an **overlap**.

It consumes/subtracts time rather than adding time.

Therefore:

- `pause_before_sec` adds time
- transition duration subtracts/overlaps time

These mechanisms coexist and must not be conflated.

## 17.2 Crossfade

A crossfade is a normal dissolve:

- outgoing fades out
- incoming fades in
- both occur simultaneously

## 17.3 Zoom out

The incoming scene begins zoomed in and scales down to normal size over the transition duration.

`zoom_scale` is optional; the current default is `1.3`.

The zoom is anchored at the **center of the canvas**.

The outgoing scene fades underneath during the same transition.

Do not anchor the zoom to the top-left corner.

## 17.4 Push hard

A hard push physically moves both scenes:

- outgoing slides fully off-screen in the specified direction
- incoming slides in from the opposite edge
- the edge is sharp

The position changes continuously during the transition.

## 17.5 Push soft

A soft push is intentionally **not a slide**.

Both clips remain stationary.

The incoming clip stays fully opaque underneath.

Only the outgoing clip receives the moving mask.

The mask boundary sweeps across the frame in the chosen direction and uses a soft feather band at the moving boundary.

For:

```text
direction = left
```

the peeling begins at the right edge and moves leftward.

For:

```text
direction = right
```

the behavior is mirrored.

The progress of the moving boundary must use one shared absolute transition clock so the visual relationship between the two scenes cannot drift.

## 17.6 Combined transition behavior

A scene can simultaneously be:

- the incoming scene of its own `transition_in`
- the outgoing scene of the next scene's transition

The renderer must combine those behaviors into one coherent wrapper rather than attaching competing position/mask functions that overwrite one another.

When debugging transition problems, test the actual assembled pipeline, not only isolated transition helper functions.

---

# 18. Performance conventions that affect script design

Most performance concerns belong to the implementation, not the JSON author.

The important author-facing principle is:

> Prefer semantics that remain stable and cacheable; do not encode frame-by-frame behavior when a keyframe can describe it.

For the renderer:

- cache expensive element rendering by meaningful visual state, not raw frame number
- caption rendering is naturally cacheable by caption chunk and active word
- benchmark real end-to-end rendering with unique, monotonically increasing timestamps
- do not trust repeated-timestamp cache-hit benchmarks as evidence of real render speed
- preview rendering must begin at the reduced resolution rather than rendering full resolution first
- verify actual output dimensions with media metadata tools rather than trusting self-reported values

These are pipeline invariants, not extra JSON fields.

---

# 19. Authoring principles for LLM-generated scripts

When generating or editing a script:

## 19.1 Prefer one source of truth

Do not duplicate information when the schema already gives it a single authoritative location.

Examples:

- narration text exists once
- caption text is derived from narration
- asset paths live in `asset_registry`
- music loudness uses `duck_to_narration_pct`
- generated-model defaults live in `generation_defaults`

Do not invent parallel fields that express the same concept.

## 19.2 Use explicit references

Use registry keys instead of raw paths in scenes.

Use registry keys for generation dependencies.

Use local scene word indices rather than manually calculated global indices.

## 19.3 Do not encode implementation details unnecessarily

Natural-language descriptions should describe the intended visual/audio result.

Provider-specific structured options should be passed through actual structured fields when supported.

For example, image dimensions should come from `project.resolution`, not only from prompt text.

## 19.4 Make dependencies obvious

For image-to-image and audio-to-audio, explicitly name the source registry key.

When a generation asset depends on another generated asset, make the dependency chain intentional.

## 19.5 Make visual continuity explicit

Because elements are scene-scoped, redeclare anything that should continue into the next scene.

When using image-to-image, describe what must remain unchanged if continuity matters.

---

# 20. Validation vs convention

This document is not a replacement for schema validation.

Validation should enforce structural rules such as:

- valid JSON/schema shape
- required fields
- valid enum values
- asset path safety
- existence of required non-generated assets
- valid asset references
- valid source dependencies
- valid trigger-word bounds
- valid keyframe sizing fields
- valid caption values
- valid transition shapes

This document explains intended authoring behavior and runtime semantics that may be difficult to infer from the raw model definitions.

When the schema and this document disagree, **fix this document or the implementation rather than silently creating a third interpretation.**

---

# 21. Canonical checklist for a new script

Before considering a new script ready:

### Project

- title is lowercase_with_underscores
- title is stable and contains no date/time
- date is `YYYY-MM-DD`
- `tts_model` is explicitly chosen
- `voice_id` is present
- resolution is the canonical canvas
- generation defaults are explicitly understood
- caption defaults are defined

### Assets

- every scene asset reference exists in `asset_registry`
- every registry path is under `assets/`
- non-generated assets exist on disk
- generated assets have complete `generate` metadata
- image-to-image and audio-to-audio have `source_asset`
- text-to-image and text-to-audio do not have `source_asset`
- image generation has an explicit boolean `transparent_background`
- generation dependencies form an acyclic graph

### Scenes

- at least one scene exists
- first scene has `transition_in: null`
- authored `duration_sec` values are `null`
- trigger indices are local to each scene
- trigger indices are within the scene's word count
- elements are redeclared per scene
- each keyframe uses exactly one fractional size field
- background assets are referenced through registry keys

### Audio

- narration is written exactly once per scene
- captions therefore match narration automatically
- background music uses change-event semantics
- `bg_music` has no volume field
- SFX have their own volume
- music ducking uses `duck_to_narration_pct`
- music remains ducked continuously through pauses

### Generation

- asset-level model overrides are used only when needed
- otherwise the project default is used
- provider model IDs are verified rather than guessed
- generation CLI can order dependencies correctly
- generated outputs go to the exact registry paths

---

# 22. Important legacy cleanup

Individual scripts may still contain a top-level:

```json
"_conventions": {}
```

This is no longer the preferred architecture.

The intended architecture is:

```text
SCRIPT_CONVENTIONS.md
        ↓
canonical authoring rules for all scripts

Pydantic schema + validation
        ↓
actual enforcement

individual JSON scripts
        ↓
content/configuration only
```

Do not create a new per-script convention block merely because an old example contains one.

When changing the schema or renderer behavior, update this document and the corresponding validation/tests together so there is one canonical description of the system.
