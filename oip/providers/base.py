"""Provider interface: anything that can return an OptionChainData."""
from __future__ import annotations

from typing import List, Optional, Protocol

from ..chain import OptionChainData


class OptionDataProvider(Protocol):
    def get_chain(self, symbol: str,
                  max_expiries: Optional[int] = None) -> OptionChainData:
        ...
