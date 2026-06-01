# Results

Each run of the **Option-Implied Price** GitHub Action writes its output here,
under `results/<TICKER>/`:

- `report.txt` — the full text report (forward, expected move, IV skew,
  risk-neutral percentiles, positioning) plus the ASCII heatmap.
- `heatmap.png` — the probability-cone heatmap image.

## Run it from your phone

1. Open the **GitHub mobile app** → this repo → **Actions**.
2. Pick **Option-Implied Price** → **Run workflow**.
3. Type a ticker (e.g. `AAPL`) and tap run.
4. You'll get a notification when it finishes; the result appears here and in
   the run's **summary** (and as a downloadable artifact).

> `EXAMPLE_SYNTHETIC/` is a sample produced from synthetic data so you can see
> the output format — it is **not** real market data.
