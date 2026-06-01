"""Orchestration: turn a raw chain into gated, confidence-aware analysis.

Per expiry we: estimate the implied forward/discount from parity, clean the
chain, score signal-to-noise, and -- only when the score permits -- fit the
risk-neutral density.  The quality label decides how much we are willing to say:

    high   -> forward, expected move, RND percentiles, density (heatmap)
    medium -> forward, expected move, IV skew; RND marked indicative
    low    -> expected move band only, with a "mostly noise" banner
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from .chain import ExpiryChain, OptionChainData
from .expectedmove import ExpectedMove, atm_iv_from_points, expected_move
from .filters import (CleanPoint, FilterConfig, QualityScore, clean_expiry,
                      compute_quality)
from .forward import ForwardEstimate, estimate_forward
from .positioning import Positioning, compute_positioning
from .rnd import LognormalMixture, calibrate_mixture


@dataclass
class ExpiryAnalysis:
    expiry: str
    ttm_years: float
    spot: float
    forward: ForwardEstimate
    quality: QualityScore
    points: List[CleanPoint]
    expected_move: Optional[ExpectedMove] = None
    rnd: Optional[LognormalMixture] = None
    rnd_trustworthy: bool = False
    skew_25d: Optional[float] = None      # IV(25d put) - IV(25d call), a skew gauge
    positioning: Optional[Positioning] = None  # OI layer (NOT a forecast)
    notes: List[str] = field(default_factory=list)

    @property
    def days(self) -> float:
        return self.ttm_years * 365.0


@dataclass
class SymbolAnalysis:
    symbol: str
    spot: float
    asof: Optional[str]
    expiries: List[ExpiryAnalysis] = field(default_factory=list)


def analyze_expiry(chain: ExpiryChain, cfg: FilterConfig,
                   risk_free_rate: float = 0.04,
                   n_components: int = 2) -> ExpiryAnalysis:
    fwd = estimate_forward(chain, risk_free_rate, moneyness_band=0.10)
    points, raw_otm, arb_viol = clean_expiry(chain, fwd.forward, fwd.discount, cfg)
    quality = compute_quality(points, raw_otm, fwd.r2, arb_viol)

    res = ExpiryAnalysis(expiry=chain.expiry, ttm_years=chain.ttm_years,
                         spot=chain.spot, forward=fwd, quality=quality,
                         points=points)
    res.notes.extend(quality.notes)

    sigma_atm = atm_iv_from_points(points, fwd.forward)

    # Risk-neutral density: only attempt when not "low" quality.
    rnd = None
    if quality.label in ("high", "medium") and sigma_atm:
        rnd = calibrate_mixture(points, fwd.forward, fwd.discount,
                                atm_total_vol=sigma_atm * math.sqrt(chain.ttm_years),
                                n_components=n_components)
        if rnd is not None:
            # Trust the density only if it priced the chain well and is admissible.
            ref = max(fwd.forward * 0.01, 0.05)
            trustworthy = (quality.label == "high" and rnd.rmse < ref
                           and abs(rnd.mean() - fwd.forward) < 0.01 * fwd.forward)
            res.rnd = rnd
            res.rnd_trustworthy = bool(trustworthy)
            if not trustworthy:
                res.notes.append("RND fit indicative only (elevated pricing error)")

    # Expected move: prefer a trustworthy RND's std, else closed-form ATM-IV move.
    if sigma_atm:
        rnd_std = res.rnd.std() if (res.rnd and res.rnd_trustworthy) else None
        res.expected_move = expected_move(fwd.forward, chain.ttm_years,
                                          sigma_atm, rnd_std)

    res.skew_25d = _skew_25d(points, fwd.forward, chain.ttm_years)
    # Positioning is computed from the RAW chain, independent of the pricing
    # filters, and is reported as a separate layer (not mixed into the density).
    res.positioning = compute_positioning(chain)
    return res


def analyze_symbol(data: OptionChainData, cfg: Optional[FilterConfig] = None,
                   risk_free_rate: float = 0.04,
                   n_components: int = 2,
                   max_expiries: Optional[int] = None) -> SymbolAnalysis:
    cfg = cfg or FilterConfig()
    out = SymbolAnalysis(symbol=data.symbol, spot=data.spot, asof=data.asof)
    expiries = data.expiries[:max_expiries] if max_expiries else data.expiries
    for ch in expiries:
        try:
            out.expiries.append(
                analyze_expiry(ch, cfg, risk_free_rate, n_components))
        except Exception as e:  # one bad expiry shouldn't sink the whole report
            out.expiries.append(ExpiryAnalysis(
                expiry=ch.expiry, ttm_years=ch.ttm_years, spot=ch.spot,
                forward=ForwardEstimate(ch.spot, 1.0, 0, 0.0, "error"),
                quality=QualityScore(0, 0, 0, 0, 0, 0, 0, "low",
                                     [f"analysis failed: {e}"]),
                points=[]))
    return out


def _skew_25d(points: List[CleanPoint], forward: float, ttm: float) -> Optional[float]:
    """A simple 25-delta-ish skew: put IV ~10% OTM minus call IV ~10% OTM."""
    puts = [p for p in points if not p.is_call and p.strike < forward]
    calls = [p for p in points if p.is_call and p.strike > forward]
    if not puts or not calls:
        return None
    target_lo = forward * 0.90
    target_hi = forward * 1.10
    put = min(puts, key=lambda p: abs(p.strike - target_lo))
    call = min(calls, key=lambda p: abs(p.strike - target_hi))
    return put.iv - call.iv
