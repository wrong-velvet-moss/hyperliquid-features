"""hl-signals: collect Hyperliquid fair-value / funding / (later) liquidation
data and test whether any of it is predictive of forward returns."""

from .api import HyperliquidInfo

__all__ = ["HyperliquidInfo"]
