# CLAUDE.md — RHR (Rabbit Hole Radar)

## Начало каждой сессии

1. Прочитай этот файл целиком (он короткий и содержит rules/constraints)
2. Прочитай `memory/MEMORY.md` — основная память проекта
3. Проверь статус: `python3 run.py status`
4. Запусти тесты: `python3 -m pytest --tb=short -q`

## Что такое RHR

Система автоматического сбора и анализа бизнес-возможностей:
- **Passive income** — пассивный доход
- **Micro SaaS** — маленькие SaaS-продукты
- **AI wrappers** — обёртки над ИИ с монетизацией
- **DeFi yield** — доходность в децентрализованных финансах
- **Automation** — боты и скрипты с монетизацией

Архитектура: Repo-as-database (SQLite), GitHub Actions для пайплайна.

## Архитектура

```
Коллекторы (8 шт) → signals (SQLite) → LLM-классификатор → candidates → GitHub Issues
     ↓                                                                    ↓
  Dedup                                                 Dashboard / Telegram
```

### Коллекторы (собирают сигналы)
| Коллектор | Источник | Расписание |
|-----------|----------|------------|
| hackernews | HN API (front, show, ask, best) | каждые 30 мин |
| reddit | Reddit RSS (7 сабреддитов) | каждые 30 мин |
| rss | IndieHackers, HN, ProductHunt | каждые 4 часа |
| youtube | YouTube Data API v3 | 2x/день |
| producthunt | Product Hunt GraphQL | 1x/день |
| defillama | DeFiLlama API | каждые 6 часов |
| gumroad | Gumroad products | каждые 6 часов |
| telegram | t.me/s/ скрап (12 каналов) | 2x/день |
| **x_via_grok** | Grok Task → JSON в signals/incoming/ | 1x/день |

### Пайплайн
```
signals (kept) → dedup → classify (LLM) → score → candidates (L2-scored)
```

### Воронка
```
L2-scored → L3-demand-check → L4-micro-MVP → L5-prod → archived
```

## CLI команды

```bash
python3 run.py init              # Применить schema.sql
python3 run.py scan              # Все коллекторы
python3 run.py scan hackernews   # Один коллектор
python3 run.py pipeline          # dedup → classify → score
python3 run.py status            # Статус по воронке
python3 run.py track --dry-run   # Preview GitHub issues
python3 run.py score --rescore   # Пересчитать скоры
python3 run.py ingest-stdin      # JSON lines → signals
```

## Rules

- НЕ коммитить `.env` или токены
- Все enum-поля должны иметь CHECK constraints в schema.sql + runtime validation
- `MIN_SCORE_TO_TRACK = 0.05`
- LLM-выход валидируется через whitelist enum + `math.isnan/isinf`
- `summary` от LLM ≤ 280 символов
- CLI: только `python3` (не `python`)
- DB коммитится workflows (PRAGMA wal_checkpoint(TRUNCATE) перед git add)
- `data/rhr.db` — НЕ в .gitignore (repo-as-database pattern)

## Grok Pipeline

- Grok Task ищет в X/Twitter + глубокий интернет (форумы, отзывы)
- Записывает JSON в `signals/incoming/grok_<ДАТА>.json`
- Watchdog проверяет наличие файла в 22:00 НСК, шлёт Telegram-пинок
- Ingest: 22:30 НСК, `grok_ingest.py` → `run.py ingest-stdin` → pipeline
- Дедупликация: normalize_url (strip UTM) → проверка signals.url в БД

## Пороги

| Параметр | Значение |
|----------|----------|
| Grok score (в промте) | 60/100 |
| Grok engagement | 100 лайков = сигнал |
| MIN_SCORE_TO_TRACK | 0.05 |
| YouTube quota | 8000 units/день (*/12) |
| HN min_points | 15 |
| Reddit min_score | 10 |

## Инфраструктура

- **Repo**: github.com/mat3213-glitch/rhr (публичный)
- **LLM Backend**: GitHub Models (`models.inference.ai.azure.com`) через `gh auth token`
- **Secrets**: YOUTUBE_API_KEY, PRODUCTHUNT_API_TOKEN в GitHub Secrets
- **DB**: `data/rhr.db` коммитится workflows
- **Dashboard**: `dashboard/index.html` (Chart.js)
- **Тесты**: 356+, `python3 -m pytest`

## Конвенции

- Python 3.12+, type hints, `from __future__ import annotations`
- Коллекторы декорированы `@register`, наследуют `Collector`
- Единый HTTP-клиент: `collectors/http_util.py` с SSRF-защитой
- Prompt injection defense: `<input>` теги + system instruction
- Checkout: `actions/checkout@v4`, Python: `actions/setup-python@v5`

## Контекст сессии

- Последний аудит: 2026-07-05, все 49 находок исправлены
- Grok Pipeline запущен: 2026-07-10, первый боевой прогон
- Репо сделан публичным: 2026-07-10 (для Grok MCP доступа)
- YouTube ключ: в .env + GitHub Secrets
- WATCHDOG: 22:00 НСК, INGEST: 22:30 НСК
