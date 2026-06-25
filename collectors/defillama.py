"""DeFiLlama collector — free public API, no auth.

Uses the /protocols endpoint for protocol TVL data.
The /pools endpoint is too large (~50MB) for reliable fetching.

Filters: chains, min TVL.
"""
from __future__ import annotations

import httpx

from collectors.base import Collector, register
from models import RawItem, utcnow_iso

PROTOCOLS_API = "https://api.llama.fi"


@register
class DeFiLlamaCollector(Collector):
    type = "defillama"

    def fetch(self) -> list[RawItem]:
        chains = self.params.get("chains", [])
        min_tvl = float(self.params.get("min_tvl_usd", 1_000_000))

        items: list[RawItem] = []

        protos = self._fetch_protocols(chains, min_tvl)
        items.extend(protos)

        return items

    def _fetch_protocols(self, chains: list[str], min_tvl: float) -> list[RawItem]:
        try:
            with httpx.Client(timeout=60) as client:
                r = client.get(f"{PROTOCOLS_API}/protocols")
                r.raise_for_status()
                data = r.json()
        except Exception:
            return []

        chain_set = {c.lower() for c in chains} if chains else None
        items: list[RawItem] = []
        for proto in data:
            tvl = proto.get("tvl") or 0
            if tvl < min_tvl:
                continue

            proto_chains = proto.get("chains", [])
            if chain_set and not any(c.lower() in chain_set for c in proto_chains):
                continue

            slug = proto.get("slug", "")
            name = proto.get("name", "?")
            category = proto.get("category", "?")
            url = f"https://defillama.com/protocol/{slug}" if slug else ""
            change_1d = proto.get("change_1d")
            change_7d = proto.get("change_7d")

            body = (
                f"Category: {category}. TVL: ${tvl:,.0f}. "
                f"1d change: {change_1d or 0:.1f}%. 7d change: {change_7d or 0:.1f}%. "
                f"Chains: {', '.join(proto_chains[:5])}. "
            )

            items.append(
                RawItem(
                    source="defillama",
                    source_item_id=f"proto:{slug}",
                    url=url,
                    title=f"{name} — {category} (${tvl:,.0f} TVL)",
                    body_text=body,
                    author=name,
                    fetched_at=utcnow_iso(),
                    points=int(tvl / 10000),
                )
            )
        return items
