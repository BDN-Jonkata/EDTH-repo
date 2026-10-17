"""Automatic observed-behaviour pipeline using the team's two-axis estimator."""

from dataclasses import replace

from drone_behavior import BehaviorConfig, BehaviorModel
from friend_foe.estimator import EstimatorConfig, FriendFoeEstimator, for_scenario


class AutomaticEstimator:
    def __init__(self, behavior_config=None, config=None, verified_ids=()):
        config = replace(config or EstimatorConfig(), suspicious_requires_behavior=True)
        policy = replace(behavior_config or BehaviorConfig(), memory_ttl_s=config.memory_ttl_s)
        self.behavior = BehaviorModel(policy, config.threat_tau_s, config.max_dt_s, config.llr_limit)
        self.estimator = FriendFoeEstimator(config, threat_llr=self.behavior)
        for track_id in verified_ids:
            self.estimator.register_identity(track_id)
        self._last_t = None

    @classmethod
    def for_scenario(cls, scenario, config=None):
        # Policy and the own-fleet roster are public inputs. Targets/clutter/roles are never read.
        policy = scenario.get("config", {}).get("drone_behavior", {})
        return cls(BehaviorConfig(**policy), for_scenario(scenario, config),
                   [f["id"] for f in scenario["friendlies"]])

    def update(self, t, tracks, beacons):
        self.behavior.begin(t)
        # A repeated renderer tick must not advance warmup or reuse evidence.
        if self._last_t is not None and t <= self._last_t:
            return list(self._last_result)
        result = self.estimator.update(t, tracks, beacons)
        self.behavior.verified = {c.track_id for c in result if c.cls == "friendly"}
        self._last_t, self._last_result = t, result
        return result

    def explain(self, track_id):
        return self.behavior.explain(track_id)
