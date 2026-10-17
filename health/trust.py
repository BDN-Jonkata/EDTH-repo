"""Turn a node's trust into the weight of one reading in the tracker.

A reading is weighted by making it noisier: every sigma is divided by the square root of the trust, so trust 1
leaves it alone, 0.25 doubles its sigmas, and trust 0 drops it. The tracker itself is unchanged.
"""

import math
from dataclasses import replace
from typing import Optional

from tracker.measurement import Measurement

MIN_TRUST = 0.05     # below this a reading carries no usable weight


def weighted(m: Measurement, trust: float) -> Optional[Measurement]:
    """The reading with its noise scaled by the trust, or None when there is none to give."""
    if trust < MIN_TRUST:
        return None
    if trust >= 1.0:
        return m
    scale = 1.0 / math.sqrt(trust)
    return replace(m, sigma_bearing=m.sigma_bearing * scale, sigma_range=m.sigma_range * scale,
                   sigma_radial=m.sigma_radial * scale)
