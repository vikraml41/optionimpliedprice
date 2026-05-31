"""Risk-neutral density via a mixture of lognormals (Bahra / Melick-Thomas).

Why a lognormal mixture (docs/RESEARCH.md sec 4):
  * non-negative and integrates to 1 *by construction* (no negative-density
    pathology that naive Breeden-Litzenberger second-differencing suffers);
  * the forward (martingale) constraint ``sum w_i F_i = F`` is baked in, so the
    mean of the RND is exactly the option-implied forward;
  * 2-3 components capture skew and bimodality, which is plenty for single names;
  * stable to calibrate from a handful of clean quotes.

We calibrate by matching clean OTM option mids in *price* space, but the inputs
were already smoothed by restricting to liquidity-screened strikes and weighting
by vega.  The fitted object is fully analytic -> smooth density, CDF, and
percentiles without numerical differentiation.

IMPORTANT: this is the RISK-NEUTRAL density.  Its mean is the forward, a
cost-of-carry artifact, NOT a price prediction.  See the module docs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from .blackscholes import (black_call_undiscounted, black_put_undiscounted,
                           norm_cdf)
from .filters import CleanPoint
from .optimize import nelder_mead

SQRT_2PI = math.sqrt(2.0 * math.pi)


@dataclass
class LognormalMixture:
    weights: List[float]      # sum to 1
    mus: List[float]          # log-space means
    sigmas: List[float]       # log-space stdevs (total, i.e. over [0,T])
    forward: float
    discount: float
    rmse: float               # calibration RMSE in price units
    n_components: int

    # -- density / distribution ------------------------------------------------
    def pdf(self, x: float) -> float:
        if x <= 0:
            return 0.0
        total = 0.0
        for w, mu, sig in zip(self.weights, self.mus, self.sigmas):
            z = (math.log(x) - mu) / sig
            total += w * math.exp(-0.5 * z * z) / (x * sig * SQRT_2PI)
        return total

    def cdf(self, x: float) -> float:
        if x <= 0:
            return 0.0
        return sum(w * norm_cdf((math.log(x) - mu) / sig)
                   for w, mu, sig in zip(self.weights, self.mus, self.sigmas))

    def mean(self) -> float:
        return sum(w * math.exp(mu + 0.5 * sig * sig)
                   for w, mu, sig in zip(self.weights, self.mus, self.sigmas))

    def variance(self) -> float:
        m = self.mean()
        second = sum(w * math.exp(2 * mu + 2 * sig * sig)
                     for w, mu, sig in zip(self.weights, self.mus, self.sigmas))
        return max(second - m * m, 0.0)

    def std(self) -> float:
        return math.sqrt(self.variance())

    def quantile(self, p: float, lo: float = 1e-6, hi: float = None) -> float:
        """Invert the CDF for percentile ``p`` in (0,1) via bisection."""
        if hi is None:
            hi = self.forward * 10.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if self.cdf(mid) < p:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-7 * self.forward:
                break
        return 0.5 * (lo + hi)

    # -- pricing (for calibration & diagnostics) -------------------------------
    def model_price(self, strike: float, is_call: bool) -> float:
        und = 0.0
        for w, mu, sig in zip(self.weights, self.mus, self.sigmas):
            fi = math.exp(mu + 0.5 * sig * sig)
            und += w * (black_call_undiscounted(fi, strike, sig) if is_call
                        else black_put_undiscounted(fi, strike, sig))
        return self.discount * und


def _build(params, forward, discount, n_comp):
    """Map unconstrained params -> a valid, forward-matching mixture.

    Parameterization keeps every constraint automatically satisfied:
      * weights via softmax (non-negative, sum to 1);
      * the LAST component's forward F_n is solved from the martingale
        constraint so that sum w_i F_i = F exactly;
      * sigmas via exp() (strictly positive).
    Returns None if the implied F_n is non-positive (rejected with a penalty).
    """
    # weights
    raw_w = params[0:n_comp - 1] + [0.0]
    mx = max(raw_w)
    exps = [math.exp(v - mx) for v in raw_w]
    ssum = sum(exps)
    weights = [e / ssum for e in exps]

    sigmas = [math.exp(params[n_comp - 1 + i]) for i in range(n_comp)]

    # component forwards: first n-1 free (as multiples of F), last solved.
    fk = [forward * math.exp(params[2 * n_comp - 1 + i]) for i in range(n_comp - 1)]
    used = sum(weights[i] * fk[i] for i in range(n_comp - 1))
    if weights[-1] <= 1e-9:
        return None
    f_last = (forward - used) / weights[-1]
    if f_last <= 0:
        return None
    fwds = fk + [f_last]

    mus = [math.log(f) - 0.5 * s * s for f, s in zip(fwds, sigmas)]
    return weights, mus, sigmas


def calibrate_mixture(points: List[CleanPoint], forward: float, discount: float,
                      atm_total_vol: float, n_components: int = 2
                      ) -> Optional[LognormalMixture]:
    """Calibrate a lognormal mixture to clean OTM quotes.

    ``atm_total_vol`` (sigma*sqrt(T)) seeds the components.  Falls back to a
    single lognormal if there are too few points for a mixture.
    """
    pts = [p for p in points if p.price > 0]
    if len(pts) < 3:
        return None
    # With very few points, don't over-fit: cap component count.
    if len(pts) < 6:
        n_components = min(n_components, 1 if len(pts) < 4 else 2)
    n_components = max(1, n_components)

    s0 = max(atm_total_vol, 1e-3)

    if n_components == 1:
        # Single lognormal: only sigma is free (forward fixed = F).
        def obj1(p):
            sig = math.exp(p[0])
            mu = math.log(forward) - 0.5 * sig * sig
            mix = LognormalMixture([1.0], [mu], [sig], forward, discount, 0.0, 1)
            return _sse(mix, pts)
        best = nelder_mead(obj1, [math.log(s0)], step=0.3)
        sig = math.exp(best[0])
        mu = math.log(forward) - 0.5 * sig * sig
        mix = LognormalMixture([1.0], [mu], [sig], forward, discount, 0.0, 1)
        mix.rmse = math.sqrt(_sse(mix, pts) / len(pts))
        return mix

    # Multi-component.  Params: [w_1..w_{n-1}, log s_1..log s_n, logF_1..logF_{n-1}]
    n = n_components
    x0 = ([0.0] * (n - 1)
          + [math.log(s0 * 0.8)] + [math.log(s0 * 1.3)] * (n - 1)
          + [0.02] + [-0.02] * (n - 2 if n > 2 else 0))
    # ensure correct length for the F block (n-1 entries)
    fblock = [0.02 * (1 if i % 2 == 0 else -1) for i in range(n - 1)]
    x0 = [0.0] * (n - 1) + [math.log(s0 * (0.7 + 0.4 * i)) for i in range(n)] + fblock

    big = 1e9

    def obj(p):
        built = _build(p, forward, discount, n)
        if built is None:
            return big
        weights, mus, sigmas = built
        mix = LognormalMixture(weights, mus, sigmas, forward, discount, 0.0, n)
        return _sse(mix, pts)

    best = nelder_mead(obj, x0, step=0.25, max_iter=3000)
    built = _build(best, forward, discount, n)
    if built is None:
        return None
    weights, mus, sigmas = built
    mix = LognormalMixture(weights, mus, sigmas, forward, discount, 0.0, n)
    mix.rmse = math.sqrt(_sse(mix, pts) / len(pts))
    return mix


def _sse(mix: LognormalMixture, pts: List[CleanPoint]) -> float:
    """Vega-weighted sum of squared pricing errors."""
    total = 0.0
    for p in pts:
        model = mix.model_price(p.strike, p.is_call)
        err = (model - p.price)
        total += p.vega_weight * err * err
    return total
