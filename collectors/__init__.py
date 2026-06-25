"""Importing this package registers all collectors with the registry.

`run.py` does `import collectors` once; after that every Collector subclass
is available via collectors.base.get_collector(...).
"""
from collectors import (  # noqa: F401
    hackernews,
    rss_generic,
    defillama,
    producthunt,
    youtube_search,
    gumroad,
    reddit,
    telegram,
)
