"""Load and validate the sensor/platform catalog (no database needed)."""
from __future__ import annotations

import json
from pathlib import Path

CATALOG_DIR = Path(__file__).parent / "catalog"
DETECTION_KINDS = {"eo_camera", "thermal_camera", "microphone", "rf_receiver", "radar"}
WEATHERS = ("fog", "rain", "wind", "night")
# noise fields each native output type needs
NATIVE_NOISE = {
    "bearing_elevation": ("bearing_deg", "elevation_deg"),
    "bearing_level": ("bearing_deg", "level_db"),
    "level": ("level_db", "source_level_db"),
    "bearing_rssi": ("bearing_deg", "rssi_db"),
    "range_azimuth_doppler": ("range_m", "azimuth_deg", "radial_mps"),
}
# a module counts as "still working" in a weather if it keeps most of its range and detections
ROBUST_RANGE, ROBUST_PD = 0.7, 0.8


def load_catalog():
    modules = json.loads((CATALOG_DIR / "sensor_modules.json").read_text(encoding="utf-8"))["modules"]
    platforms = json.loads((CATALOG_DIR / "platform_models.json").read_text(encoding="utf-8"))["platforms"]
    return {"modules": modules, "platforms": platforms}


def robust_modules(platform, modules_by_id, weather):
    """Detection modules on the platform that still work in the given weather."""
    out = []
    for link in platform["modules"]:
        m = modules_by_id[link["module_id"]]
        if m["kind"] not in DETECTION_KINDS:
            continue
        w = m["weather_effects"][weather]
        if w["range_mult"] >= ROBUST_RANGE and w["pd_mult"] >= ROBUST_PD:
            out.append(m["id"])
    return out


def validate(catalog):
    """Return a list of error strings (empty if the catalog is consistent)."""
    errors = []
    modules_by_id = {}
    for m in catalog["modules"]:
        if m["id"] in modules_by_id:
            errors.append("duplicate module id: " + m["id"])
        modules_by_id[m["id"]] = m
        if m["kind"] in DETECTION_KINDS:
            for w in WEATHERS:
                eff = m["weather_effects"].get(w)
                if not eff or not all(k in eff for k in ("range_mult", "noise_mult", "pd_mult")):
                    errors.append("module %s: missing or incomplete weather effect '%s'" % (m["id"], w))
            for k in ("range_m", "min_range_m", "fov_deg", "pointing", "pd", "pd_far", "rate_hz", "latency_ms", "noise"):
                if k not in m["sim"]:
                    errors.append("module %s: sim.%s missing" % (m["id"], k))
            if m["sim"].get("pointing") not in ("forward", "omni"):
                errors.append("module %s: sim.pointing must be forward or omni" % m["id"])
            native = m.get("native") or {}
            if native.get("type") not in NATIVE_NOISE:
                errors.append("module %s: native.type must be one of %s" % (m["id"], sorted(NATIVE_NOISE)))
            else:
                for k in NATIVE_NOISE[native["type"]]:
                    if k not in m["sim"]["noise"]:
                        errors.append("module %s: sim.noise.%s missing for native type %s" % (m["id"], k, native["type"]))
                if not native.get("fields"):
                    errors.append("module %s: native.fields missing" % m["id"])
        if m["kind"] == "radar" and "resolution_cell" not in m["sim"]:
            errors.append("module %s: radar needs sim.resolution_cell (close targets merge)" % m["id"])
        if m.get("verified") and not m.get("source"):
            errors.append("module %s: verified=true needs a source" % m["id"])

    seen = set()
    for p in catalog["platforms"]:
        if p["id"] in seen:
            errors.append("duplicate platform id: " + p["id"])
        seen.add(p["id"])
        missing = [l["module_id"] for l in p["modules"] if l["module_id"] not in modules_by_id]
        if missing:
            errors.append("platform %s: unknown modules %s" % (p["id"], missing))
            continue
        kinds = {modules_by_id[l["module_id"]]["kind"] for l in p["modules"]} & DETECTION_KINDS
        if len(kinds) < 2:
            errors.append("platform %s: needs at least 2 different detection modalities, has %s" % (p["id"], sorted(kinds)))
        for w in WEATHERS:
            if not robust_modules(p, modules_by_id, w):
                errors.append("platform %s: no module that still works in %s" % (p["id"], w))
    return errors


def resilience_table(catalog):
    """Rows of (platform id, {weather: [modules that still work]}) for display."""
    modules_by_id = {m["id"]: m for m in catalog["modules"]}
    return [(p["id"], {w: robust_modules(p, modules_by_id, w) for w in WEATHERS}) for p in catalog["platforms"]]
