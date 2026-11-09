import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import "./intelligence.css";

type Company = {
  id: number;
  name: string;
  category: string;
  city: string;
  state: string;
  website: string | null;
  public_phone: string | null;
  score: number;
  score_reasons: string[];
  verified_source_count: number;
  project_count: number;
};

type AppUser = { id: number; email: string; role: "admin" | "sales" | "viewer" };
type SavedSearch = { id: number; name: string; filters: Record<string, string | number | boolean | null> };
type AuditEvent = { id: number; actor_email: string | null; action: string; entity_type: string; entity_id: string | null; occurred_at: string };
type ResearchEvidence = {
  citation: string;
  source_id: number;
  source_url: string;
  source_title: string | null;
  verification_status: string;
  company_id: number | null;
  company_name: string | null;
  project_name: string | null;
  excerpt: string;
  retrieval: "text" | "graph";
  relevance_score: number;
  used_in_answer: boolean;
};
type ResearchResult = {
  query: string;
  answer: string;
  mode: "retrieval_only" | "openai";
  evidence: ResearchEvidence[];
  graph_context: { relationship_type?: string; from_company?: string; to_company?: string; project_name?: string; company_name?: string; context_type?: string; status?: string }[];
  graph_neighbors: number;
  workflow: string[];
};
type EnrichmentClaim = {
  claim_type: string;
  text: string;
  citation: string;
  source_id: number;
  quote: string;
  source_title: string;
  source_url: string;
};
type EnrichmentResult = {
  company_id: number;
  company_name: string;
  claims: EnrichmentClaim[];
  sources_used: { source_id: number; title: string; url: string }[];
  persisted: false;
  human_review_required: true;
};
type KnowledgeNode = {
  id: string;
  type: "company" | "project";
  entity_id: number;
  label: string;
  category?: string;
  city?: string;
  score?: number;
  verified_sources?: number;
  project_count?: number;
  status?: string;
  estimated_units?: number | null;
  estimated_doors?: number | null;
  demand_confidence?: string;
  company_id?: number;
};
type KnowledgeEdge = { id: string; source: string; target: string; type: string; project_id?: number | null };
type KnowledgeGraphData = {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  total_companies: number;
  included_companies: number;
  total_projects: number;
  included_projects: number;
  truncated: boolean;
};

type CompanyDetail = Company & {
  description: string | null;
  sources: { id: number; url: string; title: string | null; source_type: string; verification_status: string; discovered_at: string; has_content: boolean }[];
  opportunity_report: {
    score: number;
    priority: "low" | "medium" | "high";
    score_components: { key: string; label: string; points: number; maximum: number }[];
    positive_signals: string[];
    evidence_gaps: string[];
    recommended_actions: string[];
    next_sales_action: { action: string; reason: string; due_date: string | null; activity_id: number | null; status: "scheduled" | "recommended" | "paused" };
    latest_sales_outcome: string | null;
    evidence_summary: { verified_sources: number; unverified_sources: number; rejected_sources: number; projects: number; professional_contacts: number };
    human_review_required: boolean;
  };
  projects: { id: number; name: string; location: string | null; status: string; estimated_units: number | null; estimated_doors: number | null; explicit_estimated_doors: number | null; doors_per_unit: number | null; estimate_method: string; estimate_basis: string | null; demand_confidence: string; demand_notes: string | null }[];
  relationships: { id: number; related_company_id: number; related_company_name: string; relationship_type: string; project_name: string | null; notes: string | null }[];
  activities: { id: number; activity_type: string; notes: string; next_action: string | null; sales_outcome: string | null; due_date: string | null; completed_at: string | null; created_at: string }[];
};

type DashboardNextAction = { activity_id: number; company_id: number; company_name: string; action: string; due_date: string | null } | null;
type Summary = { companies: number; projects: number; verified_sources: number; open_follow_ups: number; next_action: DashboardNextAction };
type ActivityForm = { activity_type: string; notes: string; next_action: string; sales_outcome: string; due_date: string };

const emptySummary: Summary = { companies: 0, projects: 0, verified_sources: 0, open_follow_ups: 0, next_action: null };

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: "same-origin", ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ? JSON.stringify(body.detail) : `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function App() {
  const [user, setUser] = useState<AppUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [companies, setCompanies] = useState<Company[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [summary, setSummary] = useState<Summary>(emptySummary);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [verification, setVerification] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [hasProject, setHasProject] = useState("");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const pageSize = 25;
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [selectedSearchId, setSelectedSearchId] = useState("");
  const [saveSearchName, setSaveSearchName] = useState("");
  const [teamEmail, setTeamEmail] = useState("");
  const [teamPassword, setTeamPassword] = useState("");
  const [teamRole, setTeamRole] = useState<"sales" | "viewer" | "admin">("sales");
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [teamNotice, setTeamNotice] = useState("");
  const [researchQuestion, setResearchQuestion] = useState("");
  const [researchResult, setResearchResult] = useState<ResearchResult | null>(null);
  const [researchStatus, setResearchStatus] = useState<{ generation_available: boolean; provider: string; model: string; privacy: string } | null>(null);
  const [researchBusy, setResearchBusy] = useState(false);
  const [researchError, setResearchError] = useState("");
  const [useAiAnswer, setUseAiAnswer] = useState(false);
  const [aiEnrichment, setAiEnrichment] = useState<EnrichmentResult | null>(null);
  const [aiEnrichmentBusy, setAiEnrichmentBusy] = useState(false);
  const [aiEnrichmentError, setAiEnrichmentError] = useState("");
  const [includeGraph, setIncludeGraph] = useState(true);
  const [knowledgeGraph, setKnowledgeGraph] = useState<KnowledgeGraphData | null>(null);
  const [graphQuery, setGraphQuery] = useState("");
  const [graphCity, setGraphCity] = useState("");
  const [graphError, setGraphError] = useState("");
  const [graphBusy, setGraphBusy] = useState(false);
  const [graphSelection, setGraphSelection] = useState<KnowledgeNode | null>(null);
  const [activity, setActivity] = useState<ActivityForm>({ activity_type: "call", notes: "", next_action: "", sales_outcome: "", due_date: "" });
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request<AppUser>("/api/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  useEffect(() => {
    if (!user) return;
    request<SavedSearch[]>("/api/saved-searches").then(setSavedSearches).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Could not load saved searches.");
    });
    request<string[]>("/api/categories").then(setCategories).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Could not load prospect categories.");
    });
    request<typeof researchStatus>("/api/research/status").then(setResearchStatus).catch((reason) => {
      setResearchError(reason instanceof Error ? reason.message : "Could not load research configuration.");
    });
    void loadKnowledgeGraph();
  }, [user]);

  async function loadCompanies() {
    setError("");
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      if (category) params.set("category", category);
      if (verification) params.set("verification", verification);
      if (city.trim()) params.set("city", city.trim());
      if (state.trim()) params.set("state", state.trim());
      if (hasProject) params.set("has_project", hasProject);
      params.set("limit", String(pageSize));
      params.set("offset", String(offset));
      const [rowsResponse, totals] = await Promise.all([
        fetch(`/api/companies?${params}`),
        request<Summary>("/api/dashboard/summary"),
      ]);
      if (!rowsResponse.ok) throw new Error(`Could not load prospects (${rowsResponse.status}).`);
      const rows = await rowsResponse.json() as Company[];
      setCompanies(rows);
      setTotal(Number(rowsResponse.headers.get("X-Total-Count") || rows.length));
      setSummary(totals);
      if (selectedId !== null && !rows.some((row) => row.id === selectedId)) {
        setSelectedId(null);
        setDetail(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load prospects.");
    }
  }

  async function loadDetail(id: number) {
    setSelectedId(id);
    setError("");
    try {
      setDetail(await request<CompanyDetail>(`/api/companies/${id}`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load company profile.");
    }
  }

  async function loadKnowledgeGraph(queryText = graphQuery, cityText = graphCity) {
    setGraphBusy(true);
    setGraphError("");
    try {
      const params = new URLSearchParams({ limit: "120" });
      if (queryText.trim()) params.set("q", queryText.trim());
      if (cityText.trim()) params.set("city", cityText.trim());
      setKnowledgeGraph(await request<KnowledgeGraphData>(`/api/knowledge-graph?${params}`));
      setGraphSelection(null);
    } catch (reason) {
      setGraphError(reason instanceof Error ? reason.message : "Could not load the knowledge graph.");
    } finally {
      setGraphBusy(false);
    }
  }

  useEffect(() => {
    if (!user) return;
    const timer = window.setTimeout(() => void loadCompanies(), 200);
    return () => window.clearTimeout(timer);
  }, [query, category, verification, city, state, hasProject, offset, user]);

  useEffect(() => {
    setOffset(0);
  }, [query, category, verification, city, state, hasProject]);

  useEffect(() => {
    if (selectedId !== null) void loadDetail(selectedId);
  }, [selectedId]);

  async function saveActivity(event: FormEvent) {
    event.preventDefault();
    if (!detail) return;
    setBusy(true);
    setNotice("");
    setError("");
    try {
      await request(`/api/companies/${detail.id}/activities`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...activity, due_date: activity.due_date || null, next_action: activity.next_action || null }),
      });
      setActivity({ activity_type: "call", notes: "", next_action: "", sales_outcome: "", due_date: "" });
      setNotice("Follow-up saved.");
      await loadDetail(detail.id);
      await loadCompanies();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save follow-up.");
    } finally {
      setBusy(false);
    }
  }

  async function importCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setNotice("");
    setError("");
    const form = new FormData();
    form.append("file", file);
    try {
      const result = await request<{ companies_created: number; sources_created: number; projects_created: number; source_contents_added: number; workflow: { stages: string[]; duplicate_rows_skipped: number; score_preview: { average: number; minimum: number; maximum: number } | null } }>("/api/import/csv", { method: "POST", body: form });
      const duplicateMessage = result.workflow.duplicate_rows_skipped ? ` ${result.workflow.duplicate_rows_skipped} duplicate row(s) skipped.` : "";
      const scoreMessage = result.workflow.score_preview ? ` Average lead score preview: ${result.workflow.score_preview.average}.` : "";
      setNotice(`Imported ${result.companies_created} companies, ${result.sources_created} sources (${result.source_contents_added} searchable excerpts), and ${result.projects_created} projects.${duplicateMessage}${scoreMessage} Workflow: ${result.workflow.stages.join(" → ")}.`);
      await Promise.all([
        loadCompanies(),
        loadKnowledgeGraph(),
        request<string[]>("/api/categories").then(setCategories),
      ]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "CSV import failed.");
    } finally {
      event.target.value = "";
      setBusy(false);
    }
  }

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setAuthBusy(true);
    setAuthError("");
    try {
      const signedIn = await request<AppUser>("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      setUser(signedIn);
    } catch (reason) {
      setAuthError(reason instanceof Error ? reason.message : "Sign in failed.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function signOut() {
    try {
      await request("/api/auth/logout", { method: "POST" });
      setUser(null);
      setCompanies([]);
      setDetail(null);
      setSummary(emptySummary);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not sign out.");
    }
  }

  function applyFilters(filters: SavedSearch["filters"]) {
    setQuery(String(filters.q || ""));
    setCategory(String(filters.category || ""));
    setCity(String(filters.city || ""));
    setState(String(filters.state || ""));
    setVerification(String(filters.verification || ""));
    setHasProject(filters.has_project === true ? "true" : filters.has_project === false ? "false" : "");
    setOffset(0);
  }

  async function saveSearch() {
    if (!saveSearchName.trim()) return;
    const filters = {
      q: query.trim() || null,
      category: category || null,
      city: city.trim() || null,
      state: state.trim() || null,
      verification: verification || null,
      has_project: hasProject ? hasProject === "true" : null,
    };
    try {
      const saved = await request<SavedSearch>("/api/saved-searches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: saveSearchName.trim(), filters }),
      });
      setSavedSearches((previous) => [...previous, saved].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedSearchId(String(saved.id));
      setSaveSearchName("");
      setNotice("Search saved to your account.");
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save search.");
    }
  }

  async function deleteSavedSearch() {
    if (!selectedSearchId) return;
    try {
      await request(`/api/saved-searches/${selectedSearchId}`, { method: "DELETE" });
      setSavedSearches((previous) => previous.filter((item) => item.id !== Number(selectedSearchId)));
      setSelectedSearchId("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete saved search.");
    }
  }

  async function addTeamMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTeamNotice("");
    try {
      await request("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: teamEmail, password: teamPassword, role: teamRole }),
      });
      setTeamEmail("");
      setTeamPassword("");
      setTeamNotice("Team account created.");
      const events = await request<AuditEvent[]>("/api/audit");
      setAuditEvents(events);
    } catch (reason) {
      setTeamNotice(reason instanceof Error ? reason.message : "Could not create team account.");
    }
  }

  async function loadAudit() {
    try {
      setAuditEvents(await request<AuditEvent[]>("/api/audit"));
    } catch (reason) {
      setTeamNotice(reason instanceof Error ? reason.message : "Could not load audit trail.");
    }
  }

  async function submitResearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setResearchBusy(true);
    setResearchError("");
    try {
      setResearchResult(await request<ResearchResult>("/api/research/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: researchQuestion, top_k: 5, include_graph: includeGraph, use_llm: useAiAnswer }),
      }));
    } catch (reason) {
      setResearchError(reason instanceof Error ? reason.message : "Research request failed.");
    } finally {
      setResearchBusy(false);
    }
  }

  async function enrichCompany(companyId: number) {
    setAiEnrichmentBusy(true);
    setAiEnrichmentError("");
    try {
      setAiEnrichment(await request<EnrichmentResult>(`/api/companies/${companyId}/ai-enrichment`, {
        method: "POST",
      }));
    } catch (reason) {
      setAiEnrichmentError(reason instanceof Error ? reason.message : "AI enrichment failed.");
    } finally {
      setAiEnrichmentBusy(false);
    }
  }

  if (authLoading) return <div className="auth-page"><div className="auth-card">Checking your session…</div></div>;
  if (!user) return <LoginPage onSubmit={signIn} busy={authBusy} error={authError} />;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark">V</div>
        <div className="brand-name">VIDYA<span>INTELLIGENCE</span></div>
        <div className="nav-label">WORKSPACE</div>
        <button className="nav-item active"><span>◈</span> Market overview</button>
        <button className="nav-item" onClick={() => document.getElementById("prospects")?.scrollIntoView({ behavior: "smooth" })}><span>◎</span> Prospects</button>
        <button className="nav-item" onClick={() => document.getElementById("knowledge-graph")?.scrollIntoView({ behavior: "smooth" })}><span>⌘</span> Knowledge graph</button>
        <button className="nav-item" onClick={() => document.getElementById("research")?.scrollIntoView({ behavior: "smooth" })}><span>⌕</span> Research</button>
        <div className="sidebar-bottom">
          <div className="city-card"><span className="pulse" /> PILOT REGION<strong>Varanasi, UP</strong></div>
          <div className="user-badge"><div className="avatar">{user.email.slice(0, 2).toUpperCase()}</div><div>{user.email}<small>{user.role} account</small></div><button className="signout" onClick={signOut}>Sign out</button></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar"><div>Market intelligence <span className="crumb">/ Varanasi pilot</span></div><div className="top-actions"><span className="live-dot" /> Data workspace {user.role === "admin" && <AdminTools onSubmit={addTeamMember} email={teamEmail} setEmail={setTeamEmail} password={teamPassword} setPassword={setTeamPassword} role={teamRole} setRole={setTeamRole} notice={teamNotice} events={auditEvents} onOpen={loadAudit} />}<button className="icon-button" onClick={signOut} aria-label="Sign out">↗</button></div></header>
        <section className="welcome">
          <div><div className="eyebrow">MONDAY, MARKET BRIEF</div><h1>Find your next<br /><em>great opportunity.</em></h1><p>Source-backed prospects and project signals, organized for your sales team.</p></div>
          <div className="welcome-art" aria-hidden="true"><div className="sun" /><div className="hill hill-back" /><div className="hill hill-front" /><div className="door-shape"><div /></div></div>
        </section>

        <section className="metrics" aria-label="Market summary">
          <Metric label="PROSPECTS TRACKED" value={summary.companies} icon="◎" trend="In your workspace" />
          <Metric label="PROJECT SIGNALS" value={summary.projects} icon="⌂" trend="Linked to prospects" />
          <Metric label="VERIFIED SOURCES" value={summary.verified_sources} icon="↗" trend="Evidence checked" />
          <Metric label="OPEN NEXT ACTIONS" value={summary.open_follow_ups} icon="◷" trend="Sales follow-ups to close" />
        </section>
        <section className="dashboard-next-action" aria-label="Next recommended sales action">
          <div><div className="eyebrow">SALES PRIORITY</div><strong>{summary.next_action?.action || "Review a prospect profile for its recommended next step."}</strong>
            <small>{summary.next_action ? `${summary.next_action.company_name}${summary.next_action.due_date ? ` · due ${summary.next_action.due_date}` : ""}` : "No open scheduled follow-ups"}</small>
          </div>
          {summary.next_action && <button className="button secondary" onClick={() => { setSelectedId(summary.next_action?.company_id ?? null); document.getElementById("prospects")?.scrollIntoView({ behavior: "smooth" }); }}>Open prospect →</button>}
        </section>

        <section className="knowledge-graph-section" id="knowledge-graph">
          <div className="section-heading">
            <div><div className="eyebrow">CONNECTED MARKET INTELLIGENCE</div><h2>Knowledge graph</h2><p>Explore how local companies connect to projects and each other.</p></div>
            <button className="button secondary" onClick={() => void loadKnowledgeGraph()} disabled={graphBusy}>{graphBusy ? "Loading…" : "↻ Refresh graph"}</button>
          </div>
          <form className="graph-filters" onSubmit={(event) => { event.preventDefault(); void loadKnowledgeGraph(); }}>
            <input aria-label="Search graph companies" placeholder="Find a company or category" value={graphQuery} onChange={(event) => setGraphQuery(event.target.value)} />
            <input aria-label="Filter graph by city" placeholder="City" value={graphCity} onChange={(event) => setGraphCity(event.target.value)} />
            <button className="button primary" disabled={graphBusy}>Explore</button>
          </form>
          {graphError && <div className="notice error" role="alert">{graphError}<button onClick={() => setGraphError("")} aria-label="Dismiss">×</button></div>}
          {knowledgeGraph && <KnowledgeGraphView data={knowledgeGraph} selection={graphSelection} onSelect={setGraphSelection} onOpenCompany={(companyId) => { setSelectedId(companyId); document.getElementById("prospects")?.scrollIntoView({ behavior: "smooth" }); }} />}
        </section>

        <section className="research-section" id="research">
          <div className="section-heading"><div><div className="eyebrow">EVIDENCE-LED DISCOVERY</div><h2>Research desk</h2><p>Search reviewed sources, then follow company and project relationships.</p></div><span className="research-mode">RAG + GRAPH RETRIEVAL</span></div>
          <form className="research-form" onSubmit={submitResearch}>
            <label htmlFor="research-question">What would you like to find out?</label>
            <div className="research-query-row"><input id="research-question" minLength={3} maxLength={1000} required placeholder="e.g. Which verified sources mention upcoming housing projects in Varanasi?" value={researchQuestion} onChange={(event) => setResearchQuestion(event.target.value)} /><button className="button primary" disabled={researchBusy}>{researchBusy ? "Researching…" : "Research"}</button></div>
            <div className="research-options"><label><input type="checkbox" checked={includeGraph} onChange={(event) => setIncludeGraph(event.target.checked)} /> Expand related companies and projects (GraphRAG)</label><label title={researchStatus?.privacy}><input type="checkbox" checked={useAiAnswer} disabled={!researchStatus?.generation_available} onChange={(event) => setUseAiAnswer(event.target.checked)} /> Generate an AI answer{researchStatus?.generation_available ? ` with ${researchStatus.model}` : " (provider not configured)"}</label></div>
            <p className="privacy-note">{researchStatus?.privacy || "AI answers are off by default. Configure a provider to enable them."} Add source excerpts through the reviewed CSV import to make records searchable.</p>
          </form>
          {researchError && <div className="notice error" role="alert">{researchError}<button onClick={() => setResearchError("")} aria-label="Dismiss">×</button></div>}
          {researchResult && <ResearchPanel result={researchResult} />}
        </section>

        <section className="prospects-section" id="prospects">
          <div className="section-heading"><div><div className="eyebrow">YOUR PIPELINE</div><h2>Prospect intelligence</h2><p>Prioritize relevant businesses with transparent evidence and next steps.</p></div>
            <div className="header-buttons"><a className="button secondary" href="/api/export.csv">↓ Export CSV</a>{user.role === "admin" && <label className={`button primary ${busy ? "disabled" : ""}`}>＋ Import reviewed CSV<input type="file" accept=".csv,text/csv" onChange={importCsv} disabled={busy} hidden /></label>}</div>
          </div>
          {(notice || error) && <div className={`notice ${error ? "error" : ""}`} role="status">{error || notice}<button onClick={() => { setError(""); setNotice(""); }} aria-label="Dismiss">×</button></div>}
          <div className="workspace-grid">
            <div className="list-panel">
              <div className="filters">
                <label className="searchbox"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search companies, categories..." /></label>
                <select value={category} onChange={(event) => setCategory(event.target.value)} aria-label="Filter by category"><option value="">All categories</option>{categories.map((item) => <option key={item}>{item}</option>)}</select>
                <select value={verification} onChange={(event) => setVerification(event.target.value)} aria-label="Filter by source status"><option value="">All evidence</option><option value="verified">Verified sources</option><option value="unverified">Needs verification</option></select>
                <input className="city-filter" value={city} onChange={(event) => setCity(event.target.value)} placeholder="City" aria-label="Filter by city" />
                <input className="city-filter" value={state} onChange={(event) => setState(event.target.value)} placeholder="State" aria-label="Filter by state" />
                <select value={hasProject} onChange={(event) => setHasProject(event.target.value)} aria-label="Filter by project"><option value="">Any project status</option><option value="true">Has linked project</option><option value="false">No linked project</option></select>
                <div className="saved-search-controls"><select aria-label="Saved searches" value={selectedSearchId} onChange={(event) => { setSelectedSearchId(event.target.value); const selected = savedSearches.find((item) => item.id === Number(event.target.value)); if (selected) applyFilters(selected.filters); }}><option value="">Saved searches</option>{savedSearches.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select>{selectedSearchId && <button className="text-button" onClick={deleteSavedSearch}>Delete</button>}<input aria-label="New saved search name" placeholder="Save current filters as…" value={saveSearchName} onChange={(event) => setSaveSearchName(event.target.value)} /><button className="button secondary" onClick={saveSearch} disabled={!saveSearchName.trim()}>Save view</button></div>
              </div>
              <div className="table-scroll"><table><thead><tr><th>BUSINESS</th><th>LOCATION</th><th>EVIDENCE</th><th>LEAD SCORE</th></tr></thead>
                <tbody>{companies.map((company) => <tr key={company.id} className={selectedId === company.id ? "selected" : ""} onClick={() => setSelectedId(company.id)}>
                  <td><div className="company-cell"><div className="company-icon">{company.name.slice(0, 1).toUpperCase()}</div><div><strong>{company.name}</strong><small>{company.category}</small></div></div></td>
                  <td>{company.city}<small className="sub-cell">{company.state}</small></td>
                  <td><span className={`evidence ${company.verified_source_count ? "verified" : ""}`}><i />{company.verified_source_count ? "Verified" : "Unverified"}</span><small className="sub-cell">{company.project_count} projects</small></td>
                  <td><Score score={company.score} /></td>
                </tr>)}
                {!companies.length && <tr><td colSpan={4} className="empty-row">No prospects match these filters. Import a reviewed CSV to get started.</td></tr>}
                </tbody></table></div>
              <div className="table-footer">Showing <strong>{total === 0 ? 0 : offset + 1}–{Math.min(offset + companies.length, total)}</strong> of {total} prospects <button className="text-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button><button className="text-button" disabled={offset + pageSize >= total} onClick={() => setOffset(offset + pageSize)}>Next</button><span>Scores are evidence-based guidance, not predictions.</span></div>
            </div>
            <aside className="detail-panel">
              {detail ? <CompanyProfile company={detail} companies={companies} activity={activity} setActivity={setActivity} saveActivity={saveActivity} refresh={async () => { await loadDetail(detail.id); await loadCompanies(); await loadKnowledgeGraph(); }} canWrite={user.role !== "viewer"} busy={busy} aiAvailable={researchStatus?.generation_available ?? false} enrichment={aiEnrichment?.company_id === detail.id ? aiEnrichment : null} enrichmentBusy={aiEnrichmentBusy} enrichmentError={aiEnrichmentError} onEnrich={() => void enrichCompany(detail.id)} /> :
                <div className="profile-empty"><div className="empty-orbit">◎</div><h3>Select a prospect</h3><p>Review its source evidence, project signals, relationships, and recommended next step.</p><div className="empty-hint">TIP <span>Verified sources improve confidence—not commercial fit.</span></div></div>}
            </aside>
          </div>
        </section>
        <footer>VIDYA TIMBER <span>•</span> ARCHWOOD <small>Private pilot workspace · Data should be verified before outreach</small></footer>
      </main>
    </div>
  );
}

function Metric({ label, value, icon, trend }: { label: string; value: number; icon: string; trend: string }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span><i>{icon}</i></div><strong>{value.toLocaleString("en-IN")}</strong><small><span className="metric-mark">↗</span> {trend}</small></article>;
}

function LoginPage({ onSubmit, busy, error }: { onSubmit: (event: FormEvent<HTMLFormElement>) => void; busy: boolean; error: string }) {
  return <div className="auth-page"><form className="auth-card" onSubmit={onSubmit}>
    <div className="brand-mark">V</div><div className="eyebrow">VIDYA TIMBER · MARKET INTELLIGENCE</div>
    <h1>Welcome back.</h1><p>Sign in to your team's source-backed market workspace.</p>
    {error && <div className="notice error" role="alert">{error}</div>}
    <label>Email address<input name="email" type="email" autoComplete="username" required /></label>
    <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
    <button className="button primary full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
  </form></div>;
}

function AdminTools({ onSubmit, email, setEmail, password, setPassword, role, setRole, notice, events, onOpen }: {
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  email: string;
  setEmail: (value: string) => void;
  password: string;
  setPassword: (value: string) => void;
  role: "admin" | "sales" | "viewer";
  setRole: (value: "admin" | "sales" | "viewer") => void;
  notice: string;
  events: AuditEvent[];
  onOpen: () => void;
}) {
  return <details className="admin-tools" onToggle={(event) => { if (event.currentTarget.open) onOpen(); }}>
    <summary>Admin</summary>
    <div className="admin-popover">
      <strong>Create team account</strong>
      <form onSubmit={onSubmit}>
        <input aria-label="Team member email" type="email" required placeholder="name@company.com" value={email} onChange={(event) => setEmail(event.target.value)} />
        <input aria-label="Temporary password" type="password" minLength={12} required placeholder="Temporary password (12+ chars)" value={password} onChange={(event) => setPassword(event.target.value)} />
        <div className="form-row"><select aria-label="Team member role" value={role} onChange={(event) => setRole(event.target.value as "admin" | "sales" | "viewer")}><option value="sales">Sales</option><option value="viewer">Viewer</option><option value="admin">Admin</option></select><button className="button primary">Create user</button></div>
      </form>
      {notice && <small className="muted">{notice}</small>}
      <div className="admin-audit"><strong>Recent audit events</strong>{events.slice(0, 8).map((event) => <div key={event.id}><span>{event.action} {event.entity_type}</span><small>{event.actor_email || "System"} · {new Date(event.occurred_at).toLocaleString("en-IN")}</small></div>)}</div>
    </div>
  </details>;
}

function KnowledgeGraphView({ data, selection, onSelect, onOpenCompany }: {
  data: KnowledgeGraphData;
  selection: KnowledgeNode | null;
  onSelect: (node: KnowledgeNode | null) => void;
  onOpenCompany: (companyId: number) => void;
}) {
  const positions = useMemo(() => {
    const result = new Map<string, { x: number; y: number }>();
    const companies = data.nodes.filter((node) => node.type === "company");
    const projects = data.nodes.filter((node) => node.type === "project");
    const companyPositions = new Map<number, { x: number; y: number }>();
    companies.forEach((node, index) => {
      const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(companies.length, 1);
      const radius = companies.length <= 8 ? 175 : companies.length <= 20 ? 225 : 260;
      const point = { x: 500 + radius * Math.cos(angle), y: 310 + radius * 0.72 * Math.sin(angle) };
      companyPositions.set(node.entity_id, point);
      result.set(node.id, point);
    });
    const projectIndex = new Map<number, number>();
    projects.forEach((node) => {
      const parent = companyPositions.get(node.company_id || 0) || { x: 500, y: 310 };
      const index = projectIndex.get(node.company_id || 0) || 0;
      projectIndex.set(node.company_id || 0, index + 1);
      const angle = index * 2.4 - Math.PI / 2;
      const radius = 45 + Math.floor(index / 5) * 20;
      result.set(node.id, {
        x: Math.max(28, Math.min(972, parent.x + Math.cos(angle) * radius)),
        y: Math.max(30, Math.min(590, parent.y + Math.sin(angle) * radius)),
      });
    });
    return result;
  }, [data.nodes]);
  const nodeById = useMemo(() => new Map(data.nodes.map((node) => [node.id, node])), [data.nodes]);
  const connected = selection ? data.edges.filter((edge) => edge.source === selection.id || edge.target === selection.id) : [];

  function companyColor(category: string | undefined) {
    const value = (category || "").toLowerCase();
    if (value.includes("architect") || value.includes("design")) return "#b99154";
    if (value.includes("builder") || value.includes("developer")) return "#3c7963";
    if (value.includes("contractor") || value.includes("construction")) return "#527fa0";
    return "#6d8274";
  }

  return <div className="knowledge-graph">
    <div className="graph-summary">
      <span><i className="graph-legend-company" />Companies <strong>{data.included_companies}</strong></span>
      <span><i className="graph-legend-project" />Projects <strong>{data.included_projects}</strong></span>
      <span><i className="graph-legend-link" />Connections <strong>{data.edges.length}</strong></span>
      {data.truncated && <small>Bounded view: {data.included_companies}/{data.total_companies} companies and {data.included_projects}/{data.total_projects} projects.</small>}
    </div>
    {!data.nodes.length ? <div className="graph-empty">No companies or projects match. Import reviewed records or adjust your search.</div> :
      <div className="graph-canvas-scroll"><svg className="graph-canvas" viewBox="0 0 1000 640" role="img" aria-label="Interactive knowledge graph of companies and construction projects">
        <defs><marker id="graph-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#b9c5bc" /></marker></defs>
        {data.edges.map((edge) => {
          const start = positions.get(edge.source);
          const end = positions.get(edge.target);
          if (!start || !end) return null;
          const relation = edge.type !== "has project";
          return <line key={edge.id} className={`graph-edge-line ${relation ? "business-edge" : "project-edge"}`} x1={start.x} y1={start.y} x2={end.x} y2={end.y} markerEnd={relation ? "url(#graph-arrow)" : undefined}><title>{edge.type}</title></line>;
        })}
        {data.nodes.map((node) => {
          const point = positions.get(node.id);
          if (!point) return null;
          const selected = selection?.id === node.id;
          const radius = node.type === "project" ? 7 : 10 + Math.min((node.score || 0) / 18, 5);
          const label = node.label.length > 21 ? `${node.label.slice(0, 19)}…` : node.label;
          return <g key={node.id} className={`graph-node-group ${selected ? "selected" : ""}`} transform={`translate(${point.x} ${point.y})`} role="button" tabIndex={0} aria-label={`${node.type}: ${node.label}`} onClick={() => onSelect(node)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(node); } }}>
            <title>{node.type === "company" ? `${node.label} · ${node.category} · lead score ${node.score}` : `${node.label} · ${node.status}`}</title>
            <circle r={radius} fill={node.type === "project" ? "#d6a858" : companyColor(node.category)} />
            {node.type === "company" && node.verified_sources ? <circle r={radius + 4} className="graph-verified-ring" /> : null}
            <text y={radius + 13} textAnchor="middle">{label}</text>
          </g>;
        })}
      </svg></div>}
    {selection && <div className="graph-selection">
      <div className="graph-selected-title"><span className={`graph-selected-icon ${selection.type}`} /> <div><strong>{selection.label}</strong><small>{selection.type === "company" ? `${selection.category} · ${selection.city} · Score ${selection.score}` : `${selection.status} · ${selection.city || "Location not recorded"}`}</small></div></div>
      <div className="graph-connected">
        {selection.type === "company" && <span>{selection.verified_sources} verified source(s) · {selection.project_count} project(s)</span>}
        {selection.type === "project" && <span>{selection.estimated_units ?? "Units n/a"} units · {selection.estimated_doors ?? "Doors n/a"} estimated doors · {selection.demand_confidence} confidence</span>}
        {connected.map((edge) => {
          const other = nodeById.get(edge.source === selection.id ? edge.target : edge.source);
          return <span key={edge.id}>{edge.type} <b>{other?.label || "Related record"}</b></span>;
        })}
      </div>
      {selection.type === "company" && <button className="button secondary" onClick={() => onOpenCompany(selection.entity_id)}>Open company profile →</button>}
      {selection.type === "project" && selection.company_id && <button className="button secondary" onClick={() => { if (selection.company_id) onOpenCompany(selection.company_id); }}>Open owning company →</button>}
      <button className="text-button" onClick={() => onSelect(null)}>Clear selection</button>
    </div>}
  </div>;
}

function ResearchPanel({ result }: { result: ResearchResult }) {
  return <div className="research-results">
    <div className="research-answer">
      <div className="research-result-heading"><span>{result.mode === "openai" ? "AI ANSWER · SOURCE-GROUNDED" : "RETRIEVAL RESULTS · NO AI SYNTHESIS"}</span><small>{result.workflow.join(" → ")}</small></div>
      <p>{result.answer}</p>
      {result.mode === "openai" && <small className="privacy-note">Claims cite verified excerpts below. Confirm important details at the original sources.</small>}
    </div>
    <div className="research-columns">
      <section><div className="research-subheading">Retrieved source evidence <span>{result.evidence.length}</span></div>
        {result.evidence.length ? result.evidence.map((item) => <article className="evidence-card" key={item.source_id}>
          <div className="evidence-card-top"><strong>[{item.citation}] {item.source_title || item.company_name || "Source"}</strong><span className={`evidence ${item.verification_status === "verified" ? "verified" : ""}`}><i />{item.verification_status}</span></div>
          <small>{item.company_name || "Unlinked source"}{item.project_name ? ` · ${item.project_name}` : ""} · {item.retrieval === "graph" ? "Graph expansion" : `Relevance ${item.relevance_score.toFixed(2)}`}</small>
          <p>{item.excerpt || "No reviewed source excerpt was stored."}</p>
          <a href={item.source_url} target="_blank" rel="noreferrer">Open original source ↗</a>
        </article>) : <div className="research-empty">No source matched. Add source excerpts to reviewed CSV records and mark them verified after review.</div>}
      </section>
      <section><div className="research-subheading">Company & project graph <span>{result.graph_neighbors} companies</span></div>
        {result.graph_context.length ? result.graph_context.map((item, index) => <article className="graph-card" key={`${item.context_type || "relation"}-${index}`}>
          <span className="graph-node">{item.from_company || item.company_name || "Project"}</span>
          <span className="graph-edge">{item.relationship_type || "has project"} →</span>
          <strong>{item.to_company || item.project_name}</strong>
          {item.status && <small>{item.status}</small>}
        </article>) : <div className="research-empty">No linked companies or projects found around these sources.</div>}
      </section>
    </div>
  </div>;
}

function ProjectDemandEditor({ project, canWrite, onSaved }: {
  project: CompanyDetail["projects"][number];
  canWrite: boolean;
  onSaved: () => void;
}) {
  const [units, setUnits] = useState(project.estimated_units?.toString() || "");
  const [explicitDoors, setExplicitDoors] = useState(project.explicit_estimated_doors?.toString() || "");
  const [doorsPerUnit, setDoorsPerUnit] = useState(project.doors_per_unit?.toString() || "");
  const [basis, setBasis] = useState(project.estimate_basis || "");
  const [confidence, setConfidence] = useState(project.demand_confidence);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setUnits(project.estimated_units?.toString() || "");
    setExplicitDoors(project.explicit_estimated_doors?.toString() || "");
    setDoorsPerUnit(project.doors_per_unit?.toString() || "");
    setBasis(project.estimate_basis || "");
    setConfidence(project.demand_confidence);
  }, [project]);

  async function saveDemand(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await request(`/api/projects/${project.id}/demand`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          estimated_units: units ? Number(units) : null,
          estimated_doors: explicitDoors ? Number(explicitDoors) : null,
          doors_per_unit: doorsPerUnit ? Number(doorsPerUnit) : null,
          estimate_basis: basis || null,
          demand_confidence: confidence,
          demand_notes: project.demand_notes,
        }),
      });
      setMessage("Estimate saved.");
      onSaved();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not save estimate.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="project-card">
    <div><strong>{project.name}</strong><span>{project.location || "Location not recorded"} · {project.status}</span></div>
    <div className="project-demand">{project.estimated_doors !== null ? `${project.estimated_doors.toLocaleString("en-IN")} est. doors` : "Demand not estimated"}{project.estimated_units !== null ? <small>{project.estimated_units.toLocaleString("en-IN")} units · {project.demand_confidence} confidence</small> : null}</div>
    <div className="demand-basis"><span>Estimate method</span><strong>{project.estimate_method}</strong>{project.estimate_basis && <small>{project.estimate_basis}</small>}</div>
    {project.demand_notes && <p>{project.demand_notes}</p>}
    {canWrite && <details className="demand-editor"><summary>Edit assumptions</summary><form onSubmit={saveDemand}>
      <div className="form-row"><label>Units<input type="number" min="0" step="1" value={units} onChange={(event) => setUnits(event.target.value)} /></label><label>Doors per unit<input type="number" min="0" max="100" step="0.1" value={doorsPerUnit} onChange={(event) => setDoorsPerUnit(event.target.value)} /></label></div>
      <div className="form-row"><label>Explicit door estimate<input type="number" min="0" step="1" value={explicitDoors} onChange={(event) => setExplicitDoors(event.target.value)} placeholder="Leave blank to calculate" /></label><label>Confidence<select value={confidence} onChange={(event) => setConfidence(event.target.value)}><option value="unknown">Unknown</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label></div>
      <label>Evidence / assumptions<input value={basis} onChange={(event) => setBasis(event.target.value)} placeholder="e.g. project brochure; 4 doors per residential unit" /></label>
      <button className="button secondary" disabled={busy}>{busy ? "Saving…" : "Save estimate"}</button>{message && <small className="muted">{message}</small>}
    </form></details>}
  </div>;
}

function Score({ score }: { score: number }) {
  const tone = score >= 65 ? "high" : score >= 40 ? "mid" : "low";
  return <div className={`score ${tone}`}><div className="score-track"><i style={{ width: `${score}%` }} /></div><strong>{score}</strong></div>;
}

function CompanyProfile({ company, companies, activity, setActivity, saveActivity, refresh, canWrite, busy, aiAvailable, enrichment, enrichmentBusy, enrichmentError, onEnrich }: {
  company: CompanyDetail;
  companies: Company[];
  activity: ActivityForm;
  setActivity: (form: ActivityForm) => void;
  saveActivity: (event: FormEvent) => void;
  refresh: () => void;
  canWrite: boolean;
  busy: boolean;
  aiAvailable: boolean;
  enrichment: EnrichmentResult | null;
  enrichmentBusy: boolean;
  enrichmentError: string;
  onEnrich: () => void;
}) {
  const [relatedCompanyId, setRelatedCompanyId] = useState("");
  const [relationshipType, setRelationshipType] = useState("works with");
  const [relationshipMessage, setRelationshipMessage] = useState("");
  const [relationshipBusy, setRelationshipBusy] = useState(false);
  const [activityMessage, setActivityMessage] = useState("");
  const [relatedProjectId, setRelatedProjectId] = useState("");
  const relatedCompanies = companies.filter((item) => item.id !== company.id);

  async function completeFollowUp(activityId: number) {
    try {
      await request(`/api/activities/${activityId}/complete`, { method: "POST" });
      setActivityMessage("Follow-up completed.");
      refresh();
    } catch (reason) {
      setActivityMessage(reason instanceof Error ? reason.message : "Could not complete follow-up.");
    }
  }

  async function saveRelationship(event: FormEvent) {
    event.preventDefault();
    if (!relatedCompanyId) return;
    setRelationshipBusy(true);
    setRelationshipMessage("");
    try {
      await request("/api/relationships", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_id: company.id,
          related_company_id: Number(relatedCompanyId),
          relationship_type: relationshipType,
          project_id: relatedProjectId ? Number(relatedProjectId) : null,
        }),
      });
      setRelationshipMessage("Relationship added.");
      setRelatedCompanyId("");
      setRelatedProjectId("");
      refresh();
    } catch (reason) {
      setRelationshipMessage(reason instanceof Error ? reason.message : "Could not save relationship.");
    } finally {
      setRelationshipBusy(false);
    }
  }

  async function removeRelationship(relationshipId: number) {
    try {
      await request(`/api/relationships/${relationshipId}`, { method: "DELETE" });
      refresh();
    } catch (reason) {
      setRelationshipMessage(reason instanceof Error ? reason.message : "Could not remove relationship.");
    }
  }

  return <div className="profile-content">
    <div className="profile-heading"><div className="company-icon large">{company.name.slice(0, 1).toUpperCase()}</div><div><div className="eyebrow">PROSPECT PROFILE</div><h3>{company.name}</h3><span>{company.category} · {company.city}</span></div></div>
    {company.description && <p className="description">{company.description}</p>}
    <div className="score-explanation"><div className="score-line"><span>LEAD SCORE</span><Score score={company.score} /></div><ul>{company.score_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
      <div className="score-breakdown">{company.opportunity_report.score_components.map((component) => <div key={component.key}><span>{component.label}</span><strong>{component.points}/{component.maximum}</strong></div>)}</div>
    </div>
    <div className="opportunity-report">
      <div className="opportunity-heading"><strong>Opportunity brief</strong><span className={`priority ${company.opportunity_report.priority}`}>{company.opportunity_report.priority} priority</span></div>
      <small>{company.opportunity_report.evidence_summary.verified_sources} verified · {company.opportunity_report.evidence_summary.unverified_sources} unverified · {company.opportunity_report.evidence_summary.rejected_sources} rejected · {company.opportunity_report.evidence_summary.projects} projects · {company.opportunity_report.evidence_summary.professional_contacts} business contacts</small>
      <div className={`next-sales-action ${company.opportunity_report.next_sales_action.status}`}>
        <b>Next recommended sales action</b>
        <p>{company.opportunity_report.next_sales_action.action}</p>
        <small>{company.opportunity_report.next_sales_action.reason}{company.opportunity_report.next_sales_action.due_date ? ` Due ${company.opportunity_report.next_sales_action.due_date}.` : ""}</small>
      </div>
      {company.opportunity_report.positive_signals.length > 0 && <div><b>Signals</b><ul>{company.opportunity_report.positive_signals.map((signal) => <li key={signal}>{signal}</li>)}</ul></div>}
      {company.opportunity_report.evidence_gaps.length > 0 && <div><b>Evidence gaps</b><ul>{company.opportunity_report.evidence_gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul></div>}
      <div><b>Recommended next steps</b><ul>{company.opportunity_report.recommended_actions.map((action) => <li key={action}>{action}</li>)}</ul></div>
      <small className="privacy-note">Evidence-based guidance, not a prediction. Human review is required before acting.</small>
    </div>
    <div className="ai-enrichment">
      <div className="opportunity-heading"><strong>AI-assisted source review</strong><span className="research-mode">OPT-IN</span></div>
      <p className="privacy-note">Only verified source excerpts are sent to the configured AI provider. Suggested claims remain drafts and are never saved automatically.</p>
      <button className="button secondary" onClick={onEnrich} disabled={!aiAvailable || enrichmentBusy || !company.sources.some((source) => source.verification_status === "verified" && source.has_content)}>
        {enrichmentBusy ? "Reviewing verified sources…" : "Extract evidence-backed signals"}
      </button>
      {!aiAvailable && <small className="muted">Configure the AI provider to enable enrichment.</small>}
      {!company.sources.some((source) => source.verification_status === "verified" && source.has_content) && <small className="muted">Add a source excerpt and verify it before AI extraction.</small>}
      {enrichmentError && <div className="notice error" role="alert">{enrichmentError}</div>}
      {enrichment && <div className="enrichment-claims">
        {!enrichment.claims.length && <p className="muted small-text">No structured claims were supported by the selected excerpts.</p>}
        {enrichment.claims.map((claim, index) => <article className="enrichment-claim" key={`${claim.source_id}-${index}`}>
          <strong>{claim.claim_type.replaceAll("_", " ")}</strong><p>{claim.text}</p>
          <blockquote>{claim.quote}</blockquote>
          <a href={claim.source_url} target="_blank" rel="noreferrer">[{claim.citation}] {claim.source_title} ↗</a>
        </article>)}
      </div>}
    </div>
    <SectionTitle title="Source evidence" count={company.sources.length} />
    {company.sources.length ? <div className="profile-list">{company.sources.map((source) => <a className="source-row" key={source.id} href={source.url} target="_blank" rel="noreferrer"><span className="source-icon">↗</span><span><strong>{source.title || source.source_type}</strong><small>{source.verification_status} · discovered {source.discovered_at}</small></span><b>↗</b></a>)}</div> : <p className="muted small-text">No source records. Import evidence before acting on this lead.</p>}
    <SectionTitle title="Project signals" count={company.projects.length} />
    {company.projects.map((project) => <ProjectDemandEditor key={project.id} project={project} canWrite={canWrite} onSaved={refresh} />)}
    {!company.projects.length && <p className="muted small-text">No linked projects recorded.</p>}
    <SectionTitle title="Business relationships" count={company.relationships.length} />
    {company.relationships.map((relation) => <div className="relationship-row" key={relation.id}><span className="relationship-symbol">⤷</span><span><strong>{relation.related_company_name}</strong><small>{relation.relationship_type}{relation.project_name ? ` · ${relation.project_name}` : ""}</small></span>{canWrite && <button className="text-button" onClick={() => removeRelationship(relation.id)}>Remove</button>}</div>)}
    {!company.relationships.length && <p className="muted small-text">No relationships mapped yet.</p>}
    {canWrite && relatedCompanies.length > 0 && <form className="relationship-form" onSubmit={saveRelationship}>
      <select aria-label="Related company" required value={relatedCompanyId} onChange={(event) => setRelatedCompanyId(event.target.value)}><option value="">Link another company...</option>{relatedCompanies.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select>
      <select aria-label="Relationship project (optional)" value={relatedProjectId} onChange={(event) => setRelatedProjectId(event.target.value)}><option value="">No associated project</option>{company.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select>
      <div className="form-row"><input aria-label="Relationship type" value={relationshipType} onChange={(event) => setRelationshipType(event.target.value)} /><button className="button secondary" disabled={relationshipBusy}>Link</button></div>
      {relationshipMessage && <small className="muted">{relationshipMessage}</small>}
    </form>}
    <SectionTitle title="Sales activity" count={company.activities.length} />
    {canWrite && <form className="activity-form" onSubmit={saveActivity}>
      <div className="form-row"><select value={activity.activity_type} onChange={(event) => setActivity({ ...activity, activity_type: event.target.value })}><option value="call">Call</option><option value="email">Email</option><option value="meeting">Meeting</option><option value="note">Note</option></select><input type="date" value={activity.due_date} onChange={(event) => setActivity({ ...activity, due_date: event.target.value })} aria-label="Follow-up due date" /></div>
      <textarea required placeholder="Add a note about this interaction..." value={activity.notes} onChange={(event) => setActivity({ ...activity, notes: event.target.value })} />
      <input placeholder="Next recommended action (optional)" value={activity.next_action} onChange={(event) => setActivity({ ...activity, next_action: event.target.value })} />
      <select aria-label="Sales outcome" value={activity.sales_outcome} onChange={(event) => setActivity({ ...activity, sales_outcome: event.target.value })}>
        <option value="">Record sales outcome (optional)</option>
        <option value="contacted">Contacted</option><option value="interested">Interested</option>
        <option value="qualified">Qualified</option><option value="proposal_sent">Proposal sent</option>
        <option value="won">Won</option><option value="lost">Lost</option>
        <option value="not_interested">Not interested</option><option value="no_response">No response</option>
      </select>
      <button className="button primary full" disabled={busy}>Save sales activity</button>
    </form>}
    {activityMessage && <p className="muted small-text">{activityMessage}</p>}
    {company.activities.map((item) => <div className={`activity-item ${item.completed_at ? "completed" : ""}`} key={item.id}><div><strong>{item.activity_type}{item.sales_outcome && <span className="sales-outcome"> · {item.sales_outcome.replaceAll("_", " ")}</span>}</strong><time>{new Date(item.created_at).toLocaleDateString("en-IN")}{item.due_date ? ` · due ${item.due_date}` : ""}</time></div><p>{item.notes}</p>{item.next_action && <div className="next-action"><small>{item.completed_at ? "Completed: " : "Next: "}{item.next_action}</small>{canWrite && !item.completed_at && <button onClick={() => void completeFollowUp(item.id)}>Mark done</button>}</div>}</div>)}
  </div>;
}

function SectionTitle({ title, count }: { title: string; count: number }) {
  return <div className="section-title"><h4>{title}</h4><span>{count}</span></div>;
}

export default App;
