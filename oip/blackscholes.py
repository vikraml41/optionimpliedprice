"""Black-76 / Black-Scholes pricing and implied-vol inversion (stdlib only).

We work in *forward* (Black-76) terms throughout: prices are expressed via the
forward ``F`` and a discount factor ``DF``.  This neutralizes the dividend yield
and rate -- both are summarized by ``(F, DF)``, which we estimate directly from
the chain via put-call parity (see :mod:`oip.forward`).

Using "total volatility" ``s = sigma * sqrt(T)`` keeps the option-math free of
an explicit ``T`` and avoids a class of numerical bugs.
"""
from __future__ import annotations

import math

SQRT_2 = math.sqrt(2.0)
SQRT_2PI = math.sqrt(2.0 * math.pi)


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT_2))


def _d1_d2(forward: float, strike: float, total_vol: float):
    s = total_vol
    d1 = (math.log(forward / strike) + 0.5 * s * s) / s
    return d1, d1 - s


def black_call_undiscounted(forward: float, strike: float, total_vol: float) -> float:
    """Undiscounted Black-76 call = E^Q[(S_T - K)+]; multiply by DF for price."""
    if total_vol <= 0.0:
        return max(forward - strike, 0.0)
    d1, d2 = _d1_d2(forward, strike, total_vol)
    return forward * norm_cdf(d1) - strike * norm_cdf(d2)


def black_put_undiscounted(forward: float, strike: float, total_vol: float) -> float:
    if total_vol <= 0.0:
        return max(strike - forward, 0.0)
    d1, d2 = _d1_d2(forward, strike, total_vol)
    return strike * norm_cdf(-d2) - forward * norm_cdf(-d1)


def black_price(forward, strike, total_vol, discount, is_call):
    und = (black_call_undiscounted(forward, strike, total_vol)
           if is_call else black_put_undiscounted(forward, strike, total_vol))
    return discount * und


def implied_total_vol(price, forward, strike, discount, is_call,
                      lo=1e-6, hi=5.0, tol=1e-8, max_iter=100):
    """Invert a *discounted* option price to total volatility ``s = sigma*sqrt(T)``.

    Returns ``None`` when the price is outside no-arbitrage bounds (so the
    caller can drop the quote rather than fit to garbage).
    """
    if price <= 0.0 or discount <= 0.0:
        return None
    target = price / discount  # undiscounted payoff expectation

    # No-arbitrage bounds on the undiscounted value.
    if is_call:
        intrinsic = max(forward - strike, 0.0)
        upper = forward
    else:
        intrinsic = max(strike - forward, 0.0)
        upper = strike
    # Allow a hair below intrinsic for rounding; reject clearly impossible quotes.
    if target <= intrinsic - 1e-9 or target >= upper - 1e-12:
        if target <= intrinsic + 1e-9:
            return lo  # essentially zero time value
        return None

    f = lambda s: (black_call_undiscounted(forward, strike, s) if is_call
                   else black_put_undiscounted(forward, strike, s)) - target
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < tol:
            return mid
        if flo * fm <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def implied_vol(price, forward, strike, discount, ttm_years, is_call):
    """Annualized Black implied volatility, or ``None`` if not invertible."""
    if ttm_years <= 0:
        return None
    s = implied_total_vol(price, forward, strike, discount, is_call)
    if s is None:
        return None
    return s / math.sqrt(ttm_years)
