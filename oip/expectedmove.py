"""Expected-move calculations -- the most robustly extractable quantity.

Primary (rigorous): 1-sigma move = S * sigma_ATM * sqrt(T)  (in price units),
which contains the realized move ~68% of the time under a lognormal approx.

We deliberately do NOT use the folklore "expected move = 0.85 * straddle":
the ATM straddle price equals the *mean absolute deviation*
  E|S_T - F| = S * sigma * sqrt(T) * sqrt(2/pi) ~= 0.8 * S*sigma*sqrt(T),
so the 1-sigma move is ~1.25 * straddle, not 0.85 * straddle.  We expose the
straddle only as a cross-check.  (docs/RESEARCH.md sec 6.)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .filters import CleanPoint

SQRT_2_OVER_PI = math.sqrt(2.0 / math.pi)


@dataclass
class ExpectedMove:
    sigma_atm: float          # annualized ATM implied vol
    move_1sigma: float        # absolute price move (1 std dev)
    move_1sigma_pct: float
    low_1sigma: float         # forward - move
    high_1sigma: float        # forward + move
    straddle_implied: float   # ATM straddle price implied by sigma_atm (cross-check)
    source: str               # "rnd_std" or "atm_iv"


def atm_iv_from_points(points, forward) -> Optional[float]:
    """Interpolate the ATM implied vol from the cleaned smile at K = forward."""
    if not points:
        return None
    below = [p for p in points if p.strike <= forward]
    above = [p for p in points if p.strike >= forward]
    if below and above:
        lo = max(below, key=lambda p: p.strike)
        hi = min(above, key=lambda p: p.strike)
        if hi.strike == lo.strike:
            return lo.iv
        w = (forward - lo.strike) / (hi.strike - lo.strike)
        return lo.iv + w * (hi.iv - lo.iv)
    # forward outside the cleaned range: take the nearest strike's IV
    nearest = min(points, key=lambda p: abs(p.strike - forward))
    return nearest.iv


def expected_move(forward: float, ttm_years: float, sigma_atm: float,
                  rnd_std: Optional[float] = None) -> ExpectedMove:
    """Compute the expected move.

    Prefers the RND standard deviation when a trustworthy density was fit
    (it accounts for skew/fat tails); otherwise uses the closed-form ATM-IV move.
    """
    iv_move = forward * sigma_atm * math.sqrt(ttm_years)
    if rnd_std is not None and rnd_std > 0:
        move = rnd_std
        source = "rnd_std"
    else:
        move = iv_move
        source = "atm_iv"
    straddle = forward * sigma_atm * math.sqrt(ttm_years) * SQRT_2_OVER_PI
    return ExpectedMove(
        sigma_atm=sigma_atm,
        move_1sigma=move,
        move_1sigma_pct=move / forward,
        low_1sigma=forward - move,
        high_1sigma=forward + move,
        straddle_implied=straddle,
        source=source,
    )
