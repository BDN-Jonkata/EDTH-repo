"""Relative motion cues between observed contacts and verified moving allies.

These are conservative simulation heuristics, not a proof of intent. A collision
prediction alone supports suspicion; hostility also needs responsive pursuit.
No geography, scenario roles, future paths or target IDs enter this module.
"""
import math
from bisect import bisect_left

_TIME = lambda sample: sample['t']


def at(series, t):
    if not series or t < series[0]['t'] - 1e-8 or t > series[-1]['t'] + 1e-8:
        return None
    if len(series) == 1:
        return series[0]
    # The first sample at or after t, never the first one: same result as a hand-written binary search, in C.
    lo = min(max(bisect_left(series, t - 1e-8, key=_TIME), 1), len(series) - 1)
    a, b = series[lo-1], series[lo]
    w = max(0, min(1, (t - a['t']) / (b['t'] - a['t'])))
    return {k: a[k] + w * (b[k] - a[k]) for k in ('x', 'y', 'vx', 'vy', 'sigma')}


def cosine(a, b):
    return (a['vx'] * b['vx'] + a['vy'] * b['vy']) / max(1, math.hypot(a['vx'], a['vy']) * math.hypot(b['vx'], b['vy']))


def turn(a, b):
    return math.atan2(a['vx'] * b['vy'] - a['vy'] * b['vx'], a['vx'] * b['vx'] + a['vy'] * b['vy'])


def maneuvers(series):
    events = []
    for s in series:
        old = at(series, s['t'] - 2)
        if old is None or min(math.hypot(old['vx'], old['vy']), math.hypot(s['vx'], s['vy'])) < 2:
            continue
        angle = turn(old, s)
        # A continuous circle is one maneuver, not a new decision every sample.
        if abs(angle) >= 0.28 and (not events or
                (s['t'] - events[-1][0] >= 3 and angle * events[-1][1] < 0)):
            events.append((s['t'], angle))
    return events


def assess(contact, ally, ally_maneuvers=None):
    """`ally_maneuvers` is `maneuvers(ally)` when the caller has it already (it depends on the ally only)."""
    pairs = [(s, at(ally, s['t'])) for s in contact]
    pairs = [(s, a) for s, a in pairs if a is not None]
    empty = {'response_count': 0, 'closing_m': 0.0, 'intercept_episodes': 0, 'response_lag_s': 0.0}
    if len(pairs) < 2 or pairs[-1][0]['t'] - pairs[0][0]['t'] < 8:
        return 0.0, [], empty, False
    rows = []
    for s, a in pairs:
        dx, dy, vx, vy = s['x'] - a['x'], s['y'] - a['y'], s['vx'] - a['vx'], s['vy'] - a['vy']
        d, sigma = math.hypot(dx, dy), math.hypot(s['sigma'], a['sigma'])
        closing = -(dx * vx + dy * vy) / max(d, 1)
        toward = -(dx * s['vx'] + dy * s['vy']) / max(d, 1)
        tcpa = -(dx * vx + dy * vy) / max(vx * vx + vy * vy, 1)
        miss = math.hypot(dx + vx * tcpa, dy + vy * tcpa)
        resolved = sigma <= 12 and d > 2 * sigma + 5
        moving = math.hypot(a['vx'], a['vy']) >= 2 and math.hypot(s['vx'], s['vy']) >= 2
        hazard = resolved and moving and closing > 2 and toward > 2 and 0 < tcpa <= 12 and miss + 2 * sigma < 25
        converging = resolved and moving and closing > 1.5 and toward > 2 and 0 < tcpa <= 30 and miss - 2 * sigma < 35
        rows.append({'t': s['t'], 'd': d, 'closing': closing, 'toward': toward,
                     'hazard': hazard, 'converging': converging, 'resolved': resolved,
                     'aimed': toward / max(1, math.hypot(s['vx'], s['vy'])) > 0.55})
    span = rows[-1]['t'] - rows[0]['t']
    episodes, run_start, last_end = 0, None, -math.inf
    for r in rows:
        if r['hazard']:
            if run_start is None:
                run_start = r['t']
            if r['t'] - run_start >= 2 and run_start - last_end >= 3:
                episodes += 1
                last_end = math.inf  # count this sustained encounter once
        else:
            if run_start is not None:
                last_end = r['t']
            run_start = None
    current = rows[-1]
    risk, reasons = (1.2, ['sustained_collision_course']) if episodes and current['hazard'] else (0.0, [])
    if episodes >= 2:
        risk, reasons = 2.1, ['repeated_intercept_approaches']
    events = maneuvers(ally) if ally_maneuvers is None else ally_maneuvers
    # Compare the same time interval for every lag. A pursuer must follow our
    # maneuvers later; our investigator following the contact has the reverse lag.
    times = [s['t'] for s, _ in pairs if max(contact[0]['t'], ally[0]['t']) + 3 <= s['t'] <= min(contact[-1]['t'], ally[-1]['t']) - 3]
    fits = []
    ally_at = {t: at(ally, t) for t in times}      # the same ally sample for every lag
    for lag in (-3, -2, -1, 0, 1, 2, 3):
        comparisons = [(at(contact, t + lag), ally_at[t]) for t in times]
        usable = [(s, a) for s, a in comparisons if s and a and min(math.hypot(s['vx'], s['vy']), math.hypot(a['vx'], a['vy'])) >= 2]
        fits.append((sum(1 - cosine(s, a) for s, a in usable) / len(usable) if len(usable) >= 8 else 2.0, lag))
    best_error, lag = min(fits)
    earlier_error = min(error for error, delay in fits if delay <= 0)
    responses = 0
    if lag > 0 and best_error < 0.12 and best_error + 0.015 < earlier_error and best_error < 0.75 * earlier_error:
        for t, angle in events:
            a, s, old = at(ally, t), at(contact, t + lag), at(contact, t + lag - 2)
            if s and old and turn(old, s) * angle > 0.035 and cosine(s, a) > 0.8:
                responses += 1
    closing_m = rows[0]['d'] - current['d']
    pursuing = (span >= 12 and responses >= 2 and
                sum(r['aimed'] and r['resolved'] for r in rows) / len(rows) >= 0.65)
    if pursuing:
        risk = max(risk, 1.8)
        reasons.append('responsive_pursuit')
        closure = closing_m > max(35, 4 * math.hypot(pairs[-1][0]['sigma'], pairs[-1][1]['sigma']))
        sustained_closing = sum(r['closing'] > 1.5 and r['toward'] > 2 for r in rows) / len(rows) >= 0.3
        speed_excess = sum(math.hypot(s['vx'], s['vy']) - math.hypot(a['vx'], a['vy']) for s, a in pairs) / len(pairs) > 1
        if (closure and sustained_closing and speed_excess and current['converging']) or episodes >= 2:
            risk = 3.8
            reasons.append('pursuit_with_intercept_risk')
    features = {'response_count': responses, 'closing_m': closing_m, 'intercept_episodes': episodes, 'response_lag_s': lag if responses else 0.0}
    return risk, sorted(set(reasons)), features, current['converging']
