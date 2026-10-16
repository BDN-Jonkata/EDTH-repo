"""Score the friend/foe estimator on a scenario.

Roles come from `scenario.json` (`friendlies[]` and `targets[]`), never from
`truth.json`. A track is "flagged" when its class is suspicious or hostile.

What matters to an operator:
* friendlies must not be flagged, and hostiles must never be called friendly;
* friendlies should be confirmed quickly and hostiles flagged quickly;
* the investigation requests should go to hostiles, never to friendlies.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from friend_foe.estimator import Classification, EstimatorConfig, FriendFoeEstimator, for_scenario
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
    time_to_friendly_s: Optional[float]       # mean time until a friendly is first called friendly
    friendlies_never_confirmed: int
    time_to_flag_s: Optional[float]           # mean time from a hostile first appearing to its first flag
    hostiles_never_flagged: int
    requests: int
    requests_on_friendlies: int
    infeasible_requests: int                  # weather leaves no module able to identify the object
    mean_standoff_m: Optional[float]


class _Tally:
    def __init__(self, roles: Dict[str, str], warmup_s: float):
        self.roles, self.warmup_s = roles, warmup_s
        self.first_seen: Dict[str, float] = {}
        self.first_friendly: Dict[str, float] = {}
        self.first_flag: Dict[str, float] = {}
        self.friendly_frames = self.friendly_flagged_frames = 0
        self.hostile_frames = self.hostile_friendly_frames = 0
        self.flagged_friendlies = set()

    def add(self, t: float, c: Classification) -> None:
        role, flagged = self.roles[c.track_id], c.cls in FLAGGED
        self.first_seen.setdefault(c.track_id, t)
        if c.cls == "friendly":
            self.first_friendly.setdefault(c.track_id, t)
        if flagged:
            self.first_flag.setdefault(c.track_id, t)
        if role == "friendly" and t >= self.warmup_s:
            self.friendly_frames += 1
            self.friendly_flagged_frames += flagged
            if flagged:
                self.flagged_friendlies.add(c.track_id)
        if role == "hostile":
            self.hostile_frames += 1
            self.hostile_friendly_frames += c.cls == "friendly"

    def ids(self, role: str) -> List[str]:
        return [i for i, r in self.roles.items() if r == role]


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _ratio(a: int, b: int) -> float:
    return a / b if b else 0.0


def _metrics(tally: _Tally, requests: List[dict]) -> RunMetrics:
    friendlies, hostiles = tally.ids("friendly"), tally.ids("hostile")
    confirmed = [tally.first_friendly[i] for i in friendlies if i in tally.first_friendly]
    flagged = [tally.first_flag[i] - tally.first_seen[i] for i in hostiles if i in tally.first_flag]
    return RunMetrics(
        friendly_flag_frac=_ratio(tally.friendly_flagged_frames, tally.friendly_frames),
        friendlies_flagged=len(tally.flagged_friendlies),
        hostile_as_friendly_frac=_ratio(tally.hostile_friendly_frames, tally.hostile_frames),
        time_to_friendly_s=_mean(confirmed),
        friendlies_never_confirmed=len(friendlies) - len(confirmed),
        time_to_flag_s=_mean(flagged),
        hostiles_never_flagged=len([i for i in hostiles if i in tally.first_seen]) - len(flagged),
        requests=len(requests),
        requests_on_friendlies=sum(tally.roles[r["track_id"]] == "friendly" for r in requests),
        infeasible_requests=sum(not r["feasible"] for r in requests),
        mean_standoff_m=_mean([r["standoff_m"] for r in requests]),
    )


def evaluate(
    scenario: dict,
    config: Optional[EstimatorConfig] = None,
    seed: int = 0,
    dt: float = 0.5,
    warmup_s: float = 10.0,
) -> RunMetrics:
    roles = {f["id"]: "friendly" for f in scenario["friendlies"]}
    roles.update({tg["id"]: "hostile" for tg in scenario["targets"]})
    estimator = FriendFoeEstimator(for_scenario(scenario, config))
    trigger = InvestigationTrigger(weather_from_scenario(scenario), modules_in_scenario(scenario))
    tally, requests = _Tally(roles, warmup_s), []
    for t, tracks, beacons in frames_from_scenario(scenario, dt=dt, seed=seed):
        found = estimator.update(t, tracks, beacons)
        for c in found:
            tally.add(t, c)
        requests += trigger.update(t, found, tracks)
    return _metrics(tally, requests)
