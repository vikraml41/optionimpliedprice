"""Data structures for an option chain (provider-agnostic)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class OptionQuote:
    strike: float
    is_call: bool
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    volume: int = 0
    open_interest: int = 0

    @property
    def mid(self) -> Optional[float]:
        if self.bid is not None and self.ask is not None and self.ask > 0:
            return 0.5 * (self.bid + self.ask)
        return self.last  # fall back to last only when no two-sided quote

    @property
    def spread(self) -> Optional[float]:
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    @property
    def rel_spread(self) -> Optional[float]:
        m = self.mid
        s = self.spread
        if m and m > 0 and s is not None:
            return s / m
        return None


@dataclass
class ExpiryChain:
    """All quotes for a single expiration date."""
    expiry: str            # ISO date string
    ttm_years: float       # time to maturity in years
    spot: float
    calls: List[OptionQuote] = field(default_factory=list)
    puts: List[OptionQuote] = field(default_factory=list)

    def strikes(self) -> List[float]:
        ks = {q.strike for q in self.calls} | {q.strike for q in self.puts}
        return sorted(ks)

    def call_at(self, strike):
        return next((q for q in self.calls if q.strike == strike), None)

    def put_at(self, strike):
        return next((q for q in self.puts if q.strike == strike), None)


@dataclass
class OptionChainData:
    """A symbol's full chain across expiries, as returned by a provider."""
    symbol: str
    spot: float
    expiries: List[ExpiryChain] = field(default_factory=list)
    asof: Optional[str] = None
