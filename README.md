# Vidya Timber Market Intelligence MVP

A local-first pilot for source-backed business prospects, construction project signals, relationship mapping, evidence-based lead scoring, and sales follow-ups.

## Architecture

The application runs as a Docker Compose stack: a React dashboard calls a FastAPI backend, which stores application data in PostgreSQL. CSV imports and source-backed research use deterministic LangGraph workflows; an optional OpenAI-compatible provider is used only when AI answers are explicitly enabled.

<!-- mermaid-checked: no \n, no em-dash/en-dash, no {} in labels, subgraphs are id["label"], arrows are -->|"label"|, all subgraphs closed by end, ids unique -->
~~~mermaid
flowchart TD
    subgraph Client["Client Layer"]
        Browser["Web browser"]
        McpClient["MCP client"]
    end
    subgraph Presentation["Presentation Layer"]
        Dashboard["React and Vite dashboard"]
    end
    subgraph Application["Application Layer"]
        Api["FastAPI REST API"]
        ImportFlow["LangGraph CSV import"]
        ResearchFlow["LangGraph research"]
        McpServer["Read-only MCP server"]
    end
    subgraph Storage["Data Layer"]
        Postgres[("PostgreSQL 17")]
    end
    subgraph OptionalServices["Optional External Service"]
        AiProvider["OpenAI-compatible API"]
    end

    Browser -->|"opens"| Dashboard
    Dashboard -->|"HTTP API requests"| Api
    Api -->|"valid CSV"| ImportFlow
    Api -->|"research query"| ResearchFlow
    Api -->|"SQLAlchemy sessions"| Postgres
    ImportFlow -->|"validated records"| Postgres
    ResearchFlow -->|"local evidence retrieval"| Postgres
    ResearchFlow -.->|"opt-in verified excerpts"| AiProvider
    McpClient -->|"stdio transport"| McpServer
    McpServer -->|"read-only queries"| Postgres
~~~

### Technology Stack Summary

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| Presentation | React, TypeScript, Vite | React 19.1, TypeScript 5.8, Vite 6 | Dashboard and development-time API proxy |
| Application | FastAPI, Uvicorn, Pydantic | FastAPI 0.115, Uvicorn 0.34 | REST API, validation, and HTTP serving |
| Workflows | LangGraph | 1.2 | Deterministic CSV import and research orchestration |
| Persistence | SQLAlchemy, psycopg | SQLAlchemy 2.0, psycopg 3.2 | ORM and PostgreSQL connectivity |
| Schema management | Alembic | 1.15 | Versioned database migrations |
| Data store | PostgreSQL | 17 | Persistent application records |
| Tool integration | MCP Python SDK | 1.30 | Read-only local tools over stdio |
| Local deployment | Docker Compose | N/A | Runs the database, API, and dashboard |

### Data Storage and External Services

PostgreSQL is the application's only persistent store; there is no cache, message broker, or separate graph database. The knowledge graph is derived from company, project, and relationship records. Research uses local lexical retrieval by default. If configured and explicitly requested, verified source excerpts and the query are sent to the configured OpenAI-compatible endpoint for answer generation. The MCP server is a separate stdio process that connects to the same database and exposes read-only tools.

### Key Architectural Decisions

- The API and workflow modules use SQLAlchemy sessions directly; the repository does not introduce a separate repository or service layer.
- CSV import validates and normalizes the full input before persisting records, with database changes and the audit record committed together.
- MCP runs over local stdio rather than exposing a network endpoint, and its tools are read-only.

### Component Relationships

<!-- mermaid-checked: no \n, no em-dash/en-dash, no {} in labels, subgraphs are id["label"], arrows are -->|"label"|, all subgraphs closed by end, ids unique -->
~~~mermaid
flowchart LR
    subgraph PresentationComponents["Presentation"]
        cDashboard["React dashboard"]
    end
    subgraph BusinessComponents["Application and workflows"]
        cApi["FastAPI routes"]
        cAuth["Authentication and role checks"]
        cImport["CSV import workflow"]
        cResearch["Research workflow"]
        cMcp["MCP tools"]
    end
    subgraph DataComponents["Data access"]
        cSessions["SQLAlchemy sessions"]
        cModels["SQLAlchemy models"]
        cPostgres[("PostgreSQL")]
    end
    subgraph OperationsComponents["Operations"]
        cMigrations["Alembic migrations"]
    end

    cDashboard -->|"HTTP JSON requests"| cApi
    cApi -->|"authorizes requests"| cAuth
    cApi -->|"runs imports"| cImport
    cApi -->|"runs research"| cResearch
    cApi -->|"opens database sessions"| cSessions
    cImport -->|"uses session and models"| cModels
    cResearch -->|"uses session and models"| cModels
    cMcp -->|"uses session and models"| cModels
    cSessions -->|"executes queries"| cPostgres
    cModels -->|"maps application records"| cPostgres
    cMigrations -->|"updates schema"| cPostgres
~~~

### Component Inventory

| Component | Layer | Type | Responsibility |
|---|---|---|---|
| React dashboard | Presentation | Single-page application | Prospect search, profiles, graph, research, and sales workflows |
| FastAPI routes | Application | REST API | Authentication, authorization, and dashboard operations |
| Authentication and role checks | Application | Cross-cutting concern | Session-cookie authentication and admin, sales, and viewer permissions |
| CSV import workflow | Application | LangGraph workflow | Parse, validate, deduplicate, enrich, score, and persist reviewed CSV records |
| Research workflow | Application | LangGraph workflow | Search stored evidence, expand through relationships, and optionally generate cited answers |
| MCP tools | Integration | stdio server | Expose read-only search, company, project, relationship, and research tools |
| SQLAlchemy sessions and models | Data access | ORM | Manage database sessions and map application records |
| Alembic migrations | Operations | Schema management | Apply versioned database schema changes |

See the [full architecture reference](.github/modernize/assessment/engines/facts/architecture-diagram.md) for the standalone diagram and component inventory.

## Run locally

Requirements: Docker Desktop with Docker Compose.

```powershell
Copy-Item .env.example .env
# Edit .env and replace all example passwords with unique values.
docker compose up --build
```

Open the dashboard at <http://localhost:5173>. The API and interactive API docs are at <http://localhost:8000> and <http://localhost:8000/docs>.

The first boot creates the administrator from `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`. The API uses an HttpOnly, SameSite session cookie, Argon2id password hashes, and admin/sales/viewer roles. Admins can add team accounts from the dashboard. Set `COOKIE_SECURE=true` behind HTTPS. Change all sample `.env` secrets; do not expose this development deployment directly to the internet.

The database starts empty. Import the reviewed CSV template in `data/prospects-template.csv` after adding source-backed records. The API accepts UTF-8 CSV files up to 5 MB. Required columns are `name`, `category`, `city`, `state`, and `source_url`; project and contact fields are optional. `estimated_units` and `estimated_doors` must be non-negative whole numbers; `doors_per_unit` must be between 0 and 100. A source must use an `http` or `https` URL. Import validates the complete file before committing it and matches companies by case-insensitive name + city.

## Included in this pilot

- PostgreSQL schema for companies, projects, source evidence, business relationships, and sales activities.
- Prospect search, category/evidence filters, profile evidence links, and CSV export.
- Reviewable CSV ingestion with basic validation and deduplication.
- LangGraph-orchestrated CSV intake (`parse → validate/normalize → deduplicate → enrich/score → persist`) with stage reporting, atomic validation, and no autonomous web collection or LLM calls.
- Role-gated admin, sales, and read-only viewer access, account provisioning, and revocable server-side sessions.
- Versioned Alembic migrations; existing MVP databases receive the project-demand schema migration.
- Admin-visible audit history for imports, team account creation, relationship changes, and sales actions.
- Paginated prospect results with city, category, evidence, and project filters; user-owned saved searches.
- Editable relationship mapping with project associations.
- Interactive knowledge graph that visualizes company-to-company relationships and company-to-project links, with filters, verification/lead-score indicators, and shortcuts to company profiles. The graph reuses PostgreSQL records; it does not require a separate graph database.
- Project demand estimates with explicit-vs-derived distinction, formula, source/assumption notes, and confidence.
- Lead scores with visible factors: category fit (10–30 points), any verified source (+20), and linked projects (+10 each, up to 30); total capped at 100. This is a prioritization aid, not a conversion prediction.
- Sales activity capture with notes, next actions, optional follow-up dates, and completion tracking.
- Research desk with local lexical retrieval over stored source excerpts and GraphRAG-style expansion through linked companies, relationships, and projects.
- Optional citation-constrained AI answer generation; disabled unless configured and explicitly requested per research query.
- Local stdio MCP server with read-only tools for company search, company profiles, project signals, relationship context, and source-backed research.

The CSV workflow is a deterministic LangGraph state graph, not an AI agent: source-backed rows are parsed and fully validated before any records are staged; exact duplicate source/project rows are skipped; demand fields and a transparent score preview are derived; then database writes and the audit record commit together. Validation errors stop before persistence. No CSV data is sent to an LLM or external tracing service.

## Research desk: RAG and relationship graph

The authenticated Research desk searches stored source titles, excerpts, and linked company/project metadata. It uses local lexical ranking (no embedding service) and can expand results through recorded company relationships and projects. The graph expansion is bounded to linked records already in this database; it does not crawl external sites or infer relationships. Results show the source URL, verification status, excerpts, retrieval path, and graph context.

To make records useful for research, include `source_content` in the reviewed CSV template. It is an optional excerpt field, limited to 20,000 characters per row. Only include publicly usable information that has been reviewed for the intended purpose. Records default to `unverified`; a human must explicitly set `verification_status` to `verified` before the text is eligible for hosted AI generation. Unverified excerpts may appear in local search results but are never included in a provider prompt.

AI answer generation is off by default. To enable it, set `RAG_OPENAI_API_KEY` in `.env`, optionally set `RAG_OPENAI_MODEL` and `RAG_OPENAI_BASE_URL`, and restart the API. A user must also opt in for each query in the dashboard. Only excerpts marked `verified` are sent to the configured OpenAI-compatible endpoint; query text is sent with them. No source text is sent when generation is not requested. Treat provider terms, retention, and regional processing as part of your source/privacy review. Generated answers require citations to retrieved evidence; verify important claims against the original URLs.

## MCP server

The project includes a read-only Model Context Protocol (MCP) server for MCP-compatible clients. It uses stdio (no listening network port) and connects to the same PostgreSQL database configured for the Compose API service. The workspace configuration is in `.vscode/mcp.json`.

1. Copy `.env.example` to `.env` and set unique database/admin passwords.
2. Start the stack once so database migrations are applied: `docker compose up -d --build`.
3. In VS Code, open the workspace MCP servers view and start `vidya-timber-intelligence`. The configured `docker compose run` starts a short-lived MCP process connected to the Compose database.

Available tools:

- `search_companies`: search and filter prospects with explainable scores.
- `get_company_profile`: return a company's stored evidence, projects, and relationships.
- `list_projects`: find project records and their documented demand estimates.
- `get_company_relationships`: inspect direct company connections and linked projects.
- `research_market`: search stored sources and expand across local graph relationships without calling an LLM.

All tools are read-only and constrain result limits. `research_market` returns excerpts only for records marked verified and excludes internal relationship notes. The MCP process has the database access of the API container, so only enable the server for trusted local MCP clients. It does not expose a remotely accessible MCP endpoint. An MCP client's own model/provider policy is separate: review it before allowing that client to process business data.

## Data collection and validation

The MVP intentionally imports human-reviewed public records instead of crawling sites. Record only information suitable for business outreach, preserve the original source URL, and verify that the source and its terms permit the intended use. Keep discovery dates and source status current; the import date is recorded for each source. Do not treat AI-extracted or directory data as verified until a person checks it. Avoid collecting sensitive personal data.

Project door estimates are never silently inferred. A project may store an explicit door estimate, or calculate one as `units × doors per unit`; the interface displays the method, assumptions, and confidence. Treat all estimates as hypotheses until specifications are confirmed.

## Development and tests

Backend (Python 3.11+):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements-dev.txt
$env:DATABASE_URL = "sqlite:///./vidya-dev.db"
$env:BOOTSTRAP_ADMIN_EMAIL = "admin@example.com"
$env:BOOTSTRAP_ADMIN_PASSWORD = "a-unique-local-password"
$env:PYTHONPATH = "$PWD\backend"
alembic -c backend\alembic.ini upgrade head
python -m app.bootstrap
python -m pytest backend\tests
uvicorn app.main:app --app-dir backend --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run build
npm run dev
```

## Pilot boundaries and next phase

This is a hardened local pilot foundation, not a fully production-certified deployment. Before internet exposure, add TLS termination, rate limiting and login lockout, managed secrets, database backup/restore drills, monitoring, retention policy, and a formal privacy/data-source review. Scheduled collection and CRM integration remain excluded until approved sources, sufficient verified data, and measurable commercial outcomes justify them. The optional AI answer feature is a bounded research aid, not an autonomous agent or a substitute for source verification.

The first paid pilot should validate the source policy, CSV format, sales workflow, scoring criteria, and a small set of manually verified Varanasi prospects. Expand geography or automate collection only after data quality and commercial usefulness are measured.
