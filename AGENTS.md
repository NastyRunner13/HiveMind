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
│   │   │   ├── knowledge.py  # Semantic search (ACL via X-Slack-User-Id header)
│   │   │   ├── digests.py    # Digest generation & listing
│   │   │   └── router.py     # Route aggregator
│   │   ├── events/           # Redis Streams event bus
│   │   │   ├── bus.py        # EventBus with publish/subscribe
│   │   │   └── consumers.py  # Background consumers (knowledge indexing)
│   │   ├── models/           # SQLAlchemy ORM models (source of truth)
│   │   │   ├── base.py       # Base model with UUID + timestamps
│   │   │   ├── workspace.py  # Slack workspace
│   │   │   ├── channel.py    # Slack channels
│   │   │   ├── user.py       # Slack users
│   │   │   ├── message.py    # Ingested messages
│   │   │   ├── file_metadata.py # File metadata index
│   │   │   ├── embedding.py  # DocumentChunk with pgvector + ACL
│   │   │   ├── digest.py     # Generated channel summaries
│   │   │   └── membership.py # Channel membership for ACL enforcement
│   │   ├── schemas/          # Pydantic request/response schemas
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

## Current State (What's Been Built)

### Foundation (Milestone 1 — Complete)

| Component | Status | Notes |
|-----------|--------|-------|
| FastAPI app with lifespan | ✅ Complete | `app/main.py` — manages DB, Redis, Slack, Scheduler lifecycle |
| Settings / config | ✅ Complete | `app/config.py` — Redis, LLM, Embedding, Digest settings |
| Async database engine | ✅ Complete | `app/database.py` |
| Models: User, Channel, Message, FileMetadata, Workspace | ✅ Complete | `app/models/` |
| Pydantic schemas | ✅ Complete | `app/schemas/` |
| Alembic initial migration | ✅ Complete | `alembic/versions/0001_initial_schema.py` |
| Slack bot (Socket Mode) | ✅ Complete | `app/slack/bot.py` |
| Slack event handlers | ✅ Complete | `app/slack/events.py` — @mentions route through AI agent |
| Slack historical sync | ✅ Complete | `app/slack/sync.py` |
| Ingestion service | ✅ Complete | `app/services/ingestion.py` — publishes events to Redis |
| API: health, channels, messages | ✅ Complete | `app/api/` |
| Docker Compose (PostgreSQL) | ✅ Complete | `docker-compose.yml` |
| **Slack unit tests** (44 tests) | ✅ Complete | `tests/slack/` — expected to pass in CI; verify locally after venv recreation |
| **Slack live integration tests** (7 tests) | ✅ Complete | `tests/slack/test_live.py` |
| **Slack API connectivity** | ✅ Verified | Bot token, read/write, channels/users all working |
| CI/CD pipeline | ✅ Complete | `.github/workflows/ci.yml` — lint, test, Docker build |

### Core Intelligence (Milestone 2 — Complete)

| Component | Status | Notes |
|-----------|--------|-------|
| **Redis Event Bus** | ✅ Complete | `app/events/bus.py` — Redis Streams publish/subscribe |
| **Knowledge Fabric (pgvector)** | ✅ Complete | `app/models/embedding.py`, `app/services/knowledge_service.py` |
| **Embedding Service** | ✅ Complete | `app/services/embedding_service.py` — local sentence-transformers (384 dims) |
| **AI Agent (LangGraph)** | ✅ Complete | `app/agent/` — ReAct agent with 5 ACL-scoped tools |
| **Daily Digest** | ✅ Complete | `app/services/digest_service.py`, `app/services/scheduler.py` — public-only, source-channel delivery |
| **Knowledge API** | ✅ Complete | `POST /api/v1/knowledge/search`, `GET /api/v1/knowledge/status` |
| **Digest API** | ✅ Complete | `POST /api/v1/digests/generate`, `GET /api/v1/digests` |
| **Alembic migration 0002** | ✅ Complete | pgvector extension + `document_chunks` + `digests` tables |
| **Docker Compose** | ✅ Complete | Added Redis 7, switched to `pgvector/pgvector:pg16` |
| **CI pipeline** | ✅ Complete | pgvector image + Redis service in CI |

### Security & Indexing (Milestone 3 — Complete, 174 tests passing)

| Component | Status | Notes |
|-----------|--------|-------|
| **Semantic indexing consumer** | ✅ Complete | `app/events/consumers.py` — Redis Streams consumer for `MESSAGE_INGESTED` and `MESSAGE_EDITED` events, launched as asyncio task in `main.py` lifespan |
| **Idempotent indexing** | ✅ Complete | `knowledge_service.is_already_indexed()` + `delete_chunks_for_source()` for re-indexing |
| **`channel_memberships` table** | ✅ Complete | `app/models/membership.py` + Alembic migration `0003` — denormalized Slack IDs for O(1) ACL lookups |
| **Membership service** | ✅ Complete | `app/services/membership_service.py` — real-time join/leave events + bulk sync + daily cron |
| **Server-derived ACL context** | ✅ Complete | `app_mention` handler resolves memberships server-side; Knowledge API uses `X-Slack-User-Id` header, no client-supplied ACL |
| **ACL-scoped agent tools** | ✅ Complete | `app/agent/tools.py` — `create_tools(user_slack_id, user_channel_ids)` factory returns closures; LLM cannot control ACL params |
| **Per-request agent graph** | ✅ Complete | `app/agent/graph.py` — `build_agent_graph(user_slack_id, user_channel_ids)` creates scoped tools per request |
| **Safe digests** | ✅ Complete | `digest_service.generate_daily_digest()` filters to `PUBLIC` channels only; `deliver_to_slack()` posts to source channel |
| **Personalized digests** | ✅ Complete | `digest_service.generate_personalized_digest()` — on-demand, includes private channels user is member of. Triggered via agent tool (`personalized=True`) or `@HiveMind digest --me` |
| **Per-tool audit logging** | ✅ Complete | `agent_service._extract_tool_call_details()` + `AGENT_TOOL_CALL` events published per tool invocation with user, tool name, args, and channel |
| **Embedding dimension safety** | ✅ Complete | `config.validate_embedding_dimensions()` — startup validation blocks boot if `EMBEDDING_DIMENSIONS != SCHEMA_EMBEDDING_DIMENSIONS` |
| **Scheduler decoupling** | ✅ Complete | Scheduler starts unconditionally in `main.py` — membership sync always runs, digest job guarded by `digest_enabled` |
| **Membership sync events** | ✅ Complete | `member_joined_channel` / `member_left_channel` handlers in `app/slack/events.py` |
| **Daily membership cron** | ✅ Complete | Scheduler runs `full_sync_all_channels` at 03:00 as safety net |
| **Security tests** | ✅ Complete | 7 tests in `tests/agent/test_tool_security.py` — no exposed ACL params, private channel denial, negative tests |
| **Audit logging tests** | ✅ Complete | 10 tests in `tests/agent/test_agent_audit.py` — tool call extraction, arg sanitization, event publishing |
| **Consumer tests** | ✅ Complete | 5 tests in `tests/events/test_consumers.py` — indexing, idempotency, missing fields, re-indexing |
| **Membership tests** | ✅ Complete | 7 tests in `tests/services/test_membership_service.py` — join/leave, bulk sync, edge cases |
| **Personalized digest tests** | ✅ Complete | 5 tests in `tests/services/test_personalized_digest.py` — membership lookup, private channel inclusion, edge cases |
| **Embedding safety tests** | ✅ Complete | 5 tests in `tests/services/test_embedding_dimension_safety.py` — match/mismatch validation, error messages |
| **Scheduler tests** | ✅ Complete | 9 tests in `tests/services/test_scheduler.py` — lifecycle, digest job, membership sync, decoupling |

---

## What's Next (Upcoming Work)

> **See [IMPLEMENTATION_REVIEW.md](IMPLEMENTATION_REVIEW.md) for the full gap analysis.** The priorities below are derived from that review, cross-referenced against `concepts/hivemind_concept_v3.md`.

### P0: Fix Local Verification

1. **Recreate local Python environment** — `backend/.venv` is broken (points to missing Python 3.12 install on Windows)
2. **Install dependencies** — `pip install -r requirements.txt`
3. **Run unit tests** — verify all tests pass locally before claiming CI-green
4. **Run Alembic migrations** — `alembic upgrade head` against local PostgreSQL with pgvector (now includes migration `0003` for `channel_memberships`)
5. **Fix Docker healthcheck** — Dockerfile points to `/api/v1/health` but app serves `/health`; update Docker to use `/health`

### ~~P0: Wire Semantic Indexing End-to-End~~ ✅ DONE

~~6. Add event consumer for `MESSAGE_INGESTED`~~ → `app/events/consumers.py` — Redis Streams consumer with event router
~~7. Make indexing idempotent~~ → `knowledge_service.is_already_indexed()` + `delete_chunks_for_source()`
~~8. Add integration test~~ → 5 tests in `tests/events/test_consumers.py`

### ~~P0: Make ACL Context Trustworthy~~ ✅ DONE

~~9. Add `channel_memberships` table~~ → `app/models/membership.py` + migration `0003`
~~10. Derive user/channel access server-side~~ → `app_mention` handler calls `membership_service.get_user_channel_ids()`
~~11. Remove client-supplied ACL authority~~ → Knowledge API uses `X-Slack-User-Id` header, no query param spoofing
~~12. Add negative tests~~ → 7 security tests in `tests/agent/test_tool_security.py`

### ~~P1: Lock Down Agent Tools~~ ✅ DONE

~~13. Inject trusted user context into tools~~ → `create_tools(user_slack_id, user_channel_ids)` closure factory
~~14. Apply ACL checks in all data-accessing tools~~ → All 5 tools check `user_channel_ids` for private channels
~~15. Log tool calls~~ → ✅ `agent_service._extract_tool_call_details()` walks LangGraph message history; `AGENT_TOOL_CALL` events published per tool invocation with user, tool name, args, and channel. Arg values truncated via `_sanitize_args()`. Tests in `tests/agent/test_agent_audit.py`.

### ~~P1: Make Digests Safe~~ ✅ DONE

~~16. Skip private channels in global digests~~ → `generate_daily_digest()` filters to `ChannelType.PUBLIC`
~~17. Post channel digests only to their source channel~~ → `deliver_to_slack()` resolves source channel first
~~18. Build personalized digests~~ → ✅ `digest_service.generate_personalized_digest(user_slack_id)` — on-demand only, queries user's channel memberships via `membership_service`, generates combined digest across all accessible channels (public + private). Triggered via agent tool (`personalized=True`) or `@HiveMind digest --me`. No cron, no pre-generation, no DB storage — returned directly. Tests in `tests/services/test_personalized_digest.py`.

### ~~P1: Embedding Dimension Safety~~ ✅ DONE

~~19. Treat embedding dimension as a schema-level decision~~ → ✅ Added `SCHEMA_EMBEDDING_DIMENSIONS` setting in `config.py`. `validate_embedding_dimensions()` method compares runtime `EMBEDDING_DIMENSIONS` against `SCHEMA_EMBEDDING_DIMENSIONS` and raises `SystemExit` with clear migration instructions on mismatch. Validated at startup in `main.py`.
~~20. Document the current default~~ → ✅ Updated `embedding.py` model docstring, `.env.example` with comprehensive comments, and `config.py` inline docs. Local: sentence-transformers (all-MiniLM-L6-v2, 384 dims). OpenAI: text-embedding-3-small (1536 dims, requires migration). Tests in `tests/services/test_embedding_dimension_safety.py`.

### ~~P1: Minor Issues Found During Review~~ ✅ DONE

~~21. Decouple membership sync from digest scheduler~~ → ✅ Removed `if settings.digest_enabled:` guard from `main.py`. Scheduler now starts unconditionally — membership sync cron always runs, digest job is guarded internally by `digest_enabled`. Updated `scheduler.py` docstring. Tests in `tests/services/test_scheduler.py`.
~~22. Add per-tool audit logging~~ → ✅ Same as item #15. `AGENT_TOOL_CALL` events + `tools_used` list in `AGENT_RESPONSE` event.

### P2: Prepare for Multi-Platform Support (Future)

23. **Add `Platform` enum** — `SLACK`, `TEAMS`, `DISCORD`, `EMAIL`, `JIRA`, `NOTION`
24. **Add platform-neutral internal entities** — abstract users, channels, messages with UUID-based internal IDs
25. **Add platform mapping tables** — `user_platform_mappings`, `workspace_integrations`
26. **Move Slack code under `integrations/slack/`** — keep new integrations behind adapter interfaces

### P2: Phase 1 Feature Expansion (After Core is Solid)

27. ~~**Personalized digests**~~ → ✅ Moved to P1 and completed (item #18)
28. **Task & Action Management** — Planner/Jira integration (see concept §3)
29. **Proactive Nudges** — scheduled behaviors and triggers (see concept §8)
30. **Onboarding Flow** — new team member knowledge transfer (see concept §5)
31. **Knowledge Transfer Engine** — project KT generation (see concept §7)

### Phase 2 (Future — After Phase 1 is Stable with Real Users)

32. **Self-Improving Skills Engine** — workflow pattern detection from event bus traces
33. **Skill Crystallization** — convert detected patterns into reusable, versioned skills
34. **Prerequisites**: Active users on Phase 1, Event Bus logging traces, stable core features, RBAC fully functional

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
