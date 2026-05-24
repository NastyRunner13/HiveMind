# AGENT.md — AI Agent Guidelines for HiveMind 🐝

> This document provides context and guidelines for AI coding agents (Copilot, Cursor, Claude, etc.) working on the HiveMind codebase.

---

## Project Overview

**HiveMind** is an AI Team Intelligence Agent built with a two-phase architecture:

- **Phase 1 (Current)**: Core Intelligence — daily summaries, knowledge retrieval, task management, proactive nudges, onboarding, and knowledge transfer. Uses FastAPI + PostgreSQL + Slack Bolt.
- **Phase 2 (Planned)**: Self-Improving Skills Engine — HiveMind learns team workflows and crystallizes them into reusable, version-controlled skills.

**Key Architectural Constraint**: Phase 1 features are **independent and self-contained**. Phase 2 **enhances** but never replaces them. If the Skills Engine is disabled, every feature continues working exactly as designed.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+ / FastAPI |
| Database | PostgreSQL 16 (async via `asyncpg` + SQLAlchemy 2.0) |
| Migrations | Alembic |
| Bot | Slack Bolt (Socket Mode for dev, Events API for prod) |
| Config | Pydantic Settings (`.env` file) |
| Deployment | Docker + docker-compose |

---

## Project Structure

```
HiveMind/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI route handlers (thin layer)
│   │   ├── models/           # SQLAlchemy ORM models (source of truth)
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── services/         # Business logic (testable, no HTTP dependency)
│   │   ├── slack/            # Slack bot, events, and sync modules
│   │   ├── config.py         # Settings via pydantic-settings
│   │   ├── database.py       # Async SQLAlchemy engine + session factory
│   │   └── main.py           # FastAPI app with lifespan management
│   ├── tests/                # Test suite (modular, per-integration)
│   │   ├── conftest.py       # Root-level shared fixtures
│   │   └── slack/            # Slack integration tests
│   │       ├── conftest.py   # Slack-specific fixtures & sample events
│   │       ├── test_bot.py   # Bot lifecycle tests (9 tests)
│   │       ├── test_events.py# Event handler tests (17 tests)
│   │       ├── test_sync.py  # Sync utility tests (16 tests)
│   │       └── test_live.py  # Live Slack API integration tests (7 tests)
│   ├── alembic/              # Database migration scripts
│   ├── pytest.ini            # Pytest configuration (asyncio auto mode)
│   ├── requirements.txt
│   └── .env.example
├── docker-compose.yml        # PostgreSQL dev infrastructure
├── README.md
├── CONTRIBUTING.md
└── .gitignore
```

---

## Architecture Principles

When modifying this codebase, follow these architectural rules:

### 1. Layered Architecture

```
API Routes (thin) → Services (business logic) → Models (database)
     ↑                                              ↑
  Schemas                                      Alembic migrations
```

- **API routes** validate input via Pydantic schemas, call services, return responses
- **Services** contain all business logic — they are HTTP-independent and testable
- **Models** are SQLAlchemy ORM classes that define the database schema
- **Never put business logic in route handlers**

### 2. Async-First

- All database operations use **async SQLAlchemy** with `asyncpg`
- Use `async def` for route handlers and service methods
- Use `AsyncSession` for database sessions (not sync `Session`)

### 3. Database Conventions

- **Table names**: `snake_case`, plural (e.g., `channels`, `file_metadata`)
- **Primary keys**: UUID v4 (`uuid.uuid4`), column name `id`
- **Timestamps**: All models inherit `created_at` and `updated_at` from `BaseModel`
- **Foreign keys**: Use `Mapped` with explicit `ForeignKey` references
- **Indexes**: Add indexes on columns used for lookups (e.g., `slack_id`)
- **Migrations**: Always generate via `alembic revision --autogenerate`

### 4. Configuration

- All settings are in `app/config.py` via `pydantic-settings`
- Environment variables are loaded from `.env` (never committed)
- Use `get_settings()` to access settings (cached via `@lru_cache`)
- Add new settings to both `config.py` AND `.env.example`

### 5. Security (Critical)

HiveMind handles sensitive team data. These rules are non-negotiable:

- **Never use a service account for file access** — always use OBO (On-Behalf-Of) token exchange
- **Vector store searches MUST include ACL metadata filters** — at the database level, not post-query
- **DMs are never indexed** unless both parties opt in
- **Every file access must be logged** to the audit trail
- **Tokens must be encrypted at rest** and short-lived
- **Never cache file content in shared caches** — cache per-user or don't cache

### 6. Slack Integration

- Slack bot is initialized in `app/slack/bot.py` using `slack-bolt`
- Event handlers are in `app/slack/events.py`
- Historical data sync is in `app/slack/sync.py`
- Socket Mode is used for local development (no public URL needed)
- The bot's lifecycle is managed via FastAPI's `lifespan` context

### 7. Testing

- Tests are organized modularly under `backend/tests/` with **subpackages per integration** (e.g., `tests/slack/`)
- Each subpackage has its own `conftest.py` for integration-specific fixtures
- **Unit tests** use `unittest.mock` with `AsyncMock` for mocked Slack API responses — no credentials needed
- **Live integration tests** hit the real Slack API using credentials from `.env` — run separately with `-s` for output
- Use `pytest-asyncio` with `asyncio_mode = auto` (configured in `pytest.ini`)
- Test filenames: drop the integration prefix (e.g., `test_bot.py` not `test_slack_bot.py`) since the subfolder provides context
- When adding a new integration, create `tests/<integration>/` with its own `conftest.py`

---

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Python files | `snake_case.py` | `channel_service.py` |
| Classes | `PascalCase` | `FileMetadata` |
| Functions/methods | `snake_case` | `sync_channels()` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRIES` |
| Database tables | `snake_case` plural | `file_metadata` |
| API routes | `kebab-case` | `/api/v1/file-metadata` |
| Environment vars | `UPPER_SNAKE_CASE` | `SLACK_BOT_TOKEN` |

---

## Common Tasks for Agents

### Adding a New API Endpoint

1. Create/update the route handler in `backend/app/api/`
2. Create Pydantic schemas in `backend/app/schemas/`
3. Implement business logic in `backend/app/services/`
4. Register the route in `backend/app/api/router.py`

### Adding a New Database Model

1. Create the model in `backend/app/models/`
2. Import it in `backend/app/models/__init__.py`
3. Generate migration: `alembic revision --autogenerate -m "add <model>"`
4. Create corresponding schemas in `backend/app/schemas/`

### Adding a New Slack Event Handler

1. Add the handler in `backend/app/slack/events.py`
2. Register it with the Slack app in the `register_events()` function
3. Create/update the ingestion service in `backend/app/services/ingestion.py`

### Adding Tests for an Integration

1. Create a test subpackage: `backend/tests/<integration>/`
2. Add `__init__.py` and `conftest.py` with integration-specific fixtures
3. Write unit tests with mocked API responses (no real credentials needed)
4. Write live integration tests (skipped automatically if credentials are missing)
5. Run: `python -m pytest tests/<integration>/ -v`

### Adding a New Integration (Phase 1)

1. Create a new module: `backend/app/integrations/<platform>/`
2. Include: `client.py` (API client), `models.py` (platform-specific models), `sync.py` (data sync)
3. Add credentials to `config.py` and `.env.example`
4. Register with the event bus for real-time updates

---

## Dependencies

### Current (requirements.txt)

| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `sqlalchemy[asyncio]` | ORM with async support |
| `asyncpg` | PostgreSQL async driver |
| `alembic` | Database migrations |
| `slack-bolt` | Slack bot framework |
| `slack-sdk` | Slack API client |
| `pydantic-settings` | Configuration management |
| `python-dotenv` | `.env` file loader |
| `httpx` | Async HTTP client |
| `pytest` | Test framework |
| `pytest-asyncio` | Async test support |

### Planned (Not Yet Installed)

| Package | Purpose | Phase |
|---------|---------|-------|
| `langchain` | LLM orchestration | 1 |
| `langgraph` | Agent workflow graphs | 1 |
| `pgvector` | Vector embeddings in PostgreSQL | 1 |
| `redis` | Cache + event bus (Redis Streams) | 1 |
| `qdrant-client` | Vector database (at scale) | 1 |

---

## Commit & Branch Conventions

See [CONTRIBUTING.md](CONTRIBUTING.md) for full details. Quick reference:

- **Branches**: `feature/`, `fix/`, `refactor/`, `docs/`, `chore/`
- **Commits**: Conventional Commits — `feat(scope): description`
- **PRs**: Squash and merge to `main`

---

## Current State (What's Been Built)

| Component | Status | Notes |
|-----------|--------|-------|
| FastAPI app with lifespan | ✅ Complete | `app/main.py` |
| Settings / config | ✅ Complete | `app/config.py` |
| Async database engine | ✅ Complete | `app/database.py` |
| Models: User, Channel, Message, FileMetadata, Workspace | ✅ Complete | `app/models/` |
| Pydantic schemas | ✅ Complete | `app/schemas/` |
| Alembic initial migration | ✅ Complete | `alembic/versions/` |
| Slack bot (Socket Mode) | ✅ Complete | `app/slack/bot.py` |
| Slack event handlers | ✅ Complete | `app/slack/events.py` |
| Slack historical sync | ✅ Complete | `app/slack/sync.py` |
| Ingestion service | ✅ Complete | `app/services/ingestion.py` |
| API: health, channels, messages | ✅ Complete | `app/api/` |
| Docker Compose (PostgreSQL) | ✅ Complete | `docker-compose.yml` |
| **Slack unit tests** (42 tests) | ✅ Complete | `tests/slack/test_bot.py`, `test_events.py`, `test_sync.py` |
| **Slack live integration tests** (7 tests) | ✅ Complete | `tests/slack/test_live.py` — verified against real workspace |
| **Slack API connectivity** | ✅ Verified | Bot token, read/write messages, list channels/users all working |

---

## What's Next (Upcoming Work)

Based on the Phase 1 roadmap priority:

1. **Knowledge Fabric** — pgvector integration, embeddings, semantic search
2. **Redis Streams Event Bus** — decouple ingestion from processing
3. **Daily Digest** — channel summary generation with LLM
4. **RBAC** — role model, OBO token exchange, ACL-scoped vector search
5. **Task Management** — Planner/Jira integration
6. **Proactive Nudges** — scheduled behaviors and triggers

---

## Running Tests

```bash
# From backend/ directory with venv activated:

# Run ALL unit tests (no Slack credentials needed)
python -m pytest tests/slack/test_bot.py tests/slack/test_events.py tests/slack/test_sync.py -v

# Run Slack live integration tests (requires .env with valid SLACK_BOT_TOKEN)
python -m pytest tests/slack/test_live.py -v -s

# Run everything
python -m pytest -v -s

# Run only unit tests (skip live tests)
python -m pytest tests/ -v --ignore=tests/slack/test_live.py
```

### Slack Test Setup (for live tests)

1. Ensure `.env` has valid `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN`
2. Create a `#hivemind-test` channel in your Slack workspace
3. Invite the bot (`@HiveMind`) to the channel
4. Post at least one message in the channel
5. Live tests will post a timestamped test message and read it back

---

## Do's and Don'ts

### ✅ Do

- Use async patterns everywhere (async def, AsyncSession, await)
- Add type hints to all function signatures
- Write Google-style docstrings for public functions
- Create Alembic migrations for any model changes
- Follow Conventional Commits for git messages
- Add new settings to both `config.py` and `.env.example`
- Keep API route handlers thin — delegate to services
- Use `Mapped[]` type annotations for SQLAlchemy columns

### ❌ Don't

- Don't put business logic in API route handlers
- Don't use synchronous database operations
- Don't hardcode configuration values — use Settings
- Don't import from `app.main` in other modules (circular imports)
- Don't skip Alembic — never modify the database schema manually
- Don't commit `.env` files — only `.env.example`
- Don't use a service account for user file access (security violation)
- Don't cache content in shared caches without per-user isolation
