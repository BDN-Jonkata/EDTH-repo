"""Bounded, explainable motion evidence. No truth roles, target IDs or future paths.

These are simulation policy scores, not calibrated real-world intent probabilities.
An authorized corridor is operational configuration, not inferred from smooth flight.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

from drone_behavior.encounters import assess as assess_encounter


@dataclass
class BehaviorConfig:
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
        """Compatibility constructor; assessment no longer depends on C2 geography."""
        return cls(**overrides)

    def __post_init__(self):
        for name in ("window_s", "sample_period_s", "min_history_s", "max_gap_s", "max_sigma_m", "memory_ttl_s"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not 0 < self.min_existence <= 1 or not self.sample_period_s <= self.max_gap_s <= self.window_s:
            raise ValueError("invalid behaviour sampling or existence settings")
        for c in self.corridors:
            if (not all(math.isfinite(v) for v in c["start"] + c["end"]) or
                    math.dist(c["start"], c["end"]) <= 0 or
                    not math.isfinite(c["half_width_m"]) or c["half_width_m"] <= 0 or
                    not math.isfinite(c.get("max_speed_mps", 30)) or c.get("max_speed_mps", 30) <= 0):
                raise ValueError("invalid authorized corridor")


def _mean(values):
    return sum(values) / len(values)


def _smooth_history(h):
    out = [dict(h[0])]
    for a, b in zip(h, h[1:]):
        gain = 1 - math.exp(-(b["t"] - a["t"]) / 1.5)
        p = out[-1]
        out.append(dict(b, vx=p["vx"] + gain * (b["vx"] - p["vx"]),
                        vy=p["vy"] + gain * (b["vy"] - p["vy"])))
    return out


def _features(h):
    motion = [(h[0]["vx"], h[0]["vy"])]
    for a, b in zip(h, h[1:]):
        # Tracker velocity is a noisy derivative. A short time-based filter keeps
        # its frame-to-frame jitter from masquerading as an erratic flight path.
        gain = 1 - math.exp(-(b["t"] - a["t"]) / 1.5)
        px, py = motion[-1]
        motion.append((px + gain * (b["vx"] - px), py + gain * (b["vy"] - py)))
    speeds = [math.hypot(vx, vy) for vx, vy in motion]
    pairs = list(zip(h, h[1:]))
    path = sum((speeds[i] + speeds[i + 1]) * (b["t"] - a["t"]) / 2 for i, (a, b) in enumerate(pairs))
    angles = [math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1])
              for a, b in zip(motion, motion[1:]) if min(math.hypot(*a), math.hypot(*b)) >= 2]
    total_turn = sum(abs(a) for a in angles)
    span = h[-1]["t"] - h[0]["t"]
    dx, dy = h[-1]["x"] - h[0]["x"], h[-1]["y"] - h[0]["y"]
    integrated = [sum((motion[i][k] + motion[i + 1][k]) * (b["t"] - a["t"]) / 2
                      for i, (a, b) in enumerate(pairs)) for k in (0, 1)]
    speed = _mean(speeds)
    return {
        "mean_speed_mps": speed,
        "course_vx_mps": motion[-1][0], "course_vy_mps": motion[-1][1],
        "speed_cv": math.sqrt(_mean([(v - speed) ** 2 for v in speeds])) / max(speed, 1),
        "mean_turn_rad_s": total_turn / max(span, 0.5),
        "signed_turn_rad_s": sum(angles) / max(span, 0.5),
        "total_turn_rad": total_turn,
        "turn_coherence": abs(sum(angles)) / max(total_turn, 1e-9),
        "velocity_consistency": max(0.0, 1 - math.hypot(dx - integrated[0], dy - integrated[1]) / max(path, 20)),
        "path_m": path,
        "displacement_m": math.hypot(dx, dy),
    }


class BehaviorModel:
    """Callable `threat_llr` hook. Call begin(t) before each estimator update.

    A rolling window describes ONE bounded evidence state. The hook returns its
    change after the estimator's forgetting, rather than adding the entire window
    on every frame. Duplicate, stale, predicted and poor-quality states add zero.
    `observed_t` (optional internal metadata) distinguishes fresh measurements from
    extrapolation; otherwise TrackState.t must be the last observed state time.
    """

    version = "encounter-policy-v3"

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
        self._allies = {}

    def begin(self, t):
        if not math.isfinite(t) or t < self.now:
            raise ValueError("behaviour time must be finite and monotonic")
        self.now = t
        self.memory = {k: v for k, v in self.memory.items() if t - v["seen"] <= self.config.memory_ttl_s}
        self.verified.intersection_update(self.memory)
        # Freeze observed ally histories before evaluating any track. Input order
        # cannot change the reference, and stale/predicted references are excluded.
        self._allies = {k: _smooth_history(self.memory[k]["history"]) for k in sorted(self.verified)
                        if k in self.memory and len(self.memory[k]["history"]) >= 2 and
                        t - self.memory[k]["history"][-1]["t"] <= self.config.max_gap_s and
                        self.memory[k]["history"][-1]["t"] - self.memory[k]["history"][0]["t"] >= 8}
        self._profiles = {k: _features(self.memory[k]["history"]) for k in self._allies}

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
            if h:
                prev, elapsed = h[-1], t - h[-1]["t"]
                residual = math.hypot(tr.position[0] - prev["x"] - prev["vx"] * elapsed,
                                      tr.position[1] - prev["y"] - prev["vy"] * elapsed)
                if residual > max(30, 4 * math.hypot(prev["sigma"], tr.pos_sigma) + 5 * elapsed ** 2):
                    h.clear()  # an association jump starts a new observed history
            m["obs"], m["eval"] = obs, t
            h.append({"t": t, "x": tr.position[0], "y": tr.position[1], "vx": tr.velocity[0],
                      "vy": tr.velocity[1], "sigma": tr.pos_sigma, "existence": tr.existence_prob})
            h[:] = [s for s in h if t - s["t"] <= cfg.window_s + 1e-8]
            score, reasons, features = self._score(tr.track_id, h)
            quality = _mean([s["existence"] for s in h]) / (1 + (_mean([s["sigma"] for s in h]) / 15) ** 2)
            target = max(-self.evidence_limit, min(self.evidence_limit, score * quality))
            retained = None
            # Losing one maneuver from the moving window is not a new observation
            # that disproves an encounter. Keep that bounded evidence while it
            # decays; a new association or sustained safe motion can clear it.
            if (m["llr"] > max(0, target) and score > -2 and
                    h[-1]["t"] - h[0]["t"] >= cfg.min_history_s and m.get("risk")):
                target = m["llr"]
                retained = dict(m["risk"], age_s=t - m["risk"]["t"])
                reasons = reasons + ["recent_encounter_evidence"]
            elif target > 0:
                m["risk"] = {"t": t, "reasons": list(reasons), "features": dict(features)}
            else:
                m.pop("risk", None)
            increment = target - m["llr"]
            m["llr"] = target
            m["result"] = {"quality": quality, "observed_s": h[-1]["t"] - h[0]["t"],
                           "reasons": reasons, "features": features, "last_observed_t": t,
                           "retained_risk": retained,
                           "pattern": self._pattern(features) if len(h) >= 2 else "insufficient_history"}
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
        risk, reasons, converging = 0.0, [], False
        motion = _smooth_history(h)
        for ally_id, history in self._allies.items():
            if ally_id == track_id:
                continue
            score, cues, details, blocked = assess_encounter(motion, history)
            converging = converging or blocked
            quality = _mean([s["existence"] for s in history]) / (1 + (_mean([s["sigma"] for s in history]) / 15) ** 2)
            if score * quality > risk:
                risk, reasons = score * quality, cues
                f.update(details, reference_track_id=ally_id)
        if risk:
            return risk, reasons, f
        if converging:
            return 0.0, ["converging_traffic"], f
        if span >= 10:
            if any(self._in_corridor(h, c) for c in cfg.corridors):
                return -3.2, ["authorized_corridor_transit"], f
            if (span >= 15 and f["speed_cv"] < 0.35 and f["mean_speed_mps"] > 2 and
                    f["displacement_m"] > max(60, 0.85 * f["path_m"]) and f["velocity_consistency"] > 0.75 and
                    f["mean_turn_rad_s"] < 0.15):
                strength = 3.4 * min(1, (span - 10) / 8)
                return -strength, ["sustained_safe_transit"], f
            if (span >= 18 and f["path_m"] >= 100 and f["speed_cv"] < 0.3 and
                    f["total_turn_rad"] >= math.pi / 2 and f["turn_coherence"] > 0.75 and
                    0.04 <= f["mean_turn_rad_s"] <= 0.4 and f["velocity_consistency"] > 0.75):
                return -3.3, ["consistent_orbit"], f
            if f["speed_cv"] < 0.35 and f["mean_speed_mps"] > 2 and f["displacement_m"] > 0.85 * f["path_m"]:
                return -0.7, ["developing_transit_pattern"], f
            for friend_id in sorted(self._profiles.keys() - {track_id}):
                pf = self._profiles[friend_id]
                if (abs(pf["mean_speed_mps"] - f["mean_speed_mps"]) < 2 and
                        abs(pf["mean_turn_rad_s"] - f["mean_turn_rad_s"]) < 0.05):
                    return -0.5, ["resembles_verified_patrol_only"], f
        return 0.0, ["ambiguous_motion"], f

    @staticmethod
    def _pattern(f):
        if f.get("response_count", 0) >= 2:
            return "pursuit"
        if f["mean_speed_mps"] < 2:
            return "hover"
        if f["total_turn_rad"] >= math.pi / 2 and f["turn_coherence"] > 0.65:
            return "orbit"
        if f["displacement_m"] > 0.85 * f["path_m"] and f["speed_cv"] < 0.35:
            return "transit"
        return "maneuvering"

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
