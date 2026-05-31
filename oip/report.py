"""Human-readable CLI report for a SymbolAnalysis."""
from __future__ import annotations

from .analyze import ExpiryAnalysis, SymbolAnalysis

_BANNER = {
    "high": "HIGH confidence - clear signal",
    "medium": "MEDIUM confidence - indicative",
    "low": "LOW confidence - chain mostly NOISE",
}


def format_report(a: SymbolAnalysis) -> str:
    L = []
    L.append("=" * 72)
    L.append(f" {a.symbol}   spot={a.spot:.2f}   as of {a.asof}")
    L.append("=" * 72)
    L.append("")
    L.append("Reminder: options price RISK (size of move, skew), not DIRECTION.")
    L.append("The implied forward is cost-of-carry, not a target. RND is")
    L.append("risk-neutral, not a real-world probability forecast.")
    L.append("")

    for ex in a.expiries:
        L.append("-" * 72)
        L.append(f"Expiry {ex.expiry}  (~{ex.days:.0f}d)   "
                 f"[{_BANNER.get(ex.quality.label, ex.quality.label)}]  "
                 f"quality={ex.quality.overall:.2f}")
        fwd = ex.forward
        L.append(f"  implied forward : {fwd.forward:.2f}   "
                 f"({fwd.method}, R^2={fwd.r2:.2f}, {fwd.n_pairs} pairs)")
        if ex.expected_move:
            em = ex.expected_move
            L.append(f"  expected move   : +/-{em.move_1sigma:.2f}  "
                     f"(+/-{em.move_1sigma_pct*100:.1f}%, 1 sigma ~68%)  "
                     f"[{em.low_1sigma:.2f} .. {em.high_1sigma:.2f}]")
            L.append(f"  ATM implied vol : {em.sigma_atm*100:.1f}%   "
                     f"(straddle x-check {em.straddle_implied:.2f}; "
                     f"source={em.source})")
        if ex.skew_25d is not None:
            tilt = ("put-skew (downside fear)" if ex.skew_25d > 0.005
                    else "call-skew" if ex.skew_25d < -0.005 else "flat")
            L.append(f"  IV skew (~+/-10%): {ex.skew_25d*100:+.1f} vol pts  ({tilt})")

        if ex.rnd is not None and ex.rnd_trustworthy:
            r = ex.rnd
            ps = [0.05, 0.25, 0.50, 0.75, 0.95]
            qs = [r.quantile(p) for p in ps]
            L.append("  implied distribution percentiles (risk-neutral):")
            L.append("    " + "  ".join(f"P{int(p*100):02d}={q:.1f}"
                                        for p, q in zip(ps, qs)))
            L.append(f"    components={r.n_components}  std={r.std():.2f}  "
                     f"fit_rmse={r.rmse:.3f}")
        elif ex.quality.label != "low":
            L.append("  implied distribution: indicative only (see notes)")
        else:
            L.append("  implied distribution: SUPPRESSED (chain too noisy)")

        for note in ex.quality.notes:
            L.append(f"    ! {note}")
        for note in ex.notes:
            if note not in ex.quality.notes:
                L.append(f"    - {note}")
    L.append("-" * 72)
    return "\n".join(L)
