# Option-Implied Price: Research & Design Knowledge Base

> Synthesized from academic papers, central-bank working papers, exchange
> methodology docs, and practitioner sources (see **Sources** at the end).
> Purpose: build a tool that extracts *option-implied price information* from
> equity option chains **without presenting noise as signal** — especially for
> high-volume names where the chain is often "mostly noise."

---

## TL;DR — the core thesis

1. **Options do not predict direction.** The center of the option-implied
   distribution is *mechanically pinned to the forward* `F = S·e^{(r−q)T}` by
   put–call parity. The "implied price" is the forward by construction; it
   carries cost-of-carry information, **not** a directional forecast. Anyone
   selling "options say the stock is going to $X" is misreading a no-arbitrage
   artifact as alpha.

2. **What options *do* tell you is risk, not direction:** the *magnitude* of the
   expected move (implied vol), the *shape* of the risk-neutral distribution
   (skew/kurtosis), and the *term structure* of uncertainty. These are
   reliably extractable even for noisy liquid names.

3. **Risk-neutral ≠ real-world.** The extracted density is the risk-neutral
   density `Q`, related to the physical density `P` by the pricing kernel
   `q(x) = M(x)·p(x)`. The gap is the risk premium (the variance risk premium
   is its most-measured component). So even a clean RND is *not* a probability
   forecast of where the stock will actually be.

4. **The chain is genuinely noisy**, and the noise is worst exactly where the
   interesting information lives (the tails). A credible tool must (a) filter
   aggressively, (b) fit in implied-vol space with smoothing, (c) enforce
   no-arbitrage, and (d) **score its own signal-to-noise and refuse to over-claim
   when the chain can't support it.**

---

## 1. Why high-volume / liquid options often show "no clear implication"

| Claim | Detail / formula | Confidence |
|---|---|---|
| Risk-neutral measure is a *pricing* device, not a forecast | `C = e^{−rT} E^Q[payoff]`; `Q` is chosen so discounted prices are martingales | High |
| Under `Q`, every asset drifts at `r` | counterfactual vs real equity premium ⇒ `E^Q[S_T] ≠ E^P[S_T]` | High |
| `P` and `Q` linked by pricing kernel | `q(x) = M(x)·p(x)`; `M` non-trivial & empirically non-monotonic | High |
| **Put–call parity pins the mean to the forward** | `C − P = e^{−rT}(F − K)` ⇒ mean of RND `= F = S·e^{(r−q)T}` | High |
| Forward is a martingale ⇒ no built-in drift | option-implied forward "reflects no directional bias" | High |
| IV measures **magnitude, not direction** | high IV ⇒ big move *either way*; cannot say which | High |
| Variance risk premium (VRP) is the measurable Q–P wedge | `VRP = implied variance − realized variance`, reliably **positive** for indices | High |
| It's the **VRP**, not the implied price level, that has (weak) return-predictive content | strongest at quarterly horizon, **index-level only** | High |

**Design implication:** Never display the RND mean / forward as a "price
target." Label it explicitly as *"forward (cost-of-carry), not a forecast."*
The directional center is the *least* informative output; lead with the
**move/uncertainty**, not the level.

---

## 2. Sources of noise that corrupt extraction

| Noise source | Why it hurts | Mitigation |
|---|---|---|
| **2nd-derivative amplification** | RND `= e^{rT}·∂²C/∂K²`; differencing noisy prices ⇒ oscillating/negative densities (ill-posed inverse problem) | smooth in IV space first |
| **Discrete strikes** | resolution bounded by strike spacing `ΔK`; features finer than `ΔK` unrecoverable | interpolate IV curve |
| **Sparse quotes** | often only ~5–50 actively-quoted strikes/expiry, concentrated near forward | restrict to liquid band |
| **Wide bid-ask ⇒ unreliable mid** | mid uncertainty ≈ ±(spread/2); wide-spread mids are noise | spread filters; weight by liquidity |
| **Relative-spread filter is biased** | `spread/mid` over-discards cheap OTM strikes (the tails) | use spread caps *and* abs floors jointly |
| **High OI ≠ tight spread** | far-OTM can have OI but wide spreads | check spread directly, not just OI |
| **Microstructure noise / tick size** | bid-ask bounce + discreteness **biases** implied moments, even when liquid; worse for low-priced options | smoothing; drop sub-tick-spread quotes |
| **American early-exercise premium** | put–call parity `C−P=S−K e^{−rT}` holds only for European; single-name equity options are American ⇒ biased forward/IV; de-Americanization error grows with the premium | de-Americanize, or restrict to OTM where premium is small |
| **Discrete dividends** | mis-modeled dividends move the early-exercise boundary ⇒ contaminate ITM-call/ITM-put IV | use implied forward from parity, prefer OTM |
| **No-arbitrage violations in raw quotes** | stale/async quotes create butterfly/calendar/vertical violations ⇒ extraction unstable | filter/repair before fitting |
| **Free-data (Yahoo) anomalies** | documented gross bid/ask/last errors, stale `lastPrice`, ~15-min delay, off-hours staleness | check `lastTradeDate`, prefer bid/ask over last, validate parity |
| **Deep OTM/ITM least reliable — yet govern the tails** | $0.01–0.05 prices, tick ≈ 10–100% of premium, widest rel. spreads | **tails are extrapolated, not measured** — graft parametric tails, flag low confidence |

---

## 3. Concrete filtering & data-quality rules (with thresholds)

These are the actual screens used by CBOE, OptionMetrics-based studies, and
BKM(2003). Treat numbers as **defaults**, expose them as config.

### Hard liquidity screen (per contract)
- Drop `bid <= 0` (zero-bid options).
- Drop penny options below a floor (default **`< $0.10`** mid; configurable $0.05–$0.10).
- Drop `open_interest == 0` and (optionally) `volume == 0`.
- A commonly-cited screen: `volume > 1000, open_interest > 100, IV > 0, last > $0.10` (aggressive; relax for single names).
- **Prefer mid-quote** `= (bid+ask)/2`, **not** last (avoids stale prints).
- Spread filters (apply **jointly**, not either/or):
  - absolute cap, e.g. drop `ask − bid > $0.30` for low-priced names, and
  - relative cap `spread% = (ask−bid)/mid` (but know this is biased against cheap OTM — use a more lenient relative cap so you don't gut the tails).

### Strike / moneyness selection
- Use **OTM puts below spot + OTM calls above spot**; discard ITM (illiquid, intrinsic-dominated, early-exercise-laden).
- Moneyness band `S/K ∈ [0.7, 1.3]` (default); tighten to `[0.8, 1.2]` or `[0.9, 1.05]` for a stricter, cleaner core.
- BKM near-money band: `−2.5% ≤ (S·e^{rτ}/K − 1) ≤ +2.5%` for robust moment estimation.

### CBOE / VIX strike-selection rules (the canonical illiquid-strike cutoff)
- **Forward `F`** = strike with the **smallest `|C − P|`**.
- **`K0`** = strike **at or immediately below `F`** (the ATM divider).
- Walking OTM in each wing, include only **non-zero-bid** strikes; **stop at the first occurrence of two consecutive zero-bid strikes**, and discard everything beyond — *even if a bid reappears.* (This is the key "cut the illiquid tail" rule.)
- Weight each strike by **`ΔK_i / K_i²`** (down-weights far strikes).

### Time-to-expiry filters
- Avoid 0DTE and ultra-short: VIX uses near-term **> 23 days**, next-term **< 37 days**, interpolating to 30.
- Default usable window ≈ **7–180 days**; avoid very long-dated illiquid LEAPS for RND.
- BKM moment work uses **15–30 days**.

### No-arbitrage enforcement (before/while fitting)
- **Vertical/monotonicity:** `C(K)` non-increasing in `K`; `P(K)` non-decreasing.
- **Butterfly/convexity:** `C(K−ΔK) − 2C(K) + C(K+ΔK) ≥ 0` (== non-negative discrete density).
- **Calendar:** total implied variance `w(k,T)` non-decreasing in `T`.
- **Put–call parity** consistency check (flag large deviations as stale/async).

---

## 4. Robust RND extraction (method recommendations)

**Recommended pipeline (Bliss–Panigirtzoglou / Figlewski lineage):**

1. Invert clean quotes to **Black–Scholes implied vols** (use the implied
   forward from parity, not raw spot, to neutralize dividends/rate).
2. **Fit a smooth curve in IV space** — IV is far better-conditioned than price
   (price spans orders of magnitude, dominated by intrinsic value).
   - Interpolate against **Black–Scholes delta** (bounded [0,1], concentrates
     knots near ATM where data is dense) — Bliss–Panigirtzoglou — or against
     log-moneyness.
   - Use a **penalized / smoothing spline**: minimize
     `Σ(σ_i − g(x_i))² + λ∫g''²`; `λ` trades fit vs smoothness. Weight points
     by **vega** (down-weights low-information deep-OTM).
   - Figlewski's concrete choice: degree-4 smoothing spline on IV vs strike.
3. Reconstruct dense smooth `C(K)` via Black–Scholes on the fitted IV curve.
4. Apply **Breeden–Litzenberger** to the *smooth* price function:
   `f(K) = e^{rT} ∂²C/∂K²` (numerically stable now).
5. **Tails:** only a limited strike range trades — **graft parametric tails**
   (Generalized Extreme Value / Generalized Pareto, à la Figlewski), matching
   both density value and CDF at the splice strikes. *Mark tail region as
   extrapolated / low-confidence.*

**Parametric alternatives (non-negative & normalized by construction):**
- **Mixture of 2–3 lognormals** (Bahra / Melick–Thomas): `f = α g₁ + (1−α) g₂`;
  5 params; captures skew/bimodality; enforce forward constraint
  `∫K f dK = F` directly. Good, stable default for single names.
- **SVI / SSVI** (Gatheral–Jacquier): total variance
  `w(k) = a + b[ρ(k−m) + √((k−m)²+σ²)]`; arbitrage-free subclass exists;
  butterfly-free ⇔ density ≥ 0, calendar-free ⇔ `w` non-decreasing in `T`.
- **SABR** (Hagan): convenient smile fit but asymptotic formula can produce
  **negative densities** in wings/long maturities — less safe for tails.
- **Edgeworth/Gram–Charlier:** can go **negative** in tails for large
  skew/kurtosis — avoid for extreme smiles.
- **Mixture Density Networks:** flexible, non-negative by construction; heavier
  machinery, optional.

**Pitfalls to encode as guardrails:** naive finite-differencing of raw prices;
fitting in price space; un-penalized splines (interpolate noise); ignoring
non-negativity (cubic-spline-on-IV can still yield negative densities unless
constrained).

---

## 5. Signal-to-noise scoring — let the tool refuse to over-claim

The tool should compute a **chain quality / confidence score** and gate its
outputs on it. Proposed components (each 0–1, then weighted):

| Metric | How | Reading |
|---|---|---|
| **Coverage** | fraction of strikes with valid two-sided quotes (`bid>0 & ask>0` & computable IV) | low ⇒ can't support RND |
| **Spread quality** | median `(ask−bid)/mid` over the near-money band | high ⇒ noisy mids |
| **Liquidity depth** | volume & open-interest levels / concentration near ATM | thin ⇒ stale |
| **Arbitrage cleanliness** | % of strikes passing monotonicity + convexity + calendar | violations ⇒ unstable |
| **Smoothing burden** | how much regularization (`λ`) / repair was needed to get an arbitrage-free fit | heavy ⇒ low signal |
| **RND admissibility** | density ≥ 0 everywhere, integrates to 1, mean ≈ forward | failure ⇒ reject |
| **Stability** | day-over-day stability of RND moments vs stable spot (optional) | violent swings ⇒ noise-driven |
| **VRP sanity** | implied vol vs trailing realized vol; index VRP normally positive ~2–4 vol pts | wildly off ⇒ anomaly flag |

**Gating policy (suggested):**
- **High confidence:** show RND, percentiles, skew, term structure.
- **Medium:** show expected move + IV skew/term structure only; mark RND as
  indicative, widen/hide tails.
- **Low / "mostly noise":** show **only** the ATM expected move with a wide
  uncertainty band and an explicit *"option chain too illiquid/noisy for a
  reliable implied distribution"* banner. **Do not** draw a confident heatmap.

---

## 6. What IS vs IS NOT reliably extractable

### Reliable (even for noisy liquid names)
- **ATM expected move (1σ):** `EM₁σ = S · σ_ATM · √(T/365)` (calendar days;
  use `T/252` for trading days). Contains the realized move ≈ 68% of the time.
- **Straddle cross-check:** ATM straddle price `≈ 0.8 · S · σ_ATM · √T`
  (this equals the **mean absolute deviation** `E|S_T−F| = S·σ√T·√(2/π)`),
  so `EM₁σ ≈ 1.25 × straddle`. ⚠️ **Do not** use the folk "EM ≈ 0.85 ×
  straddle" — it conflates MAD with 1σ. Use the closed-form as primary.
- **IV level, skew/smile shape, IV term structure** — robust, informative
  about tail-risk pricing and expected vol path.
- **Probability of finishing ITM** ≈ `|delta|`; **probability of touching** a
  level ≈ `2 × |delta|` (rule of thumb, best near-ATM/short-dated).
- **Full RND** via the smoothed pipeline — *when the quality score permits.*

### NOT reliable (do not present as such)
- A **precise directional point forecast** of future price. RND density
  forecasts are statistically biased and rejected out-of-sample.
- The **RND mean as a "price target"** — it's the forward, a no-arbitrage
  artifact, not a view (and it's `Q`, not `P`).
- **Any density from an illiquid / wide-spread / arbitrage-violating chain** —
  output is noise dressed as signal.
- **Tails as measured fact** — they are extrapolated; label accordingly.

---

## 7. Direct implications for the heatmap

The user's idea — a heatmap of expirations (x) × price levels (y), color =
where the market concentrates probability/strikes — is sound **if** it plots
*risk-neutral probability density* (or a liquidity-validated proxy) rather than
raw open interest:

- **Color = RND density per expiry** (a "probability cone"), normalized per
  column so each expiry integrates to 1. Hotter = higher implied probability.
- Overlay the **spot**, the **forward curve** (dashed, labeled "not a
  forecast"), and the **±1σ expected-move band**.
- **Gate by the quality score:** render full density only for high-confidence
  expiries; for low-confidence expiries show just the expected-move band (or
  grey them out) — *never* paint a confident hot zone on a noise-dominated
  chain.
- If also showing **open-interest concentration**, keep it a *separate* layer
  and label it as positioning, **not** probability — OI clusters at round
  strikes are a market-structure artifact, not a forecast.

---

## Sources

**Why liquid options lack directional signal / Q vs P / VRP**
- Risk-neutral measure — Wikipedia: https://en.wikipedia.org/wiki/Risk-neutral_measure
- Forward measure — Wikipedia: https://en.wikipedia.org/wiki/Forward_measure
- Matching distributions: Recovery of implied physical densities (arXiv 1803.03996): https://arxiv.org/pdf/1803.03996
- Bollerslev, Tauchen, Zhou, "Expected Stock Returns and Variance Risk Premia" (Fed FEDS 2007-11): https://www.federalreserve.gov/pubs/feds/2007/200711/200711pap.pdf
- The Variance Risk Premium in Equilibrium Models (NBER w27108): https://www.nber.org/system/files/working_papers/w27108/w27108.pdf
- Taleb, "Risk Neutral Option Pricing…" (arXiv 1405.2609): https://arxiv.org/pdf/1405.2609

**Noise sources / microstructure / American & dividends / data quality**
- Figlewski, "Risk Neutral Densities: A Review" (NYU Stern): https://pages.stern.nyu.edu/~sfiglews/documents/RND%20Review%20ver4.pdf
- Option Implied RND Estimation: Robust & Flexible Method (Springer Comp. Econ.): https://link.springer.com/article/10.1007/s10614-018-9846-1
- Microstructural biases in empirical tests of option pricing models (Springer): https://link.springer.com/article/10.1007/s11147-009-9039-0
- Perrakis, "Tick Size, Microstructure Noise and Volatility Inversion": https://www.concordia.ca/content/dam/jmsb/docs/profiles/stylianos-perrakis-tick-size-volatility-inversion-2011.pdf
- Neural Network to Extract Implied Information from American Options (T&F): https://www.tandfonline.com/doi/full/10.1080/1350486X.2022.2097099
- Put–call parity — Wikipedia: https://en.wikipedia.org/wiki/Put%E2%80%93call_parity
- Yahoo options data anomalies (Elite Trader): https://www.elitetrader.com/et/threads/options-data-at-finance-yahoo-com-completely-wrong.300193/

**Filtering thresholds / CBOE VIX / BKM / OptionMetrics**
- CBOE Volatility Index Mathematics Methodology: https://cdn.cboe.com/api/global/us_indices/governance/Cboe_Volatility_Index_Mathematics_Methodology.pdf
- VIX — Wikipedia: https://en.wikipedia.org/wiki/VIX
- Macroption — VIX Calculation Explained: https://www.macroption.com/vix-calculation/
- Bakshi, Kapadia & Madan (2003), RFS: https://people.umass.edu/nkapadia/docs/Bakshi_Kapadia_Madan_2003_RFS.pdf
- Wallmeier (2024), Quality issues of IVs in OptionMetrics IvyDB (J. Futures Markets): https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22495

**Robust RND extraction methods**
- Risk Neutral Density Estimation from Option Prices — BSIC, Bocconi: https://bsic.it/risk-neutral-density-estimation-from-option-prices/
- Figlewski, "Estimating the Implied Risk Neutral Density" (SSRN 1354492): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1354492
- Bliss & Panigirtzoglou, "Testing the stability of implied PDFs" (BoE WP114): https://ideas.repec.org/p/boe/boeewp/114.html
- Bahra, "Implied Risk-Neutral PDFs from Option Prices" (BoE WP66 / SSRN 77429): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=77429
- Gatheral & Jacquier, "Arbitrage-free SVI volatility surfaces" (arXiv 1204.0646): https://arxiv.org/abs/1204.0646
- NY Fed Staff Report 677, option-based risk-neutral distributions: https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr677.pdf
- Jackwerth/Figlewski, "Risk-Neutral Densities: A Review" (Annual Reviews): https://www.annualreviews.org/content/journals/10.1146/annurev-financial-110217-022944
- Monteiro, Tütüncü & Vicente, nonnegative cubic-spline RND (ScienceDirect): https://www.sciencedirect.com/science/article/abs/pii/S0377221707002871

**Expected move / what's extractable / signal-to-noise**
- OptionsHawk — Calculating Expected Moves: https://optionshawk.com/calculating-expected-moves-using-options/
- projectfinance — Expected Move Explained: https://www.projectfinance.com/expected-move/
- Alpha Architect — The Variance Risk Premium is Pervasive: https://alphaarchitect.com/the-variance-risk-premium-is-pervasive/
- tastytrade — Probability of Touch: https://www.tastytrade.com/tt/shows/market-measures/episodes/probability-of-touch-after-touch-01-04-2016
- USC Jones — Term Structure of Equity Option Implied Volatility: https://msbfile03.usc.edu/digitalmeasures/christoj/intellcont/jones_wang-1.pdf

> **Method note:** In this environment WebFetch was IP-blocked (HTTP 403), so
> claims were drawn from WebSearch result excerpts of the above primary
> sources. Canonical formulas (put–call parity, `F=S·e^{(r−q)T}`,
> Breeden–Litzenberger `e^{rT}∂²C/∂K²`, `EM₁σ=S·σ√(T/365)`, straddle≈MAD)
> are independently cross-corroborated and verified against first principles.
> Study-specific numeric thresholds (BKM ±2.5%, moneyness 0.7–1.3, VIX 23/37-day)
> are reproduced as stated by multiple sources but should be re-confirmed
> against the primary PDFs before being quoted verbatim in published work.
