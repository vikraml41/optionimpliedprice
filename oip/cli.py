"""Command-line entrypoint for the option-implied-price tool.

Examples
--------
  # Live data (needs `pip install yfinance` on your machine):
  python -m oip.cli AAPL --max-expiries 6 --heatmap aapl.png

  # Offline demo with synthetic data (works with the stdlib alone):
  python -m oip.cli --synthetic clean
  python -m oip.cli --synthetic noisy_megacap     # the 'mostly noise' case
"""
from __future__ import annotations

import argparse
import sys

from .analyze import analyze_symbol
from .filters import FilterConfig
from .report import format_report
from .viz.heatmap import render_png, render_text


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oip",
        description="Show option-implied price information (forward, expected "
                    "move, risk-neutral distribution) with a confidence-gated "
                    "heatmap. Designed to NOT present noise as signal.")
    p.add_argument("symbol", nargs="?", help="ticker, e.g. AAPL (omit with --synthetic)")
    p.add_argument("--synthetic", metavar="PROFILE", default=None,
                   choices=["clean", "noisy_megacap", "illiquid"],
                   help="use a synthetic chain instead of live data")
    p.add_argument("--max-expiries", type=int, default=6)
    p.add_argument("--components", type=int, default=2,
                   help="lognormal mixture components (1-3)")
    p.add_argument("--rate", type=float, default=0.04,
                   help="risk-free rate fallback if parity regression fails")
    p.add_argument("--heatmap", metavar="PATH", default=None,
                   help="write a PNG heatmap to PATH (requires matplotlib)")
    p.add_argument("--no-text-heatmap", action="store_true",
                   help="suppress the ASCII heatmap")
    p.add_argument("--no-color", action="store_true")
    # filter overrides
    p.add_argument("--min-oi", type=int, default=0)
    p.add_argument("--min-price", type=float, default=0.10)
    p.add_argument("--max-rel-spread", type=float, default=0.60)
    p.add_argument("--moneyness-band", type=float, default=0.30)
    return p


def get_provider(args):
    if args.synthetic:
        from .providers.synthetic import SyntheticProvider
        return SyntheticProvider(profile=args.synthetic), args.synthetic.upper()
    if not args.symbol:
        raise SystemExit("error: provide a SYMBOL or use --synthetic PROFILE")
    from .providers.yfinance_provider import YFinanceProvider
    return YFinanceProvider(), args.symbol.upper()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    provider, symbol = get_provider(args)

    try:
        data = provider.get_chain(symbol, max_expiries=args.max_expiries)
    except Exception as e:
        print(f"error fetching chain for {symbol}: {e}", file=sys.stderr)
        return 2

    if not data.expiries:
        print(f"no usable expiries for {symbol}", file=sys.stderr)
        return 3

    cfg = FilterConfig(
        min_open_interest=args.min_oi,
        min_price=args.min_price,
        max_rel_spread=args.max_rel_spread,
        moneyness_band=args.moneyness_band,
    )
    analysis = analyze_symbol(data, cfg=cfg, risk_free_rate=args.rate,
                              n_components=max(1, min(3, args.components)),
                              max_expiries=args.max_expiries)

    print(format_report(analysis))

    if not args.no_text_heatmap:
        print("\nIMPLIED-PRICE HEATMAP (probability cone)\n")
        print(render_text(analysis, use_color=not args.no_color))

    if args.heatmap:
        out = render_png(analysis, args.heatmap)
        if out:
            print(f"\nwrote heatmap PNG -> {out}")
        else:
            print("\n(matplotlib not available; install it for the PNG heatmap)",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
