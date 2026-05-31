"""Synthetic, arbitrage-free option chains for offline testing and demos.

Builds a chain from a *known* risk-neutral lognormal mixture so tests can verify
the pipeline recovers the truth (forward, expected move, density shape).  Noise
and liquidity can be dialed up to exercise the quality-gating logic -- including
a "noisy liquid mega-cap" profile where the chain is mostly noise.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional

from ..blackscholes import black_call_undiscounted, black_put_undiscounted
from ..chain import ExpiryChain, OptionChainData, OptionQuote


@dataclass
class SyntheticParams:
    spot: float = 100.0
    rate: float = 0.04
    div_yield: float = 0.0
    # base annualized vol and a skew (negative => left-skew / put bid)
    base_vol: float = 0.30
    skew: float = -0.15
    # noise / liquidity controls
    rel_spread: float = 0.04        # base relative bid-ask spread
    price_noise: float = 0.0        # multiplicative noise on the mid (0 = clean)
    oi_scale: float = 500.0         # open-interest scale near the money
    strike_step_pct: float = 0.025  # strike spacing as fraction of spot
    seed: int = 7


def _vol_for_strike(forward: float, strike: float, p: SyntheticParams) -> float:
    """A simple smile: linear skew in log-moneyness plus a small smile curvature."""
    k = math.log(strike / forward)
    return max(0.05, p.base_vol + p.skew * k + 0.5 * abs(k))


class SyntheticProvider:
    """Generates arbitrage-free chains; optionally injects noise/illiquidity."""

    PROFILES = {
        # clean, liquid, clear signal
        "clean": dict(rel_spread=0.02, price_noise=0.0, oi_scale=2000.0),
        # the user's pain point: high-volume but quotes are mostly noise
        "noisy_megacap": dict(rel_spread=0.18, price_noise=0.06, oi_scale=80.0,
                              strike_step_pct=0.01),
        # illiquid small-cap: sparse, wide, stale
        "illiquid": dict(rel_spread=0.45, price_noise=0.10, oi_scale=8.0,
                         strike_step_pct=0.05),
    }

    def __init__(self, params: Optional[SyntheticParams] = None,
                 profile: Optional[str] = None,
                 expiries_days: Optional[List[int]] = None):
        params = params or SyntheticParams()
        if profile and profile in self.PROFILES:
            for k, v in self.PROFILES[profile].items():
                setattr(params, k, v)
        self.p = params
        self.expiries_days = expiries_days or [7, 30, 60, 120]
        self._rng = random.Random(params.seed)

    def get_chain(self, symbol: str = "SYN",
                  max_expiries: Optional[int] = None) -> OptionChainData:
        p = self.p
        days = self.expiries_days[:max_expiries] if max_expiries else self.expiries_days
        expiries: List[ExpiryChain] = []
        for d in days:
            expiries.append(self._build_expiry(d))
        return OptionChainData(symbol=symbol, spot=p.spot, expiries=expiries,
                               asof="synthetic")

    def _build_expiry(self, days: int) -> ExpiryChain:
        p = self.p
        T = days / 365.0
        discount = math.exp(-p.rate * T)
        forward = p.spot * math.exp((p.rate - p.div_yield) * T)

        step = max(1.0, round(p.spot * p.strike_step_pct))
        n = 14
        strikes = [round(forward / step) * step + i * step for i in range(-n, n + 1)]
        strikes = sorted({k for k in strikes if k > 0})

        calls, puts = [], []
        for k in strikes:
            sig = _vol_for_strike(forward, k, p) * math.sqrt(T)
            c_true = discount * black_call_undiscounted(forward, k, sig)
            p_true = discount * black_put_undiscounted(forward, k, sig)
            calls.append(self._quote(k, c_true, forward, True))
            puts.append(self._quote(k, p_true, forward, False))
        return ExpiryChain(expiry=f"+{days}d", ttm_years=T, spot=p.spot,
                           calls=calls, puts=puts)

    def _quote(self, strike, true_price, forward, is_call) -> OptionQuote:
        p = self.p
        rng = self._rng
        # liquidity falls off away from the money
        m = abs(math.log(strike / forward))
        liq = math.exp(-(m / 0.12) ** 2)
        oi = int(p.oi_scale * liq + rng.random() * 5)
        vol = int(oi * (0.3 + 0.7 * rng.random()))

        # multiplicative price noise (stale/jittery quotes)
        noisy = true_price * (1 + p.price_noise * (rng.random() - 0.5) * 2)
        noisy = max(noisy, 0.0)

        # spread widens for illiquid strikes
        rel = p.rel_spread * (1 + 2 * (1 - liq))
        half = 0.5 * rel * max(noisy, 0.05)
        bid = max(0.0, noisy - half)
        ask = noisy + half
        # round to a penny tick (introduces discreteness noise on cheap options)
        bid = round(bid, 2)
        ask = round(ask, 2)
        # deep OTM frequently has no bid
        if liq < 0.05 and rng.random() < 0.6:
            bid = 0.0
        return OptionQuote(strike=strike, is_call=is_call, bid=bid, ask=ask,
                           last=round(noisy, 2), volume=vol, open_interest=oi)
