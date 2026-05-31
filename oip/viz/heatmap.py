"""Implied-price heatmap: expiry (x) x price level (y), color = implied density.

Design (docs/RESEARCH.md sec 7):
  * Color = RISK-NEUTRAL probability density per expiry (a "probability cone"),
    normalized per column so each expiry is comparable.  Hotter = where the
    market prices more probability mass.
  * Overlays: spot, the implied-forward curve (labelled NOT a forecast), and the
    +/-1 sigma expected-move band.
  * CONFIDENCE GATING: only 'high'-quality expiries get a full density column;
    lower-quality expiries show just the expected-move band, so we never paint a
    confident hot zone on a noise-dominated chain.

A matplotlib PNG is produced when matplotlib is available; otherwise a coloured
text heatmap is printed/returned so the tool is useful with the stdlib alone.
"""
from __future__ import annotations

import math
from typing import List, Optional

from ..analyze import ExpiryAnalysis, SymbolAnalysis


def _price_grid(analysis: SymbolAnalysis, n=160, span_sigmas=3.5):
    """A common price axis covering +/- span_sigmas of the largest expected move."""
    spot = analysis.spot
    lo, hi = spot, spot
    for ex in analysis.expiries:
        if ex.expected_move:
            m = ex.expected_move.move_1sigma * span_sigmas
            lo = min(lo, ex.forward.forward - m)
            hi = max(hi, ex.forward.forward + m)
    lo = max(lo, 0.01 * spot)
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _column_density(ex: ExpiryAnalysis, grid: List[float]):
    """Return a normalized density column for an expiry, or None if not gated in."""
    if ex.rnd is not None and ex.rnd_trustworthy:
        vals = [ex.rnd.pdf(x) for x in grid]
    elif ex.expected_move is not None:
        # Fallback: a Gaussian bump at the forward with the expected-move width,
        # rendered dimmer to signal lower confidence.
        f = ex.forward.forward
        s = ex.expected_move.move_1sigma
        vals = [math.exp(-0.5 * ((x - f) / s) ** 2) for x in grid]
        mx = max(vals) or 1.0
        return [0.45 * v / mx for v in vals]  # capped intensity => visibly dimmer
    else:
        return None
    mx = max(vals) or 1.0
    return [v / mx for v in vals]


# ---------------------------------------------------------------------------
# Matplotlib renderer
# ---------------------------------------------------------------------------
def render_png(analysis: SymbolAnalysis, path: str, n_price=200) -> Optional[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return None

    grid = _price_grid(analysis, n=n_price)
    exps = [e for e in analysis.expiries if e.expected_move is not None]
    if not exps:
        return None
    xs = [e.days for e in exps]

    Z = np.zeros((len(grid), len(exps)))
    for j, ex in enumerate(exps):
        col = _column_density(ex, grid)
        if col is not None:
            Z[:, j] = col

    fig, ax = plt.subplots(figsize=(11, 7))
    # pcolormesh wants cell edges; build them from the (possibly uneven) axes.
    xe = _edges(xs)
    ye = _edges(grid)
    mesh = ax.pcolormesh(xe, ye, Z, cmap="inferno", shading="auto")
    cbar = fig.colorbar(mesh, ax=ax)
    cbar.set_label("implied probability density (normalized per expiry)")

    # Overlays.
    ax.axhline(analysis.spot, color="white", lw=1.0, ls=":", alpha=0.7,
               label=f"spot {analysis.spot:.2f}")
    fcurve = [e.forward.forward for e in exps]
    ax.plot(xs, fcurve, color="cyan", lw=1.5, marker="o", ms=3,
            label="implied forward (NOT a forecast)")
    hi = [e.forward.forward + e.expected_move.move_1sigma for e in exps]
    lo = [e.forward.forward - e.expected_move.move_1sigma for e in exps]
    ax.plot(xs, hi, color="lime", lw=1.0, ls="--", alpha=0.8, label="+/-1 sigma expected move")
    ax.plot(xs, lo, color="lime", lw=1.0, ls="--", alpha=0.8)

    # Mark low-confidence expiries.
    for ex in exps:
        if not (ex.rnd is not None and ex.rnd_trustworthy):
            ax.annotate("low-conf", (ex.days, grid[-1]), color="orange",
                        fontsize=7, ha="center", va="top")

    ax.set_xlabel("days to expiration")
    ax.set_ylabel("price level")
    ax.set_title(f"{analysis.symbol}  option-implied price distribution "
                 f"(as of {analysis.asof})")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def _edges(centers):
    if len(centers) == 1:
        c = centers[0]
        return [c - 0.5, c + 0.5]
    e = [centers[0] - 0.5 * (centers[1] - centers[0])]
    for i in range(len(centers) - 1):
        e.append(0.5 * (centers[i] + centers[i + 1]))
    e.append(centers[-1] + 0.5 * (centers[-1] - centers[-2]))
    return e


# ---------------------------------------------------------------------------
# Text renderer (stdlib only)
# ---------------------------------------------------------------------------
_SHADES = " .:-=+*#%@"


def render_text(analysis: SymbolAnalysis, rows=22, use_color=True) -> str:
    exps = [e for e in analysis.expiries if e.expected_move is not None]
    if not exps:
        return "(no analyzable expiries)"

    # Price axis (descending so high prices are at the top).
    full_grid = _price_grid(analysis, n=rows)
    grid = list(reversed(full_grid))

    cols = []
    for ex in exps:
        col = _column_density(ex, grid)
        cols.append(col if col is not None else [0.0] * len(grid))

    forwards = [e.forward.forward for e in exps]
    em_hi = [e.forward.forward + e.expected_move.move_1sigma for e in exps]
    em_lo = [e.forward.forward - e.expected_move.move_1sigma for e in exps]

    cw = 7  # column width
    lines = []
    header = "price".rjust(9) + " |" + "".join(
        f"{int(round(e.days)):>{cw}}" for e in exps)
    lines.append(header)
    lines.append(" " * 9 + " +" + "-" * (cw * len(exps)))

    for r, price in enumerate(grid):
        cells = ""
        for j, ex in enumerate(exps):
            intensity = cols[j][r]
            ch = _SHADES[min(len(_SHADES) - 1, int(intensity * (len(_SHADES) - 1)))]
            cell = ch * (cw - 2)
            # mark forward (F) and expected-move band edges (|)
            if abs(price - forwards[j]) <= _half_step(grid, r):
                cell = cell[:-1] + "F" if cell else "F"
            mark = ""
            if abs(price - em_hi[j]) <= _half_step(grid, r) or \
               abs(price - em_lo[j]) <= _half_step(grid, r):
                mark = "~"
            cells += (cell + mark).rjust(cw)
        line = f"{price:9.2f} |{cells}"
        if abs(price - analysis.spot) <= _half_step(grid, r):
            line += "  <- spot"
        lines.append(_colorize(line) if use_color else line)

    # Footer: confidence per expiry.
    conf = " " * 9 + " |" + "".join(
        f"{_conf_tag(e):>{cw}}" for e in exps)
    lines.append(" " * 9 + " +" + "-" * (cw * len(exps)))
    lines.append(conf)
    lines.append("")
    lines.append("legend: '" + _SHADES + "' = low->high implied density | "
                 "F=forward  ~=+/-1 sigma  | hi/me/lo = confidence")
    lines.append("note: the forward is cost-of-carry, NOT a price prediction; "
                 "density is risk-neutral, not real-world probability.")
    return "\n".join(lines)


def _half_step(grid, r):
    if len(grid) < 2:
        return 0.5
    if r == 0:
        return abs(grid[1] - grid[0]) / 2
    return abs(grid[r] - grid[r - 1]) / 2


def _conf_tag(ex: ExpiryAnalysis) -> str:
    return {"high": "hi", "medium": "me", "low": "lo"}.get(ex.quality.label, "?")


def _colorize(line: str) -> str:
    # Map shade characters to ANSI 256 'inferno-ish' colors for terminal flair.
    out = []
    palette = {" ": 16, ".": 52, ":": 88, "-": 124, "=": 160, "+": 196,
               "*": 202, "#": 208, "%": 214, "@": 220}
    for ch in line:
        if ch in palette and ch != " ":
            out.append(f"\033[38;5;{palette[ch]}m{ch}\033[0m")
        else:
            out.append(ch)
    return "".join(out)
