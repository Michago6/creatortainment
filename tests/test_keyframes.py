"""Tests easing functions and pure element keyframe-state interpolation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from creatortainment.render.keyframes import (
    ease_bounce,
    ease_in,
    ease_in_out,
    ease_instant,
    ease_linear,
    ease_out,
    resolve_element_state,
)
from creatortainment.timeline import timed_element


ROOT = Path(__file__).parents[1]


def _script() -> dict:
    """Load the real portrait example script."""
    return json.loads(
        (ROOT / "scripts/testing_scripts/example_script.json").read_text(
            encoding="utf-8"
        )
    )


def _manifest() -> dict:
    """Load the real project alignment fixture."""
    return json.loads(
        (ROOT / "projects/understanding_gpu_architecture/build_manifests/example_script.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.parametrize(
    "easing",
    [ease_instant, ease_linear, ease_in, ease_out, ease_in_out, ease_bounce],
)
def test_easing_endpoints(easing) -> None:
    """Every easing reaches exact zero and one at its endpoints."""
    assert easing(0.0) == 0.0
    assert easing(1.0) == 1.0


def test_linear_midpoint() -> None:
    """Linear easing leaves the midpoint unchanged."""
    assert ease_linear(0.5) == 0.5


@pytest.mark.parametrize("easing", [ease_in, ease_out, ease_in_out])
def test_standard_easings_are_monotonic(easing) -> None:
    """Non-bounce easing functions are monotonic over the unit interval."""
    values = [easing(index / 20) for index in range(21)]
    assert values == sorted(values)


def test_resolve_gpu_diagram_at_keyframe_and_between() -> None:
    """GPU diagram state snaps at endpoints and interpolates between them."""
    script = _script()
    manifest = _manifest()
    element = timed_element(
        script["scenes"][0]["elements"][1],
        script["scenes"][0],
        manifest["scenes"][0],
        manifest,
    )
    first, second = element["keyframes"]
    start = first["time_sec"]
    end = second["time_sec"]
    assert resolve_element_state(element, start)["size_value"] == first["target_width_frac"]
    assert resolve_element_state(element, end)["size_value"] == second["target_width_frac"]
    middle = resolve_element_state(element, (start + end) / 2)
    assert first["target_width_frac"] < middle["size_value"] < second["target_width_frac"]


def test_resolve_core_grid_before_after_and_instant_step() -> None:
    """Core grid holds before its first keyframe and steps on instant transitions."""
    script = _script()
    manifest = _manifest()
    element = timed_element(
        script["scenes"][2]["elements"][1],
        script["scenes"][2],
        manifest["scenes"][2],
        manifest,
    )
    first, second, third = element["keyframes"]
    assert resolve_element_state(element, first["time_sec"] - 1)["size_value"] == first["target_width_frac"]
    assert resolve_element_state(element, third["time_sec"] + 1)["size_value"] == third["target_width_frac"]
    instant_element = {
        "keyframes": [
            {"time_sec": 1.0, "pos": [0, 0], "target_width_frac": 0.1, "opacity": 0.0, "easing": "instant"},
            {"time_sec": 2.0, "pos": [10, 10], "target_width_frac": 0.5, "opacity": 1.0, "easing": "instant"},
        ]
    }
    assert resolve_element_state(instant_element, 1.999)["opacity"] == 0.0
    assert resolve_element_state(instant_element, 2.0)["opacity"] == 1.0


def test_resolve_rejects_mixed_size_fields() -> None:
    """Interpolation refuses to guess between height and width sizing."""
    element = {
        "keyframes": [
            {"time_sec": 0.0, "pos": [0, 0], "target_height_frac": 0.1},
            {"time_sec": 1.0, "pos": [0, 0], "target_width_frac": 0.2},
        ]
    }
    with pytest.raises(ValueError, match="Cannot interpolate"):
        resolve_element_state(element, 0.5)
