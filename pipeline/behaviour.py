"""The drone-behaviour module (`drone_behavior/`) as the pipeline uses it.

On the pipeline's real tracks the module's motion rules cannot tell a hostile from a bird or a car: a hostile
that flies a steady straight path looks like safe transit (strong evidence for `peaceful`), and pursuit
evidence never appears because the Python scenarios' hostiles do not react to our drones (only the viewer's
JavaScript simulation has actors that do). Measured on 8 tuning seeds at 15 % loss, switching it on made
34 to 47 % of the hostile tracks `peaceful` and none `hostile`, and cost 27 points of hostiles counted.

So by default the pipeline runs it in a safe mode: motion alone never makes a track `peaceful` (the estimator's
`peaceful_min_updates` is set out of reach), which leaves what the module is good at (identity from beacons,
suspicion and hostility from encounter evidence) and stops it clearing real hostiles. This is a setting of the
estimator, not a change of the module; `motion_peaceful=True` gives the module's own behaviour.
"""

from friend_foe.automatic import AutomaticEstimator
from friend_foe.estimator import EstimatorConfig

NEVER = 10 ** 9      # updates a track would need before motion alone could call it peaceful


def automatic_estimator(scenario: dict, motion_peaceful: bool = False) -> AutomaticEstimator:
    config = None if motion_peaceful else EstimatorConfig(peaceful_min_updates=NEVER)
    return AutomaticEstimator.for_scenario(scenario, config)
