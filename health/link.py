"""One node's link, judged from the sequence numbers and the arrival times of what it sends.

Every message a node sends carries `seq`, counting all its messages from 1 (docs/data-formats.md), so a gap in
the numbers is a message lost and a long silence is a link that is down. Two layers look at the same outcomes
(a message arrived, or was missing), and a state comes out of them:

* **Bayesian**: a two-state link, good or bursty, filtered message by message (a hidden Markov model). It gives
  `p_bad`, the probability the link is in the bursty state right now.
* **Frequentist**: the loss rate over the last `window` outcomes with its Wilson confidence interval, and a CUSUM
  change test for a jump of the loss rate from `cusum_p0` to `cusum_p1`. Under the no-change hypothesis a CUSUM
  alarm (threshold `h = ln(200)`) is expected no more often than once in about 200 messages (Lorden's bound).

State, as in the viewer's mock simulation (`ui/viewer/storefwd.js`): `ok`, `degraded` (at least 30 % of the recent
numbers missing, ok again below 20 %), `offline` (nothing heard for 4 s) and `presumed_dead` (15 s; C2 cannot tell
a dead node from a jammed one). The loss rates, transition chances and thresholds are assumptions.

Plain Python only, no imports from the rest of the repository, so the JavaScript port can follow it line by line;
`health/golden.py` writes the shared cases that port is checked against.
"""

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

OK, DEGRADED, OFFLINE, PRESUMED_DEAD = "ok", "degraded", "offline", "presumed_dead"


@dataclass
class HealthConfig:
    loss_good: float = 0.02         # chance a message is lost while the link is good (fitted to common/channel.py's chain)
    loss_bad: float = 0.95          # and while it is in a burst (the channel's bursts lose everything)
    stay_good: float = 0.97         # chance per message to stay in each state
    stay_bad: float = 0.80          # the channel's mean burst is 5 messages
    prior_bad: float = 0.1
    window: int = 40                # outcomes the frequentist layer looks at
    wilson_z: float = 1.96          # 95 % interval
    degraded_loss: float = 0.30     # degraded at this loss rate, or when confidently above it
    recovered_loss: float = 0.20    # ok again below this
    min_outcomes: int = 20          # needed before the loss rate counts
    cusum_p0: float = 0.10          # the loss rate to be shifted away from
    cusum_p1: float = 0.50          # and the shifted rate to detect
    cusum_h: float = math.log(200)  # alarm threshold: about one false alarm in 200 messages
    max_gap: int = 200              # a longer jump in `seq` counts as this many lost messages
    offline_s: float = 4.0
    dead_s: float = 15.0
    half_life_s: float = 10.0       # trust halves every this many seconds of age
    late_s: float = 3.0             # a reading older than this goes to history, not to the live picture
    layers: str = "both"            # "both", "bayes" or "freq": which layer decides `degraded` (for the ablation)


def wilson(missed: int, n: int, z: float) -> Tuple[float, float]:
    """Wilson score interval for the loss rate; (0, 1) with no outcomes."""
    if n == 0:
        return 0.0, 1.0
    p, z2 = missed / n, z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


class LinkHealth:
    def __init__(self, config: HealthConfig, t: float = 0.0):
        self.config = config
        self.last_seq: Optional[int] = None
        self.last_heard = t
        self.p_bad = config.prior_bad
        self.outcomes: Deque[int] = deque(maxlen=config.window)     # 1 = the message was lost
        self.cusum = 0.0
        self.degraded = False

    def observe(self, seq: int, t: float) -> None:
        """A message with number `seq` arrived at `t`; the numbers skipped are messages lost."""
        if self.last_seq is not None:
            if seq <= self.last_seq:
                return                                  # a duplicate or a late resend: nothing new about the link
            for _ in range(min(seq - self.last_seq - 1, self.config.max_gap)):
                self._outcome(1)
        self._outcome(0)
        self.last_seq, self.last_heard = seq, t
        self._update_degraded()

    def _outcome(self, lost: int) -> None:
        cfg = self.config
        bad = self.p_bad * cfg.stay_bad + (1 - self.p_bad) * (1 - cfg.stay_good)
        like_bad = cfg.loss_bad if lost else 1 - cfg.loss_bad
        like_good = cfg.loss_good if lost else 1 - cfg.loss_good
        self.p_bad = bad * like_bad / (bad * like_bad + (1 - bad) * like_good)
        self.outcomes.append(lost)
        step = (math.log(cfg.cusum_p1 / cfg.cusum_p0) if lost else math.log((1 - cfg.cusum_p1) / (1 - cfg.cusum_p0)))
        self.cusum = min(2 * cfg.cusum_h, max(0.0, self.cusum + step))

    @property
    def loss_rate(self) -> float:
        return sum(self.outcomes) / len(self.outcomes) if self.outcomes else 0.0

    @property
    def alarm(self) -> bool:
        return self.cusum > self.config.cusum_h

    def interval(self) -> Tuple[float, float]:
        return wilson(sum(self.outcomes), len(self.outcomes), self.config.wilson_z)

    def _update_degraded(self) -> None:
        cfg = self.config
        if len(self.outcomes) < cfg.min_outcomes:
            return
        bayes_bad, bayes_ok = self.p_bad > 0.5, self.p_bad < 0.2
        freq_bad = self.alarm or self.interval()[0] >= cfg.degraded_loss or self.loss_rate >= cfg.degraded_loss
        freq_ok = not self.alarm and self.loss_rate < cfg.recovered_loss
        use_bayes, use_freq = cfg.layers in ("both", "bayes"), cfg.layers in ("both", "freq")
        if (use_bayes and bayes_bad) or (use_freq and freq_bad):
            self.degraded = True
        elif (bayes_ok or not use_bayes) and (freq_ok or not use_freq):
            self.degraded = False

    def state(self, t: float) -> str:
        silent = t - self.last_heard
        if silent >= self.config.dead_s:
            return PRESUMED_DEAD
        if silent >= self.config.offline_s:
            return OFFLINE
        return DEGRADED if self.degraded else OK
