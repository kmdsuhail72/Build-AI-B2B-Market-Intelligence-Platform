# Vidya Timber Market Intelligence MVP

A local-first pilot for source-backed business prospects, construction project signals, relationship mapping, evidence-based lead scoring, and sales follow-ups.

## Architecture

The application runs as a Docker Compose stack: a React dashboard calls a FastAPI backend, which stores application data in PostgreSQL. CSV imports and source-backed research use deterministic LangGraph workflows; an optional OpenAI-compatible provider is used only when AI answers or company enrichment are explicitly requested.

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

PostgreSQL is the application's only persistent store; there is no cache, message broker, or separate graph database. The knowledge graph is derived from company, project, and relationship records. Research uses local lexical retrieval and graph expansion by default. If configured and explicitly requested, verified source excerpts are sent to the configured OpenAI-compatible endpoint for cited answers or draft company enrichment. The MCP server is a separate stdio process that connects to the same database and exposes read-only tools.

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

### Optional synthetic demo

To populate a local instance with sample prospects, projects, contacts, a business relationship, and follow-up activities, run the seeder after the API is healthy:

```powershell
docker compose exec api python -m app.seed_demo
```

The command creates or updates the sales account `demo@vidya.local`, seeds three clearly labeled synthetic prospects, and prints a newly generated password. Save that password from the command output; it is not stored in the repository. Running the command again resets the demo account password. All demo records are marked as synthetic and unverified, and their source URLs and contact details use reserved example domains. They are for demonstration only and must not be treated as real business intelligence.

The database starts empty unless you run the optional demo seeder. For real data, import the reviewed CSV template in `data/prospects-template.csv` after adding source-backed records. The API accepts UTF-8 CSV files up to 5 MB. Required columns are `name`, `category`, `city`, `state`, and `source_url`; project and contact fields are optional. `estimated_units` and `estimated_doors` must be non-negative whole numbers; `doors_per_unit` must be between 0 and 100. A source must use an `http` or `https` URL. Import validates the complete file before committing it and matches companies by case-insensitive name + city + state.

## Included in this pilot

- PostgreSQL schema for companies, projects, source evidence, business relationships, and sales activities.
- Normalized city/state locations and professionally scoped business contacts linked to companies, evidence, and project-specific activities.
- Prospect search, category/evidence/city/state filters, profile source links, and enriched CSV export.
- Reviewable CSV ingestion with basic validation and deduplication.
- LangGraph-orchestrated CSV intake (`parse → validate/normalize → deduplicate → enrich/score → persist`) with stage reporting, atomic validation, and no autonomous web collection or LLM calls.
- Role-gated admin, sales, and read-only viewer access, account provisioning, and revocable server-side sessions.
- Versioned Alembic migrations; existing MVP databases receive the project-demand schema migration.
- Admin-visible audit history for imports, team account creation, relationship changes, and sales actions.
- Paginated prospect results with city, category, evidence, and project filters; user-owned saved searches.
- Editable relationship mapping with project associations.
- Interactive knowledge graph that visualizes company-to-company relationships and company-to-project links, with filters, verification/lead-score indicators, and shortcuts to company profiles. The graph reuses PostgreSQL records; it does not require a separate graph database.
- Project demand estimates with explicit-vs-derived distinction, formula, source/assumption notes, and confidence.
- Lead scores with a visible 100-point breakdown: category fit (10–30), verified evidence (20–30), projects (up to 30), public website (5), and professional contact (5). Scores guide prioritization; they are not conversion predictions.
- Sales activity capture for calls, emails, meetings, and notes, with structured outcomes, next actions, due dates, and completion tracking.
- Dashboard-level next scheduled action and per-company recommendations that respect open follow-ups and recorded outcomes.
- Research desk with local lexical retrieval over stored source excerpts and GraphRAG-style expansion through linked companies, relationships, and projects.
- Optional citation-constrained AI answers and evidence-quoted company enrichment; both are disabled unless configured and explicitly requested.
- Company opportunity briefs with disclosed score components, evidence gaps, and actionable human-review steps.
- Local stdio MCP server with read-only tools for company search, company profiles, project signals, relationship context, and source-backed research.

The CSV workflow is a deterministic LangGraph state graph, not an AI agent: source-backed rows are parsed and fully validated before any records are staged; exact duplicate source/project rows are skipped; demand fields and a transparent score preview are derived; then database writes and the audit record commit together. Validation errors stop before persistence. No CSV data is sent to an LLM or external tracing service.

## Database and data quality

PostgreSQL stores companies, city/state reference locations, professional people, company-to-person links, projects, source evidence, relationships, and sales activities. A company is identified during import by its case-insensitive name, city, and state, so the same city name in different states remains distinct. Location reference rows use normalized state/city keys, and existing installations are backfilled to them by Alembic migration `0004`. Structured sales outcomes are added by migration `0005`.

Contacts are limited to professional business names, roles, business email addresses, and business phone numbers. Company links retain a source record for provenance; imports keep contacts unverified until reviewed. Activities can optionally link to a contact and project, and the API checks those links belong to the selected company. Do not store sensitive personal details.

CSV ingestion validates field lengths, URLs, numeric project estimates, demand confidence, contact details, and discovery dates before writing anything. Database constraints and indexes protect core entities and common city/state, project-status, source-verification, and follow-up queries. Each import, its duplicate counts, and its audit event commit atomically. The authenticated CSV export includes prospect scores and reasons, project signals, all original source references and verification dates, business relationships, professional contacts, sales activity/outcomes, and the next recommended action.

## Research desk: RAG and relationship graph

The authenticated Research desk searches stored source titles, excerpts, and linked company/project metadata. It uses local lexical ranking (no embedding service) and can expand results through recorded company relationships and projects. The graph expansion is bounded to linked records already in this database; it does not crawl external sites or infer relationships. Results show the source URL, verification status, excerpts, retrieval path, and graph context.

To make records useful for research, include `source_content` in the reviewed CSV template. It is an optional excerpt field, limited to 20,000 characters per row. Only include publicly usable information that has been reviewed for the intended purpose. Records default to `unverified`; a human must explicitly set `verification_status` to `verified` before the text is eligible for hosted AI generation. Unverified excerpts may appear in local search results but are never included in a provider prompt.

AI answer generation is off by default. To enable it, set `RAG_OPENAI_API_KEY` in `.env`, optionally set `RAG_OPENAI_MODEL` and `RAG_OPENAI_BASE_URL`, and restart the API. A user must also opt in for each query in the dashboard. Only excerpts marked `verified` are sent to the configured OpenAI-compatible endpoint; query text is sent with them. No source text is sent when generation is not requested. Treat provider terms, retention, and regional processing as part of your source/privacy review. Generated answers require citations to retrieved evidence; verify important claims against the original URLs.

Company profiles include a deterministic opportunity brief and a separate, opt-in AI extraction action. Enrichment uses up to five verified excerpts (maximum 4,000 characters each); unverified text is excluded. The model must return an exact quoted span and source ID for every proposed claim. The API rejects claims whose quote does not match the submitted source text. Results are drafts only: they are audited but never written into company or project records automatically. A person must verify claims at the original source before updating records or contacting a prospect.

Lead scores are deterministic and add to 100 possible points: business category relevance (up to 30), verified sources (20 for the first, then 5 per additional source up to 30), linked projects (10 each up to 30), a public website (5), and a linked professional business contact (5). Each company profile shows the component points, positive signals, evidence gaps, and recommended next actions. The score is a prioritization aid, not a probability of conversion. Revisit the weights against measured sales outcomes before treating them as predictive.

The existing RAG and relationship-graph expansion are used because they expose source citations and connected companies/projects in a reviewable flow. An autonomous AI agent is intentionally not used: the current pilot has no approved write actions or measured outcome that would justify delegating decisions to one.

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

The application supports two compliant ingestion paths:

- **Approved JSON APIs and feeds:** A Python collector fetches only endpoints explicitly listed in a local configuration whose access method and terms have been reviewed. It accepts HTTPS JSON only, disables redirects, rejects hosts that resolve to non-public IP addresses, and applies response and record limits. It does not crawl arbitrary pages or scrape Google Maps; an official API can be used when its terms allow it. Configure API credentials through environment variables referenced by name; never put tokens in the feed configuration or commit them.
- **Human-reviewed sources:** For sources without a permitted machine-readable endpoint, use their approved export/download process and import reviewed records with the existing CSV workflow. This includes manual research from company websites and portfolios, RERA, government announcements, news, directories, or Google Maps where its terms allow the intended access and reuse.

No feeds are preconfigured. To configure one, create a local JSON file (for example `data\approved-feeds.json`) using this schema. The example is illustrative only; replace the endpoint and terms URL with a source you have actually reviewed. Allowed `access_method` values are `official_api`, `public_json_feed`, and `licensed_api`. `fields` maps dotted JSON paths to the CSV columns; `defaults` can provide fixed geographic values when the feed omits them. `headers_env` maps optional HTTP headers to environment variable names for API credentials. The review date is an operator assertion, not an automated legal determination.

```json
{
  "version": 1,
  "sources": [
    {
      "id": "up-project-feed",
      "name": "Reviewed UP project feed",
      "access_method": "official_api",
      "endpoint": "https://api.example.org/projects",
      "terms_url": "https://api.example.org/terms",
      "terms_reviewed_on": "2026-11-10",
      "records_path": "data.projects",
      "fields": {
        "name": "developer.name",
        "category": "developer.category",
        "city": "location.city",
        "state": "location.state",
        "source_url": "public_url",
        "project_name": "name",
        "project_status": "status",
        "estimated_units": "units"
      },
      "defaults": {
        "state": "Uttar Pradesh"
      },
      "headers_env": {
        "Authorization": "UP_PROJECT_FEED_TOKEN"
      }
    }
  ]
}
```

Run the collector from the `backend` directory. It writes a CSV for inspection; it does not persist records directly. Review the output and upload it using the admin CSV import in the dashboard.

```powershell
python -m app.workflows.approved_json_feeds `
  --config ..\data\approved-feeds.json `
  --output ..\data\collected-prospects.csv
```

The collector marks every record `unverified` and records its discovery date. The CSV import validates the complete file, deduplicates repeated observations, enriches project demand and score previews, then commits the records and audit entry together. Discovery dates are retained on source records and in CSV exports. A public announcement or portfolio can provide evidence of a project not found in RERA, but do not infer registration status from absence; preserve the evidence URL and verify claims independently.

For every source, record only information suitable for the intended business purpose, preserve the original record URL, and confirm terms, applicable laws, privacy requirements, and access restrictions before collection or reuse. Do not bypass login, paywalls, rate limits, or other controls; do not treat AI-extracted or directory data as verified until a person checks it; and avoid sensitive personal data. Public availability alone does not grant permission to collect or reuse information.

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

GitHub Actions runs the backend suite against its SQLite test fixtures, verifies a fresh PostgreSQL 17 migration upgrade/downgrade/re-upgrade, and builds the frontend with Node.js 22 on pushes, pull requests, and manual dispatch.

## Pilot boundaries and next phase

This is a hardened local pilot foundation, not a fully production-certified deployment. Before internet exposure, add TLS termination, rate limiting and login lockout, managed secrets, database backup/restore drills, monitoring, retention policy, and a formal privacy/data-source review. Scheduled collection and CRM integration remain excluded until approved sources, sufficient verified data, and measurable commercial outcomes justify them. The optional AI answer feature is a bounded research aid, not an autonomous agent or a substitute for source verification.

The first paid pilot should validate the source policy, CSV format, sales workflow, scoring criteria, and a small set of manually verified Varanasi prospects. Expand geography or automate collection only after data quality and commercial usefulness are measured.
