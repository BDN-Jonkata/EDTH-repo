"""Scenario generator: one config + one seed -> scenario (what the system may read) and truth (scoring only).

Same config and same seed always give the same result. Targets, friendly patrols and ground
sensors are drawn from separate random streams, so changing one part does not reshuffle another.
Motion follows the models the simulation uses: friendlies fly circular patrols, hostiles follow
piecewise-linear waypoint paths with a small sideways wobble.
"""
from __future__ import annotations

import copy
import math
import random
import re

import catalog as cat

SCHEMA = "edth.scenario/1"
AREA = 1000.0
SEED_SETS = {"tuning": (1, 99), "test": (1000, 1099)}  # never tune on the test seeds
MOTIONS = ("straight", "waypoints", "loiter", "hover", "mixed")
FRIENDLY_ANCHORS = [(250, 700), (760, 780), (780, 250), (380, 200), (520, 520)]
SENSOR_KINDS = ("eo_camera", "thermal_camera", "microphone", "rf_receiver", "radar")
SIGNATURE_KEYS = ("eo", "thermal", "acoustic", "rf", "radar")

DEFAULT_CONFIG = {
    "name": "scenario",
    "seed": 1,
    "seed_set": None,
    "preset": None,
    "description": "",
    "duration_s": 120,
    "c2": [470, 350],
    "targets": {
        "count": 2,
        "speed_mps": [8, 16],
        "altitude_m": [20, 120],
        "motion": "straight",
        "hover_prob": 0.0,
        "sudden_turn_prob": 0.0,
        "enter_t": [5, 20],
        "wobble_m": 5,
        "signature_spread": 0.15,
        "crossing": {"enabled": True, "t": 51, "min_sep_m": 8, "max_sep_m": 20},
    },
    "friendlies": {
        "platforms": ["mini4pro", "anafi_thermal", "px4_quad_passive", "px4_quad_radar", "skydio_x10"],
        "altitude_m": 60,
        "speed_mps": [5, 11],
        "beacon": {"enabled": True, "rate_hz": 2, "pos_sigma_m": 3},
    },
    "ground": [
        {"id": "GS1", "platform": "gs_eo_acoustic", "position": [300, 300]},
        {"id": "GS2", "platform": "gs_radar_rf", "position": [655, 460]},
    ],
    "sensor_set": {"enabled_kinds": list(SENSOR_KINDS)},
    "environment": {
        "weather": "clear",
        "time_of_day": "day",
        "clutter": {"false_alarms_per_min": 3},
    },
    "degradations": {
        "clock": {"enabled": False, "offset_ms": [0, 200], "drift_ppm": 50},
        "pose": {"enabled": False, "position_err_m": 5, "heading_err_deg": 3},
        "network": {"enabled": False, "loss": 0.0, "burst": False, "latency_ms": [0, 0],
                    "out_of_order": False, "topology": "mesh", "jamming_zones": []},
        "dropout": [],
    },
}


# ------------------------------------------------------------------ config
def merge(base, over):
    """Deep-merge `over` into a copy of `base` (lists and scalars in `over` replace)."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def seed_for(seed_set, index):
    """Seed number `index` (0-based) of the tuning or test set."""
    lo, hi = SEED_SETS[seed_set]
    if not 0 <= index <= hi - lo:
        raise ValueError("index %d outside the %s seed set (0..%d)" % (index, seed_set, hi - lo))
    return lo + index


def resolve(config):
    """Defaults + config. Does not validate."""
    cfg = merge(DEFAULT_CONFIG, config)
    if isinstance(config.get("targets"), list):
        cfg["targets"] = copy.deepcopy(config["targets"])  # explicit target list replaces the generator spec
    return cfg


def validate_config(cfg, catalog=None):
    """Return a list of error strings (empty if the config can be generated)."""
    catalog = catalog or cat.load_catalog()
    platforms = {p["id"]: p for p in catalog["platforms"]}
    errors = []
    if not isinstance(cfg["seed"], int) or isinstance(cfg["seed"], bool):
        errors.append("seed must be an integer")
    elif cfg.get("seed_set"):
        if cfg["seed_set"] not in SEED_SETS:
            errors.append("seed_set must be one of %s" % sorted(SEED_SETS))
        else:
            lo, hi = SEED_SETS[cfg["seed_set"]]
            if not lo <= cfg["seed"] <= hi:
                errors.append("seed %d is outside the %s seed set (%d-%d)" % (cfg["seed"], cfg["seed_set"], lo, hi))
    if not 30 <= cfg["duration_s"] <= 3600:
        errors.append("duration_s must be between 30 and 3600")
    c2 = cfg["c2"]
    if len(c2) != 2 or not all(0 <= v <= AREA for v in c2):
        errors.append("c2 must be [x, y] inside the 1000 m area")

    t = cfg["targets"]
    if isinstance(t, dict):
        if not 0 <= t["count"] <= 8:
            errors.append("targets.count must be 0..8")
        for key in ("speed_mps", "altitude_m", "enter_t"):
            if len(t[key]) != 2 or t[key][0] > t[key][1]:
                errors.append("targets.%s must be [low, high]" % key)
        if t["motion"] not in MOTIONS:
            errors.append("targets.motion must be one of %s" % (MOTIONS,))
        for key in ("hover_prob", "sudden_turn_prob"):
            if not 0 <= t[key] <= 1:
                errors.append("targets.%s must be between 0 and 1" % key)
        cr = t["crossing"]
        if cr["enabled"] and t["count"] >= 2:
            if not 15 <= cr["t"] <= cfg["duration_s"] - 15:
                errors.append("targets.crossing.t must leave 15 s before and after the crossing")
            if cr["min_sep_m"] > cr["max_sep_m"]:
                errors.append("targets.crossing min_sep_m must not exceed max_sep_m")
    else:
        for i, tg in enumerate(t):
            if not tg.get("waypoints") or len(tg["waypoints"]) < 2:
                errors.append("targets[%d] needs at least 2 waypoints [t, x, y]" % i)

    plats = cfg["friendlies"]["platforms"]
    if not 1 <= len(plats) <= 8:
        errors.append("friendlies.platforms needs 1..8 entries")
    for pid in plats:
        if pid not in platforms or platforms[pid]["platform"] != "uas":
            errors.append("friendly platform '%s' is not a UAS in the catalog" % pid)
    seen = set()
    for g in cfg["ground"]:
        if g["id"] in seen:
            errors.append("duplicate ground id " + g["id"])
        seen.add(g["id"])
        if g["platform"] not in platforms or platforms[g["platform"]]["platform"] != "ground":
            errors.append("ground platform '%s' is not a ground sensor in the catalog" % g["platform"])
        if not all(0 <= v <= AREA for v in g["position"]):
            errors.append("ground sensor %s is outside the area" % g["id"])
    bad = [k for k in cfg["sensor_set"]["enabled_kinds"] if k not in SENSOR_KINDS]
    if bad:
        errors.append("unknown sensor kinds: %s" % bad)
    if cfg["environment"]["weather"] not in cat.WEATHERS + ("clear",):
        errors.append("environment.weather must be clear, fog, rain, wind or night")
    net = cfg["degradations"]["network"]
    if not 0 <= net["loss"] <= 1:
        errors.append("degradations.network.loss must be between 0 and 1")
    return errors


# ------------------------------------------------------------------ motion models (same maths as ui/viewer/sim.js)
def friendly_state(f, t):
    lp = f["loop"]
    a = lp["th0"] + lp["dir"] * (lp["v"] / lp["R"]) * t
    return {
        "x": lp["cx"] + lp["R"] * math.cos(a), "y": lp["cy"] + lp["R"] * math.sin(a),
        "vx": -lp["dir"] * lp["v"] * math.sin(a), "vy": lp["dir"] * lp["v"] * math.cos(a),
    }


def _target_pos(tg, t):
    wps = tg["waypoints"]
    i = 0
    while i < len(wps) - 2 and t > wps[i + 1][0]:
        i += 1
    (t0, x0, y0), (t1, x1, y1) = wps[i], wps[i + 1]
    s = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
    dx, dy = x1 - x0, y1 - y0
    seg = math.hypot(dx, dy)
    x, y = x0 + dx * s, y0 + dy * s
    if seg > 1e-6:  # no wobble while hovering; it fades to zero at each waypoint so turns stay continuous
        taper = max(0.0, min(1.0, (t - t0) / 2.0, (t1 - t) / 2.0))
        w = tg["wobble_m"] * taper * math.sin(0.35 * (t - wps[0][0]) + tg["phase"])
        x -= dy / seg * w
        y += dx / seg * w
    return x, y


def target_state(tg, t):
    """Position and velocity of a hostile at time t, or None before it enters, after it exits or outside the area."""
    wps = tg["waypoints"]
    if t < wps[0][0] or t > wps[-1][0]:
        return None
    x, y = _target_pos(tg, t)
    if not (0 <= x <= AREA and 0 <= y <= AREA):
        return None
    xa, ya = _target_pos(tg, t - 0.05)
    xb, yb = _target_pos(tg, t + 0.05)
    return {"x": x, "y": y, "vx": (xb - xa) / 0.1, "vy": (yb - ya) / 0.1}


# ------------------------------------------------------------------ generation
def _streams(seed):
    return {name: random.Random(seed * 1000003 + i) for i, name in enumerate(("friendly", "target", "ground"))}


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "scenario"


def _ray_to_edge(x, y, ux, uy):
    """Distance from (x, y) along (ux, uy) to the edge of the area."""
    best = 1e9
    for lo, p, u in ((0, x, ux), (AREA, x, ux), (0, y, uy), (AREA, y, uy)):
        if abs(u) > 1e-9:
            d = (lo - p) / u
            if d > 1e-6:
                best = min(best, d)
    return best


def _make_friendlies(cfg, rng):
    f = cfg["friendlies"]
    out = []
    for i, pid in enumerate(f["platforms"]):
        ax, ay = FRIENDLY_ANCHORS[i % len(FRIENDLY_ANCHORS)]
        radius = round(100 + 10 * i + rng.uniform(-10, 10), 1)
        cx = min(AREA - radius - 20, max(radius + 20, ax + rng.uniform(-50, 50)))
        cy = min(AREA - radius - 20, max(radius + 20, ay + rng.uniform(-50, 50)))
        loop = {"cx": round(cx, 1), "cy": round(cy, 1), "R": radius,
                "v": round(rng.uniform(*f["speed_mps"]), 1), "dir": rng.choice((-1, 1)),
                "th0": round(rng.uniform(0, 2 * math.pi), 3)}
        out.append({"id": "F%d" % (i + 1), "role": "friendly", "platform": pid, "altitude_m": f["altitude_m"], "loop": loop})
    return out


def _make_ground(cfg):
    out = []
    cx, cy = AREA / 2, AREA / 2
    for g in cfg["ground"]:
        x, y = g["position"]
        # a mast faces the village centre unless told otherwise (compass degrees, 0 = north, clockwise)
        heading = g.get("heading_deg")
        if heading is None:
            heading = round(math.degrees(math.atan2(cx - x, cy - y)) % 360, 1)
        out.append({"id": g["id"], "role": "ground", "platform": g["platform"], "position": [x, y], "heading_deg": heading})
    return out


def _signature(spec, rng):
    return {k: round(max(0.2, min(1.5, 1 + rng.uniform(-1, 1) * spec["signature_spread"])), 2) for k in SIGNATURE_KEYS}


def _edge_point(rng):
    side = rng.choice(("W", "E", "S", "N"))
    u = rng.uniform(80, AREA - 80)
    return {"W": (15, u), "E": (AREA - 15, u), "S": (u, 15), "N": (u, AREA - 15)}[side]


def _finish(wps, speed, t_start):
    """Turn a list of (x, y, hold_s) points into timed waypoints [t, x, y] flown at `speed`."""
    out, t = [], t_start
    prev = None
    for x, y, hold in wps:
        if prev is not None:
            t += math.hypot(x - prev[0], y - prev[1]) / speed
        out.append([round(t, 2), round(x, 1), round(y, 1)])
        if hold:
            t += hold
            out.append([round(t, 2), round(x, 1), round(y, 1)])
        prev = (x, y)
    return out


def _crossing_paths(spec, rng, duration):
    """Two hostiles that pass within a few metres of each other at the crossing time."""
    cr = spec["crossing"]
    tc = min(cr["t"], duration - 15)
    px, py = rng.uniform(420, 580), rng.uniform(420, 580)
    sep = rng.uniform(cr["min_sep_m"], cr["max_sep_m"])
    phi = rng.uniform(0, 2 * math.pi)
    points = [(px, py), (px + sep * math.cos(phi), py + sep * math.sin(phi))]
    heads = [math.radians(rng.uniform(-50, -20)), math.radians(rng.uniform(200, 235))]
    paths = []
    for (qx, qy), head in zip(points, heads):
        ux, uy = math.cos(head), math.sin(head)
        v = rng.uniform(*spec["speed_mps"])
        edge_in = _ray_to_edge(qx, qy, -ux, -uy)
        length_in = min(edge_in - 15, v * (tc - 3))  # start inside the area, entering no earlier than t = 3 s
        length_out = _ray_to_edge(qx, qy, ux, uy) + 5
        t0 = tc - length_in / v
        wps = [[round(t0, 2), round(qx - ux * length_in, 1), round(qy - uy * length_in, 1)],
               [round(tc, 2), round(qx, 1), round(qy, 1)],
               [round(tc + length_out / v, 2), round(qx + ux * length_out, 1), round(qy + uy * length_out, 1)]]
        paths.append((wps, v, "crossing"))
    return paths


def _free_path(spec, rng, motion, duration):
    """A hostile that enters at an edge, flies through the village and leaves (or loiters/hovers on the way)."""
    v = rng.uniform(*spec["speed_mps"])
    t0 = rng.uniform(*spec["enter_t"])
    ex, ey = _edge_point(rng)
    if motion == "mixed":
        motion = rng.choice(("straight", "waypoints", "loiter", "hover"))
    if rng.random() < spec["hover_prob"] and motion in ("straight", "waypoints"):
        motion = "hover"
    pts = [(ex, ey, 0)]
    q = (rng.uniform(250, 750), rng.uniform(250, 750))

    def turn(prev, cur):
        # a sudden turn: swing the next leg 60-120 degrees away from the current heading
        if rng.random() < spec["sudden_turn_prob"]:
            ang = math.atan2(cur[1] - prev[1], cur[0] - prev[0]) + rng.choice((-1, 1)) * math.radians(rng.uniform(60, 120))
            d = rng.uniform(80, 160)
            return (min(AREA - 30, max(30, cur[0] + d * math.cos(ang))), min(AREA - 30, max(30, cur[1] + d * math.sin(ang))), 0)
        return None

    if motion == "straight":
        pts.append((q[0], q[1], 0))
    elif motion == "waypoints":
        for _ in range(rng.randint(2, 3)):
            pts.append((rng.uniform(150, 850), rng.uniform(150, 850), 0))
    elif motion == "hover":
        pts.append((q[0], q[1], rng.uniform(6, 15)))
    elif motion == "loiter":
        pts.append((q[0], q[1], 0))
        r, a0, turns = rng.uniform(60, 100), rng.uniform(0, 2 * math.pi), rng.uniform(0.8, 1.6)
        steps = int(turns * 16)
        for k in range(1, steps + 1):
            a = a0 + 2 * math.pi * turns * k / steps
            pts.append((min(AREA - 20, max(20, q[0] + r * (math.cos(a) - math.cos(a0)))), min(AREA - 20, max(20, q[1] + r * (math.sin(a) - math.sin(a0)))), 0))
    extra = []
    for i in range(1, len(pts)):
        tp = turn(pts[i - 1], pts[i])
        if tp:
            extra.append((i, tp))
    for off, (i, tp) in enumerate(extra):
        pts.insert(i + 1 + off, tp)
    # leave through the far side
    last = pts[-1]
    ang = math.atan2(AREA / 2 - last[1], AREA / 2 - last[0]) + math.pi + rng.uniform(-0.6, 0.6)
    ux, uy = math.cos(ang), math.sin(ang)
    pts.append((last[0] + ux * (_ray_to_edge(last[0], last[1], ux, uy) + 5), last[1] + uy * (_ray_to_edge(last[0], last[1], ux, uy) + 5), 0))
    return _finish(pts, v, t0), v, motion


def _make_targets(cfg, rng):
    spec = cfg["targets"]
    duration = cfg["duration_s"]
    if isinstance(spec, list):  # explicit list: use as given, fill in the gaps
        out = []
        for i, tg in enumerate(spec):
            out.append({
                "id": tg.get("id", "H%d" % (i + 1)), "role": tg.get("role", "hostile"), "motion": tg.get("motion", "explicit"),
                "speed_mps": tg.get("speed_mps"), "altitude_m": tg.get("altitude_m", 80), "waypoints": tg["waypoints"],
                "wobble_m": tg.get("wobble_m", 5), "phase": tg.get("phase", round(rng.uniform(0, 2 * math.pi), 2)),
                "signature": tg.get("signature") or _signature(DEFAULT_CONFIG["targets"], rng), "emits": tg.get("emits", True),
            })
        return out
    out = []
    planned = []
    if spec["crossing"]["enabled"] and spec["count"] >= 2:
        planned.extend(_crossing_paths(spec, rng, duration))
    while len(planned) < spec["count"]:
        wps, v, motion = _free_path(spec, rng, spec["motion"], duration)
        planned.append((wps, v, motion))
    for i, (wps, v, motion) in enumerate(planned):
        out.append({
            "id": "H%d" % (i + 1), "role": "hostile", "motion": motion, "speed_mps": round(v, 1),
            "altitude_m": round(rng.uniform(*spec["altitude_m"]), 1), "waypoints": wps,
            "wobble_m": spec["wobble_m"], "phase": round(rng.uniform(0, 2 * math.pi), 2),
            "signature": _signature(spec, rng), "emits": True,
        })
    return out


def _sensors_of(platform, modules_by_id, enabled):
    return [{"module": l["module_id"], "kind": modules_by_id[l["module_id"]]["kind"]}
            for l in platform["modules"] if modules_by_id[l["module_id"]]["kind"] in enabled]


def generate(config, catalog=None, truth_dt=0.1):
    """Return (scenario, truth) for a config. Raises ValueError if the config is invalid."""
    catalog = catalog or cat.load_catalog()
    cfg = resolve(config)
    errors = validate_config(cfg, catalog)
    if errors:
        raise ValueError("invalid scenario config:\n  - " + "\n  - ".join(errors))
    rng = _streams(cfg["seed"])
    modules_by_id = {m["id"]: m for m in catalog["modules"]}
    platforms = {p["id"]: p for p in catalog["platforms"]}
    enabled = set(cfg["sensor_set"]["enabled_kinds"])

    friendlies = _make_friendlies(cfg, rng["friendly"])
    ground = _make_ground(cfg)
    targets = _make_targets(cfg, rng["target"])
    for node in friendlies + ground:
        node["sensors"] = _sensors_of(platforms[node["platform"]], modules_by_id, enabled)

    scenario_id = "%s-s%d" % (_slug(cfg["name"]), cfg["seed"])
    scenario = {
        "schema": SCHEMA, "id": scenario_id, "name": cfg["name"], "seed": cfg["seed"], "seed_set": cfg["seed_set"],
        "preset": cfg["preset"], "description": cfg["description"], "duration_s": cfg["duration_s"],
        "area": {"size_m": AREA}, "c2": cfg["c2"],
        "friendlies": friendlies, "ground": ground, "targets": targets,
        "beacon": cfg["friendlies"]["beacon"], "sensor_set": cfg["sensor_set"],
        "environment": cfg["environment"], "degradations": cfg["degradations"],
        "config": cfg,
    }
    truth = build_truth(scenario, truth_dt)
    return scenario, truth


# ------------------------------------------------------------------ ground truth (kept apart from the scenario)
def build_truth(scenario, dt=0.1):
    """Sampled positions of every object plus events (enter, exit, crossings). For scoring only."""
    n = int(round(scenario["duration_s"] / dt))
    objects = []
    for f in scenario["friendlies"]:
        samples = []
        for k in range(n + 1):
            t = k * dt
            s = friendly_state(f, t)
            samples.append([round(t, 3), round(s["x"], 1), round(s["y"], 1), round(s["vx"], 2), round(s["vy"], 2)])
        objects.append({"id": f["id"], "kind": "friendly", "platform": f["platform"], "altitude_m": f["altitude_m"], "samples": samples})
    hostile_samples = {}
    for tg in scenario["targets"]:
        samples = []
        for k in range(n + 1):
            t = k * dt
            s = target_state(tg, t)
            if s:
                samples.append([round(t, 3), round(s["x"], 1), round(s["y"], 1), round(s["vx"], 2), round(s["vy"], 2)])
        hostile_samples[tg["id"]] = {row[0]: row for row in samples}
        objects.append({"id": tg["id"], "kind": "hostile", "motion": tg["motion"], "altitude_m": tg["altitude_m"], "samples": samples})

    events = []
    for tg in scenario["targets"]:
        rows = hostile_samples[tg["id"]]
        if rows:
            ts = sorted(rows)
            events.append({"type": "enter", "id": tg["id"], "t": ts[0]})
            events.append({"type": "exit", "id": tg["id"], "t": ts[-1]})
    ids = [tg["id"] for tg in scenario["targets"]]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = hostile_samples[ids[i]], hostile_samples[ids[j]]
            both = sorted(set(a) & set(b))
            seps = [(math.hypot(a[t][1] - b[t][1], a[t][2] - b[t][2]), t) for t in both]
            # local minima below 60 m are close crossings; minima within 3 s of each other are one crossing
            found = []
            for k in range(1, len(seps) - 1):
                if seps[k][0] < 60 and seps[k][0] <= seps[k - 1][0] and seps[k][0] < seps[k + 1][0]:
                    if found and seps[k][1] - found[-1][1] < 3:
                        if seps[k][0] < found[-1][0]:
                            found[-1] = seps[k]
                    else:
                        found.append(seps[k])
            for sep, t in found:
                events.append({"type": "crossing", "a": ids[i], "b": ids[j], "t": t, "sep_m": round(sep, 1),
                               "x": round((a[t][1] + b[t][1]) / 2, 1), "y": round((a[t][2] + b[t][2]) / 2, 1)})
    events.sort(key=lambda e: e["t"])
    return {"schema": "edth.truth/2", "scenario_id": scenario["id"], "seed": scenario["seed"], "duration_s": scenario["duration_s"],
            "dt_s": dt, "columns": ["t", "x", "y", "vx", "vy"], "objects": objects, "events": events}
