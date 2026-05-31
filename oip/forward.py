"""Estimate the option-implied forward and discount factor from put-call parity.

Put-call parity (European):  C(K) - P(K) = DF * (F - K)
                            = (DF * F) - (DF) * K

So regressing the call-minus-put price ``y = C - P`` on strike ``K`` gives a
line with slope ``-DF`` and intercept ``DF*F``.  This recovers BOTH the forward
``F`` and the discount factor ``DF`` directly from the chain -- no need to know
the dividend yield or borrow, which is exactly why this is robust for single
names (their implied dividends/borrow are otherwise hard to pin down).

The forward is the mean of the risk-neutral distribution.  We label it as such
everywhere: it is *cost-of-carry*, NOT a directional forecast (see docs/RESEARCH.md).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .chain import ExpiryChain


@dataclass
class ForwardEstimate:
    forward: float
    discount: float
    n_pairs: int
    r2: float           # regression fit quality (1.0 = perfect parity)
    method: str         # "parity" or "carry_fallback"


def estimate_forward(chain: ExpiryChain, risk_free_rate: float = 0.04,
                     moneyness_band: float = 0.10) -> Optional[ForwardEstimate]:
    """Estimate (forward, discount) via parity regression over near-money pairs.

    ``moneyness_band`` restricts the regression to strikes within +/-band of spot,
    where both legs are liquid and parity is cleanest.
    """
    spot = chain.spot
    lo_k, hi_k = spot * (1 - moneyness_band), spot * (1 + moneyness_band)

    xs, ys = [], []
    for k in chain.strikes():
        if not (lo_k <= k <= hi_k):
            continue
        c, p = chain.call_at(k), chain.put_at(k)
        if c is None or p is None:
            continue
        cm, pm = c.mid, p.mid
        if cm is None or pm is None or cm <= 0 or pm <= 0:
            continue
        xs.append(k)
        ys.append(cm - pm)

    if len(xs) >= 3:
        n = len(xs)
        kbar = sum(xs) / n
        ybar = sum(ys) / n
        sxx = sum((k - kbar) ** 2 for k in xs)
        sxy = sum((k - kbar) * (y - ybar) for k, y in zip(xs, ys))
        if sxx > 1e-12:
            slope = sxy / sxx
            intercept = ybar - slope * kbar
            discount = -slope
            if 0.5 < discount <= 1.0001 and intercept != 0:
                forward = intercept / discount
                # R^2 of the fit -- low R^2 flags stale/async (noisy) quotes.
                ss_tot = sum((y - ybar) ** 2 for y in ys)
                ss_res = sum((y - (intercept + slope * k)) ** 2
                             for k, y in zip(xs, ys))
                r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 1.0
                if 0.5 * spot < forward < 2.0 * spot:
                    return ForwardEstimate(forward, discount, n, r2, "parity")

    # Fallback: cost-of-carry with the supplied risk-free rate, no dividends.
    df = math.exp(-risk_free_rate * chain.ttm_years)
    fwd = spot / df  # = spot * e^{rT}
    return ForwardEstimate(fwd, df, len(xs), 0.0, "carry_fallback")
