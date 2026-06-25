# 🐰 Rabbit Hole Radar (RHR)

**Catching demand signals from the deepest rabbit holes of the internet →
turning them into vibe-coded products → shipping only what shows traction.**

RHR is a pipeline that scans "deep internet" sources (forums, aggregators,
Telegram, X, Discord, niche Substacks) for signals of *how people make money*
and *what people want but don't have*, normalises/dedups/classifies them,
scores candidates against a tunable model, and funnels the winners through a
two-stage sandbox (demand-check → micro-MVP) before any real resources are
spent on a launch.

```
[Sources] → [L0 raw] → [L1 normalize/dedup] → [L2 score] → [L3 demand-check] → [L4 micro-MVP] → [L5 prod]
     ↑                                                                                  ↓
     └──────────────── winner metrics feed back into the scoring model ←────────────────┘
```

## Why

The internet's real money-making knowledge lives in rabbit holes: buried
threads, niche Discords, agg charts, "I want X but Y" complaints. Most of it
is noise; the signal is *demand that can be turned into a small digital
product (bot / wrapper / micro-SaaS / content asset)* — i.e. things you can
vibe-code fast. RHR automates the finding, filtering and pre-validation so
you spend cycles only on candidates with demonstrated pull.

## Architecture (in one breath)

- **Monorepo on GitHub, $0 baseline runtime.**
- **Public repo** holds the "clean" collectors (HN, RSS, public aggregators)
  and runs them on GitHub Actions cron — unlimited minutes on public repos.
- **Private repo / private part** holds normalised signals, scoring, sandbox
  metrics (2000–3000 free Actions min/mo is plenty at this volume).
- **Self-hosted runner** on a Linux box runs the sensitive/heavy jobs:
  Telegram sessions (Telethon), proxy-scraping, local Ollama pre-filter.
- **Repo-as-database**: SQLite file committed to the repo, JSON append-only
  logs. Versioning is free, diffs are inspectable in git.
- **GitHub Issues = candidate kanban**. One issue per L2 candidate, labels =
  funnel stage (`L2-scored`, `L3-demand-check`, `L4-mvp`, `L5-prod`,
  `archived`). `track.py` creates issues via `gh` CLI.
- **GitHub Pages dashboard** reads issues via API and renders a pipeline view.

## Stack

| Layer        | Choice                                                         |
|--------------|----------------------------------------------------------------|
| Language     | Python 3.12                                                    |
| Scraping     | `httpx` + `feedparser` + `selectolax`; `telethon` for Telegram |
| Storage      | SQLite via `sqlite-utils`; `pydantic` schemas                  |
| Scheduling   | GitHub Actions cron                                            |
| Tracking     | GitHub Issues + Projects; `gh` CLI                             |
| LLM (hybrid) | Local (Ollama / your free-LLM deploy) for cheap pre-filter; Grok + Perplexity as "smart scanners" for X / closed web; cloud free-tiers for deep analysis |
| Sandbox      | GitHub Pages / Vercel landings; Vercel / Render / Fly micro-MVPs |

## Quick start

```bash
# 1. Install (uv recommended; pip works too)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Initialise the SQLite database
sqlite3 data/rhr.db < data/schema.sql

# 3. Run the First Slice end-to-end (scan HN + RSS → classify → score)
python run.py scan      # fetch raw signals from configured sources
python run.py pipeline  # normalize → dedup → classify → score
python run.py track --dry-run   # preview candidates that would become issues
python run.py track              # actually create GitHub issues (needs `gh` auth)
```

## Layout

```
rhr/
├── collectors/        # one module per source, all implement Collector
├── pipeline/          # normalize, dedup, classify, score, track
├── scoring/           # weights.yaml (your hand on the pipe) + model.py
├── sandbox/           # demand_check landings, mvp_templates, metrics
├── data/              # SQLite DB + JSON dumps (gitignored except schema)
├── dashboard/         # static GitHub Pages site
├── config/            # sources.yaml, keywords.yaml
└── .github/workflows/ # cron scan + classify/score jobs
```

## Funnel stages

| Stage | Meaning                                                          |
|-------|------------------------------------------------------------------|
| L0    | Raw item fetched from a source                                   |
| L1    | Normalised into a unified `Signal`, deduplicated                 |
| L2    | Classified + scored; candidate extracted                         |
| L3    | Demand-check: SEO/competition analysis + landing + email capture |
| L4    | Micro-MVP vibe-coded from a template, deployed, metrics tracked  |
| L5    | Prod: real resources committed                                   |

## Status

**Phase 1 — First Slice** (in progress): HN + RSS collectors → normalize/dedup
→ LLM classification stub → scoring → GitHub Issue creation. End-to-end
pipeline on the cheapest path before breadth is added.

See `PLAN.md` for the full roadmap (phases, budget, sandbox design).
