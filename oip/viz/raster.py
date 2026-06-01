"""Render the implied-price heatmap to a PNG using the stdlib-only Canvas.

Used as the fallback when matplotlib is unavailable (and exercised in the
sandbox to produce sample images).  Same semantics as the matplotlib renderer:
color = risk-neutral density (a "probability cone"), gated by per-expiry
confidence, with spot / forward-curve / +-1sigma overlays.
"""
from __future__ import annotations

import math
from typing import List, Optional

from ..analyze import ExpiryAnalysis, SymbolAnalysis
from .font5x7 import draw_text, text_width
from .pngwriter import Canvas

# inferno-ish colormap control points (position, r, g, b)
_CMAP = [
    (0.00, 0, 0, 4), (0.15, 40, 11, 84), (0.30, 101, 21, 110),
    (0.45, 159, 42, 99), (0.60, 212, 72, 66), (0.75, 245, 125, 21),
    (0.90, 250, 193, 39), (1.00, 252, 255, 164),
]


def _cmap(t: float):
    t = max(0.0, min(1.0, t))
    for i in range(len(_CMAP) - 1):
        p0, r0, g0, b0 = _CMAP[i]
        p1, r1, g1, b1 = _CMAP[i + 1]
        if t <= p1:
            f = (t - p0) / (p1 - p0) if p1 > p0 else 0.0
            return (int(r0 + f * (r1 - r0)), int(g0 + f * (g1 - g0)),
                    int(b0 + f * (b1 - b0)))
    return _CMAP[-1][1:]


def _intensity_fn(ex: ExpiryAnalysis, pmin: float, pmax: float):
    """Return (fn(price)->0..1, dimmed?) for an expiry, or (None, _)."""
    if ex.rnd is not None and ex.rnd_trustworthy:
        rnd = ex.rnd
        samples = [rnd.pdf(pmin + (pmax - pmin) * i / 200) for i in range(201)]
        mx = max(samples) or 1.0
        return (lambda p: rnd.pdf(p) / mx), False
    if ex.expected_move is not None:
        f = ex.forward.forward
        s = ex.expected_move.move_1sigma
        return (lambda p: 0.5 * math.exp(-0.5 * ((p - f) / s) ** 2)), True
    return None, False


def render(analysis: SymbolAnalysis, path: str, W: int = 960, H: int = 620,
           span_sigmas: float = 3.0, show_oi: bool = False) -> Optional[str]:
    exps = [e for e in analysis.expiries if e.expected_move is not None]
    if not exps:
        return None

    # price range across all expiries
    pmin = pmax = analysis.spot
    for e in exps:
        m = e.expected_move.move_1sigma * span_sigmas
        pmin = min(pmin, e.forward.forward - m)
        pmax = max(pmax, e.forward.forward + m)
    pmin = max(pmin, 0.01)
    days = [e.days for e in exps]
    dmin, dmax = min(days), max(days)
    if dmax == dmin:
        dmax = dmin + 1

    L, R, T, B = 78, 150, 46, 52       # margins
    pw, ph = W - L - R, H - T - B

    def px_of_day(d):
        return L + int(pw * (d - dmin) / (dmax - dmin)) if dmax > dmin else L + pw // 2

    def py_of_price(p):
        return T + int(ph * (pmax - p) / (pmax - pmin))

    def price_of_py(py):
        return pmax - (py - T) / ph * (pmax - pmin)

    cv = Canvas(W, H, bg=(8, 8, 16))

    # precompute per-expiry intensity fns and x positions
    fns = [_intensity_fn(e, pmin, pmax) for e in exps]
    xs = [px_of_day(d) for d in days]

    # paint the cone: for each plot column, interpolate between bracketing expiries
    for sx in range(pw):
        x = L + sx
        d = dmin + (dmax - dmin) * sx / pw
        # find bracketing expiry indices
        j = 0
        while j < len(days) - 1 and days[j + 1] < d:
            j += 1
        if j >= len(days) - 1:
            i0 = i1 = len(days) - 1
            t = 0.0
        else:
            i0, i1 = j, j + 1
            span = days[i1] - days[i0]
            t = (d - days[i0]) / span if span > 0 else 0.0
        f0, dim0 = fns[i0]
        f1, dim1 = fns[i1]
        for sy in range(ph):
            y = T + sy
            p = price_of_py(y)
            v0 = f0(p) if f0 else 0.0
            v1 = f1(p) if f1 else 0.0
            val = (1 - t) * v0 + t * v1
            if val > 0.003:
                cv.set(x, y, _cmap(val))

    # axes frame
    frame = (90, 90, 110)
    cv.hline(L, L + pw, T + ph, frame)
    cv.vline(L, T, T + ph, frame)

    # y-axis price ticks/labels
    for i in range(7):
        p = pmin + (pmax - pmin) * i / 6
        y = py_of_price(p)
        cv.hline(L - 4, L, y, frame)
        lbl = f"{p:.0f}"
        draw_text(cv, lbl, L - 8 - text_width(lbl), y - 3, (190, 190, 205))

    # x-axis day ticks at each expiry
    for e, x in zip(exps, xs):
        cv.vline(x, T + ph, T + ph + 4, frame)
        lbl = f"{e.days:.0f}D"
        draw_text(cv, lbl, x - text_width(lbl) // 2, T + ph + 8, (190, 190, 205))

    # spot line (dotted, light)
    ysp = py_of_price(analysis.spot)
    cv.hline(L, L + pw, ysp, (160, 160, 175), dotted=True)
    draw_text(cv, f"SPOT {analysis.spot:.2f}", L + 4, ysp - 9, (190, 190, 205))

    # forward curve (cyan) + +-1sigma band (green dashed)
    cyan, green, orange = (90, 220, 230), (120, 230, 130), (250, 170, 40)
    for k in range(len(exps) - 1):
        cv.line(xs[k], py_of_price(exps[k].forward.forward),
                xs[k + 1], py_of_price(exps[k + 1].forward.forward), cyan, thick=2)
        for sgn in (+1, -1):
            cv.line(xs[k], py_of_price(exps[k].forward.forward
                                       + sgn * exps[k].expected_move.move_1sigma),
                    xs[k + 1], py_of_price(exps[k + 1].forward.forward
                                           + sgn * exps[k + 1].expected_move.move_1sigma),
                    green, dashed=True)
    for e, x in zip(exps, xs):
        yf = py_of_price(e.forward.forward)
        cv.rect(x - 2, yf - 2, x + 2, yf + 2, cyan)
        if not (e.rnd is not None and e.rnd_trustworthy):
            draw_text(cv, "LO", x - 6, T + 2, orange)  # low-confidence marker

    # positioning overlay (separate layer): OI walls + max pain
    if show_oi:
        call_c, put_c, mp_c = (255, 123, 123), (127, 179, 255), (235, 235, 245)
        half = max(3, pw // (len(exps) * 4))
        for e, x in zip(exps, xs):
            pos = e.positioning
            if not pos:
                continue
            if pos.call_wall is not None and pmin <= pos.call_wall <= pmax:
                y = py_of_price(pos.call_wall)
                cv.hline(x - half, x + half, y, call_c)
            if pos.put_wall is not None and pmin <= pos.put_wall <= pmax:
                y = py_of_price(pos.put_wall)
                cv.hline(x - half, x + half, y, put_c)
            if pos.max_pain is not None and pmin <= pos.max_pain <= pmax:
                y = py_of_price(pos.max_pain)
                cv.line(x - 4, y - 4, x + 4, y + 4, mp_c)
                cv.line(x - 4, y + 4, x + 4, y - 4, mp_c)

    # title + subtitle
    draw_text(cv, f"{analysis.symbol} OPTION-IMPLIED PRICE", L, 10,
              (235, 235, 245), scale=2)
    sub = ("COLOR=RISK-NEUTRAL DENSITY  CYAN=FORWARD (NOT A FORECAST)  "
           "GREEN=+/-1 SIGMA")
    if show_oi:
        sub += "  RED/BLUE=CALL/PUT OI WALL  X=MAX PAIN (POSITIONING)"
    draw_text(cv, sub, L, 32, (150, 150, 170))

    # colorbar
    cbx0, cbx1 = W - R + 30, W - R + 52
    for sy in range(ph):
        val = 1.0 - sy / ph
        cv.hline(cbx0, cbx1, T + sy, _cmap(val))
    cv.rect(cbx0 - 1, T - 1, cbx0 - 1, T + ph, frame)
    draw_text(cv, "HIGH", cbx1 + 4, T - 2, (190, 190, 205))
    draw_text(cv, "LOW", cbx1 + 4, T + ph - 6, (190, 190, 205))
    draw_text(cv, "IMPLIED", cbx0 - 6, T + ph + 14, (150, 150, 170))
    draw_text(cv, "PROB.", cbx0 - 2, T + ph + 24, (150, 150, 170))

    cv.write_png(path)
    return path
