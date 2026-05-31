"""A compact Nelder-Mead simplex optimizer (stdlib only).

Good enough for the low-dimensional (<=5 param) mixture calibration here, and
keeps the tool free of a SciPy dependency.
"""
from __future__ import annotations

from typing import Callable, List, Sequence


def nelder_mead(f: Callable[[List[float]], float], x0: Sequence[float],
                step: float = 0.25, max_iter: int = 2000,
                xtol: float = 1e-7, ftol: float = 1e-9) -> List[float]:
    n = len(x0)
    # Build initial simplex.
    simplex = [list(x0)]
    for i in range(n):
        pt = list(x0)
        pt[i] += step if pt[i] == 0 else step * (abs(pt[i]) + 1.0)
        simplex.append(pt)
    fvals = [f(p) for p in simplex]

    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5
    for _ in range(max_iter):
        order = sorted(range(n + 1), key=lambda i: fvals[i])
        simplex = [simplex[i] for i in order]
        fvals = [fvals[i] for i in order]

        # Convergence checks.
        if abs(fvals[-1] - fvals[0]) <= ftol:
            break
        spread = max(max(abs(simplex[k][j] - simplex[0][j]) for k in range(1, n + 1))
                     for j in range(n))
        if spread <= xtol:
            break

        centroid = [sum(simplex[k][j] for k in range(n)) / n for j in range(n)]
        worst = simplex[-1]

        # Reflection.
        xr = [centroid[j] + alpha * (centroid[j] - worst[j]) for j in range(n)]
        fr = f(xr)
        if fvals[0] <= fr < fvals[-2]:
            simplex[-1], fvals[-1] = xr, fr
            continue
        # Expansion.
        if fr < fvals[0]:
            xe = [centroid[j] + gamma * (xr[j] - centroid[j]) for j in range(n)]
            fe = f(xe)
            if fe < fr:
                simplex[-1], fvals[-1] = xe, fe
            else:
                simplex[-1], fvals[-1] = xr, fr
            continue
        # Contraction.
        xc = [centroid[j] + rho * (worst[j] - centroid[j]) for j in range(n)]
        fc = f(xc)
        if fc < fvals[-1]:
            simplex[-1], fvals[-1] = xc, fc
            continue
        # Shrink.
        best = simplex[0]
        for k in range(1, n + 1):
            simplex[k] = [best[j] + sigma * (simplex[k][j] - best[j]) for j in range(n)]
            fvals[k] = f(simplex[k])

    order = sorted(range(n + 1), key=lambda i: fvals[i])
    return simplex[order[0]]
