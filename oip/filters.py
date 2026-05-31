"""Chain cleaning and a signal-to-noise quality score.

Implements the concrete screens from the research base (docs/RESEARCH.md sec 3 & 5):
mid-quotes only, drop zero-bid / penny / zero-OI, spread caps, OTM-only,
moneyness band, the CBOE two-consecutive-zero-bid tail cutoff, plus a 0-1
quality score that the rest of the tool *gates* its claims on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .blackscholes import implied_vol
from .chain import ExpiryChain, OptionQuote


@dataclass
class FilterConfig:
    min_open_interest: int = 0       # drop OI strictly below this (0 = drop OI==0)
    drop_zero_oi: bool = True
    min_price: float = 0.10          # penny-option floor on the mid
    max_rel_spread: float = 0.60     # drop quotes with spread/mid above this
    max_abs_spread: Optional[float] = None
    moneyness_band: float = 0.30     # keep strikes within +/- this fraction of forward
    require_two_sided: bool = True   # require bid>0 and ask>0
    two_consecutive_zero_bid_cutoff: bool = True


@dataclass
class CleanPoint:
    """An OTM strike that survived cleaning, carried as (strike, price, iv, weight)."""
    strike: float
    is_call: bool
    price: float
    iv: float
    vega_weight: float
    open_interest: int
    volume: int
    rel_spread: float


@dataclass
class QualityScore:
    overall: float                       # 0-1 composite
    coverage: float
    spread_quality: float
    liquidity: float
    arbitrage_cleanliness: float
    parity_r2: float
    n_clean: int
    label: str                           # "high" | "medium" | "low"
    notes: List[str] = field(default_factory=list)


def _walk_wing(quotes_by_strike: Dict[float, OptionQuote], strikes, cfg: FilterConfig):
    """Apply the CBOE two-consecutive-zero-bid cutoff while walking out a wing."""
    kept = []
    zero_run = 0
    for k in strikes:
        q = quotes_by_strike.get(k)
        bid = q.bid if q else None
        if bid is None or bid <= 0:
            zero_run += 1
            if cfg.two_consecutive_zero_bid_cutoff and zero_run >= 2:
                break
            continue
        zero_run = 0
        kept.append(k)
    return kept


def clean_expiry(chain: ExpiryChain, forward: float, discount: float,
                 cfg: FilterConfig):
    """Return (clean_points, raw_otm_count, arb_violations).

    Uses OTM puts below the forward and OTM calls above it (the liquid,
    non-intrinsic side), then runs liquidity + no-arbitrage screens.
    """
    calls = {q.strike: q for q in chain.calls}
    puts = {q.strike: q for q in chain.puts}
    all_strikes = chain.strikes()

    lo_k = forward * (1 - cfg.moneyness_band)
    hi_k = forward * (1 + cfg.moneyness_band)

    # OTM calls: strikes >= forward, walking UP. OTM puts: strikes <= forward, walking DOWN.
    up = [k for k in all_strikes if forward <= k <= hi_k]
    down = [k for k in reversed(all_strikes) if lo_k <= k <= forward]

    keep_calls = set(_walk_wing(calls, up, cfg))
    keep_puts = set(_walk_wing(puts, down, cfg))

    raw_otm = len(up) + len(down)
    points: List[CleanPoint] = []

    def consider(q: OptionQuote, is_call: bool):
        if q is None:
            return
        if cfg.require_two_sided and not (q.bid and q.ask and q.bid > 0 and q.ask > 0):
            return
        if cfg.drop_zero_oi and q.open_interest <= 0:
            return
        if q.open_interest < cfg.min_open_interest:
            return
        m = q.mid
        if m is None or m < cfg.min_price:
            return
        rs = q.rel_spread
        if rs is not None and rs > cfg.max_rel_spread:
            return
        if cfg.max_abs_spread is not None and q.spread is not None \
                and q.spread > cfg.max_abs_spread:
            return
        iv = implied_vol(m, forward, q.strike, discount, chain.ttm_years, is_call)
        if iv is None or iv <= 0:
            return
        # Vega weight: down-weight low-information deep-OTM (Bliss-Panigirtzoglou).
        from .blackscholes import norm_pdf
        import math as _m
        s = iv * _m.sqrt(chain.ttm_years)
        d1 = (_m.log(forward / q.strike) + 0.5 * s * s) / s
        vega = forward * norm_pdf(d1) * _m.sqrt(chain.ttm_years)
        points.append(CleanPoint(q.strike, is_call, m, iv, max(vega, 1e-8),
                                 q.open_interest, q.volume,
                                 rs if rs is not None else 0.0))

    for k in keep_calls:
        consider(calls.get(k), True)
    for k in keep_puts:
        consider(puts.get(k), False)

    points.sort(key=lambda p: p.strike)
    arb_violations = _count_convexity_violations(points, forward, chain.ttm_years)
    return points, raw_otm, arb_violations


def _count_convexity_violations(points: List[CleanPoint], forward: float,
                                ttm_years: float) -> int:
    """Count butterfly/convexity violations across strikes.

    Every clean point's IV maps to one smile, so we reconstruct a common
    undiscounted call value ``C(K)`` at each strike from its own IV and check
    discrete convexity ``C(K-) - 2C(K) + C(K+) >= 0`` (== non-negative density).
    A negative second difference flags a stale/arbitrageable quote.
    """
    if len(points) < 3:
        return 0
    import math as _m
    from .blackscholes import black_call_undiscounted
    cs = []
    for p in points:
        s = p.iv * _m.sqrt(ttm_years)
        cs.append((p.strike, black_call_undiscounted(forward, p.strike, s)))
    viol = 0
    for i in range(1, len(cs) - 1):
        (k0, c0), (k1, c1), (k2, c2) = cs[i - 1], cs[i], cs[i + 1]
        # second difference normalized by strike spacing
        d2 = (c2 - c1) / (k2 - k1) - (c1 - c0) / (k1 - k0)
        if d2 < -1e-6:
            viol += 1
    return viol


def compute_quality(points: List[CleanPoint], raw_otm: int, parity_r2: float,
                    arb_violations: int) -> QualityScore:
    notes: List[str] = []
    n = len(points)

    coverage = (n / raw_otm) if raw_otm > 0 else 0.0
    coverage = min(coverage, 1.0)

    if points:
        med_rs = sorted(p.rel_spread for p in points)[n // 2]
    else:
        med_rs = 1.0
    # spread quality: 1 at 0% spread, ~0 by 50% spread
    spread_quality = max(0.0, 1.0 - med_rs / 0.5)

    if points:
        oi_total = sum(p.open_interest for p in points)
        # saturating: lots of OI -> ~1
        liquidity = min(1.0, oi_total / (50.0 * max(n, 1)))
    else:
        liquidity = 0.0

    arb_clean = 1.0 if n == 0 else max(0.0, 1.0 - arb_violations / n)

    # Composite weights (sum to 1).
    overall = (0.30 * coverage + 0.25 * spread_quality + 0.20 * liquidity
               + 0.15 * arb_clean + 0.10 * max(0.0, parity_r2))

    if n < 5:
        notes.append(f"only {n} clean strikes after filtering")
        overall = min(overall, 0.45)
    if med_rs > 0.30:
        notes.append(f"wide median spread ({med_rs:.0%} of mid)")
    if parity_r2 < 0.9:
        notes.append(f"put-call parity fit weak (R^2={parity_r2:.2f}) -> stale/async quotes")

    if overall >= 0.66 and n >= 6:
        label = "high"
    elif overall >= 0.40 and n >= 4:
        label = "medium"
    else:
        label = "low"
        notes.append("chain too illiquid/noisy for a reliable implied distribution")

    return QualityScore(overall, coverage, spread_quality, liquidity, arb_clean,
                        parity_r2, n, label, notes)
