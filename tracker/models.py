"""Measurement models: how a bearing, a range and a radial speed relate to the state [x, y, vx, vy],
how well a measurement fits a track (the gate), and how to start a track from the first readings.

Same approach as the mock tracker in ui/viewer/sim.js. A pair of readings gates as a sum of
independent scalar tests, which is an approximation (range and bearing errors are independent here).
"""

import math
from typing import List, Optional, Tuple

from tracker.ekf import Mat, Vec, innovation_variance, scalar_update, wrap_pi
from tracker.measurement import BEARING, RANGE, RANGE_BEARING, Measurement

GATE_1DOF = 6.63            # chi-square, 99 %
GATE_2DOF = 9.21
GATE_3DOF = 11.34
GATE_CHI2 = {1: GATE_1DOF, 2: GATE_2DOF, 3: GATE_3DOF}
MIN_TRIANGULATION_ANGLE = math.radians(15.0)   # rays closer to parallel give a useless fix
MAX_RAY_FACTOR = 1.2        # the crossing must lie within this times each sensor's range
GATE_PARTS = {BEARING: ("bearing",), RANGE: ("range",), RANGE_BEARING: ("range", "bearing", "radial")}

Fix = Tuple[float, float, Mat]   # x, y and the 2x2 covariance as [[a, b], [b, c]]


def scalar_model(state: Vec, m: Measurement, which: str) -> Tuple[float, Vec, float]:
    """(residual, Jacobian row over x y vx vy, variance) of one scalar reading against the state."""
    dx, dy = state[0] - m.pose.x, state[1] - m.pose.y
    r2 = max(dx * dx + dy * dy, 1.0)
    r = math.sqrt(r2)
    if which == "bearing":
        return wrap_pi(m.bearing - math.atan2(dy, dx)), [-dy / r2, dx / r2, 0.0, 0.0], m.sigma_bearing ** 2
    if which == "range":
        return m.range_m - r, [dx / r, dy / r, 0.0, 0.0], m.sigma_range ** 2
    vx, vy = state[2] - m.pose.vx, state[3] - m.pose.vy
    dot = dx * vx + dy * vy   # radial speed relative to the sensor
    h = [vx / r - dx * dot / (r2 * r), vy / r - dy * dot / (r2 * r), dx / r, dy / r]
    return m.radial_mps - dot / r, h, m.sigma_radial ** 2


def gate_parts(m: Measurement) -> tuple:
    """The scalar tests a reading makes: a bearing that also carries a range (an RF reading with a signal-strength range) tests both."""
    if m.kind == BEARING and m.range_m is not None:
        return ("range", "bearing")
    return GATE_PARTS[m.kind]


def gate_cost(state: Vec, cov: Mat, m: Measurement) -> Optional[float]:
    """Lower is a better fit; None when the reading is outside the gate. The log term stops a wide
    track from beating a precise one. A radar reading counts its radial speed too: two targets that pass at
    a few metres are told apart by how fast each is moving along the line of sight, which is the one thing
    their ranges and bearings cannot show."""
    parts = gate_parts(m)
    d2 = log_s = 0.0
    for which in parts:
        residual, h, variance = scalar_model(state, m, which)
        s = innovation_variance(cov, h, variance)
        d2 += residual * residual / s
        log_s += math.log(s)
    return d2 + log_s if d2 <= GATE_CHI2[len(parts)] else None


def apply_measurement(state: Vec, cov: Mat, m: Measurement):
    for which in gate_parts(m):
        residual, h, variance = scalar_model(state, m, which)
        state, cov = scalar_update(state, cov, residual, h, variance)
    return state, cov


def fix_from_range_bearing(m: Measurement) -> Fix:
    c, s = math.cos(m.bearing), math.sin(m.bearing)
    sr, sp = m.sigma_range, m.range_m * m.sigma_bearing   # along and across the line of sight
    cov = [[sr * sr * c * c + sp * sp * s * s, (sr * sr - sp * sp) * c * s],
           [(sr * sr - sp * sp) * c * s, sr * sr * s * s + sp * sp * c * c]]
    return m.pose.x + m.range_m * c, m.pose.y + m.range_m * s, cov


def triangulate(a: Measurement, b: Measurement) -> Optional[Fix]:
    """Where two bearings from different sensors cross, with the uncertainty across each ray."""
    det = math.sin(a.bearing - b.bearing)
    if abs(det) < math.sin(MIN_TRIANGULATION_ANGLE):
        return None
    dx, dy = b.pose.x - a.pose.x, b.pose.y - a.pose.y
    t1 = (-dx * math.sin(b.bearing) + math.cos(b.bearing) * dy) / det
    t2 = (math.cos(a.bearing) * dy - math.sin(a.bearing) * dx) / det
    if t1 <= 0 or t2 <= 0 or t1 > a.max_range_m * MAX_RAY_FACTOR or t2 > b.max_range_m * MAX_RAY_FACTOR:
        return None
    info = _ray_information([(a, t1), (b, t2)])
    return a.pose.x + t1 * math.cos(a.bearing), a.pose.y + t1 * math.sin(a.bearing), _invert(info)


def _ray_information(rays: List[Tuple[Measurement, float]]) -> Mat:
    info = [[0.0, 0.0], [0.0, 0.0]]
    for m, distance in rays:
        nx, ny = -math.sin(m.bearing), math.cos(m.bearing)
        sigma = max(distance * m.sigma_bearing, 1.0)
        for i, u in enumerate((nx, ny)):
            for j, v in enumerate((nx, ny)):
                info[i][j] += u * v / (sigma * sigma)
    return info


def _invert(m: Mat) -> Mat:
    det = m[0][0] * m[1][1] - m[0][1] * m[1][0]
    return [[m[1][1] / det, -m[0][1] / det], [-m[1][0] / det, m[0][0] / det]]
