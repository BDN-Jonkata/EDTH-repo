"""Score a run: the estimated tracks against `truth.json`, with the metrics in docs/concept.md.

Per time step, estimated tracks are matched to the true objects present (hostile, friendly, benign and clutter)
by optimal assignment inside a distance gate, so a track on a friendly or on a bird is never taken for
a hostile. Legacy count metrics presume a track hostile unless its class is friendly or peaceful.
The separate `strict_hostile_*` metrics count only the actual `hostile` label; tracking coverage and
kinematic errors do not depend on classification. Every function reads truth only through `truth.py`.
"""

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from common.assignment import assign
from scoring.truth import State, TruthObject, load_truth, present_at

NOT_HOSTILE_CLASSES = ("friendly", "peaceful")
MIN_HEADING_SPEED_MPS = 1.0   # heading of a slower object is noise


@dataclass(frozen=True)
class Estimate:
    track_id: str
    t: float
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    cls: Optional[str] = None

    @property
    def counted(self) -> bool:
        return self.cls not in NOT_HOSTILE_CLASSES


@dataclass
class ScoreConfig:
    gate_m: float = 50.0          # a track farther than this from an object is not on it
    continuity_m: float = 10.0    # a pair kept from the last step is worth this much distance (noise margin)
    ospa_cutoff_m: float = 100.0
    ospa_order: int = 2
    warmup_s: float = 0.0         # steps before this are not scored


@dataclass
class RunScore:
    steps: int                              # time steps scored
    count_error_mean_abs: float             # |counted tracks - true hostiles|, averaged over steps
    count_error_bias: float                 # counted - true, averaged (positive = too many)
    pos_rmse_m: Optional[float]             # matched hostile tracks only
    vel_rmse_mps: Optional[float]
    heading_rmse_deg: Optional[float]
    ospa_m: float                           # hostiles vs counted tracks, cutoff `ospa_cutoff_m`
    id_swaps: int                           # hostile objects whose matched track id changed
    hostile_detected_frac: float            # hostile object-steps matched to a counted track
    friendlies_flagged: int                 # friendlies matched to a counted track at least once
    friendly_flag_frac: float               # friendly object-steps matched to a counted track
    clutter_flagged_frac: float             # clutter object-steps matched to a counted track
    false_tracks_mean: float                # counted tracks matching no object, per step
    benign_flag_frac: float = 0.0           # non-allied benign drone object-steps matched to a counted track
    ident_covered_frac: float = 0.0         # hostile-present steps with a drone in identification range (scoring/identification.py)
    ident_delay_s: float = 0.0              # mean time from a hostile first present to the first drone in range
    hostile_tracked_frac: float = 0.0       # matched hostile object-steps, regardless of assessed class
    matched_hostile_samples: int = 0
    hostile_samples: int = 0
    count_exact_frac: float = 0.0           # legacy presumed-threat count exactly equals truth count
    strict_hostile_count_error_mean_abs: float = 0.0
    strict_hostile_count_error_bias: float = 0.0
    strict_hostile_count_exact_frac: float = 0.0
    strict_hostile_detected_frac: float = 0.0
    strict_friendlies_flagged: int = 0


def _dist(est: Estimate, state: State) -> float:
    return math.hypot(est.x - state[0], est.y - state[1])


def match_step(ests: Sequence[Estimate], present: Sequence[Tuple[TruthObject, State]], gate_m: float,
               previous: Optional[Dict[str, str]] = None, continuity_m: float = 0.0):
    """{track_id: (object, state)} for the tracks matched to an object present.

    `previous` maps object id -> the track id it had at the last step. Keeping that pair is worth
    `continuity_m` of distance, so two objects passing closer than the position noise do not trade
    tracks because of the noise alone (the standard remedy in multi-object tracking scores).
    """
    previous = previous or {}
    cost = [[_dist(e, s) - (continuity_m if previous.get(o.id) == e.track_id else 0.0) for o, s in present] for e in ests]
    pairs = assign(cost, gate_m) if ests and present else []
    return {ests[i].track_id: present[j] for i, j in pairs if _dist(ests[i], present[j][1]) <= gate_m}


def ospa(truth_xy: List[Tuple[float, float]], est_xy: List[Tuple[float, float]], cutoff: float, order: int) -> float:
    """OSPA distance between two point sets (0 when both are empty)."""
    small, large = sorted((truth_xy, est_xy), key=len)
    if not large:
        return 0.0
    cost = [[min(math.dist(a, b), cutoff) ** order for b in large] for a in small]
    matched = sum(cost[i][j] for i, j in assign(cost)) if small else 0.0
    return ((matched + cutoff ** order * (len(large) - len(small))) / len(large)) ** (1 / order)


class _Accum:
    def __init__(self) -> None:
        self.steps = 0
        self.count_err: List[int] = []
        self.pos_sq: List[float] = []
        self.vel_sq: List[float] = []
        self.heading_sq: List[float] = []
        self.ospa: List[float] = []
        self.false_tracks: List[int] = []
        self.last_track: Dict[str, str] = {}           # object id -> track id it was last matched to
        self.id_swaps = 0
        self.swap_events: List[dict] = []              # one per ID swap, with the context that explains it
        self.seen_tracks = set()                       # every track id scored so far
        self.frames: Dict[Tuple[str, bool], int] = {}  # (kind, matched to a counted track) -> object-steps
        self.flagged_friendlies = set()
        self.strict_count_err: List[int] = []
        self.hostile_samples = 0
        self.matched_hostile_samples = 0
        self.strict_hostile_samples = 0
        self.strict_flagged_friendlies = set()

    def object_step(self, obj: TruthObject, flagged: bool) -> None:
        self.frames[(obj.kind, flagged)] = self.frames.get((obj.kind, flagged), 0) + 1
        if flagged and obj.kind == "friendly":
            self.flagged_friendlies.add(obj.id)

    def share(self, kind: str) -> float:
        yes, no = self.frames.get((kind, True), 0), self.frames.get((kind, False), 0)
        return yes / (yes + no) if yes + no else 0.0


def _heading_error_deg(est: Estimate, state: State) -> Optional[float]:
    if math.hypot(est.vx, est.vy) < MIN_HEADING_SPEED_MPS or math.hypot(state[2], state[3]) < MIN_HEADING_SPEED_MPS:
        return None
    diff = math.degrees(math.atan2(est.vy, est.vx) - math.atan2(state[3], state[2]))
    return (diff + 180.0) % 360.0 - 180.0


def _track_hostile(acc: _Accum, est: Estimate, obj: TruthObject, state: State) -> bool:
    """Adds the track's errors; returns True if this is an ID swap (the object had another track before)."""
    acc.pos_sq.append(_dist(est, state) ** 2)
    acc.vel_sq.append((est.vx - state[2]) ** 2 + (est.vy - state[3]) ** 2)
    heading = _heading_error_deg(est, state)
    if heading is not None:
        acc.heading_sq.append(heading ** 2)
    previous = acc.last_track.get(obj.id)
    swapped = previous is not None and previous != est.track_id
    acc.id_swaps += swapped
    return swapped


def _log_swap(acc: _Accum, t: float, obj: TruthObject, state: State, est: Estimate, ests: Sequence[Estimate],
              matches, present) -> None:
    old = acc.last_track[obj.id]
    on = matches[old][0].kind if old in matches else None       # what the old track is on now, if anything
    others = [math.hypot(s[0] - state[0], s[1] - state[1]) for o, s in present if o.kind == "hostile" and o.id != obj.id]
    old_est = next((e for e in ests if e.track_id == old), None)
    acc.swap_events.append({"t": t, "object": obj.id, "old": old, "new": est.track_id,
                           "old_to_object_m": _dist(old_est, state) if old_est else None,
                           "new_to_old_m": math.hypot(est.x - old_est.x, est.y - old_est.y) if old_est else None,
                           "old_alive": any(e.track_id == old for e in ests), "old_on": on,
                           "new_seen_before": est.track_id in acc.seen_tracks,
                           "nearest_other_hostile_m": min(others) if others else None})


def _score_step(acc: _Accum, ests: Sequence[Estimate], present, config: ScoreConfig, t: float = 0.0) -> None:
    matches = match_step(ests, present, config.gate_m, acc.last_track, config.continuity_m)
    est_by_id = {e.track_id: e for e in ests}
    track_on = {obj.id: est_by_id[track_id] for track_id, (obj, _) in matches.items()}
    for obj, state in present:
        est = track_on.get(obj.id)
        acc.object_step(obj, est is not None and est.counted)
        if obj.kind == "hostile":
            acc.hostile_samples += 1
            acc.matched_hostile_samples += est is not None
            acc.strict_hostile_samples += est is not None and est.cls == "hostile"
        elif obj.kind == "friendly" and est is not None and est.cls == "hostile":
            acc.strict_flagged_friendlies.add(obj.id)
        if est is not None and obj.kind == "hostile":
            if _track_hostile(acc, est, obj, state):
                _log_swap(acc, t, obj, state, est, ests, matches, present)
        if est is not None:
            acc.last_track[obj.id] = est.track_id
    counted = [e for e in ests if e.counted]
    hostile_xy = [(s[0], s[1]) for o, s in present if o.kind == "hostile"]
    acc.count_err.append(len(counted) - len(hostile_xy))
    acc.strict_count_err.append(sum(e.cls == "hostile" for e in ests) - len(hostile_xy))
    acc.ospa.append(ospa(hostile_xy, [(e.x, e.y) for e in counted], config.ospa_cutoff_m, config.ospa_order))
    acc.false_tracks.append(sum(e.track_id not in matches for e in counted))
    acc.seen_tracks.update(e.track_id for e in ests)
    acc.steps += 1


def _rmse(squares: List[float]) -> Optional[float]:
    return math.sqrt(sum(squares) / len(squares)) if squares else None


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _summary(acc: _Accum) -> RunScore:
    return RunScore(
        steps=acc.steps,
        count_error_mean_abs=_mean([abs(e) for e in acc.count_err]),
        count_error_bias=_mean(acc.count_err),
        pos_rmse_m=_rmse(acc.pos_sq),
        vel_rmse_mps=_rmse(acc.vel_sq),
        heading_rmse_deg=_rmse(acc.heading_sq),
        ospa_m=_mean(acc.ospa),
        id_swaps=acc.id_swaps,
        hostile_detected_frac=acc.share("hostile"),
        friendlies_flagged=len(acc.flagged_friendlies),
        friendly_flag_frac=acc.share("friendly"),
        clutter_flagged_frac=acc.share("clutter"),
        false_tracks_mean=_mean(acc.false_tracks),
        benign_flag_frac=acc.share("benign"),
        hostile_tracked_frac=acc.matched_hostile_samples / acc.hostile_samples if acc.hostile_samples else 0.0,
        matched_hostile_samples=acc.matched_hostile_samples,
        hostile_samples=acc.hostile_samples,
        count_exact_frac=_mean([e == 0 for e in acc.count_err]),
        strict_hostile_count_error_mean_abs=_mean([abs(e) for e in acc.strict_count_err]),
        strict_hostile_count_error_bias=_mean(acc.strict_count_err),
        strict_hostile_count_exact_frac=_mean([e == 0 for e in acc.strict_count_err]),
        strict_hostile_detected_frac=acc.strict_hostile_samples / acc.hostile_samples if acc.hostile_samples else 0.0,
        strict_friendlies_flagged=len(acc.strict_flagged_friendlies),
    )


def _run(truth: dict, frames: Iterable[Tuple[float, Sequence[Estimate]]], config: ScoreConfig) -> _Accum:
    objects, acc = load_truth(truth), _Accum()
    for t, ests in frames:
        if t >= config.warmup_s:
            _score_step(acc, ests, present_at(objects, t), config, t)
    return acc


def score(truth: dict, frames: Iterable[Tuple[float, Sequence[Estimate]]], config: Optional[ScoreConfig] = None) -> RunScore:
    """`frames` are (t, estimates at t) in time order, for example from `scoring.tracks`."""
    return _summary(_run(truth, frames, config or ScoreConfig()))


def swap_log(truth: dict, frames: Iterable[Tuple[float, Sequence[Estimate]]], config: Optional[ScoreConfig] = None) -> List[dict]:
    """Every ID swap of a hostile with its context; `scoring/swaps.py` sorts them into causes."""
    return _run(truth, frames, config or ScoreConfig()).swap_events
