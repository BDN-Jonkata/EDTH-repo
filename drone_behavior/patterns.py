"""Bounded, explainable motion evidence. No truth roles, target IDs or future paths.

These are simulation policy scores, not calibrated real-world intent probabilities.
An authorized corridor is operational configuration, not inferred from smooth flight.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BehaviorConfig:
    protected_zones: list = field(default_factory=list)  # {x, y, radius_m}
    corridors: list = field(default_factory=list)  # {start: [x,y], end: [x,y], half_width_m, max_speed_mps}
    window_s: float = 20.0
    sample_period_s: float = 0.5
    min_history_s: float = 4.0
    max_gap_s: float = 2.0
    max_sigma_m: float = 25.0
    min_existence: float = 0.6
    memory_ttl_s: float = 30.0

    @classmethod
    def for_area(cls, c2, **overrides):
        """Default simulation policy: a 150 m protected radius around our known C2."""
        return cls(**dict({"protected_zones": [{"x": c2[0], "y": c2[1], "radius_m": 150.0}]}, **overrides))

    def __post_init__(self):
        for name in ("window_s", "sample_period_s", "min_history_s", "max_gap_s", "max_sigma_m", "memory_ttl_s"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not 0 < self.min_existence <= 1 or not self.sample_period_s <= self.max_gap_s <= self.window_s:
            raise ValueError("invalid behaviour sampling or existence settings")
        for z in self.protected_zones:
            if not all(math.isfinite(z[k]) for k in ("x", "y", "radius_m")) or z["radius_m"] <= 0:
                raise ValueError("invalid protected zone")
        for c in self.corridors:
            if (not all(math.isfinite(v) for v in c["start"] + c["end"]) or
                    math.dist(c["start"], c["end"]) <= 0 or
                    not math.isfinite(c["half_width_m"]) or c["half_width_m"] <= 0 or
                    not math.isfinite(c.get("max_speed_mps", 30)) or c.get("max_speed_mps", 30) <= 0):
                raise ValueError("invalid authorized corridor")


def _mean(values):
    return sum(values) / len(values)


def _features(h):
    speeds = [math.hypot(s["vx"], s["vy"]) for s in h]
    pairs = list(zip(h, h[1:]))
    path = sum(math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in pairs)
    turns = [abs(math.atan2(a["vx"] * b["vy"] - a["vy"] * b["vx"],
                            a["vx"] * b["vx"] + a["vy"] * b["vy"])) / (b["t"] - a["t"])
             for a, b in pairs if min(math.hypot(a["vx"], a["vy"]), math.hypot(b["vx"], b["vy"])) >= 2]
    speed = _mean(speeds)
    return {
        "mean_speed_mps": speed,
        "speed_cv": math.sqrt(_mean([(v - speed) ** 2 for v in speeds])) / max(speed, 1),
        "mean_turn_rad_s": _mean(turns) if turns else 0.0,
        "path_m": path,
        "displacement_m": math.hypot(h[-1]["x"] - h[0]["x"], h[-1]["y"] - h[0]["y"]),
    }


class BehaviorModel:
    """Callable `threat_llr` hook. Call begin(t) before each estimator update.

    A rolling window describes ONE bounded evidence state. The hook returns its
    change after the estimator's forgetting, rather than adding the entire window
    on every frame. Duplicate, stale, predicted and poor-quality states add zero.
    `observed_t` (optional internal metadata) distinguishes fresh measurements from
    extrapolation; otherwise TrackState.t must be the last observed state time.
    """

    version = "motion-policy-v1"

    def __init__(self, config: Optional[BehaviorConfig] = None, threat_tau_s=20.0, max_dt_s=2.0, evidence_limit=4.0):
        self.config = config or BehaviorConfig()
        self.threat_tau_s, self.max_dt_s = threat_tau_s, max_dt_s
        self.evidence_limit = evidence_limit
        if not all(math.isfinite(v) and v > 0 for v in (threat_tau_s, max_dt_s, evidence_limit)):
            raise ValueError("evidence decay and limits must be finite and positive")
        self.now = 0.0
        self.memory = {}
        self.verified = set()
        self._profiles = {}

    def begin(self, t):
        if not math.isfinite(t) or t < self.now:
            raise ValueError("behaviour time must be finite and monotonic")
        self.now = t
        self.memory = {k: v for k, v in self.memory.items() if t - v["seen"] <= self.config.memory_ttl_s}
        self.verified.intersection_update(self.memory)
        # Freeze learned patrol features for this update so input track ordering
        # cannot change which version of a friendly's history another track sees.
        self._profiles = {k: _features(self.memory[k]["history"]) for k in self.verified
                          if len(self.memory[k]["history"]) >= 2 and
                          self.memory[k]["history"][-1]["t"] - self.memory[k]["history"][0]["t"] >= 10}

    def __call__(self, tr):
        cfg, t = self.config, self.now
        m = self.memory.setdefault(tr.track_id, {"history": [], "obs": -math.inf, "eval": -math.inf,
                                                "llr": 0.0, "called": t, "seen": t, "result": {}})
        dt = max(0.0, min(t - m["called"], self.max_dt_s))
        m["llr"] *= math.exp(-dt / self.threat_tau_s)
        m["called"], m["seen"] = t, t
        obs = getattr(tr, "observed_t", None)
        obs = tr.t if obs is None else obs
        valid = all(math.isfinite(v) for v in (tr.t, obs, tr.pos_sigma, tr.existence_prob, *tr.position, *tr.velocity))
        valid = valid and 0 <= tr.pos_sigma <= cfg.max_sigma_m and cfg.min_existence <= tr.existence_prob <= 1
        fresh = valid and obs > m["obs"] + 1e-8 and -0.5 <= t - obs <= cfg.max_gap_s
        increment = 0.0
        if fresh and t - m["eval"] >= cfg.sample_period_s - 1e-8:
            h = m["history"]
            if h and (t - h[-1]["t"] > cfg.max_gap_s or obs - m["obs"] > cfg.max_gap_s):
                h.clear()
            m["obs"], m["eval"] = obs, t
            h.append({"t": t, "x": tr.position[0], "y": tr.position[1], "vx": tr.velocity[0],
                      "vy": tr.velocity[1], "sigma": tr.pos_sigma, "existence": tr.existence_prob})
            h[:] = [s for s in h if t - s["t"] <= cfg.window_s + 1e-8]
            score, reasons, features = self._score(tr.track_id, h)
            quality = _mean([s["existence"] for s in h]) / (1 + (_mean([s["sigma"] for s in h]) / 15) ** 2)
            target = max(-self.evidence_limit, min(self.evidence_limit, score * quality))
            increment = target - m["llr"]
            m["llr"] = target
            m["result"] = {"quality": quality, "observed_s": h[-1]["t"] - h[0]["t"],
                           "reasons": reasons, "features": features, "last_observed_t": t}
        m["result"] = dict(m["result"], llr=m["llr"], increment=increment, model_version=self.version)
        return increment

    def explain(self, track_id):
        return dict(self.memory.get(track_id, {}).get("result", {}))

    def _score(self, track_id, h):
        cfg = self.config
        span = h[-1]["t"] - h[0]["t"]
        f = _features(h)
        if span < cfg.min_history_s - 1e-8:
            return 0.0, ["insufficient_history"], f
        risk, reasons = 0.0, []
        outside_all = True
        for zone in cfg.protected_zones:
            radius = zone["radius_m"]
            ds = [math.hypot(s["x"] - zone["x"], s["y"] - zone["y"]) for s in h]
            inside = [d + 2 * s["sigma"] < radius for d, s in zip(ds, h)]
            outside = [d - 2 * s["sigma"] > radius for d, s in zip(ds, h)]
            outside_all = outside_all and all(outside)
            last = h[-1]
            dwell_start = len(h) - 1
            while dwell_start > 0 and inside[dwell_start - 1]:
                dwell_start -= 1
            dwell = last["t"] - h[dwell_start]["t"] if inside[-1] else 0
            entered = inside[-1] and any(outside[:dwell_start])
            if entered and dwell >= 2 - 1e-8:
                risk = max(risk, 3.2)
                reasons.append("sustained_protected_entry")
            if inside[-1] and span >= 12 and sum(inside) / len(h) >= 0.8 and (f["mean_speed_mps"] < 2 or
                    (f["path_m"] >= 30 and f["displacement_m"] / max(1, f["path_m"]) < 0.4)):
                risk = max(risk, 3.0)
                reasons.append("protected_loiter")
            dx, dy = last["x"] - zone["x"], last["y"] - zone["y"]
            speed2 = last["vx"] ** 2 + last["vy"] ** 2
            ahead = max(0, min(8, -(dx * last["vx"] + dy * last["vy"]) / max(speed2, 1)))
            miss = math.hypot(dx + last["vx"] * ahead, dy + last["vy"] * ahead)
            closing = -(dx * last["vx"] + dy * last["vy"]) / max(ds[-1], 1)
            if (closing > 2 and ds[0] - ds[-1] > max(20, 4 * last["sigma"]) and
                    ds[-1] < radius + 150 and miss + 2 * last["sigma"] < radius):
                risk = max(risk, 1.2)
                reasons.append("approaching_protected_area")
        if risk:
            return risk, sorted(set(reasons)), f  # correlated approach/entry cues are not added together
        if outside_all and span >= 10:
            if any(self._in_corridor(h, c) for c in cfg.corridors):
                return -3.2, ["authorized_corridor_transit"], f
            if f["speed_cv"] < 0.15 and f["mean_speed_mps"] > 2 and f["displacement_m"] > 0.9 * f["path_m"]:
                return -0.7, ["consistent_transit_only"], f  # weak: smooth motion cannot establish peaceful intent
            for friend_id in sorted(self._profiles.keys() - {track_id}):
                pf = self._profiles[friend_id]
                if (abs(pf["mean_speed_mps"] - f["mean_speed_mps"]) < 2 and
                        abs(pf["mean_turn_rad_s"] - f["mean_turn_rad_s"]) < 0.05):
                    return -0.5, ["resembles_verified_patrol_only"], f
        return 0.0, ["ambiguous_motion"], f

    @staticmethod
    def _in_corridor(h, c):
        ax, ay = c["start"]
        dx, dy = c["end"][0] - ax, c["end"][1] - ay
        length = math.hypot(dx, dy)
        ux, uy = dx / length, dy / length
        for s in h:
            px, py = s["x"] - ax, s["y"] - ay
            along, across = px * ux + py * uy, abs(px * uy - py * ux)
            speed = math.hypot(s["vx"], s["vy"])
            if (not 2 * s["sigma"] <= along <= length - 2 * s["sigma"] or
                    across + 2 * s["sigma"] > c["half_width_m"] or not 2 < speed <= c.get("max_speed_mps", 30) or
                    abs(s["vx"] * ux + s["vy"] * uy) / speed < math.cos(math.pi / 9)):
                return False
        return math.hypot(h[-1]["x"] - h[0]["x"], h[-1]["y"] - h[0]["y"]) >= 40
