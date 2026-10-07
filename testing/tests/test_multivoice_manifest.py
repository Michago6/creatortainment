from __future__ import annotations

import copy
import json
from pathlib import Path

from creatortainment.audio.elevenlabs_client import (
    NarrationSegmentResult,
    WordTimestamp,
)
from creatortainment.audio.manifest import (
    build_manifest,
    refresh_cached_manifest_scenes,
)
from creatortainment.schema.models import ScriptModel


ROOT = Path(__file__).parents[2]


def _script() -> ScriptModel:
    value = json.loads(
        (ROOT / "testing/scripts/example_script.json").read_text(encoding="utf-8")
    )
    value["project"]["voice_id"] = "voice-default"
    value["scenes"] = [
        {
            "id": "scene-1",
            "bg": value["scenes"][0]["bg"],
            "narration_segments": [
                {"id": "one", "text": "Hello there.", "voice_id": "voice-a"},
                {"id": "two", "text": "Welcome back."},
            ],
            "transition_in": None,
        },
        {
            "id": "scene-2",
            "bg": value["scenes"][1]["bg"],
            "narration_segments": [
                {"id": "three", "text": "Thanks for joining.", "voice_id": "voice-b"},
            ],
            "transition_in": None,
        },
    ]
    return ScriptModel.model_validate(value)


class SegmentClient:
    def __init__(self) -> None:
        self.calls = 0

    def synthesize_segments(self, segments):
        self.calls += 1
        results = []
        for segment_index, segment in enumerate(segments):
            words = segment.text.split()
            timestamps = [
                WordTimestamp(
                    word,
                    index * 0.4,
                    index * 0.4 + 0.3,
                    segment_id=segment.id,
                    scene_id=segment.scene_id,
                    voice_id=segment.voice_id,
                    segment_word_index=index,
                )
                for index, word in enumerate(words)
            ]
            results.append(
                NarrationSegmentResult(
                    segment=segment,
                    audio_bytes=f"audio-{segment_index}".encode(),
                    word_timestamps=timestamps,
                )
            )
        return results


def test_manifest_contains_sequential_segment_records_and_flattened_timestamps(
    tmp_path: Path,
) -> None:
    client = SegmentClient()
    manifest_path = tmp_path / "build_manifest.json"

    manifest, cached = build_manifest(_script(), manifest_path, client)

    assert cached is False
    assert client.calls == 1
    assert [(item["id"], item["voice_id"]) for item in manifest["narration_segments"]] == [
        ("one", "voice-a"),
        ("two", "voice-default"),
        ("three", "voice-b"),
    ]
    assert [
        (item["word"], item["segment_id"], item["voice_id"])
        for item in manifest["word_timestamps"]
    ] == [
        ("Hello", "one", "voice-a"),
        ("there.", "one", "voice-a"),
        ("Welcome", "two", "voice-default"),
        ("back.", "two", "voice-default"),
        ("Thanks", "three", "voice-b"),
        ("for", "three", "voice-b"),
        ("joining.", "three", "voice-b"),
    ]
    assert manifest["narration_segments"][0]["start_time_sec"] == 0.0
    assert manifest["narration_segments"][0]["end_time_sec"] == 0.7
    assert manifest["narration_segments"][1]["start_time_sec"] == 0.7
    assert manifest["narration_segments"][1]["end_time_sec"] == 1.4
    assert manifest["narration_segments"][2]["start_time_sec"] == 1.7
    assert manifest["scenes"][0]["word_count"] == 4
    assert manifest["scenes"][1]["word_offset"] == 4
    assert manifest["scenes"][1]["start_time_sec"] == 1.7


def test_unchanged_multivoice_manifest_reuses_cache_and_resegments_scenes(
    tmp_path: Path,
) -> None:
    script = _script()
    client = SegmentClient()
    manifest_path = tmp_path / "build_manifest.json"
    manifest, _ = build_manifest(script, manifest_path, client)

    changed = copy.deepcopy(script)
    changed.scenes[0].narration_segments = [
        script.scenes[0].narration_segments[0],
    ]
    changed.scenes[1].narration_segments = [
        script.scenes[0].narration_segments[1],
        script.scenes[1].narration_segments[0],
    ]
    assert refresh_cached_manifest_scenes(changed, manifest, tmp_path) is True
    assert manifest["scenes"][0]["word_count"] == 2
    assert manifest["scenes"][1]["word_offset"] == 2
    assert manifest["word_timestamps"][2]["scene_id"] == "scene-2"

    _, cached = build_manifest(changed, manifest_path, client)
    assert cached is True
    assert client.calls == 1


def test_legacy_manifest_remains_unchanged(tmp_path: Path) -> None:
    value = json.loads(
        (ROOT / "testing/scripts/example_script.json").read_text(encoding="utf-8")
    )
    client = type(
        "LegacyClient",
        (),
        {
            "synthesize": lambda self, scenes: type(
                "Result",
                (),
                {
                    "audio_bytes": b"legacy",
                    "word_timestamps": [
                        WordTimestamp(word, index * 0.3, index * 0.3 + 0.2)
                        for index, word in enumerate(
                            " ".join(scene["narration_text"] for scene in scenes).split()
                        )
                    ],
                },
            )(),
        },
    )()

    manifest, _ = build_manifest(value, tmp_path / "build_manifest.json", client)

    assert "narration_segments" not in manifest
    assert "narration_audio_path" in manifest
    assert all(
        set(timestamp) == {"word", "start", "end"}
        for timestamp in manifest["word_timestamps"]
    )


def test_start_at_word_and_signed_offset_resolve_on_shared_timeline(
    tmp_path: Path,
) -> None:
    script = _script()
    script.scenes[0].narration_segments[1].start_at_word = 1
    script.scenes[0].narration_segments[1].start_offset_sec = 0.2
    manifest, _ = build_manifest(script, tmp_path / "build_manifest.json", SegmentClient())

    second = manifest["narration_segments"][1]
    assert second["start_sec"] == 0.2
    assert second["end_sec"] > second["start_sec"]
    assert manifest["word_timestamps"][2]["start"] == 0.2


def test_negative_offset_creates_real_overlap_instead_of_serializing(
    tmp_path: Path,
) -> None:
    script = _script()
    script.scenes[0].narration_segments[1].start_at_word = 2
    script.scenes[0].narration_segments[1].start_offset_sec = -0.2
    manifest, _ = build_manifest(script, tmp_path / "build_manifest.json", SegmentClient())

    first, second = manifest["narration_segments"][:2]
    assert second["start_sec"] < first["end_sec"]
    assert second["start_sec"] == 0.2


def test_three_segments_can_share_the_same_anchor_time(tmp_path: Path) -> None:
    value = _script().model_dump()
    value["scenes"][0]["narration_segments"][1]["start_at_word"] = 1
    value["scenes"][0]["narration_segments"].append(
        {"id": "same-time", "text": "Together.", "start_at_word": 1}
    )
    model = ScriptModel.model_validate(value)
    manifest, _ = build_manifest(model, tmp_path / "build_manifest.json", SegmentClient())

    starts = [record["start_sec"] for record in manifest["narration_segments"]]
    assert starts[1] == starts[2] == 0.0
