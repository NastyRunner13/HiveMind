# Contributing to HiveMind 🐝

Thank you for your interest in contributing to HiveMind! This document provides guidelines and conventions to keep the codebase clean, consistent, and easy to collaborate on.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Branch Strategy](#branch-strategy)
- [Commit Conventions](#commit-conventions)
- [Pull Request Workflow](#pull-request-workflow)
- [Code Style](#code-style)
- [Testing](#testing)
- [Project Structure Guidelines](#project-structure-guidelines)
- [Issue Reporting](#issue-reporting)

---

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/<your-username>/HiveMind.git
   cd HiveMind
   ```
3. **Add the upstream remote**:
   ```bash
   git remote add upstream https://github.com/NastyRunner13/HiveMind.git
   ```
4. **Set up the development environment** — see [README.md](README.md#getting-started) for detailed instructions
5. **Create a branch** for your work (see [Branch Strategy](#branch-strategy))

---

## Branch Strategy

We follow a **feature-branch workflow** off of `main`.

### Branch Naming Convention

```
<type>/<short-description>
```

| Type | Purpose | Example |
|------|---------|---------|
| `feature/` | New feature or capability | `feature/daily-digest` |
| `fix/` | Bug fix | `fix/slack-reconnect-crash` |
| `refactor/` | Code refactoring (no behavior change) | `refactor/models-base-class` |
| `docs/` | Documentation updates | `docs/api-endpoints` |
| `chore/` | Build, CI, tooling, dependencies | `chore/update-dependencies` |
| `hotfix/` | Urgent production fix | `hotfix/token-expiry-loop` |
| `test/` | Adding or updating tests | `test/ingestion-service` |
| `experiment/` | Exploratory work (may not be merged) | `experiment/qdrant-integration` |

### Rules

- **Always branch from `main`** — keep your branch up to date with `main` before opening a PR
- **One feature per branch** — keep branches focused and atomic
- **Delete branches after merge** — keep the repo clean
- **Never push directly to `main`** — all changes go through PRs

### Example Workflow

```bash
# Sync with upstream
git checkout main
git pull upstream main

# Create a feature branch
git checkout -b feature/knowledge-fabric

# ... do your work ...

# Push to your fork
git push origin feature/knowledge-fabric

# Open a PR from your fork → upstream/main
```

---

## Commit Conventions

We use **[Conventional Commits](https://www.conventionalcommits.org/)** for clear, parseable commit history.

### Format

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Types

| Type | When to Use |
|------|------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation only changes |
| `style` | Code style (formatting, whitespace — no logic change) |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Performance improvement |
| `test` | Adding or correcting tests |
| `build` | Build system or dependency changes |
| `ci` | CI configuration changes |
| `chore` | Other changes that don't modify src or test files |
| `revert` | Reverts a previous commit |

### Scopes

Use the module or component name as the scope:

| Scope | Description |
|-------|-------------|
| `api` | API routes and handlers |
| `models` | SQLAlchemy database models |
| `schemas` | Pydantic request/response schemas |
| `services` | Business logic layer |
| `slack` | Slack bot and integration |
| `config` | Configuration and settings |
| `db` | Database, migrations, Alembic |
| `docker` | Docker and docker-compose |
| `deps` | Dependency updates |

### Examples

```bash
# Feature commits
feat(slack): add channel sync with pagination support
feat(api): add message query endpoint with date filtering
feat(models): add file_metadata model with ACL fields

# Bug fix
fix(slack): handle rate limit 429 during channel sync
fix(db): fix async session leak on failed transactions

# Refactoring
refactor(models): extract common fields into TimestampMixin
refactor(services): split ingestion into separate workers

# Documentation
docs: add API endpoint reference to README
docs(api): add OpenAPI description for channel routes

# Chore
chore(deps): upgrade fastapi to 0.115.0
chore(docker): add redis service to docker-compose

# Multi-line commit with body
feat(services): implement Slack message ingestion pipeline

Handles message.new, message.changed, and message.deleted events.
Includes thread reply detection, file attachment metadata extraction,
and reaction tracking. Uses upsert logic to avoid duplicates.

Closes #12
```

### Rules

- **Use present tense** — "add feature" not "added feature"
- **Use imperative mood** — "move cursor to..." not "moves cursor to..."
- **Don't capitalize the description** — `feat: add thing` not `feat: Add thing`
- **No period at the end** of the description
- **Keep the first line under 72 characters**
- **Reference issues** in the footer when applicable: `Closes #42`, `Fixes #13`

---

## Pull Request Workflow

### Before Opening a PR

1. **Rebase on latest `main`**:
   ```bash
   git checkout main
   git pull upstream main
   git checkout feature/your-branch
   git rebase main
   ```
2. **Run tests** (when available):
   ```bash
   cd backend
   pytest
   ```
3. **Lint your code**:
   ```bash
   ruff check .
   ruff format .
   ```

### PR Title Format

Follow the same format as commit messages:

```
feat(slack): add historical channel sync
fix(api): return 404 for unknown channel IDs
```

### PR Description Template

```markdown
## What

Brief description of what this PR does.

## Why

Context on why this change is needed.

## How

High-level implementation approach.

## Testing

- [ ] Unit tests added/updated
- [ ] Manual testing performed
- [ ] API docs updated (if applicable)

## Screenshots / Logs

(If applicable — paste relevant screenshots or log output)

## Related Issues

Closes #XX
```

### Review Process

1. **Open a PR** from your fork to `upstream/main`
2. **Request a review** from a maintainer
3. **Address feedback** — push new commits (don't force-push during review)
4. **Squash and merge** — we squash commits on merge to keep `main` history clean

### PR Labels

| Label | Description |
|-------|-------------|
| `phase-1` | Core Intelligence features |
| `phase-2` | Skills Engine features |
| `bug` | Bug fix |
| `enhancement` | New feature or improvement |
| `documentation` | Documentation changes |
| `breaking-change` | Introduces breaking API changes |
| `good-first-issue` | Good for newcomers |
| `help-wanted` | Extra attention needed |

---

## Code Style

### Python

- **Python 3.12+** — use modern syntax (type hints, match-case, etc.)
- **Formatter**: [Ruff](https://docs.astral.sh/ruff/) (`ruff format`)
- **Linter**: [Ruff](https://docs.astral.sh/ruff/) (`ruff check`)
- **Line length**: 88 characters (Black-compatible)
- **Imports**: sorted by Ruff (isort-compatible)
- **Type hints**: required for all function signatures
- **Docstrings**: Google-style, required for all public functions and classes

### Example

```python
"""
Module docstring — describe what this module does.
"""

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Channel(BaseModel):
    """Represents a Slack channel synced into HiveMind."""

    __tablename__ = "channels"

    slack_id: Mapped[str] = mapped_column(
        String(32), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    is_private: Mapped[bool] = mapped_column(default=False)

    def is_accessible_by(self, user_role: str) -> bool:
        """Check if a user with the given role can access this channel."""
        if not self.is_private:
            return True
        return user_role in ("admin", "team_lead")
```

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Files | `snake_case.py` | `channel_service.py` |
| Classes | `PascalCase` | `FileMetadata` |
| Functions | `snake_case` | `sync_channels()` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_PAGE_SIZE` |
| API routes | `kebab-case` URLs | `/api/v1/file-metadata` |
| Database tables | `snake_case` plural | `file_metadata` |
| Branches | `type/kebab-case` | `feature/daily-digest` |

---

## Testing

### Structure

```
backend/
├── tests/
│   ├── conftest.py          # Shared fixtures
│   ├── test_api/
│   │   ├── test_channels.py
│   │   └── test_messages.py
│   ├── test_services/
│   │   ├── test_ingestion.py
│   │   └── test_channel_service.py
│   └── test_slack/
│       ├── test_events.py
│       └── test_sync.py
```

### Guidelines

- **Test file naming**: `test_<module>.py`
- **Test function naming**: `test_<what>_<condition>_<expected>`
  ```python
  def test_sync_channels_empty_workspace_returns_zero():
      ...
  ```
- **Use fixtures** for database sessions, test data, and mock clients
- **Mock external APIs** — never call Slack/GitHub/etc. in tests
- **Aim for coverage** on business logic in `services/`, not just API endpoints

---

## Project Structure Guidelines

### Where to Put Things

| What | Where | Why |
|------|-------|-----|
| New API endpoint | `backend/app/api/` | Route handlers, thin layer |
| New database model | `backend/app/models/` | SQLAlchemy ORM models |
| Request/Response shapes | `backend/app/schemas/` | Pydantic validation |
| Business logic | `backend/app/services/` | Core logic, testable |
| Slack-specific code | `backend/app/slack/` | Bot, events, sync |
| New integration | `backend/app/integrations/` | GitHub, Teams, Jira, etc. |
| Database migration | `backend/alembic/versions/` | Auto-generated via Alembic |
| Configuration | `backend/app/config.py` | Pydantic settings |

### Architecture Principles

1. **API routes are thin** — they validate input, call a service, and return a response
2. **Services contain business logic** — they are independent of HTTP/Slack and testable in isolation
3. **Models are the source of truth** — all database interactions go through SQLAlchemy models
4. **Schemas validate boundaries** — Pydantic schemas at API edges, not deep in business logic
5. **Integrations are isolated** — each external platform (Slack, Teams, Jira) gets its own module

---

## Issue Reporting

### Bug Reports

Use the following template:

```markdown
**Describe the bug**
A clear description of what the bug is.

**To Reproduce**
Steps to reproduce:
1. Start the server with `...`
2. Send request `...`
3. Observe error `...`

**Expected behavior**
What you expected to happen.

**Environment**
- OS: [e.g., Windows 11, macOS 14]
- Python: [e.g., 3.12.4]
- Docker: [e.g., 24.0.7]

**Logs**
Paste relevant log output.
```

### Feature Requests

```markdown
**Is your feature request related to a problem?**
A clear description of the problem.

**Describe the solution you'd like**
What you'd like to happen.

**Which HiveMind phase does this relate to?**
Phase 1 (Core Intelligence) / Phase 2 (Skills Engine)

**Additional context**
Any mockups, references, or examples.
```

---

## Questions?

If you're unsure about anything, open a [Discussion](https://github.com/NastyRunner13/HiveMind/discussions) or reach out to the maintainers.

---

**Thank you for contributing to HiveMind! 🐝**
