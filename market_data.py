"""Market-data provider abstraction -- the "design the interface now even if
it stays unused until there's revenue to justify Crunchbase/PitchBook-class
data" ship-list item.

Defines the interface every market-data source in this app implements, plus
the free default (`FreeDataProvider`, backed by `comparables.py`'s
YC-dataset similarity search) that's actually wired into the pipeline today.
`CrunchbaseProvider` and `PitchBookProvider` are documented stubs -- the
shape a real integration would take, gated behind an API key env var that
isn't set, so they stay inert until there's budget for one (per
FIELD_NOTES.md's stated "free/low-cost data sources only" decision).
Swapping one in later means implementing `MarketDataProvider.comparables()`
for that source and changing one line in `get_market_data_provider()`;
nothing else in the app should need to change, since callers only ever
depend on this interface, never on a concrete provider class.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def comparables(self, description: str, top_k: int = 5) -> dict[str, Any]:
        """Must return {available, comparables: [...], source, caveat} --
        the same shape regardless of provider, so callers never need to
        branch on which one is active."""
        raise NotImplementedError


class FreeDataProvider(MarketDataProvider):
    """The only provider actually wired into the pipeline today: TF-IDF
    similarity search over a real, free dataset (comparables.py)."""

    name = "free_yc_dataset"

    def comparables(self, description: str, top_k: int = 5) -> dict[str, Any]:
        from comparables import find_comparables

        return find_comparables(description, top_k=top_k)


class CrunchbaseProvider(MarketDataProvider):
    """Stub. Requires CRUNCHBASE_API_KEY -- not implemented, since
    Crunchbase's API is paid and this project has no budget for one yet.
    Implementing this for real means calling Crunchbase's Organizations
    Search endpoint and mapping its response into the same
    {available, comparables, source, caveat} shape FreeDataProvider
    returns -- nothing else in the app needs to change."""

    name = "crunchbase"

    def comparables(self, description: str, top_k: int = 5) -> dict[str, Any]:
        return {"available": False, "reason": "Crunchbase integration not implemented -- no API key/budget configured."}


class PitchBookProvider(MarketDataProvider):
    """Stub, same status as CrunchbaseProvider. PitchBook's API is
    enterprise-priced and typically needs a sales conversation rather than a
    signup, so it's lower priority to actually implement than Crunchbase."""

    name = "pitchbook"

    def comparables(self, description: str, top_k: int = 5) -> dict[str, Any]:
        return {"available": False, "reason": "PitchBook integration not implemented -- no API key/budget configured."}


def get_market_data_provider() -> MarketDataProvider:
    """Picks a provider by which API key env var is actually set. Falls
    back to the free provider -- which is the *correct* choice today, not
    merely a fallback, per the project's stated "free/low-cost data sources
    only" decision (FIELD_NOTES.md)."""
    if os.getenv("CRUNCHBASE_API_KEY", "").strip():
        return CrunchbaseProvider()
    if os.getenv("PITCHBOOK_API_KEY", "").strip():
        return PitchBookProvider()
    return FreeDataProvider()
