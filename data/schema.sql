-- Rabbit Hole Radar — SQLite schema
-- Apply with:  sqlite3 data/rhr.db < data/schema.sql
-- Idempotent (IF NOT EXISTS). Bump SCHEMA_VERSION when changing.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ───────────────────────────── metadata ─────────────────────────────
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1');

-- ───────────────────────────── L0/L1: signals ─────────────────────────────
-- A raw item fetched from a source, after normalisation. The grain of truth.
CREATE TABLE IF NOT EXISTS signals (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  source          TEXT    NOT NULL,              -- 'hackernews', 'rss', 'reddit', ...
  source_item_id  TEXT    NOT NULL,              -- id within the source (HN item id, RSS guid, ...)
  url             TEXT,
  title           TEXT,
  body_text       TEXT,                          -- normalised, de-HTML'd, truncated
  author          TEXT,
  fetched_at      TEXT    NOT NULL,              -- ISO8601 UTC
  published_at    TEXT,                          -- ISO8601 UTC, when the item was originally posted
  language        TEXT,                          -- ISO 639-1, e.g. 'en','ru'
  points          INTEGER,                       -- upvotes / karma / score at fetch time (nullable)
  comments_count  INTEGER,
  matched_groups  TEXT,                          -- JSON array of keyword groups that triggered L0 (e.g. ["money_making","build_intent"])
  embedded_links  TEXT,                          -- JSON array of URLs found in body
  dedup_key       TEXT,                          -- normalised hash for fuzzy dedup (see dedup.py)
  is_duplicate_of INTEGER,                       -- FK -> signals.id of the canonical signal, or NULL
  l1_status       TEXT    NOT NULL DEFAULT 'new',-- new | kept | duplicate | low_quality
  created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  FOREIGN KEY (is_duplicate_of) REFERENCES signals(id),
  UNIQUE (source, source_item_id)                -- never insert the same source item twice
);
CREATE INDEX IF NOT EXISTS idx_signals_source        ON signals(source);
CREATE INDEX IF NOT EXISTS idx_signals_l1_status     ON signals(l1_status);
CREATE INDEX IF NOT EXISTS idx_signals_dedup_key     ON signals(dedup_key);
CREATE INDEX IF NOT EXISTS idx_signals_fetched_at    ON signals(fetched_at);

-- ───────────────────────────── L2: candidates ─────────────────────────────
-- An extracted money-making idea, derived from one or more signals.
CREATE TABLE IF NOT EXISTS candidates (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  title                 TEXT    NOT NULL,                 -- short, human-readable: "Telegram bot that does X"
  summary               TEXT,                             -- 1-3 sentence what/why
  category              TEXT,                             -- crypto_defi | digital_asset | arbitrage | algo | other
  method_type           TEXT,                             -- staking | micro_saas | ai_wrapper | bot | content | ...
  passive_level         TEXT,                             -- hands_off | semi_passive | flip
  est_roi_band          TEXT,                             -- very_low | low | medium | high | very_high
  risk_band             TEXT,                             -- very_low | low | medium | high | very_high
  time_to_setup         TEXT,                             -- hours | day | weekend | week | month
  vibe_codability_score REAL    NOT NULL DEFAULT 0.5,     -- 0..1 how vibe-codable into a fast digital product
  trend_velocity        REAL    NOT NULL DEFAULT 0.0,     -- 0..1 momentum from source volume/recency
  passive_fit           REAL,                             -- 0..1 set by classifier from passive_level
  roi_potential         REAL,                             -- 0..1 set by classifier from est_roi_band
  risk                  REAL,                             -- 0..1 set by classifier from risk_band
  speed_to_setup        REAL,                             -- 0..1 set by classifier from time_to_setup
  score                 REAL,                             -- final composite score (see scoring/model.py)
  funnel_stage          TEXT    NOT NULL DEFAULT 'L2-scored', -- L2-scored | L3-demand-check | L4-mvp | L5-prod | archived
  archive_reason        TEXT,                             -- why it was killed (enriches scoring later)
  github_issue_number   INTEGER,                          -- issue created by track.py
  first_seen_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_candidates_stage   ON candidates(funnel_stage);
CREATE INDEX IF NOT EXISTS idx_candidates_score   ON candidates(score DESC);

-- Many-to-many: which signals fed a candidate.
CREATE TABLE IF NOT EXISTS candidate_signals (
  candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  signal_id    INTEGER NOT NULL REFERENCES signals(id)    ON DELETE CASCADE,
  weight       REAL    NOT NULL DEFAULT 1.0,              -- how central this signal was to extraction
  PRIMARY KEY (candidate_id, signal_id)
);
CREATE INDEX IF NOT EXISTS idx_cs_signal ON candidate_signals(signal_id);

-- ───────────────────────────── L3/L4: sandbox runs ─────────────────────────────
-- One row per sandbox experiment (a demand-check landing OR a micro-MVP deployment).
CREATE TABLE IF NOT EXISTS sandbox_runs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id    INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  stage           TEXT    NOT NULL,                  -- demand_check | micro_mvp
  url             TEXT,                              -- deployed landing/app URL
  deployed_at     TEXT,
  metrics_json    TEXT,                              -- freeform JSON: visits, signups, conv, revenue...
  verdict         TEXT,                              -- go | no_go | pending
  verdict_reason  TEXT,
  created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_sandbox_candidate ON sandbox_runs(candidate_id);

-- ───────────────────────────── scoring feedback ─────────────────────────────
-- When a candidate graduates or dies, record the outcome so the scoring
-- model can be re-tuned (feedback loop from prod → scoring).
CREATE TABLE IF NOT EXISTS scoring_feedback (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id    INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  outcome         TEXT    NOT NULL,                  -- graduated | killed_demand | killed_mvp | killed_manual
  actual_roi      REAL,                              -- realised, if known
  actual_passive  REAL,                              -- 0..1 how hands-off it turned out
  note            TEXT,
  created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ───────────────────────────── run log ─────────────────────────────
-- Cheap observability: what ran when, how many rows produced/changed.
CREATE TABLE IF NOT EXISTS run_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  command       TEXT NOT NULL,                       -- scan:hackernews | pipeline | track ...
  source        TEXT,
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  status        TEXT NOT NULL,                       -- ok | error
  rows_inserted INTEGER DEFAULT 0,
  rows_updated  INTEGER DEFAULT 0,
  message       TEXT
);
