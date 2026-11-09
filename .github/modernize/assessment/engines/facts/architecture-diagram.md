# Architecture Diagram

This document describes the deployed application layers and the principal interactions between the dashboard, backend workflows, database, and local MCP integration.

## Application Architecture

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

## Component Relationships

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
