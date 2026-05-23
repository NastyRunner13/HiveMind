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
│                  THE FIVE PILLARS OF HIVEMIND                 │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐  │
│  │  MEMORY  │  │  SKILLS  │  │   SOUL   │  │    CRONS    │  │
│  │ Phase 1  │  │ Phase 2  │  │ Phase 1  │  │  Phase 1    │  │
│  └──────────┘  └──────────┘  └──────────┘  └─────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              SELF-IMPROVEMENT (Phase 2)               │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12+ / FastAPI |
| **Database** | PostgreSQL 16 |
| **Vector DB** | pgvector (start) → Qdrant (scale) |
| **Cache / Events** | Redis 7 + Redis Streams |
| **Bot Framework** | Slack Bolt / MS Bot Framework |
| **Auth** | OAuth2 + JWT, Azure AD / Google Workspace SSO |
| **AI/LLM** | LangGraph + LangChain (model-agnostic) |
| **Deployment** | Docker + docker-compose (dev) → Kubernetes (prod) |

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

### 2. Start Infrastructure (PostgreSQL)

```bash
docker-compose up -d
```

This starts a PostgreSQL 16 container with the `hivemind` database.

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
# Edit .env with your Slack credentials (optional) and database settings
```

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
│   │   ├── api/              # FastAPI route handlers
│   │   │   ├── channels.py   # Channel CRUD endpoints
│   │   │   ├── health.py     # Health check endpoint
│   │   │   ├── messages.py   # Message query endpoints
│   │   │   └── router.py     # API router aggregation
│   │   ├── models/           # SQLAlchemy ORM models
│   │   │   ├── base.py       # Base model with common fields
│   │   │   ├── channel.py    # Slack channel model
│   │   │   ├── file_metadata.py  # File metadata tracking
│   │   │   ├── message.py    # Message storage model
│   │   │   ├── user.py       # User model with roles
│   │   │   └── workspace.py  # Workspace/org model
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── services/         # Business logic layer
│   │   │   ├── channel_service.py  # Channel operations
│   │   │   └── ingestion.py  # Slack data ingestion service
│   │   ├── slack/            # Slack bot integration
│   │   │   ├── bot.py        # Bot lifecycle management
│   │   │   ├── events.py     # Slack event handlers
│   │   │   └── sync.py       # Historical data sync
│   │   ├── config.py         # Pydantic settings management
│   │   ├── database.py       # SQLAlchemy async engine setup
│   │   └── main.py           # FastAPI app entry point
│   ├── alembic/              # Database migrations
│   ├── alembic.ini           # Alembic configuration
│   ├── requirements.txt      # Python dependencies
│   └── .env.example          # Environment variable template
├── docker-compose.yml        # Development infrastructure
├── AGENT.md                  # AI agent guidelines for this project
├── CONTRIBUTING.md           # Contribution guidelines
└── .gitignore
```

---

## Development

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Application health check |
| `GET` | `/api/v1/channels` | List all synced channels |
| `GET` | `/api/v1/channels/{id}` | Get channel details |
| `GET` | `/api/v1/messages` | Query messages with filters |
| `POST` | `/api/v1/messages` | Ingest a message |

### Running Tests

```bash
pytest
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

### Phase 1 — Core Intelligence (Current)

- [x] FastAPI backend with async PostgreSQL
- [x] SQLAlchemy models (Users, Channels, Messages, Files, Workspaces)
- [x] Slack bot integration (Socket Mode + Events API)
- [x] Slack data ingestion (channels, messages, files)
- [x] REST API for querying ingested data
- [x] Alembic database migrations
- [x] Docker Compose for local development
- [ ] Knowledge Fabric (vector embeddings + semantic search)
- [ ] Daily digest / channel summaries
- [ ] Task management integration (Planner/Jira)
- [ ] RBAC with OBO token exchange
- [ ] Proactive behaviors (nudges, reminders)
- [ ] Onboarding engine
- [ ] KT document generation
- [ ] Redis Streams event bus

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
