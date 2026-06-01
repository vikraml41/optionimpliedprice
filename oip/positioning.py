"""Open-interest "positioning" layer -- kept SEPARATE from the implied density.

The research base is explicit (docs/RESEARCH.md sec 7): open-interest clusters
are *market positioning / structure* artifacts (often at round strikes), NOT a
probability forecast.  This module summarizes where contracts are stacked so the
tool can show it as a clearly-labelled, distinct layer -- never mixed into the
risk-neutral density colouring.

Quantities (all positioning heuristics, not predictions):
  * total call / put open interest and the put/call OI ratio (PCR);
  * the call wall (largest call OI strike, often read as resistance) and put
    wall (largest put OI strike, often read as support);
  * max pain: the strike that minimizes the total in-the-money payout to option
    holders at expiry -- the classic "pin" heuristic.

Unlike the pricing path, positioning uses the RAW chain (all OI, including
strikes we filter out for pricing), because walls can sit far from the money.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .chain import ExpiryChain


@dataclass
class OIStrike:
    strike: float
    call_oi: int
    put_oi: int

    @property
    def total(self) -> int:
        return self.call_oi + self.put_oi


@dataclass
class Positioning:
    total_call_oi: int
    total_put_oi: int
    pcr_oi: Optional[float]            # put/call OI ratio
    call_wall: Optional[float]        # strike with most call OI (>= spot)
    put_wall: Optional[float]         # strike with most put OI (<= spot)
    max_pain: Optional[float]
    profile: List[OIStrike] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def top_walls(self, n: int = 5) -> List[OIStrike]:
        return sorted(self.profile, key=lambda s: s.total, reverse=True)[:n]


def compute_positioning(chain: ExpiryChain) -> Positioning:
    spot = chain.spot
    by_strike = {}
    for q in chain.calls:
        by_strike.setdefault(q.strike, [0, 0])[0] += max(q.open_interest, 0)
    for q in chain.puts:
        by_strike.setdefault(q.strike, [0, 0])[1] += max(q.open_interest, 0)

    profile = [OIStrike(k, v[0], v[1]) for k, v in sorted(by_strike.items())]
    total_call = sum(s.call_oi for s in profile)
    total_put = sum(s.put_oi for s in profile)
    pcr = (total_put / total_call) if total_call > 0 else None

    notes: List[str] = []
    if total_call + total_put == 0:
        notes.append("no open-interest data available")
        return Positioning(0, 0, None, None, None, None, profile, notes)

    calls_above = [s for s in profile if s.strike >= spot and s.call_oi > 0]
    puts_below = [s for s in profile if s.strike <= spot and s.put_oi > 0]
    call_wall = max(calls_above, key=lambda s: s.call_oi).strike if calls_above else None
    put_wall = max(puts_below, key=lambda s: s.put_oi).strike if puts_below else None

    max_pain = _max_pain(profile)

    if total_call + total_put < 50:
        notes.append("thin open interest -- positioning read is weak")
    return Positioning(total_call, total_put, pcr, call_wall, put_wall,
                       max_pain, profile, notes)


def _max_pain(profile: List[OIStrike]) -> Optional[float]:
    """Strike minimizing total intrinsic payout to holders at expiry.

    At settle price K: calls with strike Kc<K pay (K-Kc); puts with Kp>K pay
    (Kp-K).  Max pain is the K minimizing the summed payout (where the most
    option value expires worthless).  Pure positioning folklore -- reported with
    that caveat.
    """
    strikes = [s.strike for s in profile if s.call_oi + s.put_oi > 0]
    if len(strikes) < 3:
        return None
    best_k, best_pain = None, None
    for K in strikes:
        pain = 0.0
        for s in profile:
            if s.strike < K:
                pain += s.call_oi * (K - s.strike)
            elif s.strike > K:
                pain += s.put_oi * (s.strike - K)
        if best_pain is None or pain < best_pain:
            best_pain, best_k = pain, K
    return best_k
