<p align="center">
  <h1 align="center">🐝 HiveMind</h1>
  <p align="center">
    <strong>AI Team Intelligence Agent</strong><br/>
    <em>An AI that doesn't just observe your team — it understands it.<br/>And the longer it runs, the smarter it gets.</em>
  </p>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#getting-started">Getting Started</a> •
  <a href="#development">Development</a> •
  <a href="#roadmap">Roadmap</a> •
  <a href="#contributing">Contributing</a>
</p>

---

## The Problem

Teams today are drowning in fragmented context:

- 🗂️ Decisions get buried in Slack threads nobody bookmarks
- 📁 Files float across Teams, email, Drive, and Notion with no unified view
- 🆕 New joiners spend **weeks** piecing together "how things work here"
- 📊 Task updates live in one tool, discussions in another, and the real context in someone's head
- 🤖 Every team has unique workflows, but every AI agent treats them the same

**HiveMind** is the always-on team member that absorbs all of this — and makes it actionable. And over time, it learns *how your specific team works* and gets better at it every single day.

---

## Features

### Phase 1 — Core Intelligence *(Current Focus)*

| Feature | Description |
|---------|-------------|
| 🔌 **Universal Integration Layer** | Connects to Slack, MS Teams, Jira, Planner, GitHub, Drive, and more |
| 🧠 **Knowledge Fabric** | Lazy-loaded file intelligence — metadata indexed, content fetched on-demand |
| ✅ **Task & Action Management** | Create, update, and complete tasks via natural language |
| 📊 **Daily Intelligence** | Personalized morning briefings with key discussions, tasks, and files |
| 🚀 **Onboarding Engine** | Automated Day 1–30 onboarding with curated reading lists and team intros |
| 🔐 **Role-Based Access Control** | Enterprise-grade RBAC with OBO token exchange — never leaks across permission boundaries |
| 🎓 **Knowledge Transfer** | Auto-generated KT docs with architecture decisions, tribal knowledge, and project history |
| 🤖 **Proactive Behaviors** | Anticipates needs — nudges about unreviewed files, overdue tasks, and sprint endings |

### Phase 2 — Self-Improving Skills Engine *(Planned)*

- 🧬 **Skills Engine** — reusable, version-controlled procedures that HiveMind creates and maintains
- 🔄 **Self-Improving Loop** — observe → extract → crystallize → reuse → improve
- 📦 **Default Skill Packs** — sprint-ops, onboarding, engineering, meeting intelligence
- 🏛️ **Skill Governance** — personal → team → org-wide promotion with approval gates

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  THE FIVE PILLARS OF HIVEMIND               │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐  │
│  │  MEMORY  │  │  SKILLS  │  │   SOUL   │  │    CRONS    │  │
│  │ Phase 1  │  │ Phase 2  │  │ Phase 1  │  │  Phase 1    │  │
│  └──────────┘  └──────────┘  └──────────┘  └─────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              SELF-IMPROVEMENT (Phase 2)              │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology | Status |
|-------|-----------|--------|
| **Backend** | Python 3.12+ / FastAPI | ✅ Implemented |
| **Database** | PostgreSQL 16 + pgvector | ✅ Implemented |
| **Vector Store** | pgvector (co-located) → Qdrant (at scale) | ✅ pgvector done |
| **Event Bus** | Redis 7 (Redis Streams) | ✅ Implemented |
| **AI / LLM** | LangChain + LangGraph (OpenAI, Google, Anthropic, Ollama) | ✅ Implemented |
| **Scheduling** | APScheduler (async cron) | ✅ Implemented |
| **Bot Framework** | Slack Bolt (Socket Mode + Events API) | ✅ Implemented |
| **Auth** | OIDC Bearer Token Validation (Keycloak, Auth0, etc.) | ✅ Implemented |
| **Deployment** | Docker + docker-compose (dev) → Kubernetes (prod) | ✅ Dev done |

---

## Getting Started

### Prerequisites

- **Python 3.12+**
- **Docker & Docker Compose** (for PostgreSQL)
- **Slack App** (optional — for Slack bot integration)

### 1. Clone the Repository

```bash
git clone https://github.com/NastyRunner13/HiveMind.git
cd HiveMind
```

### 2. Start Infrastructure (PostgreSQL + Redis + Keycloak)

```bash
docker-compose up -d
```

This starts:
- **PostgreSQL 16** with pgvector extension (`hivemind-db`)
- **Redis 7** for event bus and caching (`hivemind-redis`)
- **Keycloak 25.0** OIDC provider (`hivemind-keycloak`) for API authentication

### 3. Set Up the Backend

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings:
#   - Database connection (POSTGRES_PASSWORD)
#   - Slack credentials (SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, SLACK_APP_TOKEN)
#   - OIDC settings (OIDC_ISSUER_URL, OIDC_AUDIENCE) — required for REST API auth
#   - LLM API key (LLM_API_KEY) — required for AI agent & digests
#   - Redis URL (defaults to localhost:6379)
```

> [!NOTE]
> After starting Keycloak for the first time, navigate to the admin console at http://localhost:8080 (username/password: `admin`/`admin`). Create a realm named `hivemind` and a client with the same name, then configure your `.env` settings accordingly. See `docker-compose.yml` for configuration details.

### 5. Run Database Migrations

```bash
alembic upgrade head
```

### 6. Start the Application

```bash
uvicorn app.main:app --reload
```

The API will be available at:
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

---

## Project Structure

```
HiveMind/
├── backend/
│   ├── app/
│   │   ├── agent/            # AI Agent (LangChain + LangGraph)
│   │   │   ├── llm.py        # LLM factory (OpenAI/Google/Anthropic/Ollama)
│   │   │   ├── tools.py      # ACL-scoped tool factory with closure injection
│   │   │   ├── prompts.py    # System prompts & safety instructions
│   │   │   └── graph.py      # LangGraph ReAct agent (per-request, user-scoped)
│   │   ├── api/              # FastAPI route handlers (thin layer)
│   │   │   ├── channels.py   # Channel CRUD with type filtering
│   │   │   ├── health.py     # Health check endpoint
│   │   │   ├── messages.py   # Message query endpoints
│   │   │   ├── knowledge.py  # Semantic search (ACL via X-Slack-User-Id)
│   │   │   ├── digests.py    # Digest generation & listing
│   │   │   └── router.py     # API router aggregation
│   │   ├── events/           # Redis Streams event bus
│   │   │   ├── bus.py        # EventBus with publish/subscribe
│   │   │   └── consumers.py  # Background consumers (knowledge indexing)
│   │   ├── integrations/     # Platform connector boundary
│   │   │   ├── base.py       # BasePlatformConnector protocol & DTOs
│   │   │   └── slack/        # Slack connector compatibility adapter
│   │   ├── models/           # SQLAlchemy ORM models
│   │   │   ├── base.py       # Base model with UUID + timestamps
│   │   │   ├── channel.py    # Slack channel model
│   │   │   ├── file_metadata.py  # File metadata tracking
│   │   │   ├── identity.py   # Canonical identity ORM models
│   │   │   ├── message.py    # Message storage model
│   │   │   ├── user.py       # User model with roles
│   │   │   ├── workspace.py  # Workspace/org model
│   │   │   ├── embedding.py  # DocumentChunk with pgvector + ACL
│   │   │   ├── digest.py     # Generated channel summaries
│   │   │   └── membership.py # Channel membership for ACL enforcement
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── security/         # OIDC authentication and identity resolution
│   │   │   └── auth.py       # JWT/JWKS signature and claims validator
│   │   ├── services/         # Business logic (testable, no HTTP dependency)
│   │   │   ├── authorization_service.py # Channel & message ACL checks
│   │   │   ├── ingestion.py  # Slack event → DB pipeline + event bus
│   │   │   ├── embedding_service.py  # Text chunking + embedding
│   │   │   ├── knowledge_service.py  # ACL-aware semantic search + idempotent indexing
│   │   │   ├── membership_service.py # Channel membership management + ACL lookups
│   │   │   ├── agent_service.py      # Agent orchestrator with per-tool audit logging
│   │   │   ├── digest_service.py     # LLM-powered summaries (public + personalized)
│   │   │   └── scheduler.py          # APScheduler cron jobs (digest + membership sync)
│   │   ├── slack/            # Slack bot integration
│   │   │   ├── bot.py        # Bot lifecycle management
│   │   │   ├── events.py     # Slack event handlers (→ AI agent routing)
│   │   │   └── sync.py       # Historical data sync
│   │   ├── config.py         # Pydantic settings with startup validation
│   │   ├── database.py       # Async SQLAlchemy engine + session factory
│   │   └── main.py           # FastAPI app with full lifespan management
│   ├── alembic/              # Database migrations (0001–0005)
│   ├── tests/                # Test suite (226 tests, per-integration subpackages)
│   │   ├── agent/            # Agent, tool security, audit logging tests
│   │   ├── events/           # Event bus + consumer tests
│   │   ├── services/         # Service-layer tests (digest, knowledge, etc.)
│   │   └── slack/            # Slack unit + live integration tests
│   ├── alembic.ini           # Alembic configuration
│   ├── requirements.txt      # Python dependencies
│   └── .env.example          # Environment variable template
├── docker-compose.yml        # PostgreSQL + pgvector + Redis
├── .github/workflows/ci.yml  # CI pipeline (lint, test, Docker build)
├── AGENTS.md                 # AI agent guidelines for this project
├── CONTRIBUTING.md           # Contribution guidelines
└── .gitignore
```

---

## Development

### API Endpoints

> [!IMPORTANT]
> All REST API endpoints (except `/health`) are secured by OIDC bearer token authentication. Clients must provide a valid token in the `Authorization: Bearer <token>` header, mapping to an active HiveMind user.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Application health check |
| `GET` | `/api/v1/channels` | List all synced channels |
| `GET` | `/api/v1/channels/{id}` | Get channel details |
| `GET` | `/api/v1/messages` | Query messages with filters |
| `POST` | `/api/v1/messages` | Ingest a message |
| `POST` | `/api/v1/knowledge/search` | Semantic search across the Knowledge Fabric |
| `GET` | `/api/v1/knowledge/status` | Get indexing status and stats |
| `POST` | `/api/v1/digests/generate` | Generate an on-demand channel digest |
| `GET` | `/api/v1/digests` | List past digests |
| `GET` | `/api/v1/digests/{id}` | Get a specific digest |

### Running Tests

```bash
# Run ALL unit tests (226 tests, no credentials needed)
python -m pytest tests/ -v --ignore=tests/slack/test_live.py

# Run by test suite
python -m pytest tests/slack/ -v          # Slack bot, events, sync (44 tests)
python -m pytest tests/agent/ -v           # Agent graph, tools, security, audit (22+ tests)
python -m pytest tests/services/ -v        # Services: digest, knowledge, membership, etc. (40+ tests)
python -m pytest tests/events/ -v           # Event bus + indexing consumer (10+ tests)
python -m pytest tests/security/ -v         # OIDC authentication & identity validation (25+ tests)

# Run Slack live tests (requires .env with valid SLACK_BOT_TOKEN)
python -m pytest tests/slack/test_live.py -v -s

# Run everything
python -m pytest -v -s
```

### Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

---

## Roadmap

### Phase 1 — Core Intelligence

#### Milestone 1 — Foundation ✅
- [x] FastAPI backend with async PostgreSQL
- [x] SQLAlchemy models (Users, Channels, Messages, Files, Workspaces)
- [x] Slack bot integration (Socket Mode + Events API)
- [x] Slack data ingestion (channels, messages, files)
- [x] REST API for querying ingested data
- [x] Alembic database migrations
- [x] Docker Compose for local development
- [x] CI/CD pipeline (lint, test, Docker build)
- [x] Comprehensive Slack test suite (44 unit tests + 7 live tests)

#### Milestone 2 — Core Intelligence ✅
- [x] Redis Streams event bus (decoupled event pipeline)
- [x] Knowledge Fabric (pgvector embeddings + ACL-aware semantic search)
- [x] AI Agent (LangGraph ReAct agent with 5 ACL-scoped tools)
- [x] Daily digest / channel summaries (LLM-powered + APScheduler)
- [x] Knowledge & Digest REST APIs
- [x] Provider-agnostic LLM factory (OpenAI, Google, Anthropic, Ollama)
- [x] Embedding service with local sentence-transformers (384 dims)
- [x] Semantic indexing consumer (Redis Streams → pgvector)

#### Milestone 3 — Security & Indexing ✅
- [x] Server-derived ACL context (no client-supplied authority)
- [x] ACL-scoped agent tools with closure-injected user context
- [x] Channel membership model + denormalized O(1) ACL lookups
- [x] Membership sync (real-time join/leave events + daily cron)
- [x] Safe global digests (public channels only)
- [x] Personalized on-demand digests (private + public channels)
- [x] Per-tool audit logging with arg sanitization
- [x] Embedding dimension startup safety validation
- [x] Idempotent semantic indexing with re-index support
- [x] Comprehensive test suites: agent security, audit, consumers, services

#### Milestone 4 — Secure Multi-Platform Foundation ✅
- [x] OIDC REST authentication & JWT bearer validation
- [x] Canonical identity model and workspace mapping (Alembic migration 0004)
- [x] Base connector boundary & Slack platform connector adapter
- [x] Normalized platform-neutral event schema contracts

#### Milestone 5 — RAG Agent Production Hardening ✅ *(226 tests passing)*
- [x] Workspace & time-scoped RAG retrieval (since/until filters)
- [x] Deterministic activity summary tool (broad summaries via direct DB scans)
- [x] Source attribution & citation metadata (Alembic migration 0005)
- [x] Hardened runtime controls (agent timeout, recursion bounds, and prompt injection defense)
- [x] Message deletion handling (chunk purging)
- [x] Channel ACL revalidation (membership & type updates)

#### Milestone 6 — Phase 1 Remaining *(Upcoming)*
- [x] OIDC client bearer authentication & canonical identity mapping
- [ ] RBAC with OBO token exchange for external sources (Graph)
- [ ] Task management integration (Planner/Jira)
- [ ] Proactive behaviors (nudges, reminders)
- [ ] Onboarding engine
- [ ] KT document generation

### Phase 2 — Skills Engine

- [ ] Skill registry + executor
- [ ] Progressive skill loading
- [ ] Default skill packs
- [ ] Skill crystallization (auto-create from workflows)
- [ ] Skill governance (approval, promotion, curation)
- [ ] Self-improving loop

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines on:

- 🌿 Branch naming conventions
- 📝 Commit message format
- 🔀 Pull request workflow
- 🧪 Testing requirements
- 📏 Code style standards

---

## Security

HiveMind takes security seriously. Key architectural decisions:

- **OBO Token Exchange** — HiveMind acts AS the user, not as itself. File access is verified at the source system.
- **ACL-Scoped Vector Storage** — Every embedding chunk is tagged with access control metadata. Searches are filtered at the database level.
- **Defense in Depth** — 3-layer security: ACL ingestion → filtered retrieval → post-retrieval OBO verification.
- **DM Privacy** — DMs are never indexed unless explicitly opted-in by both parties.
- **Audit Trail** — Every file access and token exchange is logged.

---

## License

This project is currently in active development. License TBD.

---

<p align="center">
  <strong>Built with 🐝 by <a href="https://github.com/NastyRunner13">NastyRunner13</a></strong>
</p>
