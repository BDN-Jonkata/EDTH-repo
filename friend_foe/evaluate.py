"""Score the friend/foe estimator on a scenario.

Roles come from `scenario.json` (`friendlies[]`, `targets[]`, `clutter[]`), never from
`truth.json`. A track is "flagged" when its class is suspicious or hostile.

What matters to an operator:
* friendlies must not be flagged, hostiles must never be called friendly, and a hostile
  called peaceful is the worst miss (it is watched and never checked);
* friendlies should be confirmed quickly and hostiles flagged quickly;
* the investigation requests should go to hostiles, not to friendlies or clutter: every
  drone sent at a bird or a vehicle is a drone not covering the village.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from friend_foe.estimator import Classification, EstimatorConfig, FriendFoeEstimator, TrackState, for_scenario
from friend_foe.investigation import InvestigationTrigger
from friend_foe.scenario_adapter import frames_from_scenario
from sensors.quality import modules_in_scenario
from sensors.weather import weather_from_scenario

FLAGGED = ("suspicious", "hostile")


@dataclass
class RunMetrics:
    friendly_flag_frac: float                 # share of friendly track-frames (after warmup) that are flagged
    friendlies_flagged: int                   # friendlies flagged at least once after warmup
    hostile_as_friendly_frac: float           # share of hostile track-frames called friendly
    hostile_as_peaceful_frac: float           # share of hostile track-frames called peaceful
    time_to_friendly_s: Optional[float]       # mean time until a friendly is first called friendly
    friendlies_never_confirmed: int
    time_to_flag_s: Optional[float]           # mean time from a hostile first appearing to its first flag
    hostiles_never_flagged: int
    clutter_flagged_frac: float               # share of clutter track-frames flagged (0 with no clutter)
    clutter_peaceful_frac: float              # share of clutter track-frames correctly called peaceful
    requests: int
    requests_on_friendlies: int
    requests_on_clutter: int
    infeasible_requests: int                  # weather leaves no module able to identify the object
    mean_standoff_m: Optional[float]
    benign_flag_frac: float = 0.0
    benign_peaceful_frac: float = 0.0
    requests_on_benign: int = 0


class _Tally:
    def __init__(self, roles: Dict[str, str], warmup_s: float):
        self.roles, self.warmup_s = roles, warmup_s
        self.frames: Counter = Counter()          # (role, class) -> track-frames counted
        self.first_seen: Dict[str, float] = {}
        self.first_friendly: Dict[str, float] = {}
        self.first_flag: Dict[str, float] = {}
        self.flagged_friendlies = set()

    def add(self, t: float, c: Classification) -> None:
        role, flagged = self.roles[c.track_id], c.cls in FLAGGED
        self.first_seen.setdefault(c.track_id, t)
        if c.cls == "friendly":
            self.first_friendly.setdefault(c.track_id, t)
        if flagged:
            self.first_flag.setdefault(c.track_id, t)
        if role == "friendly" and t < self.warmup_s:
            return                                # friendlies get a settling time; the others count from the start
        self.frames[(role, c.cls)] += 1
        if role == "friendly" and flagged:
            self.flagged_friendlies.add(c.track_id)

    def share(self, role: str, classes) -> float:
        total = sum(n for (r, _), n in self.frames.items() if r == role)
        return sum(self.frames[(role, c)] for c in classes) / total if total else 0.0

    def ids(self, role: str) -> List[str]:
        return [i for i, r in self.roles.items() if r == role]


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _metrics(tally: _Tally, requests: List[dict]) -> RunMetrics:
    friendlies, hostiles = tally.ids("friendly"), tally.ids("hostile")
    confirmed = [tally.first_friendly[i] for i in friendlies if i in tally.first_friendly]
    flagged = [tally.first_flag[i] - tally.first_seen[i] for i in hostiles if i in tally.first_flag]
    asked_about = [tally.roles[r["track_id"]] for r in requests]
    return RunMetrics(
        friendly_flag_frac=tally.share("friendly", FLAGGED),
        friendlies_flagged=len(tally.flagged_friendlies),
        hostile_as_friendly_frac=tally.share("hostile", ("friendly",)),
        hostile_as_peaceful_frac=tally.share("hostile", ("peaceful",)),
        time_to_friendly_s=_mean(confirmed),
        friendlies_never_confirmed=len(friendlies) - len(confirmed),
        time_to_flag_s=_mean(flagged),
        hostiles_never_flagged=len([i for i in hostiles if i in tally.first_seen]) - len(flagged),
        clutter_flagged_frac=tally.share("clutter", FLAGGED),
        clutter_peaceful_frac=tally.share("clutter", ("peaceful",)),
        requests=len(requests),
        requests_on_friendlies=asked_about.count("friendly"),
        requests_on_clutter=asked_about.count("clutter"),
        infeasible_requests=sum(not r["feasible"] for r in requests),
        mean_standoff_m=_mean([r["standoff_m"] for r in requests]),
        benign_flag_frac=tally.share("benign", FLAGGED),
        benign_peaceful_frac=tally.share("benign", ("peaceful",)),
        requests_on_benign=asked_about.count("benign"),
    )


def roles_of(scenario: dict) -> Dict[str, str]:
    roles = {f["id"]: "friendly" for f in scenario["friendlies"]}
    roles.update({tg["id"]: tg.get("role", "hostile") for tg in scenario["targets"]})
    roles.update({c["id"]: "clutter" for c in scenario.get("clutter", [])})
    return roles


def evaluate(
    scenario: dict,
    config: Optional[EstimatorConfig] = None,
    seed: int = 0,
    dt: float = 0.5,
    warmup_s: float = 10.0,
    threat_llr: Optional[Callable[[TrackState], float]] = None,
    automatic: bool = False,
) -> RunMetrics:
    """`threat_llr` is the behaviour hook (see estimator.py); without one, no track is ever hostile or peaceful."""
    if automatic:
        if threat_llr is not None:
            raise ValueError("automatic behaviour and an external threat hook are mutually exclusive")
        from friend_foe.automatic import AutomaticEstimator
        estimator = AutomaticEstimator.for_scenario(scenario, config)
    else:
        estimator = FriendFoeEstimator(for_scenario(scenario, config), threat_llr)
    trigger = InvestigationTrigger(weather_from_scenario(scenario), modules_in_scenario(scenario))
    tally, requests = _Tally(roles_of(scenario), warmup_s), []
    for t, tracks, beacons in frames_from_scenario(scenario, dt=dt, seed=seed):
        found = estimator.update(t, tracks, beacons)
        for c in found:
            tally.add(t, c)
        requests += trigger.update(t, found, tracks)
    return _metrics(tally, requests)
