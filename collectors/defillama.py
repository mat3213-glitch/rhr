"""DeFiLlama collector — free public API, no auth.

Uses the /v2/chains endpoint for chain TVL data.
The /protocols endpoint is too large (~50MB+) and times out.

Filters: chains, min TVL.
"""
from __future__ import annotations

import httpx

from collectors.base import Collector, register
from models import RawItem, utcnow_iso

CHAINS_API = "https://api.llama.fi/v2/chains"


@register
class DeFiLlamaCollector(Collector):
    type = "defillama"

    def fetch(self) -> list[RawItem]:
        chains = self.params.get("chains", [])
        min_tvl = float(self.params.get("min_tvl_usd", 1_000_000))

        items: list[RawItem] = []

        protos = self._fetch_chains(chains, min_tvl)
        items.extend(protos)

        return items

    def _fetch_chains(self, chains: list[str], min_tvl: float) -> list[RawItem]:
        try:
            with httpx.Client(timeout=30) as client:
                r = client.get(CHAINS_API)
                r.raise_for_status()
                data = r.json()
        except Exception:
            return []

        chain_set = {c.lower() for c in chains} if chains else None
        items: list[RawItem] = []
        for chain in data:
            tvl = chain.get("tvl") or 0
            if tvl < min_tvl:
                continue

            name = chain.get("name", "?")
            chain_name = chain.get("name", "").lower()

            if chain_set and chain_name not in chain_set:
                continue

            slug = chain.get("name", "").lower().replace(" ", "-")
            url = f"https://defillama.com/chain/{slug}"

            body = (
                f"Chain: {name}. TVL: ${tvl:,.0f}. "
            )

            items.append(
                RawItem(
                    source="defillama",
                    source_item_id=f"chain:{slug}",
                    url=url,
                    title=f"{name} chain (${tvl:,.0f} TVL)",
                    body_text=body,
                    author=name,
                    fetched_at=utcnow_iso(),
                    points=int(tvl / 10000),
                )
            )
        return items
