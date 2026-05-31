# AGENTS.md — AI Agent Guidelines for HiveMind 🐝

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
| Database | PostgreSQL 16 + pgvector (async via `asyncpg` + SQLAlchemy 2.0) |
| Vector Store | pgvector (co-located with relational data) |
| Migrations | Alembic |
| AI / LLM | LangChain + LangGraph (provider-agnostic: OpenAI, Google, Anthropic, Ollama) |
| Event Bus | Redis 7 (Redis Streams for durable event routing) |
| Scheduling | APScheduler (async, cron-like daily digest) |
| Bot | Slack Bolt (Socket Mode for dev, Events API for prod) |
| Config | Pydantic Settings (`.env` file) |
| Deployment | Docker + docker-compose |

---

## Project Structure

```
HiveMind/
├── backend/
│   ├── app/
│   │   ├── agent/            # AI Agent (LangChain + LangGraph)
│   │   │   ├── llm.py        # LLM factory (OpenAI/Google/Anthropic/Ollama)
│   │   │   ├── tools.py      # LangChain tools — per-request factory with ACL closures
│   │   │   ├── prompts.py    # System prompts & safety instructions
│   │   │   └── graph.py      # LangGraph ReAct agent (per-request, user-scoped)
│   │   ├── api/              # FastAPI route handlers (thin layer)
│   │   │   ├── health.py     # Health check endpoint
│   │   │   ├── channels.py   # Channel CRUD
│   │   │   ├── messages.py   # Message queries
│   │   │   ├── knowledge.py  # Semantic search (ACL via authenticated principal)
│   │   │   ├── digests.py    # Digest generation & listing
│   │   │   └── router.py     # Route aggregator
│   │   ├── events/           # Redis Streams event bus
│   │   │   ├── bus.py        # EventBus with publish/subscribe
│   │   │   ├── contracts.py  # Versioned platform-neutral payload contracts
│   │   │   └── consumers.py  # Background consumers (knowledge indexing)
│   │   ├── integrations/     # Platform connector boundary
│   │   │   ├── base.py       # BasePlatformConnector protocol + DTOs
│   │   │   └── slack/        # Slack connector compatibility adapter
│   │   ├── models/           # SQLAlchemy ORM models (source of truth)
│   │   │   ├── base.py       # Base model with UUID + timestamps
│   │   │   ├── workspace.py  # Slack workspace
│   │   │   ├── channel.py    # Slack channels
│   │   │   ├── user.py       # Slack users
│   │   │   ├── message.py    # Ingested messages
│   │   │   ├── file_metadata.py # File metadata index
│   │   │   ├── embedding.py  # DocumentChunk with pgvector + ACL
│   │   │   ├── digest.py     # Generated channel summaries
│   │   │   ├── identity.py   # Canonical users/platform/auth mappings
│   │   │   └── membership.py # Channel membership for ACL enforcement
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── security/         # OIDC authentication (Keycloak / Auth0 / any provider)
│   │   ├── services/         # Business logic (testable, no HTTP dependency)
│   │   │   ├── ingestion.py  # Slack event → DB pipeline + event bus
│   │   │   ├── embedding_service.py  # Text chunking + embedding
│   │   │   ├── knowledge_service.py  # ACL-aware semantic search + idempotent indexing
│   │   │   ├── membership_service.py # Channel membership management + ACL lookups
│   │   │   ├── agent_service.py      # Agent orchestrator (per-request scoped, per-tool audit logging)
│   │   │   ├── digest_service.py     # LLM-powered channel summaries (public + personalized on-demand)
│   │   │   └── scheduler.py          # APScheduler cron jobs (digest + membership sync, always active)
│   │   ├── slack/            # Slack bot, events, and sync modules
│   │   ├── config.py         # Settings via pydantic-settings
│   │   ├── database.py       # Async SQLAlchemy engine + session factory
│   │   └── main.py           # FastAPI app with lifespan management
│   ├── tests/                # Test suite (modular, per-integration)
│   │   ├── conftest.py       # Root-level shared fixtures
│   │   ├── agent/            # Agent/LangGraph tests
│   │   │   ├── test_graph.py       # Graph construction tests
│   │   │   ├── test_agent_service.py # Agent service tests
│   │   │   ├── test_agent_audit.py  # Per-tool audit logging tests
│   │   │   └── test_tool_security.py # ACL enforcement & negative security tests
│   │   ├── events/           # Event bus tests
│   │   │   └── test_consumers.py    # Knowledge indexing consumer tests
│   │   ├── services/         # Service-layer tests (digest, knowledge, etc.)
│   │   │   ├── test_digest_service.py    # Digest tests incl. private channel exclusion
│   │   │   ├── test_personalized_digest.py # On-demand personalized digest tests
│   │   │   ├── test_embedding_dimension_safety.py # Embedding dimension validation tests
│   │   │   ├── test_membership_service.py # Membership CRUD + bulk sync tests
│   │   │   └── test_scheduler.py         # Scheduler job registration + decoupling tests
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
├── docker-compose.yml        # PostgreSQL + pgvector + Redis dev infrastructure
├── tasks/                    # Task tracking (completed work, roadmap, status map)
├── concepts/                 # Product vision and concept documents
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
- **Enums**: Always specify `values_callable=lambda x: [e.value for e in x]` in `sa.Enum` columns to map Python Enums using their lowercase string values (avoiding `InvalidTextRepresentationError` mismatches with native PostgreSQL enum definitions).
- **Transaction atomicity**: Multi-table upserts (e.g., `SlackUser` → `User` → `UserPlatformMapping` in `ingest_user()`) must use a single `session.commit()` at the end. Use `session.flush()` between upserts to get persisted rows without closing the transaction. This prevents orphaned records when a downstream upsert fails (e.g., canonical `User` is never created but `SlackUser` is already committed).

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
- **Never accept caller-provided ACL context** (`user_id`, `channel_ids`, role) for privileged queries — always derive authorization from authenticated identity or server-side lookup
- **All agent tools must receive trusted server context** — the LLM must never control ACL-related tool arguments; inject verified user identity and channel memberships into tool closures
- **Global digests must exclude private channels** — posting private-channel summaries to a public digest channel is a data leak. Use `@HiveMind digest --me` or agent tool with `personalized=True` for ACL-scoped personalized digests
- **Every endpoint returning messages, files, chunks, or digests must enforce authorization** — no data access without verified identity
- **Embedding dimensions are schema-level decisions** — do not silently switch dimensions via `.env`; dimension changes require explicit Alembic migrations. The app validates `EMBEDDING_DIMENSIONS == SCHEMA_EMBEDDING_DIMENSIONS` at startup and refuses to start on mismatch

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
| `langchain-core` | LLM orchestration core |
| `langchain-openai` | OpenAI LLM/embedding provider |
| `langchain-community` | Community LLM integrations |
| `langgraph` | Agent workflow graphs (ReAct) |
| `pgvector` | Vector embeddings in PostgreSQL |
| `tiktoken` | Token counting for text chunking |
| `redis[hiredis]` | Event bus (Redis Streams) + cache |
| `apscheduler` | Cron-like async scheduling |
| `PyJWT[crypto]` | OIDC bearer token signature/claim validation (Keycloak, Auth0, etc.) |
| `pytest` | Test framework |
| `pytest-asyncio` | Async test support |
| `sentence-transformers` | Local embedding models (default: all-MiniLM-L6-v2, 384 dimensions) |
| `langchain-google-genai` | Google Gemini LLM provider |
| `langchain-anthropic` | Anthropic Claude LLM provider |
| `langchain-ollama` | Ollama local LLM provider |

### Planned (Not Yet Installed)

| Package | Purpose | Phase |
|---------|---------|-------|
| `qdrant-client` | Vector database (at scale, replaces pgvector) | 2 |

---

## Commit & Branch Conventions

See [CONTRIBUTING.md](CONTRIBUTING.md) for full details. Quick reference:

- **Branches**: `feature/`, `fix/`, `refactor/`, `docs/`, `chore/`
- **Commits**: Conventional Commits — `feat(scope): description`
- **PRs**: Squash and merge to `main`

---

## Current State & Roadmap

> **Detailed task tracking has been moved to the [`tasks/`](tasks/) directory.** This section is a compact summary for quick orientation.

### What's Built (Milestones 1–5 Complete)

| Milestone | Summary | Test Count |
|-----------|---------|------------|
| **M1: Foundation** | FastAPI + Slack bot + ingestion + CI pipeline | 44 Slack unit + 7 live |
| **M2: Core Intelligence** | Redis event bus + pgvector knowledge fabric + LangGraph agent + daily digest + APIs | — |
| **M3: Security & Indexing** | Semantic indexing consumer + channel memberships + ACL-scoped agent tools + safe digests + embedding safety | 53 |
| **M4: Multi-Platform Foundation** | OIDC auth + canonical identities + protected APIs + connector boundary + normalized events | — |
| **M5: RAG Hardening** | Workspace propagation + source-time filters + bounded tool args + activity summary tool + deletion handling | — |
| **Total non-live tests** | **222 passing** (May 31, 2026) | |

For detailed component-by-component breakdown, see [`tasks/completed.md`](tasks/completed.md).

### What's Next

| Priority | Work Item | Details |
|----------|-----------|---------|
| **P0** | Run Alembic migration `0004` against PostgreSQL + pgvector | ✅ Verified (applied and active) |
| **P0** | Run Slack live regression tests | ✅ Verified (all tests passing) |
| **P1** | Complete Slack internal canonical cutover | Remove remaining compatibility lookups |
| **P1** | Remove legacy event fallback | After queue drain + Slack/Teams parity |
| **P2** | Microsoft Graph Teams connector | First additional platform |
| **P2** | Planner/OneDrive + OBO file access | After normalized Slack+Teams ingestion |
| **P2** | Feature expansion: Tasks, Nudges, Onboarding, KT | See concept §3, §5, §7, §8 |
| **Phase 2** | Self-Improving Skills Engine | After real-user Phase 1 stability |

For the full roadmap with checkboxes, see [`tasks/roadmap.md`](tasks/roadmap.md).
For a feature-by-feature status map against the concept doc, see [`tasks/status.md`](tasks/status.md).

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

### Windows Local Setup

If the local Python virtual environment is broken (e.g., `.venv` points to a missing Python executable):

```powershell
# From the project root:
Remove-Item -Recurse -Force backend\.venv
python -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

# Verify:
cd backend
python -m pytest tests/ -v --ignore=tests/slack/test_live.py
```

---

## Do's and Don'ts

### ✅ Do

- Use async patterns everywhere (async def, AsyncSession, await)
- Always use .venv virtual enviroment
- Add type hints to all function signatures
- Write Google-style docstrings for public functions
- Create Alembic migrations for any model changes
- Follow Conventional Commits for git messages
- Add new settings to both `config.py` and `.env.example`
- Keep API route handlers thin — delegate to services
- Use `Mapped[]` type annotations for SQLAlchemy columns
- Always specify `values_callable=lambda x: [e.value for e in x]` on all `sa.Enum` columns mapped to Python Enums to keep names/values aligned with Postgres.

### ❌ Don't

- Don't put business logic in API route handlers
- Don't use synchronous database operations
- Don't hardcode configuration values — use Settings
- Don't import from `app.main` in other modules (circular imports)
- Don't skip Alembic — never modify the database schema manually
- Don't commit `.env` files — only `.env.example`
- Don't use a service account for user file access (security violation)
- Don't cache content in shared caches without per-user isolation
