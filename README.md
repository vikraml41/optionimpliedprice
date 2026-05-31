# optionimpliedprice

A tool to see the **option-implied price information** of a stock — what the
options market has *priced in* — built deliberately to **avoid presenting noise
as signal**.

> **The one thing to internalize:** options do **not** predict direction. The
> center of the option-implied distribution is mechanically the *forward*
> `F = S·e^(r−q)T` (put–call parity), which is just spot grown at cost-of-carry.
> What options reliably tell you is the **size** of the expected move, the
> **shape** (skew), and the **term structure** of uncertainty — never a price
> target. See [`docs/RESEARCH.md`](docs/RESEARCH.md) for the full, cited basis.

## What it shows

For each expiration:
- **Implied forward** (the risk-neutral mean) — labelled *not a forecast*.
- **Expected move** (±1σ) from ATM implied vol: `S·σ·√(T/365)` (the rigorous
  formula; we avoid the folklore "0.85 × straddle", which conflates mean
  absolute deviation with the 1σ move).
- **IV skew** and a **risk-neutral distribution** (lognormal mixture →
  percentiles), *only when the chain can support it*.
- A **confidence-gated heatmap** — a "probability cone" of expirations × price
  levels, hotter where the market prices more probability mass.

## The anti-noise design

Every output is gated by a **signal-to-noise quality score** (coverage, spread
quality, liquidity, no-arbitrage cleanliness, parity-fit R²):

| Quality | What the tool will say |
|---|---|
| **high** | forward, expected move, IV skew, full RND + percentiles, full heatmap |
| **medium** | forward, expected move, skew; RND marked *indicative* |
| **low** | **expected move band only**, with a *"chain mostly noise"* banner; RND **suppressed** |

It also cleans the chain first (mid-quotes only, drop zero-bid/penny/zero-OI,
spread caps, OTM-only, moneyness band, the CBOE two-consecutive-zero-bid tail
cutoff) and estimates the forward + discount directly from **put–call parity**
(so dividends/borrow need not be known).

## Install

The analytics core, the test suite, and the **text heatmap** need only the
Python standard library. For live data and the PNG heatmap:

```bash
pip install -r requirements.txt   # yfinance + matplotlib (both optional)
```

## Usage

```bash
# Live data (needs yfinance):
python -m oip.cli AAPL --max-expiries 6 --heatmap aapl.png

# Offline demos (stdlib only) — including the 'mostly noise' case:
python -m oip.cli --synthetic clean
python -m oip.cli --synthetic noisy_megacap
python -m oip.cli --synthetic illiquid        # gets gated to LOW, RND suppressed
```

Useful flags: `--components {1,2,3}` (mixture size), `--rate` (risk-free
fallback), `--min-oi`, `--min-price`, `--max-rel-spread`, `--moneyness-band`,
`--no-color`, `--no-text-heatmap`.

## Architecture

```
oip/
  blackscholes.py   Black-76 pricing + implied-vol inversion (stdlib)
  chain.py          provider-agnostic data structures
  forward.py        implied forward & discount via put-call parity regression
  filters.py        chain cleaning + signal-to-noise quality score
  rnd.py            lognormal-mixture risk-neutral density (non-neg, forward-matched)
  expectedmove.py   rigorous expected-move calcs
  optimize.py       Nelder-Mead (no SciPy dependency)
  analyze.py        orchestration + confidence gating
  report.py         CLI text report
  providers/        synthetic (offline) + yfinance (live) data sources
  viz/heatmap.py    matplotlib PNG + ASCII text heatmap
tests/test_pipeline.py   end-to-end checks (run with: python tests/test_pipeline.py)
docs/RESEARCH.md         the cited knowledge base behind every design choice
```

## Tests

```bash
python tests/test_pipeline.py
```

Verifies: Black–Scholes/parity round-trips, forward recovery, expected-move
correctness, RND admissibility (integrates to 1, mean = forward, ordered
percentiles), and that the quality gating ranks clean > noisy > illiquid.

## Caveats

- Free data (yfinance) is delayed and noisy — the filters absorb a lot, but
  garbage in can still mislead; trust the **confidence labels**.
- The risk-neutral density is **not** a real-world probability (they differ by
  the risk premium). It is what the market *prices*, not what *will happen*.
- Tails of the distribution are the least reliable part (few liquid strikes);
  treat extreme percentiles as indicative.
