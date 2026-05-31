"""End-to-end sanity tests runnable with the stdlib only (no numpy/scipy)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oip.analyze import analyze_symbol
from oip.blackscholes import (black_price, implied_vol, norm_cdf)
from oip.filters import FilterConfig
from oip.providers.synthetic import SyntheticProvider, SyntheticParams


def approx(a, b, tol):
    return abs(a - b) <= tol


def test_blackscholes_roundtrip():
    F, K, DF, T = 100.0, 95.0, 0.99, 0.25
    sigma = 0.3
    s = sigma * math.sqrt(T)
    price = black_price(F, K, s, DF, True)
    iv = implied_vol(price, F, K, DF, T, True)
    assert approx(iv, sigma, 1e-4), f"iv roundtrip failed: {iv} vs {sigma}"
    # put-call parity on undiscounted values
    c = black_price(F, K, s, DF, True)
    p = black_price(F, K, s, DF, False)
    assert approx(c - p, DF * (F - K), 1e-8)
    print("  black-scholes roundtrip + parity OK")


def test_norm_cdf():
    assert approx(norm_cdf(0), 0.5, 1e-12)
    assert approx(norm_cdf(1.96), 0.975, 1e-3)
    print("  norm_cdf OK")


def test_forward_recovery_clean():
    prov = SyntheticProvider(SyntheticParams(spot=100.0, rate=0.04, base_vol=0.30),
                             profile="clean")
    data = prov.get_chain("SYN")
    res = analyze_symbol(data)
    for ex in res.expiries:
        true_fwd = 100.0 * math.exp(0.04 * ex.ttm_years)
        assert ex.forward.method == "parity", ex.forward.method
        assert approx(ex.forward.forward, true_fwd, 0.5), \
            f"forward off: {ex.forward.forward} vs {true_fwd}"
    print("  forward recovery (parity) OK")


def test_expected_move_matches_iv():
    prov = SyntheticProvider(SyntheticParams(spot=100.0, base_vol=0.30, skew=0.0),
                             profile="clean")
    data = prov.get_chain("SYN")
    res = analyze_symbol(data)
    ex = next(e for e in res.expiries if abs(e.days - 30) < 1)
    em = ex.expected_move
    assert em is not None
    # ATM IV should recover ~0.30; 1-sigma move ~ F*0.30*sqrt(T)
    expected = ex.forward.forward * 0.30 * math.sqrt(ex.ttm_years)
    assert approx(em.move_1sigma, expected, 0.15 * expected), \
        f"expected move {em.move_1sigma} vs {expected}"
    # straddle ~ 0.8 * 1-sigma move; the 0.85x folklore would be wrong
    assert em.straddle_implied < em.move_1sigma
    print(f"  expected move OK (1s={em.move_1sigma:.2f}, straddle={em.straddle_implied:.2f})")


def test_rnd_admissible_and_centered():
    prov = SyntheticProvider(SyntheticParams(spot=100.0, base_vol=0.30, skew=-0.15),
                             profile="clean")
    data = prov.get_chain("SYN")
    res = analyze_symbol(data, n_components=2)
    ex = next(e for e in res.expiries if abs(e.days - 60) < 1)
    assert ex.rnd is not None, "expected an RND on a clean chain"
    rnd = ex.rnd
    # mean equals the forward (martingale constraint)
    assert approx(rnd.mean(), ex.forward.forward, 0.01 * ex.forward.forward)
    # density integrates to ~1 (trapezoid on a fine grid)
    lo, hi, n = 1.0, ex.forward.forward * 3, 4000
    h = (hi - lo) / n
    area = 0.5 * (rnd.pdf(lo) + rnd.pdf(hi)) + sum(rnd.pdf(lo + i * h) for i in range(1, n))
    area *= h
    assert approx(area, 1.0, 0.02), f"density integral {area}"
    # non-negativity
    assert all(rnd.pdf(lo + i * h) >= 0 for i in range(0, n + 1, 50))
    # CDF monotone & percentiles ordered
    p10, p50, p90 = rnd.quantile(0.1), rnd.quantile(0.5), rnd.quantile(0.9)
    assert p10 < p50 < p90
    print(f"  RND admissible: mean={rnd.mean():.2f} fwd={ex.forward.forward:.2f} "
          f"area={area:.3f} P10/50/90={p10:.1f}/{p50:.1f}/{p90:.1f} rmse={rnd.rmse:.4f}")


def test_noisy_megacap_is_gated_down():
    """The user's pain point: a high-volume chain that is mostly noise."""
    clean = analyze_symbol(SyntheticProvider(profile="clean").get_chain("CLN"))
    noisy = analyze_symbol(SyntheticProvider(profile="noisy_megacap").get_chain("NOZ"))
    illiq = analyze_symbol(SyntheticProvider(profile="illiquid").get_chain("ILQ"))

    def avg_q(r):
        return sum(e.quality.overall for e in r.expiries) / len(r.expiries)

    qc, qn, qi = avg_q(clean), avg_q(noisy), avg_q(illiq)
    print(f"  quality: clean={qc:.2f}  noisy_megacap={qn:.2f}  illiquid={qi:.2f}")
    assert qc > qn > qi, f"gating ordering wrong: {qc},{qn},{qi}"
    # illiquid chains must not produce a 'high' confidence label anywhere
    assert all(e.quality.label != "high" for e in illiq.expiries)
    print("  signal-to-noise gating OK")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        print(f"\n{t.__name__}:")
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL: {e}")
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
    print(f"\n{'='*50}\n{len(tests)-failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
