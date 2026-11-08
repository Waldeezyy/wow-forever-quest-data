"""Offline Polestar location normalization; never executes Lua or calls game APIs.

Polestar/Core/Compat.lua:785-792 documents the axis order and Era transform.
An Era-world result is a reference coordinate, NOT a verified live coordinate.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import math
from pathlib import Path

RAW_LOCATION_KEYS = ("map", "x", "y", "f", "z", "r")
BOUND_KEYS = ("c", "left", "right", "top", "bottom")


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _integer(value, *, minimum=0):
    return _finite_number(value) and value >= minimum and int(value) == value


def _bounds_problem(bounds):
    if not isinstance(bounds, Mapping):
        return "frame bounds are not an object"
    if not _integer(bounds.get("c")):
        return "frame c must be a nonnegative world-map integer"
    if any(not _finite_number(bounds.get(key)) for key in BOUND_KEYS[1:]):
        return "frame bounds are missing or nonfinite"
    if any(abs(bounds[key]) >= 1_000_000 for key in BOUND_KEYS[1:]):
        return "frame bounds exceed Polestar's documented import limit"
    if bounds["left"] == bounds["right"] or bounds["top"] == bounds["bottom"]:
        return "frame bounds have zero extent"
    return None


def _frame_for(catalog, frame, ui_map_id):
    frames = catalog.get(frame, {})
    if not isinstance(frames, Mapping):
        return None
    # Lua table keys are integers; JSON object keys are strings.
    return frames.get(str(ui_map_id), frames.get(ui_map_id))


def normalize_location(goal, frame_catalog) -> dict:
    """Preserve raw fields and resolve only explicitly supplied frame bounds.

    ``goal.map`` is a UiMapID, never the ``c`` world/continent-map ID. Only
    compiled Polestar f='e' and absent f are recognized. The latter uses the
    live frame in Compat, which needs C_Map unless *live* bounds are separately
    documented in the caller's catalog. Era bounds never serve as a live fallback.

    z/r retain their source values in ``raw``. This function transforms XY only;
    it does not certify heights, layers, radii, walkability or present geometry.
    Neither input is mutated.
    """
    if not isinstance(goal, Mapping) or not isinstance(frame_catalog, Mapping):
        raise TypeError("goal and frame_catalog must be mappings")
    raw = {key: deepcopy(goal.get(key)) for key in RAW_LOCATION_KEYS}
    frame = "era" if raw["f"] == "e" else "live" if raw["f"] is None else "unknown"
    result = {
        "raw": raw,
        "present_fields": [key for key in RAW_LOCATION_KEYS if key in goal],
        "ui_map_id": None,
        "map_id_kind": "UiMapID",
        "frame": frame,
        "continent_id": None,
        "world_map_id": None,
        "world_xy": None,
        "world_frame": None,
        "live_world_xy": None,
        "live_verified": False,
        "frame_catalog_key": None,
        "status": "no_location",
        "reason": None,
        "warnings": [],
    }
    if all(raw[key] is None for key in ("map", "x", "y")):
        result["reason"] = "goal has no map/XY location"
        return result
    if not _integer(raw["map"], minimum=1):
        result.update(status="invalid_location", reason="map must be a positive UiMapID integer")
        return result
    result["ui_map_id"] = int(raw["map"])
    if not all(_finite_number(raw[key]) and 0 <= raw[key] <= 100 for key in ("x", "y")):
        result.update(status="invalid_location", reason="x and y must be finite percentages in 0-100")
        return result
    if frame == "unknown":
        result.update(status="unsupported_frame", reason="unrecognized compiled frame marker")
        return result
    bounds = _frame_for(frame_catalog, frame, result["ui_map_id"])
    if bounds is None:
        result.update(
            status="unknown_era_frame" if frame == "era" else "unresolved_live_frame",
            reason="no documented %s bounds for this UiMapID" % frame,
        )
        return result
    result["frame_catalog_key"] = "%s/%d" % (frame, result["ui_map_id"])
    problem = _bounds_problem(bounds)
    if problem:
        result.update(status="invalid_frame_bounds", reason=problem)
        return result
    # Map horizontal x corresponds to WORLD Y; map vertical y to WORLD X.
    world = {
        "x": bounds["top"] + (bounds["bottom"] - bounds["top"]) * raw["y"] / 100,
        "y": bounds["left"] + (bounds["right"] - bounds["left"]) * raw["x"] / 100,
    }
    result.update(
        continent_id=int(bounds["c"]),
        world_map_id=int(bounds["c"]),
        world_xy=world,
        world_frame=frame,
        status="resolved_era_reference" if frame == "era" else "resolved_live_bounds",
    )
    if frame == "era":
        result["warnings"].append("Era-world XY is reference-only, not verified current/live geometry")
    else:
        result["live_world_xy"] = dict(world)
        result["warnings"].append("live-frame bounds are supplied data, not a live API observation")
    if raw["z"] is not None:
        result["warnings"].append("source z preserved without height/layer validation or transformation")
    if raw["r"] is not None:
        result["warnings"].append("source r preserved without changing its source radius semantics")
    return result


def _source_record(path, role):
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    return {
        "path": str(path), "role": role, "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }, data


def build_frame_catalog(source_paths, *, context_paths=(), notice_paths=(), addon_version=None) -> dict:
    """Extract literal RegisterMapFrames tables with the safe Python Lua parser.

    All literal arguments are parsed/validated, never evaluated. Conflicting
    bounds fail explicitly instead of inventing load order. Only the named input
    files are covered; this is not a discovery of every possible runtime pack.
    """
    from lua_data import iter_calls

    catalog = {
        "schema_version": 1, "source_addon": "Polestar", "addon_version": addon_version,
        "era": {}, "live": {},
        "coordinate_contract": {
            "map_field": "UiMapID", "map_xy_units": "percent_0_100",
            "c_field": "C_Map world/continent map ID, not UiMapID",
            "era_world_x": "top + (bottom - top) * y / 100",
            "era_world_y": "left + (right - left) * x / 100",
            "era_is_current_live": False,
            "z_and_r": "preserved, not transformed or validated as live height/radius",
        },
        "provenance": {"sources": [], "frame_sources": {}, "notices": []},
    }
    for path in source_paths:
        source, raw = _source_record(path, "literal_map_frames")
        source_index = len(catalog["provenance"]["sources"])
        catalog["provenance"]["sources"].append(source)
        calls = iter_calls(raw.decode("utf-8-sig"), "Polestar.RegisterMapFrames", all_args=True)
        if not calls:
            raise ValueError("No literal Polestar.RegisterMapFrames call in %s" % path)
        for arguments, offset in calls:
            if not arguments or not isinstance(arguments[0], Mapping):
                raise ValueError("RegisterMapFrames needs a literal frame table")
            if len(arguments) > 2 or (len(arguments) == 2 and not isinstance(arguments[1], str)):
                raise ValueError("Only an optional literal pack-name argument is supported")
            frames = arguments[0]
            if set(frames) - {"era"} or not isinstance(frames.get("era"), Mapping):
                raise ValueError("Expected only the documented era frame table")
            for map_id, raw_bounds in frames["era"].items():
                if not _integer(map_id, minimum=1):
                    raise ValueError("Frame key must be a positive UiMapID")
                problem = _bounds_problem(raw_bounds)
                if problem:
                    raise ValueError("UiMapID %s: %s" % (map_id, problem))
                bounds = {key: deepcopy(raw_bounds[key]) for key in BOUND_KEYS}
                if set(raw_bounds) - set(BOUND_KEYS):
                    raise ValueError("Unexpected frame bounds fields")
                key = str(int(map_id))
                old = catalog["era"].get(key)
                if old is not None and old != bounds:
                    raise ValueError("Conflicting Era bounds for UiMapID %s" % map_id)
                catalog["era"][key] = bounds
                catalog["provenance"]["frame_sources"].setdefault("era/" + key, []).append(
                    {"source_index": source_index, "call_offset": offset,
                     "pack": arguments[1] if len(arguments) == 2 else None})
    for path in context_paths:
        source, _ = _source_record(path, "semantics_or_registration")
        catalog["provenance"]["sources"].append(source)
    for path in notice_paths:
        source, raw = _source_record(path, "input_data_notice")
        source["text"] = raw.decode("utf-8-sig")
        catalog["provenance"]["notices"].append(source)
    catalog["era"] = dict(sorted(catalog["era"].items(), key=lambda pair: int(pair[0])))
    return catalog
