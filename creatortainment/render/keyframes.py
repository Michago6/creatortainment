"""Pure easing and keyframe-state resolution helpers."""

from __future__ import annotations

import math
from typing import Any, Callable


def ease_instant(t: float) -> float:
    """Return a hard step at the end of the transition."""
    return 0.0 if t < 1.0 else 1.0


def ease_linear(t: float) -> float:
    """Return linear progress."""
    return t


def ease_in(t: float) -> float:
    """Return quadratic ease-in progress."""
    return t * t


def ease_out(t: float) -> float:
    """Return quadratic ease-out progress."""
    return 1.0 - (1.0 - t) ** 2


def ease_in_out(t: float) -> float:
    """Return symmetric quadratic ease-in-out progress."""
    return 2.0 * t * t if t < 0.5 else 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0


def ease_bounce(t: float) -> float:
    """Return a damped overshooting bounce progress."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t + 0.12 * math.sin(math.pi * 4.0 * t) * (1.0 - t)


EASINGS: dict[str, Callable[[float], float]] = {
    "instant": ease_instant,
    "linear": ease_linear,
    "ease_in": ease_in,
    "ease_out": ease_out,
    "ease_in_out": ease_in_out,
    "bounce": ease_bounce,
}


def _interpolate(a: float, b: float, progress: float) -> float:
    return a + (b - a) * progress


def _state(keyframe: dict[str, Any]) -> dict[str, Any]:
    size_fields = [
        field
        for field in ("target_height_frac", "target_width_frac")
        if field in keyframe
    ]
    if len(size_fields) != 1:
        raise ValueError(
            "Each resolved keyframe must define exactly one target size field."
        )
    return {
        "pos": tuple(float(value) for value in keyframe["pos"]),
        "size_field_name": size_fields[0],
        "size_value": float(keyframe[size_fields[0]]),
        "opacity": float(keyframe.get("opacity", 1.0)),
    }


def resolve_element_state(
    element: dict[str, Any],
    absolute_time_sec: float,
) -> dict[str, Any]:
    """Resolve an element's position, size, and opacity at an absolute time."""
    keyframes = element.get("keyframes", [])
    if not keyframes:
        raise ValueError("Element must contain at least one keyframe.")
    if any("time_sec" not in keyframe for keyframe in keyframes):
        raise ValueError("Element keyframes must contain resolved time_sec values.")
    ordered = sorted(keyframes, key=lambda item: float(item["time_sec"]))
    if absolute_time_sec <= float(ordered[0]["time_sec"]):
        return _state(ordered[0])
    if absolute_time_sec >= float(ordered[-1]["time_sec"]):
        return _state(ordered[-1])

    for before, after in zip(ordered, ordered[1:]):
        before_time = float(before["time_sec"])
        after_time = float(after["time_sec"])
        if absolute_time_sec > after_time:
            continue
        start = _state(before)
        end = _state(after)
        if start["size_field_name"] != end["size_field_name"]:
            raise ValueError(
                "Cannot interpolate between target_height_frac and "
                "target_width_frac keyframes."
            )
        raw_progress = (absolute_time_sec - before_time) / (after_time - before_time)
        easing_name = str(after.get("easing", "linear"))
        try:
            progress = EASINGS[easing_name](raw_progress)
        except KeyError as exc:
            raise ValueError(f"Unknown easing {easing_name!r}.") from exc
        return {
            "pos": tuple(
                _interpolate(start["pos"][index], end["pos"][index], progress)
                for index in (0, 1)
            ),
            "size_field_name": start["size_field_name"],
            "size_value": _interpolate(
                start["size_value"], end["size_value"], progress
            ),
            "opacity": _interpolate(start["opacity"], end["opacity"], progress),
        }
    return _state(ordered[-1])
