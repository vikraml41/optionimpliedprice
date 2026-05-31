"""Live option-chain provider backed by yfinance (free, no API key).

Quotes from this free source are delayed and frequently noisy -- which is
exactly what the cleaning + quality-gating layers are designed to absorb.  The
provider only *fetches*; it does no judgement.  See docs/RESEARCH.md.
"""
from __future__ import annotations

import datetime as _dt
from typing import List, Optional

from ..chain import ExpiryChain, OptionChainData, OptionQuote


def _to_float(v):
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


class YFinanceProvider:
    def __init__(self, min_days: int = 5, max_days: int = 200):
        try:
            import yfinance  # noqa: F401
        except ImportError as e:  # pragma: no cover - environment dependent
            raise ImportError(
                "yfinance is required for live data. Install with "
                "`pip install yfinance`, or use the synthetic provider."
            ) from e
        self.min_days = min_days
        self.max_days = max_days

    def get_chain(self, symbol: str,
                  max_expiries: Optional[int] = None) -> OptionChainData:
        import yfinance as yf

        tk = yf.Ticker(symbol)
        spot = self._spot(tk)
        if spot is None:
            raise RuntimeError(f"Could not determine spot price for {symbol}")

        today = _dt.date.today()
        expiries: List[ExpiryChain] = []
        for exp in tk.options:
            exp_date = _dt.date.fromisoformat(exp)
            days = (exp_date - today).days
            if days < self.min_days or days > self.max_days:
                continue
            try:
                oc = tk.option_chain(exp)
            except Exception:
                continue
            ttm = days / 365.0
            calls = self._quotes(oc.calls, True)
            puts = self._quotes(oc.puts, False)
            if calls or puts:
                expiries.append(ExpiryChain(expiry=exp, ttm_years=ttm, spot=spot,
                                            calls=calls, puts=puts))
            if max_expiries and len(expiries) >= max_expiries:
                break

        return OptionChainData(symbol=symbol.upper(), spot=spot, expiries=expiries,
                               asof=_dt.datetime.now().isoformat(timespec="seconds"))

    def _spot(self, tk) -> Optional[float]:
        # Prefer fast_info; fall back to recent close.
        try:
            fi = tk.fast_info
            for key in ("last_price", "lastPrice", "regular_market_price"):
                v = _to_float(getattr(fi, key, None) if not isinstance(fi, dict)
                              else fi.get(key))
                if v:
                    return v
        except Exception:
            pass
        try:
            hist = tk.history(period="1d")
            if len(hist):
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return None

    def _quotes(self, df, is_call: bool) -> List[OptionQuote]:
        out: List[OptionQuote] = []
        if df is None or len(df) == 0:
            return out
        for _, row in df.iterrows():
            out.append(OptionQuote(
                strike=float(row["strike"]),
                is_call=is_call,
                bid=_to_float(row.get("bid")),
                ask=_to_float(row.get("ask")),
                last=_to_float(row.get("lastPrice")),
                volume=int(_to_float(row.get("volume")) or 0),
                open_interest=int(_to_float(row.get("openInterest")) or 0),
            ))
        return out
