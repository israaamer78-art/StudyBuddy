// =============================================================================
// StudyBuddy frontend
// =============================================================================

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// State
const state = {
  library: { exams: [] },
  view: { type: "welcome" },   // 'welcome' | 'lecture' | 'section' | 'comprehensive' | 'exam-quiz' | 'dashboard' | 'cram' | 'history'
  currentLectureId: null,
  currentLecture: null,        // full lecture from /api/lectures/:id
  currentExam: null,
  currentSectionIndex: null,
  currentSection: null,
  currentStage: "reading",     // 'reading' | 'matching' | 'mcq' | 'recall' | 'flashcards' | 'clozes'
  collapsedExams: new Set(),
  settings: { has_server_anthropic_key: false, has_server_openai_key: false },
  providerValidation: null,
  searchQuery: "",
  searchIndex: [],
  pendingSearchHighlight: "",
};

const networkState = {
  pending: 0,
  label: "",
  activeClaudeJob: null,
  online: navigator.onLine,
  lastCompletedAt: null,
};

const LOCAL_DB_NAME = "studybuddy-local";
const LOCAL_DB_VERSION = 1;
const LOCAL_STORE = "snapshots";
const LOCAL_PROJECT_KEY = "latest-project";
const PROVIDER_STORAGE_KEY = "studybuddy-selected-provider";
const MODEL_STORAGE_KEY = "studybuddy-selected-model";
const PROVIDER_VALIDATION_STORAGE_KEY = "studybuddy-provider-validation-cache";
const ANTHROPIC_KEY_STORAGE_KEY = "studybuddy-anthropic-api-key";
const ANTHROPIC_KEY_SESSION_KEY = "studybuddy-session-anthropic-api-key";
const OPENAI_KEY_STORAGE_KEY = "studybuddy-openai-api-key";
const OPENAI_KEY_SESSION_KEY = "studybuddy-session-openai-api-key";
const DEFAULT_PROVIDER = "anthropic";
const DEFAULT_MODEL = "claude-sonnet-4-6";
const PROVIDER_MODELS = {
  anthropic: [
    { id: "claude-opus-4-7", label: "Opus 4.7 - best" },
    { id: "claude-sonnet-4-6", label: "Sonnet 4.6 - balanced" },
    { id: "claude-haiku-4-5", label: "Haiku 4.5 - fastest" },
  ],
  openai: [
    { id: "gpt-5.5", label: "GPT-5.5 - best" },
    { id: "gpt-5.4-mini", label: "GPT-5.4 Mini - balanced" },
    { id: "gpt-5.4-nano", label: "GPT-5.4 Nano - fastest" },
  ],
};
const DEFAULT_MODELS = { anthropic: DEFAULT_MODEL, openai: "gpt-5.4-mini" };
const ALLOWED_PROVIDERS = new Set(Object.keys(PROVIDER_MODELS));
const ALLOWED_MODELS = new Set(Object.values(PROVIDER_MODELS).flat().map(m => m.id));

// =============================================================================
// API helpers
// =============================================================================
function classifyApiActivity(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  if (path.startsWith("/api/jobs/")) return "Checking generation";
  if (path === "/api/lectures" && method === "POST") return "Starting AI job";
  if (
    method === "POST" && (
      path.includes("/questions") ||
      path.includes("/recall") ||
      path.includes("/comprehensive") ||
      path.includes("/regenerate")
    )
  ) {
    return "Calling AI";
  }
  if (path.startsWith("/api/project")) return method === "GET" ? "Saving project" : "Importing project";
  if (method === "GET") return "Loading local data";
  return "Saving local data";
}

function setNetworkActivity(delta, label = "") {
  networkState.pending = Math.max(0, networkState.pending + delta);
  if (label) networkState.label = label;
  if (delta < 0 && networkState.pending === 0) networkState.lastCompletedAt = Date.now();
  renderNetworkStatus();
}

function setActiveClaudeJob(job) {
  networkState.activeClaudeJob = job;
  renderNetworkStatus();
}

function renderNetworkStatus() {
  const el = $("#network-status");
  const text = $("#network-status-text");
  if (!el || !text) return;

  el.classList.remove("active", "claude", "offline");
  let label = "Idle - everything loaded";
  let title = "No local backend requests or AI API calls are running.";

  if (!networkState.online && (networkState.pending > 0 || networkState.activeClaudeJob)) {
    el.classList.add("offline");
    label = "Offline - AI may fail";
    title = "Local requests can still work, but new AI API calls need internet.";
  } else if (networkState.activeClaudeJob) {
    el.classList.add("active", "claude");
    const elapsed = networkState.activeClaudeJob.display_elapsed_seconds ?? networkState.activeClaudeJob.elapsed_seconds;
    label = `AI working${elapsed != null ? ` - ${formatElapsed(elapsed)}` : ""}`;
    title = describeJobProgress(networkState.activeClaudeJob);
  } else if (networkState.pending > 0) {
    el.classList.add("active");
    label = networkState.label || "API call active";
    title = `${networkState.pending} local backend request${networkState.pending === 1 ? "" : "s"} running.`;
  } else if (!networkState.online) {
    el.classList.add("offline");
    label = "Offline - no AI";
    title = "Loaded local study content can stay visible, but new AI calls need internet.";
  }

  text.textContent = label;
  el.title = title;
}

async function api(path, opts = {}) {
  const activityLabel = opts.activityLabel || classifyApiActivity(path, opts);
  setNetworkActivity(1, activityLabel);
  const { activityLabel: _activityLabel, ...fetchOpts } = opts;
  const provider = getSelectedProvider();
  const providerApiKey = getProviderApiKey(provider);
  const headers = {
    "X-StudyBuddy-Provider": provider,
    "X-StudyBuddy-Model": getSelectedModel(),
    ...(providerApiKey && provider === "openai" ? { "X-OpenAI-Api-Key": providerApiKey } : {}),
    ...(providerApiKey && provider === "anthropic" ? { "X-Anthropic-Api-Key": providerApiKey } : {}),
    ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
    ...(opts.headers || {}),
  };
  try {
    const res = await fetch(path, {
      ...fetchOpts,
      headers,
    });
    if (!res.ok) {
      let msg = `${res.status}`;
      try { const j = await res.json(); msg = j.error || j.message || msg; } catch {}
      throw new Error(msg);
    }
    return res.json();
  } finally {
    setNetworkActivity(-1);
  }
}

function getSelectedProvider() {
  const stored = localStorage.getItem(PROVIDER_STORAGE_KEY);
  return ALLOWED_PROVIDERS.has(stored) ? stored : DEFAULT_PROVIDER;
}

function setSelectedProvider(provider) {
  const normalized = ALLOWED_PROVIDERS.has(provider) ? provider : DEFAULT_PROVIDER;
  localStorage.setItem(PROVIDER_STORAGE_KEY, normalized);
  if (!PROVIDER_MODELS[normalized].some(m => m.id === getSelectedModel())) {
    setSelectedModel(DEFAULT_MODELS[normalized]);
  }
}

function getSelectedModel() {
  const stored = localStorage.getItem(MODEL_STORAGE_KEY);
  const provider = getSelectedProvider();
  if (PROVIDER_MODELS[provider].some(m => m.id === stored)) return stored;
  return DEFAULT_MODELS[provider];
}

function setSelectedModel(model) {
  localStorage.setItem(MODEL_STORAGE_KEY, ALLOWED_MODELS.has(model) ? model : DEFAULT_MODELS[getSelectedProvider()]);
}

function getAnthropicApiKey() {
  const input = $("#anthropic-key-input");
  if (input?.value.trim()) return input.value.trim();
  return sessionStorage.getItem(ANTHROPIC_KEY_SESSION_KEY)
    || localStorage.getItem(ANTHROPIC_KEY_STORAGE_KEY)
    || "";
}

function setAnthropicApiKey(apiKey, remember = false) {
  apiKey = (apiKey || "").trim();
  if (!apiKey) {
    sessionStorage.removeItem(ANTHROPIC_KEY_SESSION_KEY);
    localStorage.removeItem(ANTHROPIC_KEY_STORAGE_KEY);
    return;
  }
  if (remember) {
    localStorage.setItem(ANTHROPIC_KEY_STORAGE_KEY, apiKey);
    sessionStorage.removeItem(ANTHROPIC_KEY_SESSION_KEY);
  } else {
    sessionStorage.setItem(ANTHROPIC_KEY_SESSION_KEY, apiKey);
    localStorage.removeItem(ANTHROPIC_KEY_STORAGE_KEY);
  }
}

function isRememberingAnthropicApiKey() {
  return Boolean(localStorage.getItem(ANTHROPIC_KEY_STORAGE_KEY));
}

function getOpenAIApiKey() {
  const input = $("#openai-key-input");
  if (input?.value.trim()) return input.value.trim();
  return sessionStorage.getItem(OPENAI_KEY_SESSION_KEY)
    || localStorage.getItem(OPENAI_KEY_STORAGE_KEY)
    || "";
}

function setOpenAIApiKey(apiKey, remember = false) {
  apiKey = (apiKey || "").trim();
  if (!apiKey) {
    sessionStorage.removeItem(OPENAI_KEY_SESSION_KEY);
    localStorage.removeItem(OPENAI_KEY_STORAGE_KEY);
    return;
  }
  if (remember) {
    localStorage.setItem(OPENAI_KEY_STORAGE_KEY, apiKey);
    sessionStorage.removeItem(OPENAI_KEY_SESSION_KEY);
  } else {
    sessionStorage.setItem(OPENAI_KEY_SESSION_KEY, apiKey);
    localStorage.removeItem(OPENAI_KEY_STORAGE_KEY);
  }
}

function isRememberingOpenAIApiKey() {
  return Boolean(localStorage.getItem(OPENAI_KEY_STORAGE_KEY));
}

function getProviderApiKey(provider = getSelectedProvider()) {
  return provider === "openai" ? getOpenAIApiKey() : getAnthropicApiKey();
}

function setProviderApiKey(provider, apiKey, remember = false) {
  if (provider === "openai") setOpenAIApiKey(apiKey, remember);
  else setAnthropicApiKey(apiKey, remember);
}

function isRememberingProviderApiKey(provider = getSelectedProvider()) {
  return provider === "openai" ? isRememberingOpenAIApiKey() : isRememberingAnthropicApiKey();
}

function normalizeApiKeyForCompare(apiKey) {
  return (apiKey || "").trim();
}

function hashApiKeyFingerprint(apiKey) {
  let hash = 2166136261;
  const normalized = normalizeApiKeyForCompare(apiKey);
  for (let i = 0; i < normalized.length; i += 1) {
    hash ^= normalized.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function validationCacheKey(provider = getSelectedProvider(), model = getSelectedModel(), apiKey = getProviderApiKey(provider)) {
  const keyHash = apiKey ? hashApiKeyFingerprint(apiKey) : "server";
  return `${provider}:${model}:${keyHash}`;
}

function loadValidationCache() {
  try {
    const cache = JSON.parse(localStorage.getItem(PROVIDER_VALIDATION_STORAGE_KEY) || "{}");
    return cache && typeof cache === "object" ? cache : {};
  } catch {
    return {};
  }
}

function getCachedProviderValidation(provider = getSelectedProvider(), model = getSelectedModel(), apiKey = getProviderApiKey(provider)) {
  const result = loadValidationCache()[validationCacheKey(provider, model, apiKey)];
  return result && typeof result === "object" ? result : null;
}

function setCachedProviderValidation(result, provider = getSelectedProvider(), model = getSelectedModel(), apiKey = getProviderApiKey(provider)) {
  const cache = loadValidationCache();
  cache[validationCacheKey(provider, model, apiKey)] = {
    ...result,
    cached: true,
    cached_at: new Date().toISOString(),
  };
  localStorage.setItem(PROVIDER_VALIDATION_STORAGE_KEY, JSON.stringify(cache));
}

function syncProviderValidationFromCache() {
  state.providerValidation = getCachedProviderValidation();
  renderProviderValidation();
}

function hasProviderKeyAvailable(provider = getSelectedProvider()) {
  const serverKey = provider === "openai" ? state.settings.has_server_openai_key : state.settings.has_server_anthropic_key;
  return Boolean(getProviderApiKey(provider) || serverKey);
}

function syncProviderWarning() {
  const warning = $("#provider-key-warning");
  if (!warning) return;
  warning.hidden = hasProviderKeyAvailable();
}

function renderProviderValidation(result = state.providerValidation) {
  const el = $("#provider-validation-status");
  if (!el) return;
  el.classList.remove("valid", "error");
  if (!result) {
    el.textContent = "Not validated yet.";
    return;
  }
  el.textContent = result.message || (result.ok ? "API key validated." : "Could not validate API key.");
  el.classList.add(result.ok ? "valid" : "error");
}

async function validateProviderKey({ silent = false, renderMissing = true } = {}) {
  const provider = getSelectedProvider();
  const model = getSelectedModel();
  const apiKey = getProviderApiKey(provider);
  const cached = getCachedProviderValidation(provider, model, apiKey);
  if (cached) {
    state.providerValidation = cached;
    renderProviderValidation(cached);
    syncProviderWarning();
    if (!silent && cached.message) toast(cached.message, cached.ok ? "success" : "error");
    return cached;
  }
  const payload = {
    provider,
    model,
    ...(provider === "openai" && apiKey ? { openai_api_key: apiKey } : {}),
    ...(provider === "anthropic" && apiKey ? { anthropic_api_key: apiKey } : {}),
  };
  if (!hasProviderKeyAvailable(payload.provider)) {
    const providerName = payload.provider === "openai" ? "OpenAI" : "Anthropic";
    const result = {
      ok: false,
      status: "missing_key",
      message: `No ${providerName} API key is configured. Add one in AI Provider Settings.`,
    };
    if (renderMissing) {
      state.providerValidation = result;
      renderProviderValidation(result);
      syncProviderWarning();
    }
    if (!silent) toast(result.message, "error");
    return result;
  }
  try {
    const result = await api("/api/settings/validate-key", {
      method: "POST",
      body: JSON.stringify(payload),
      activityLabel: `Validating ${payload.provider === "openai" ? "OpenAI" : "Anthropic"} key`,
    });
    state.providerValidation = result;
    setCachedProviderValidation(result, provider, model, apiKey);
    renderProviderValidation(result);
    syncProviderWarning();
    if (!silent) toast(result.message, result.ok ? "success" : "error");
    return result;
  } catch (e) {
    const result = { ok: false, status: "provider_error", message: e.message };
    state.providerValidation = result;
    setCachedProviderValidation(result, provider, model, apiKey);
    renderProviderValidation(result);
    syncProviderWarning();
    if (!silent) toast(e.message, "error");
    return result;
  }
}

function toast(msg, type = "") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// =============================================================================
// Local project snapshot storage (IndexedDB)
// =============================================================================
function openLocalDB() {
  return StudyBuddyLocalProjectStore.openDB?.();
}

async function saveLocalProjectSnapshot(project) {
  return StudyBuddyLocalProjectStore.saveProjectSnapshot(project);
}

async function getLocalProjectSnapshot() {
  return StudyBuddyLocalProjectStore.getProjectSnapshot();
}

function makeProjectSnapshot(library) {
  return StudyBuddyLocalProjectStore.makeProjectSnapshot(library, {
    selected_provider: getSelectedProvider(),
    selected_model: getSelectedModel(),
  });
}

async function syncLocalProjectSnapshot() {
  const project = await api("/api/project");
  project.settings = {
    ...(project.settings || {}),
    selected_provider: getSelectedProvider(),
    selected_model: getSelectedModel(),
  };
  await saveLocalProjectSnapshot(project);
  return project;
}

async function refreshSettings() {
  try {
    state.settings = await api("/api/settings");
  } catch {
    state.settings = { has_server_anthropic_key: false, has_server_openai_key: false };
  }
  syncProviderWarning();
  return state.settings;
}

async function waitForJob(jobId, onUpdate) {
  let lastProgressKey = "";
  let lastServerSeenAt = Date.now();
  try {
    while (true) {
      const job = await api(`/api/jobs/${jobId}`, { activityLabel: "Checking generation" });
    const progressKey = [
      job.status,
      job.stage,
      job.current,
      job.total,
      job.section_title,
      job.elapsed_seconds,
    ].join("|");
    const now = Date.now();
    if (progressKey !== lastProgressKey) {
      lastProgressKey = progressKey;
      lastServerSeenAt = now;
    }
    const displayJob = { ...job };
    if (job.status !== "completed" && job.status !== "failed" && job.elapsed_seconds != null) {
      displayJob.display_elapsed_seconds = job.elapsed_seconds + (now - lastServerSeenAt) / 1000;
    }
      setActiveClaudeJob(job.status === "completed" || job.status === "failed" ? null : displayJob);
      onUpdate?.(displayJob);
      if (job.status === "completed") return job.result;
      if (job.status === "failed") throw new Error(job.error || "Generation failed");
      await new Promise(resolve => setTimeout(resolve, 1800));
    }
  } catch (e) {
    setActiveClaudeJob(null);
    throw e;
  }
}

function formatElapsed(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return mins > 0 ? `${mins}m ${String(secs).padStart(2, "0")}s` : `${secs}s`;
}

function providerModelLabel(provider, model) {
  const modelInfo = PROVIDER_MODELS[provider]?.find(option => option.id === model);
  const modelLabel = modelInfo?.label?.replace(/\s+-\s+.*$/, "") || model;
  if (!modelLabel) return "";
  const providerLabel = provider === "openai" ? "OpenAI" : provider === "anthropic" ? "Anthropic" : "";
  return providerLabel ? `${providerLabel} ${modelLabel}` : modelLabel;
}

function describeJobProgress(job) {
  const parts = [job.stage || "Generating study guide"];
  const modelLabel = providerModelLabel(job.provider, job.model);
  if (modelLabel) {
    parts.push(modelLabel);
  }
  if (job.total && job.current) {
    parts.push(`${job.item_label || "section"} ${job.current} of ${job.total}`);
  }
  if (job.section_title) {
    parts.push(job.section_title);
  }
  const elapsedSeconds = job.display_elapsed_seconds ?? job.elapsed_seconds;
  if (elapsedSeconds != null) {
    parts.push(`elapsed ${formatElapsed(elapsedSeconds)}`);
  }
  return parts.join(" · ");
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function timestampForFilename() {
  return new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
}

// Initialize Mermaid
mermaid.initialize({
  startOnLoad: false,
  theme: "base",
  themeVariables: {
    primaryColor: "#d8e0cd",
    primaryTextColor: "#2f3c28",
    primaryBorderColor: "#6b8060",
    lineColor: "#6b8060",
    secondaryColor: "#f5efe4",
    tertiaryColor: "#faf6ed",
    fontFamily: "Inter, sans-serif",
    fontSize: "14px",
  },
});

// =============================================================================
// Sidebar rendering
// =============================================================================
async function refreshLibrary() {
  try {
    state.library = await api("/api/library");
    syncLocalProjectSnapshot().catch(() => {});
    await refreshSearchIndex();
    renderSidebar();
  } catch (e) {
    toast("Couldn't load library: " + e.message, "error");
  }
}

async function refreshSearchIndex() {
  const items = [];
  for (const exam of state.library.exams || []) {
    items.push({
      type: "exam",
      exam_id: exam.id,
      title: exam.name,
      meta: "Exam",
      text: exam.name,
    });
    for (const lec of exam.lectures || []) {
      items.push({
        type: "lecture",
        exam_id: exam.id,
        lecture_id: lec.id,
        title: lec.name,
        meta: exam.name,
        text: `${exam.name} ${lec.name}`,
      });
      if (state.searchQuery.trim()) {
        try {
          const detail = await api(`/api/lectures/${lec.id}`, { activityLabel: "Indexing search" });
          for (const section of detail.lecture.sections || []) {
            items.push({
              type: "section",
              exam_id: exam.id,
              lecture_id: lec.id,
              section_index: section.section_index,
              title: section.title || `Section ${section.section_index}`,
              meta: `${lec.name} · section ${section.section_index}`,
              text: [
                exam.name,
                lec.name,
                section.title,
                section.reading,
                ...(section.key_terms || []).flatMap(t => [t.term, t.definition]),
                ...(section.matching || []).flatMap(m => [m.left, m.right]),
                section.transcript_excerpt,
                section.slides_content,
              ].filter(Boolean).join(" "),
            });
          }
        } catch {
          // Search should degrade gracefully if an individual lecture cannot load.
        }
      }
    }
  }
  state.searchIndex = items;
}

function searchMatches(text, query) {
  const haystack = String(text || "").toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every(term => haystack.includes(term));
}

function searchResults() {
  const query = state.searchQuery.trim();
  if (!query) return [];
  return state.searchIndex
    .filter(item => searchMatches(item.text, query))
    .slice(0, 12);
}

function renderSidebar() {
  const wrap = $("#library");
  wrap.innerHTML = "";
  const query = state.searchQuery.trim();

  if (!query) {
    // Quick links section
    const quickLinks = document.createElement("div");
    quickLinks.className = "quick-links";
    const links = [
      { id: "dashboard", icon: "◎", label: "Dashboard" },
      { id: "cram", icon: "✦", label: "Cram Mode" },
      { id: "history", icon: "❍", label: "History" },
    ];
    for (const link of links) {
      const btn = document.createElement("button");
      btn.className = "quick-link" + (state.view.type === link.id ? " active" : "");
      btn.innerHTML = `<span class="icon">${link.icon}</span> ${link.label}`;
      btn.onclick = () => navigate(link.id);
      quickLinks.appendChild(btn);
    }
    wrap.appendChild(quickLinks);
  }

  if (query) {
    const resultWrap = document.createElement("div");
    resultWrap.className = "search-results";
    const results = searchResults();
    const label = document.createElement("div");
    label.className = "library-section-label";
    label.textContent = "Search results";
    resultWrap.appendChild(label);
    if (!results.length) {
      const empty = document.createElement("div");
      empty.className = "library-empty";
      empty.textContent = "No matches yet.";
      resultWrap.appendChild(empty);
    } else {
      for (const result of results) {
        const btn = document.createElement("button");
        btn.className = "search-result";
        btn.innerHTML = `
          <div class="search-result-title">${escapeHtml(result.title)}</div>
          <div class="search-result-meta">${escapeHtml(result.meta)}</div>
        `;
        btn.onclick = async () => {
          if (result.type === "section") {
            state.pendingSearchHighlight = state.searchQuery;
            await openLecture(result.lecture_id);
            openSection(result.section_index);
          } else if (result.type === "lecture") {
            state.pendingSearchHighlight = state.searchQuery;
            await openLecture(result.lecture_id);
          } else if (result.type === "exam") {
            state.collapsedExams.delete(result.exam_id);
            renderSidebar();
          }
        };
        resultWrap.appendChild(btn);
      }
    }
    wrap.appendChild(resultWrap);
  }

  const label = document.createElement("div");
  label.className = "library-section-label";
  label.textContent = "Exams";
  wrap.appendChild(label);

  if (!state.library.exams.length) {
    const empty = document.createElement("div");
    empty.className = "library-empty";
    empty.textContent = "No exams yet. Create one to begin.";
    wrap.appendChild(empty);
    return;
  }

  for (const exam of state.library.exams) {
    const filteredLectures = query
      ? exam.lectures.filter(lec => searchMatches(`${exam.name} ${lec.name}`, query))
      : exam.lectures;
    const examMatches = query && searchMatches(exam.name, query);
    if (query && !examMatches && !filteredLectures.length) continue;

    const group = document.createElement("div");
    group.className = "exam-group";

    const header = document.createElement("div");
    const collapsed = !query && state.collapsedExams.has(exam.id);
    header.className = "exam-header" + (collapsed ? " collapsed" : "");
    header.innerHTML = `
      <span class="caret">▾</span>
      <span class="exam-name">${escapeHtml(exam.name)}</span>
      <div class="exam-actions">
        <button class="icon-btn" data-action="quiz-exam" title="Cumulative quiz">★</button>
        <button class="icon-btn" data-action="rename-exam" title="Rename">✎</button>
        <button class="icon-btn" data-action="delete-exam" title="Delete">×</button>
      </div>
    `;
    header.onclick = (e) => {
      if (e.target.closest("[data-action]")) return;
      if (collapsed) state.collapsedExams.delete(exam.id);
      else state.collapsedExams.add(exam.id);
      renderSidebar();
    };
    header.querySelector('[data-action="quiz-exam"]').onclick = (e) => {
      e.stopPropagation();
      openExamCumulativeQuiz(exam);
    };
    header.querySelector('[data-action="rename-exam"]').onclick = async (e) => {
      e.stopPropagation();
      const name = prompt("Rename exam", exam.name);
      if (!name) return;
      try {
        await api(`/api/exams/${exam.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
        await refreshLibrary();
      } catch (err) { toast(err.message, "error"); }
    };
    header.querySelector('[data-action="delete-exam"]').onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete exam "${exam.name}" and all its lectures?`)) return;
      try {
        await api(`/api/exams/${exam.id}`, { method: "DELETE" });
        await refreshLibrary();
      } catch (err) { toast(err.message, "error"); }
    };
    group.appendChild(header);

    const list = document.createElement("ul");
    list.className = "lectures-list" + (collapsed ? " collapsed" : "");

    if (!filteredLectures.length) {
      const empty = document.createElement("li");
      empty.style.cssText = "padding: 6px 10px; font-style: italic; color: var(--ink-faint); font-size: 0.78rem;";
      empty.textContent = query ? "No lecture title matches" : "No lectures yet";
      list.appendChild(empty);
    }

    for (const lec of filteredLectures) {
      const item = document.createElement("li");
      const isActive = state.currentLectureId === lec.id;
      item.className = "lecture-item" + (isActive ? " active" : "");
      const pct = lec.progress.total > 0 ? Math.round((lec.progress.done / lec.progress.total) * 100) : 0;
      item.innerHTML = `
        <span class="lecture-name">${escapeHtml(lec.name)}</span>
        <span class="lecture-progress-mini">${lec.progress.done}/${lec.progress.total}</span>
        <div class="lecture-actions">
          <button class="icon-btn" data-action="rename-lec" title="Rename">✎</button>
          <button class="icon-btn" data-action="delete-lec" title="Delete">×</button>
        </div>
      `;
      item.onclick = (e) => {
        if (e.target.closest("[data-action]")) return;
        openLecture(lec.id);
      };
      item.querySelector('[data-action="rename-lec"]').onclick = async (e) => {
        e.stopPropagation();
        const name = prompt("Rename lecture", lec.name);
        if (!name) return;
        try {
          await api(`/api/lectures/${lec.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
          await refreshLibrary();
        } catch (err) { toast(err.message, "error"); }
      };
      item.querySelector('[data-action="delete-lec"]').onclick = async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete lecture "${lec.name}"?`)) return;
        try {
          await api(`/api/lectures/${lec.id}`, { method: "DELETE" });
          if (state.currentLectureId === lec.id) showWelcome();
          await refreshLibrary();
        } catch (err) { toast(err.message, "error"); }
      };
      list.appendChild(item);
    }
    group.appendChild(list);
    wrap.appendChild(group);
  }
}

// =============================================================================
// Navigation
// =============================================================================
function navigate(viewType) {
  state.view = { type: viewType };
  state.currentLectureId = null;
  state.currentSectionIndex = null;
  if (viewType === "dashboard") renderDashboard();
  else if (viewType === "cram") renderCram();
  else if (viewType === "history") renderHistory();
  else showWelcome();
  renderSidebar();
}

function showWelcome() {
  state.view = { type: "welcome" };
  $("#main").innerHTML = `
    <div class="welcome">
      <div class="welcome-mark">✿</div>
      <h1>Welcome to StudyBuddy</h1>
      <p>Your personal medical school study companion. Upload a lecture, drop your notes, and let it build your study guide.</p>
      <div class="welcome-tips">
        <h3>How it works</h3>
        <ol>
          <li>Create an exam (e.g. "Exam 1 — Head & Neck")</li>
          <li>Add a lecture: upload the video or paste a transcript, plus your notes</li>
          <li>Each section gives you reading, matching, MCQs, recall, flashcards & cloze cards — all from your lecture only</li>
          <li>Track confidence, missed questions resurface for review</li>
          <li>Take the comprehensive end-of-lecture quiz, then the cumulative exam quiz when ready</li>
        </ol>
      </div>
    </div>
  `;
}

// =============================================================================
// Lecture view
// =============================================================================
async function openLecture(lectureId) {
  state.currentLectureId = lectureId;
  state.view = { type: "lecture" };
  renderSidebar();
  $("#main").innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Loading lecture…</p></div>`;
  try {
    const data = await api(`/api/lectures/${lectureId}`);
    state.currentLecture = data.lecture;
    state.currentExam = data.exam;
    renderLecture();
  } catch (e) {
    toast("Couldn't load lecture: " + e.message, "error");
    showWelcome();
  }
}

function renderLecture() {
  const lec = state.currentLecture;
  const exam = state.currentExam;
  const done = lec.sections.filter(s => s.completed).length;
  const total = lec.sections.length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const main = $("#main");
  main.innerHTML = "";

  // Header
  const header = document.createElement("div");
  header.className = "lecture-header";
  header.innerHTML = `
    <div class="breadcrumb">${escapeHtml(exam.name)}</div>
    <h1 class="lecture-title">${escapeHtml(lec.name)}</h1>
    <div class="progress-bar">
      <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
      <span class="progress-text">${done} of ${total} sections complete</span>
    </div>
  `;
  main.appendChild(header);

  // Sections list
  const list = document.createElement("div");
  list.className = "sections-list";
  for (const section of lec.sections) {
    const row = document.createElement("div");
    row.className = "section-row";
    const confidenceTag = section.confidence
      ? `<span class="confidence-pill ${section.confidence}">${section.confidence}</span>` : "";
    row.innerHTML = `
      <div class="section-num">${section.section_index}</div>
      <div class="section-info">
        <h3>${escapeHtml(section.title || `Section ${section.section_index}`)}</h3>
        <div class="section-meta">
          <span>${section.key_terms?.length || 0} terms</span>
          <span>·</span>
          <span>${section.diagram ? "Has diagram" : "Text"}</span>
          ${confidenceTag}
        </div>
      </div>
      <div class="section-status ${section.completed ? "done" : ""}"></div>
    `;
    row.onclick = () => openSection(section.section_index);
    list.appendChild(row);
  }
  main.appendChild(list);

  // Comprehensive quiz card
  const compCard = document.createElement("div");
  compCard.className = "comprehensive-card";
  compCard.innerHTML = `
    <div class="comprehensive-icon">✦</div>
    <div class="comprehensive-text">
      <h3>Comprehensive Quiz</h3>
      <p>Every section, in order. Mixed Level 1 + NBME questions. Restartable anytime.</p>
    </div>
    <button class="btn">${lec.has_comprehensive_quiz ? "Resume" : "Begin"}</button>
  `;
  compCard.onclick = () => openComprehensiveQuiz();
  main.appendChild(compCard);
}

// =============================================================================
// Section study view
// =============================================================================
async function openSection(sectionIndex) {
  state.currentSectionIndex = sectionIndex;
  state.currentSection = state.currentLecture.sections.find(s => s.section_index === sectionIndex);
  state.currentStage = "reading";
  state.view = { type: "section" };
  renderSection();
  api("/api/log", {
    method: "POST",
    body: JSON.stringify({ lecture_id: state.currentLectureId, kind: "view_section", detail: { section: sectionIndex } }),
  }).catch(() => {});
}

function renderSection() {
  const section = state.currentSection;
  const main = $("#main");
  main.innerHTML = "";

  // Header
  const header = document.createElement("div");
  header.className = "study-header";
  header.innerHTML = `
    <div>
      <div class="study-subtitle">${escapeHtml(state.currentLecture.name)} · Section ${section.section_index}</div>
      <div class="study-title">${escapeHtml(section.title || "Untitled")}</div>
    </div>
    <div class="study-header-actions">
      <button class="btn ghost small" id="btn-back-lecture">← Lecture</button>
      <button class="btn ${section.completed ? "primary" : "ghost"} small" id="btn-mark-complete">
        ${section.completed ? "✓ Completed" : "Mark complete"}
      </button>
    </div>
  `;
  header.querySelector("#btn-back-lecture").onclick = () => renderLecture();
  header.querySelector("#btn-mark-complete").onclick = async () => {
    try {
      const completed = !section.completed;
      await api(`/api/lectures/${state.currentLectureId}/sections/${section.section_index}/progress`, {
        method: "POST",
        body: JSON.stringify({ completed }),
      });
      section.completed = completed;
      await refreshLibrary();
      renderSection();
    } catch (e) { toast(e.message, "error"); }
  };
  main.appendChild(header);

  // Tabs
  const tabs = document.createElement("div");
  tabs.className = "stage-tabs";
  const stages = [
    { id: "reading", label: "Reading" },
    { id: "matching", label: "Matching", count: section.matching?.length || 0 },
    { id: "mcq", label: "Quiz" },
    { id: "recall", label: "Active Recall" },
    { id: "flashcards", label: "Flashcards" },
    { id: "clozes", label: "Clozes" },
  ];
  for (const stage of stages) {
    const btn = document.createElement("button");
    btn.className = "stage-tab" + (state.currentStage === stage.id ? " active" : "");
    const countLabel = stage.count > 0 ? `<span class="count">${stage.count}</span>` : "";
    btn.innerHTML = `${stage.label}${countLabel}`;
    btn.onclick = () => {
      state.currentStage = stage.id;
      renderSection();
    };
    tabs.appendChild(btn);
  }
  main.appendChild(tabs);

  // Stage content
  const content = document.createElement("div");
  main.appendChild(content);

  if (state.currentStage === "reading") renderReadingStage(content);
  else if (state.currentStage === "matching") renderMatchingStage(content);
  else if (state.currentStage === "mcq") renderMCQStage(content);
  else if (state.currentStage === "recall") renderRecallStage(content);
  else if (state.currentStage === "flashcards") renderFlashcardsStage(content);
  else if (state.currentStage === "clozes") renderClozesStage(content);

  // Section navigation
  const nav = document.createElement("div");
  nav.className = "nav-bar";
  const total = state.currentLecture.sections.length;
  const prev = section.section_index > 1 ? section.section_index - 1 : null;
  const next = section.section_index < total ? section.section_index + 1 : null;
  nav.innerHTML = `
    <button class="btn ghost" ${prev ? "" : "disabled"} id="btn-prev-section">← Previous</button>
    <div class="center">Section ${section.section_index} of ${total}</div>
    <button class="btn ghost" ${next ? "" : "disabled"} id="btn-next-section">Next →</button>
  `;
  nav.querySelector("#btn-prev-section").onclick = () => prev && openSection(prev);
  nav.querySelector("#btn-next-section").onclick = () => next && openSection(next);
  main.appendChild(nav);
}

// ---------- Reading stage ----------
function renderReadingStage(container) {
  const section = state.currentSection;

  // Layout: main reading column + margin notes column
  const layout = document.createElement("div");
  layout.className = "reading-layout";
  layout.innerHTML = `
    <div class="reading-main">
      <div class="reading-toolbar">
        <div class="highlight-palette">
          <span class="palette-label">Select text to highlight:</span>
          <button class="hl-btn" data-color="yellow" title="Yellow"></button>
          <button class="hl-btn" data-color="green" title="Green"></button>
          <button class="hl-btn" data-color="pink" title="Pink"></button>
          <button class="hl-btn" data-color="blue" title="Blue"></button>
          <button class="hl-btn clear" data-color="clear" title="Remove highlight">×</button>
        </div>
        <button class="btn ghost small" id="regen-reading-btn">↻ Regenerate reading</button>
      </div>
      <div class="card reading">
        <div class="reading-text markdown" id="reading-text"></div>
      </div>
    </div>
    <aside class="margin-notes">
      <div class="margin-notes-header">
        <span>My notes</span>
        <span class="save-indicator" id="notes-save-status"></span>
      </div>
      <div
        id="margin-notes-area"
        contenteditable="true"
        class="notes-editor"
        data-placeholder="Write notes here. Paste images with Cmd+V. They save automatically and stay attached to this section."
      >${section.margin_notes || ""}</div>
    </aside>
  `;
  container.appendChild(layout);

  const readingEl = layout.querySelector("#reading-text");
  const readingText = section.reading || "";

  // Render markdown -> HTML
  if (readingText.includes("##") || readingText.includes("**") || readingText.includes("- ") || readingText.includes("|")) {
    readingEl.innerHTML = marked.parse(readingText, { breaks: true, gfm: true });
  } else {
    // Older plain-paragraph content
    readingEl.innerHTML = formatProse(readingText);
  }

  // Apply saved highlights
  applyHighlights(readingEl, section.highlights || []);
  applySearchHighlight(readingEl, state.searchQuery.trim() ? state.pendingSearchHighlight : "");

  // Highlight palette buttons
  let selectedColor = null;
  layout.querySelectorAll(".hl-btn").forEach(btn => {
    btn.onclick = () => {
      layout.querySelectorAll(".hl-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      selectedColor = btn.dataset.color;
    };
  });

  // Text selection handler
  readingEl.addEventListener("mouseup", async () => {
    if (!selectedColor) return;
    const sel = window.getSelection();
    if (!sel.rangeCount) return;
    const selectedText = sel.toString().trim();
    if (!selectedText) return;

    // Check that selection is within reading element
    const range = sel.getRangeAt(0);
    if (!readingEl.contains(range.commonAncestorContainer)) return;

    if (selectedColor === "clear") {
      // Remove highlight where the selection overlaps
      await removeHighlightAtSelection(section, selectedText);
      sel.removeAllRanges();
      // Re-render
      const updated = state.currentSection.highlights || [];
      readingEl.innerHTML = readingText.includes("##") || readingText.includes("**") || readingText.includes("- ") || readingText.includes("|")
        ? marked.parse(readingText, { breaks: true, gfm: true })
        : formatProse(readingText);
      applyHighlights(readingEl, updated);
      return;
    }

    // Add highlight
    try {
      const entry = await api(
        `/api/lectures/${state.currentLectureId}/sections/${section.section_index}/highlights`,
        {
          method: "POST",
          body: JSON.stringify({ text: selectedText, color: selectedColor }),
        }
      );
      section.highlights = (section.highlights || []).concat(entry);
      applyHighlights(readingEl, section.highlights);
      sel.removeAllRanges();
    } catch (e) {
      toast("Couldn't save highlight: " + e.message, "error");
    }
  });

  // Margin notes: autosave + image paste
  const notesArea = layout.querySelector("#margin-notes-area");
  const saveStatus = layout.querySelector("#notes-save-status");
  let saveTimer = null;

  function saveNotes() {
    saveStatus.textContent = "saving…";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        await api(`/api/lectures/${state.currentLectureId}/sections/${section.section_index}/notes`, {
          method: "PUT",
          body: JSON.stringify({ notes: notesArea.innerHTML }),
        });
        section.margin_notes = notesArea.innerHTML;
        saveStatus.textContent = "✓ saved";
        setTimeout(() => { saveStatus.textContent = ""; }, 1500);
      } catch (e) {
        saveStatus.textContent = "error saving";
      }
    }, 600);
  }

  notesArea.addEventListener("input", saveNotes);

  // Handle paste — images as inline base64, text as plain text
  notesArea.addEventListener("paste", (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    let handled = false;

    for (const item of items) {
      if (item.type.startsWith("image/")) {
        e.preventDefault();
        handled = true;
        const file = item.getAsFile();
        const reader = new FileReader();
        reader.onload = (ev) => {
          const img = document.createElement("img");
          img.src = ev.target.result;
          img.className = "pasted-image";
          img.alt = "Pasted screenshot";
          // Insert at caret
          const sel = window.getSelection();
          if (sel.rangeCount > 0) {
            const range = sel.getRangeAt(0);
            range.deleteContents();
            range.insertNode(img);
            // Move cursor after the image
            range.setStartAfter(img);
            range.setEndAfter(img);
            sel.removeAllRanges();
            sel.addRange(range);
          } else {
            notesArea.appendChild(img);
          }
          // Add a line break after the image for typing
          const br = document.createElement("br");
          img.after(br);
          saveNotes();
        };
        reader.readAsDataURL(file);
        break;
      }
    }

    if (!handled) {
      // Plain text paste — strip formatting
      e.preventDefault();
      const text = e.clipboardData.getData("text/plain");
      document.execCommand("insertText", false, text);
    }
  });

  // Open pasted images in a larger viewer with delete + markup tools.
  notesArea.addEventListener("click", (e) => {
    if (e.target.tagName === "IMG" && e.target.classList.contains("pasted-image")) {
      openNoteImageViewer(e.target, saveNotes);
    }
  });

  // Regenerate reading button
  layout.querySelector("#regen-reading-btn").onclick = async () => {
    if (!confirm("Regenerate this section's reading in the new notes-style format? (~5¢)")) return;
    const btn = layout.querySelector("#regen-reading-btn");
    btn.disabled = true;
    btn.textContent = "Regenerating…";
    try {
      const data = await api(
        `/api/lectures/${state.currentLectureId}/sections/${section.section_index}/reading`,
        { method: "POST", body: "{}" }
      );
      section.reading = data.reading;
      renderSection();
      toast("Reading regenerated", "success");
    } catch (e) {
      toast("Regeneration failed: " + e.message, "error");
      btn.disabled = false;
      btn.textContent = "↻ Regenerate reading";
    }
  };

  // Diagram (after the layout, full width)
  if (section.diagram) {
    const dia = document.createElement("div");
    dia.className = "diagram-container";
    if (section.diagram.type === "mermaid") {
      const id = `mermaid-${section.section_index}-${Date.now()}`;
      dia.innerHTML = `<div class="mermaid" id="${id}">${section.diagram.code}</div>`;
      if (section.diagram.caption) {
        dia.innerHTML += `<div class="diagram-caption">${escapeHtml(section.diagram.caption)}</div>`;
      }
      setTimeout(() => {
        try { mermaid.run({ querySelector: `#${id}` }); } catch (e) { console.error(e); }
      }, 50);
    } else if (section.diagram.type === "svg") {
      dia.innerHTML = section.diagram.code;
      if (section.diagram.caption) {
        dia.innerHTML += `<div class="diagram-caption">${escapeHtml(section.diagram.caption)}</div>`;
      }
    }
    container.appendChild(dia);
  }

  renderSourceCitations(container, section);

  // Key terms
  if (section.key_terms?.length) {
    const sub = document.createElement("div");
    sub.className = "section-subhead";
    sub.textContent = "Key terms";
    container.appendChild(sub);
    const grid = document.createElement("div");
    grid.className = "terms-grid";
    for (const t of section.key_terms) {
      const el = document.createElement("div");
      el.className = "term-card";
      el.innerHTML = `<div class="term-name">${escapeHtml(t.term)}</div><div class="term-def">${escapeHtml(t.definition)}</div>`;
      grid.appendChild(el);
    }
    container.appendChild(grid);
  }

  // Confidence
  const conf = document.createElement("div");
  conf.className = "confidence-chooser";
  conf.innerHTML = `
    <span class="label">How confident with this section?</span>
    <div class="options">
      <button class="confidence-btn ${section.confidence === "low" ? "selected low" : ""}" data-rating="low">Low</button>
      <button class="confidence-btn ${section.confidence === "medium" ? "selected medium" : ""}" data-rating="medium">Medium</button>
      <button class="confidence-btn ${section.confidence === "high" ? "selected high" : ""}" data-rating="high">High</button>
    </div>
  `;
  conf.querySelectorAll("[data-rating]").forEach(btn => {
    btn.onclick = async () => {
      try {
        const rating = btn.dataset.rating;
        await api(`/api/lectures/${state.currentLectureId}/sections/${section.section_index}/confidence`, {
          method: "POST",
          body: JSON.stringify({ rating }),
        });
        section.confidence = rating;
        renderSection();
      } catch (e) { toast(e.message, "error"); }
    };
  });
  container.appendChild(conf);
}

function renderSourceCitations(container, section) {
  const citations = section.source_citations || {};
  const slides = citations.slides || [];
  const transcript = citations.transcript || {};
  const factCitations = (section.fact_citations || []).filter(c =>
    (c.slide_numbers && c.slide_numbers.length) || c.transcript_excerpt
  );
  if (!slides.length && !transcript.excerpt && !factCitations.length) return;

  const panel = document.createElement("details");
  panel.className = "source-citations";
  panel.innerHTML = `
    <summary>Sources used</summary>
    <div class="citation-body">
      ${slides.length ? `
        <div class="citation-group">
          <div class="citation-label">Slides / pages</div>
          <div class="citation-chips">
            ${slides.map(s => `<span class="citation-chip" title="${escapeHtml(s.excerpt || "")}">Slide ${escapeHtml(s.slide_number)}</span>`).join("")}
          </div>
        </div>
      ` : ""}
      ${transcript.excerpt ? `
        <div class="citation-group">
          <div class="citation-label">Transcript excerpt</div>
          <p>${escapeHtml(transcript.excerpt)}</p>
        </div>
      ` : ""}
      ${factCitations.length ? `
        <div class="citation-group">
          <div class="citation-label">Fact-level matches</div>
          <ul class="fact-citation-list">
            ${factCitations.slice(0, 12).map(c => `
              <li>
                <strong>${escapeHtml(c.label || c.kind)}</strong>
                ${c.slide_numbers?.length ? `<span>slides ${c.slide_numbers.map(escapeHtml).join(", ")}</span>` : ""}
                ${c.transcript_excerpt ? `<span>transcript match</span>` : ""}
              </li>
            `).join("")}
          </ul>
        </div>
      ` : ""}
    </div>
  `;
  container.appendChild(panel);
}

// Apply highlights by wrapping matching text occurrences in the rendered HTML
function applyHighlights(element, highlights) {
  if (!highlights?.length) return;

  // Walk all text nodes, wrap matching substrings
  for (const h of highlights) {
    if (!h.text) continue;
    wrapTextInElement(element, h.text, h.id, h.color);
  }
}

function applySearchHighlight(element, query) {
  const terms = String(query || "")
    .toLowerCase()
    .split(/\s+/)
    .filter(term => term.length >= 2)
    .slice(0, 6);
  if (!terms.length) return;

  let firstMatch = null;
  for (const term of terms) {
    const matches = wrapSearchTermInElement(element, term);
    if (!firstMatch && matches[0]) firstMatch = matches[0];
  }
  if (firstMatch) {
    setTimeout(() => firstMatch.scrollIntoView({ behavior: "smooth", block: "center" }), 80);
    toast("Highlighted search match", "success");
  }
}

function wrapSearchTermInElement(root, searchTerm) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  const targets = [];
  let node;
  while ((node = walker.nextNode())) {
    if (node.parentElement.closest(".highlight, .search-hit")) continue;
    const idx = node.nodeValue.toLowerCase().indexOf(searchTerm);
    if (idx !== -1) targets.push({ node, idx });
  }
  const matches = [];
  for (const { node, idx } of targets) {
    const text = node.nodeValue;
    const before = text.slice(0, idx);
    const match = text.slice(idx, idx + searchTerm.length);
    const after = text.slice(idx + searchTerm.length);
    const span = document.createElement("span");
    span.className = "search-hit";
    span.textContent = match;
    node.parentNode.insertBefore(document.createTextNode(before), node);
    node.parentNode.insertBefore(span, node);
    node.parentNode.insertBefore(document.createTextNode(after), node);
    node.remove();
    matches.push(span);
  }
  return matches;
}

function clearSearchHighlights(root = document) {
  $$(".search-hit", root).forEach(hit => {
    hit.replaceWith(document.createTextNode(hit.textContent || ""));
  });
}

function openNoteImageViewer(img, saveNotes) {
  const overlay = document.createElement("div");
  overlay.className = "image-viewer";
  overlay.innerHTML = `
    <div class="image-viewer-panel">
      <div class="image-viewer-toolbar">
        <button class="btn ghost small" data-tool="draw">Draw</button>
        <button class="btn ghost small" data-tool="highlight">Highlight</button>
        <button class="btn ghost small" data-tool="clear">Clear markup</button>
        <button class="btn danger small" data-tool="delete">Delete</button>
        <button class="icon-btn" data-tool="close">×</button>
      </div>
      <div class="image-viewer-stage">
        <canvas class="image-markup-canvas"></canvas>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const canvas = overlay.querySelector(".image-markup-canvas");
  const ctx = canvas.getContext("2d");
  const source = new Image();
  let tool = "draw";
  let drawing = false;
  let lastPoint = null;

  const close = () => overlay.remove();
  const setTool = nextTool => {
    tool = nextTool;
    overlay.querySelectorAll("[data-tool='draw'], [data-tool='highlight']").forEach(btn => {
      btn.classList.toggle("primary", btn.dataset.tool === tool);
      btn.classList.toggle("ghost", btn.dataset.tool !== tool);
    });
  };

  function canvasPoint(e) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvas.width / rect.width),
      y: (e.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function persistCanvas() {
    img.src = canvas.toDataURL("image/png");
    saveNotes();
  }

  source.onload = () => {
    const maxWidth = Math.min(source.naturalWidth || source.width, 1200);
    const scale = maxWidth / (source.naturalWidth || source.width);
    canvas.width = maxWidth;
    canvas.height = Math.round((source.naturalHeight || source.height) * scale);
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  };
  source.src = img.src;

  canvas.addEventListener("pointerdown", e => {
    drawing = true;
    lastPoint = canvasPoint(e);
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", e => {
    if (!drawing || !lastPoint) return;
    const point = canvasPoint(e);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (tool === "highlight") {
      ctx.globalAlpha = 0.45;
      ctx.strokeStyle = "#f7e58c";
      ctx.lineWidth = 18;
    } else {
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "#b56b4a";
      ctx.lineWidth = 4;
    }
    ctx.beginPath();
    ctx.moveTo(lastPoint.x, lastPoint.y);
    ctx.lineTo(point.x, point.y);
    ctx.stroke();
    ctx.globalAlpha = 1;
    lastPoint = point;
  });
  canvas.addEventListener("pointerup", e => {
    if (!drawing) return;
    drawing = false;
    lastPoint = null;
    canvas.releasePointerCapture(e.pointerId);
    persistCanvas();
  });

  overlay.querySelector('[data-tool="draw"]').onclick = () => setTool("draw");
  overlay.querySelector('[data-tool="highlight"]').onclick = () => setTool("highlight");
  overlay.querySelector('[data-tool="clear"]').onclick = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    persistCanvas();
  };
  overlay.querySelector('[data-tool="delete"]').onclick = () => {
    if (!confirm("Delete this image from your notes?")) return;
    img.remove();
    saveNotes();
    close();
  };
  overlay.querySelector('[data-tool="close"]').onclick = close;
  overlay.addEventListener("click", e => {
    if (e.target === overlay) close();
  });
  setTool("draw");
}

function wrapTextInElement(root, searchText, highlightId, color) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  const targets = [];
  let node;
  while ((node = walker.nextNode())) {
    if (node.parentElement.closest(".highlight")) continue; // already highlighted
    const idx = node.nodeValue.indexOf(searchText);
    if (idx !== -1) {
      targets.push({ node, idx });
    }
  }
  for (const { node, idx } of targets) {
    const text = node.nodeValue;
    const before = text.slice(0, idx);
    const match = text.slice(idx, idx + searchText.length);
    const after = text.slice(idx + searchText.length);
    const span = document.createElement("span");
    span.className = `highlight hl-${color}`;
    span.dataset.highlightId = highlightId;
    span.textContent = match;
    span.title = "Click to remove highlight";
    span.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm("Remove this highlight?")) return;
      try {
        await api(
          `/api/lectures/${state.currentLectureId}/sections/${state.currentSection.section_index}/highlights/${highlightId}`,
          { method: "DELETE" }
        );
        state.currentSection.highlights = state.currentSection.highlights.filter(h => h.id !== highlightId);
        // Re-render reading
        renderSection();
      } catch (err) {
        toast("Couldn't remove highlight", "error");
      }
    };
    const frag = document.createDocumentFragment();
    if (before) frag.appendChild(document.createTextNode(before));
    frag.appendChild(span);
    if (after) frag.appendChild(document.createTextNode(after));
    node.parentNode.replaceChild(frag, node);
  }
}

async function removeHighlightAtSelection(section, selectedText) {
  // Find highlights that overlap the selected text
  const toRemove = (section.highlights || []).filter(h =>
    selectedText.includes(h.text) || h.text.includes(selectedText)
  );
  for (const h of toRemove) {
    try {
      await api(
        `/api/lectures/${state.currentLectureId}/sections/${section.section_index}/highlights/${h.id}`,
        { method: "DELETE" }
      );
    } catch (e) { /* keep going */ }
  }
  section.highlights = (section.highlights || []).filter(h => !toRemove.includes(h));
}

// ---------- Matching stage ----------
function renderMatchingStage(container) {
  const section = state.currentSection;
  const pairs = section.matching || [];
  if (!pairs.length) {
    container.innerHTML = `<div class="card"><p class="mcq-empty"><em>No matching pairs available for this section.</em></p></div>`;
    return;
  }

  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <p class="matching-instructions">Click a term on the left, then its match on the right.</p>
    <div class="matching-grid" id="match-grid"></div>
    <div id="match-done"></div>
  `;
  container.appendChild(card);

  // Build shuffled arrays
  const lefts = pairs.map((p, i) => ({ text: p.left, idx: i }));
  const rights = shuffle(pairs.map((p, i) => ({ text: p.right, idx: i })));

  const grid = card.querySelector("#match-grid");
  let selectedLeft = null;
  let matched = new Set();

  function makeTile(item, side) {
    const tile = document.createElement("div");
    tile.className = "match-tile";
    tile.textContent = item.text;
    tile.dataset.idx = item.idx;
    tile.dataset.side = side;
    tile.onclick = () => {
      if (tile.classList.contains("matched")) return;
      if (side === "left") {
        $$(".match-tile[data-side='left']", grid).forEach(t => t.classList.remove("selected"));
        tile.classList.add("selected");
        selectedLeft = item.idx;
      } else if (selectedLeft != null) {
        if (item.idx === selectedLeft) {
          // Correct match
          tile.classList.add("matched");
          const leftEl = grid.querySelector(`.match-tile[data-side='left'][data-idx='${item.idx}']`);
          leftEl.classList.remove("selected");
          leftEl.classList.add("matched");
          matched.add(item.idx);
          selectedLeft = null;
          if (matched.size === pairs.length) {
            card.querySelector("#match-done").innerHTML = `<div class="matching-complete">✓ All matched. Beautiful work.</div>`;
          }
        } else {
          tile.classList.add("wrong");
          setTimeout(() => tile.classList.remove("wrong"), 350);
        }
      }
    };
    return tile;
  }

  // Interleave for grid
  const half = pairs.length;
  for (let i = 0; i < half; i++) {
    grid.appendChild(makeTile(lefts[i], "left"));
    grid.appendChild(makeTile(rights[i], "right"));
  }
}

// ---------- MCQ stage ----------
async function renderMCQStage(container) {
  const section = state.currentSection;
  const l1 = section.questions_l1 || [];
  const nbme = section.questions_nbme || [];

  const card = document.createElement("div");
  card.className = "card";

  // Top controls
  const controls = document.createElement("div");
  controls.className = "mcq-controls";
  controls.innerHTML = `
    <div class="mcq-stats">
      <strong>${l1.length}</strong> Level 1 · <strong>${nbme.length}</strong> NBME
    </div>
    <div class="difficulty-toggle">
      <button data-diff="L1" class="active">Level 1</button>
      <button data-diff="NBME">NBME</button>
    </div>
  `;
  card.appendChild(controls);

  const listWrap = document.createElement("div");
  card.appendChild(listWrap);

  // Action row
  const actions = document.createElement("div");
  actions.style.cssText = "display:flex; gap:8px; margin-top: 16px; flex-wrap: wrap;";
  actions.innerHTML = `
    <button class="btn primary" id="btn-gen-l1">${l1.length === 0 ? "Generate" : "More"} Level 1</button>
    <button class="btn ghost" id="btn-gen-nbme">${nbme.length === 0 ? "Generate" : "More"} NBME</button>
    <button class="btn ghost" id="btn-regen-current">Regenerate current set</button>
  `;
  card.appendChild(actions);

  container.appendChild(card);

  let currentDiff = "L1";

  function renderList() {
    listWrap.innerHTML = "";
    const questions = currentDiff === "L1" ? section.questions_l1 || [] : section.questions_nbme || [];
    if (!questions.length) {
      listWrap.innerHTML = `
        <div class="mcq-empty">
          <p>No ${currentDiff === "L1" ? "Level 1" : "NBME-style"} questions generated yet for this section.</p>
          <button class="btn primary" data-act="gen-now">Generate now</button>
        </div>
      `;
      listWrap.querySelector('[data-act="gen-now"]').onclick = () => generateQuestions(currentDiff, false);
      return;
    }
    questions.forEach((q, i) => listWrap.appendChild(makeMCQCard(q, i, currentDiff)));
  }

  controls.querySelectorAll("[data-diff]").forEach(btn => {
    btn.onclick = () => {
      controls.querySelectorAll("[data-diff]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentDiff = btn.dataset.diff;
      renderList();
    };
  });

  actions.querySelector("#btn-gen-l1").onclick = () => generateQuestions("L1", false);
  actions.querySelector("#btn-gen-nbme").onclick = () => generateQuestions("NBME", false);
  actions.querySelector("#btn-regen-current").onclick = () => {
    if (confirm("Regenerate questions at this difficulty? Existing ones will be replaced.")) {
      generateQuestions(currentDiff, true);
    }
  };

  renderList();
}

function makeMCQCard(q, idx, difficulty) {
  const card = document.createElement("div");
  card.className = "mcq-card";
  const diffClass = q.difficulty === "NBME" ? "nbme" : "l1";
  card.innerHTML = `
    <div class="mcq-number">
      Question ${idx + 1}
      <span class="difficulty-badge ${diffClass}">${q.difficulty || difficulty}</span>
    </div>
    <div class="mcq-question">${escapeHtml(q.question)}</div>
    <div class="choices"></div>
    <div class="explanation-slot"></div>
  `;
  const choicesEl = card.querySelector(".choices");
  const explSlot = card.querySelector(".explanation-slot");
  q.choices.forEach((c, i) => {
    const btn = document.createElement("button");
    btn.className = "choice";
    btn.innerHTML = `<span class="letter">${String.fromCharCode(65 + i)}</span><span>${escapeHtml(c)}</span>`;
    btn.onclick = () => {
      if (btn.disabled) return;
      const correct = i === q.correct_index;
      $$(".choice", choicesEl).forEach((b, bi) => {
        b.disabled = true;
        if (bi === q.correct_index) b.classList.add("correct");
        else if (bi === i) b.classList.add("incorrect");
      });
      explSlot.innerHTML = `
        <div class="explanation ${correct ? "correct" : "incorrect"}">
          <span class="explanation-label">${correct ? "Correct" : "Not quite"}</span>
          ${escapeHtml(q.explanation || "")}
        </div>
      `;
      if (!correct) {
        api(`/api/lectures/${state.currentLectureId}/wrong-answers`, {
          method: "POST",
          body: JSON.stringify({
            section_index: state.currentSection.section_index,
            question: q,
            source: "section",
          }),
        }).catch(() => {});
      }
    };
    choicesEl.appendChild(btn);
  });
  return card;
}

async function generateQuestions(difficulty, regenerate) {
  const section = state.currentSection;
  const loading = showInlineLoader(`Generating ${difficulty === "L1" ? "Level 1" : "NBME"} questions…`);
  try {
    const data = await api(
      `/api/lectures/${state.currentLectureId}/sections/${section.section_index}/questions`,
      {
        method: "POST",
        body: JSON.stringify({ difficulty, regenerate }),
      }
    );
    section.questions_l1 = data.questions_l1 || [];
    section.questions_nbme = data.questions_nbme || [];
    renderSection();
  } catch (e) {
    toast("Generation failed: " + e.message, "error");
  } finally {
    loading.remove();
  }
}

// ---------- Active Recall stage ----------
async function renderRecallStage(container) {
  const section = state.currentSection;
  const prompts = section.recall_prompts || [];

  const card = document.createElement("div");
  card.className = "card";

  if (!prompts.length) {
    card.innerHTML = `
      <div class="mcq-empty">
        <p>No active recall prompts yet for this section.</p>
        <button class="btn primary" id="gen-recall">Generate</button>
      </div>
    `;
    card.querySelector("#gen-recall").onclick = () => generateRecall();
  } else {
    const sub = document.createElement("p");
    sub.style.cssText = "color: var(--ink-soft); margin-bottom: 18px; font-style: italic;";
    sub.textContent = "Write your answer first, then reveal the model answer. Be honest with yourself.";
    card.appendChild(sub);

    prompts.forEach((p, i) => card.appendChild(makeRecallCard(p, i)));

    const actions = document.createElement("div");
    actions.style.cssText = "margin-top: 16px; display:flex; gap:8px;";
    actions.innerHTML = `<button class="btn ghost" id="regen-recall">Regenerate prompts</button>`;
    actions.querySelector("#regen-recall").onclick = () => {
      if (confirm("Regenerate all active recall prompts for this section?")) generateRecall();
    };
    card.appendChild(actions);
  }
  container.appendChild(card);
}

function makeRecallCard(p, idx) {
  const card = document.createElement("div");
  card.className = "recall-card";
  card.innerHTML = `
    <div class="recall-number">Prompt ${idx + 1}</div>
    <div class="recall-prompt">${escapeHtml(p.prompt)}</div>
    <textarea class="recall" placeholder="Your answer..."></textarea>
    <div class="recall-actions">
      <button class="btn primary small" data-act="reveal">Reveal model answer</button>
    </div>
    <div class="model-slot"></div>
  `;
  card.querySelector('[data-act="reveal"]').onclick = (e) => {
    e.target.disabled = true;
    card.querySelector(".model-slot").innerHTML = `
      <div class="model-answer">
        <div class="model-answer-label">Model answer</div>
        <p>${escapeHtml(p.model_answer)}</p>
      </div>
    `;
  };
  return card;
}

async function generateRecall() {
  const section = state.currentSection;
  const loading = showInlineLoader("Generating active recall prompts…");
  try {
    const data = await api(
      `/api/lectures/${state.currentLectureId}/sections/${section.section_index}/recall`,
      { method: "POST", body: "{}" }
    );
    section.recall_prompts = data.recall_prompts || [];
    renderSection();
  } catch (e) {
    toast("Generation failed: " + e.message, "error");
  } finally {
    loading.remove();
  }
}

// ---------- Flashcards stage ----------
async function renderFlashcardsStage(container) {
  const section = state.currentSection;
  const cards = section.flashcards || [];

  if (!cards.length) {
    container.innerHTML = `
      <div class="card">
        <div class="mcq-empty">
          <p>No flashcards generated yet for this section.</p>
          <button class="btn primary" id="gen-cards">Generate flashcards</button>
        </div>
      </div>
    `;
    $("#gen-cards").onclick = () => generateFlashcards();
    return;
  }

  // Filter due cards
  const today = new Date().toISOString().slice(0, 10);
  const due = cards.filter(c => !c.sr_state?.due || c.sr_state.due <= today);
  const queue = due.length ? due : cards;  // if none due, study all

  const wrap = document.createElement("div");
  wrap.className = "card";

  if (!queue.length) {
    wrap.innerHTML = `
      <div class="flashcards-done">
        <div class="icon">✿</div>
        <p>All cards reviewed for today.</p>
      </div>
    `;
    container.appendChild(wrap);
    return;
  }

  let idx = 0;
  let showBack = false;

  function render() {
    const c = queue[idx];
    wrap.innerHTML = `
      <div class="flashcard-stage">
        <div class="flashcard-counter">${idx + 1} of ${queue.length}</div>
        <div class="flashcard" id="card-clickable">
          <div class="flashcard-side-label">${showBack ? "Back" : "Front"}</div>
          <div class="flashcard-text">${escapeHtml(showBack ? c.back : c.front)}</div>
          <div class="flashcard-prompt">${showBack ? "How well did you know it?" : "Tap to reveal"}</div>
        </div>
        ${showBack ? `
          <div class="flashcard-rating">
            <button class="rating-btn again" data-rating="0">Again</button>
            <button class="rating-btn hard" data-rating="1">Hard</button>
            <button class="rating-btn good" data-rating="2">Good</button>
            <button class="rating-btn easy" data-rating="3">Easy</button>
          </div>
        ` : ""}
        <div style="margin-top:12px;">
          <button class="btn ghost small" id="regen-cards">Regenerate cards</button>
        </div>
      </div>
    `;
    wrap.querySelector("#card-clickable").onclick = () => { if (!showBack) { showBack = true; render(); } };
    wrap.querySelectorAll(".rating-btn").forEach(btn => {
      btn.onclick = async () => {
        const rating = parseInt(btn.dataset.rating);
        try {
          await api(`/api/lectures/${state.currentLectureId}/sections/${section.section_index}/flashcards/${c.id}/rate`,
            { method: "POST", body: JSON.stringify({ rating }) });
        } catch (e) { toast(e.message, "error"); }
        idx++;
        showBack = false;
        if (idx >= queue.length) {
          wrap.innerHTML = `
            <div class="flashcards-done">
              <div class="icon">✿</div>
              <p>Done with this round.</p>
            </div>
          `;
        } else {
          render();
        }
      };
    });
    wrap.querySelector("#regen-cards").onclick = () => {
      if (confirm("Regenerate all flashcards for this section?")) generateFlashcards();
    };
  }

  render();
  container.appendChild(wrap);
}

async function generateFlashcards() {
  const section = state.currentSection;
  const loading = showInlineLoader("Generating flashcards…");
  try {
    const data = await api(
      `/api/lectures/${state.currentLectureId}/sections/${section.section_index}/flashcards`,
      { method: "POST", body: "{}" }
    );
    section.flashcards = data.flashcards || [];
    renderSection();
  } catch (e) { toast("Generation failed: " + e.message, "error"); }
  finally { loading.remove(); }
}

// ---------- Cloze stage ----------
async function renderClozesStage(container) {
  const section = state.currentSection;
  const clozes = section.clozes || [];

  if (!clozes.length) {
    container.innerHTML = `
      <div class="card">
        <div class="mcq-empty">
          <p>No cloze deletions generated yet for this section.</p>
          <button class="btn primary" id="gen-cloze">Generate clozes</button>
        </div>
      </div>
    `;
    $("#gen-cloze").onclick = () => generateClozes();
    return;
  }

  const wrap = document.createElement("div");
  wrap.className = "card";
  const sub = document.createElement("p");
  sub.style.cssText = "color: var(--ink-soft); margin-bottom: 16px; font-style: italic;";
  sub.textContent = "Type the missing word, or click the blank to reveal.";
  wrap.appendChild(sub);

  clozes.forEach((c, i) => wrap.appendChild(makeClozeCard(c, i)));

  const actions = document.createElement("div");
  actions.style.cssText = "margin-top: 16px;";
  actions.innerHTML = `<button class="btn ghost small" id="regen-clozes">Regenerate clozes</button>`;
  actions.querySelector("#regen-clozes").onclick = () => {
    if (confirm("Regenerate all cloze cards?")) generateClozes();
  };
  wrap.appendChild(actions);

  container.appendChild(wrap);
}

function makeClozeCard(c, idx) {
  const card = document.createElement("div");
  card.className = "cloze-card";
  const before = c.text.split(`{{${c.answer}}}`)[0] || "";
  const after = c.text.split(`{{${c.answer}}}`)[1] || "";
  card.innerHTML = `
    <div class="recall-number">Cloze ${idx + 1}</div>
    <div class="cloze-text">
      ${escapeHtml(before)}<input type="text" class="cloze-input" placeholder="?"/>${escapeHtml(after)}
    </div>
    <div class="recall-actions">
      <button class="btn ghost small" data-act="check">Check</button>
      <button class="btn ghost small" data-act="reveal">Reveal</button>
      <span class="rating-slot" style="margin-left: 12px;"></span>
    </div>
  `;
  const input = card.querySelector("input");
  const checkBtn = card.querySelector('[data-act="check"]');
  const revealBtn = card.querySelector('[data-act="reveal"]');
  const ratingSlot = card.querySelector(".rating-slot");

  function showRating() {
    ratingSlot.innerHTML = `
      <button class="rating-btn again" data-rating="0">Again</button>
      <button class="rating-btn good" data-rating="2">Good</button>
    `;
    ratingSlot.querySelectorAll("[data-rating]").forEach(btn => {
      btn.onclick = () => {
        const rating = parseInt(btn.dataset.rating);
        api(`/api/lectures/${state.currentLectureId}/sections/${state.currentSection.section_index}/clozes/${c.id}/rate`,
          { method: "POST", body: JSON.stringify({ rating }) }).catch(() => {});
        ratingSlot.innerHTML = `<span style="color: var(--sage-700); font-size: 0.85rem;">✓ Rated</span>`;
      };
    });
  }

  checkBtn.onclick = () => {
    const v = input.value.trim().toLowerCase();
    const a = c.answer.trim().toLowerCase();
    if (v === a) {
      input.classList.add("correct");
      input.classList.remove("wrong");
      input.disabled = true;
    } else {
      input.classList.add("wrong");
    }
    showRating();
  };
  revealBtn.onclick = () => {
    input.value = c.answer;
    input.classList.add("correct");
    input.disabled = true;
    showRating();
  };
  return card;
}

async function generateClozes() {
  const section = state.currentSection;
  const loading = showInlineLoader("Generating cloze cards…");
  try {
    const data = await api(
      `/api/lectures/${state.currentLectureId}/sections/${section.section_index}/clozes`,
      { method: "POST", body: "{}" }
    );
    section.clozes = data.clozes || [];
    renderSection();
  } catch (e) { toast("Generation failed: " + e.message, "error"); }
  finally { loading.remove(); }
}

// =============================================================================
// Comprehensive quiz
// =============================================================================
async function openComprehensiveQuiz() {
  state.view = { type: "comprehensive" };
  const main = $("#main");
  main.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Loading quiz…</p></div>`;

  try {
    const data = await api(`/api/lectures/${state.currentLectureId}/comprehensive`);
    let questions = data.questions || [];
    if (!questions.length) {
      const gen = confirm("No comprehensive quiz yet. Generate one now? (takes ~30 sec)");
      if (!gen) { renderLecture(); return; }
      main.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Generating comprehensive quiz…</p></div>`;
      const res = await api(`/api/lectures/${state.currentLectureId}/comprehensive`, { method: "POST", body: "{}" });
      questions = res.questions || [];
    }
    renderQuiz(questions, {
      title: "Comprehensive Quiz",
      subtitle: state.currentLecture.name,
      onRegenerate: async () => {
        if (!confirm("Regenerate the entire comprehensive quiz?")) return;
        main.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Regenerating…</p></div>`;
        const res = await api(`/api/lectures/${state.currentLectureId}/comprehensive`, { method: "POST", body: "{}" });
        renderQuiz(res.questions || [], {
          title: "Comprehensive Quiz",
          subtitle: state.currentLecture.name,
          onRegenerate: arguments.callee,
        });
      },
      source: "comprehensive",
    });
  } catch (e) {
    toast("Couldn't load quiz: " + e.message, "error");
    renderLecture();
  }
}

async function openExamCumulativeQuiz(exam) {
  state.view = { type: "exam-quiz" };
  state.currentLectureId = null;
  state.currentExam = exam;
  renderSidebar();
  const main = $("#main");
  main.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Loading cumulative quiz…</p></div>`;
  try {
    const data = await api(`/api/exams/${exam.id}/cumulative-quiz`);
    let questions = data.questions || [];
    if (!questions.length) {
      const gen = confirm(`Generate cumulative quiz for "${exam.name}"? This covers all ${exam.lectures.length} lectures and takes ~1 min.`);
      if (!gen) { showWelcome(); return; }
      main.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Generating cumulative quiz…</p></div>`;
      const res = await api(`/api/exams/${exam.id}/cumulative-quiz`, { method: "POST", body: "{}" });
      questions = res.questions || [];
    }
    renderQuiz(questions, {
      title: `${exam.name} — Cumulative Quiz`,
      subtitle: `${exam.lectures.length} lectures`,
      onRegenerate: async () => {
        if (!confirm("Regenerate cumulative quiz?")) return;
        main.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><p>Regenerating…</p></div>`;
        const res = await api(`/api/exams/${exam.id}/cumulative-quiz`, { method: "POST", body: "{}" });
        renderQuiz(res.questions || [], { title: `${exam.name} — Cumulative Quiz`, subtitle: `${exam.lectures.length} lectures` });
      },
      source: "exam",
    });
  } catch (e) {
    toast("Couldn't load cumulative quiz: " + e.message, "error");
    showWelcome();
  }
}

function renderQuiz(questions, opts) {
  const main = $("#main");
  main.innerHTML = "";

  const header = document.createElement("div");
  header.className = "study-header";
  header.innerHTML = `
    <div>
      <div class="study-subtitle">${escapeHtml(opts.subtitle || "")}</div>
      <div class="study-title">${escapeHtml(opts.title)}</div>
    </div>
    <div class="study-header-actions">
      ${state.currentLectureId ? `<button class="btn ghost small" id="back">← Lecture</button>` : `<button class="btn ghost small" id="back">← Home</button>`}
      <button class="btn ghost small" id="regen">↻ Regenerate</button>
    </div>
  `;
  header.querySelector("#back").onclick = () => state.currentLectureId ? renderLecture() : showWelcome();
  header.querySelector("#regen").onclick = () => opts.onRegenerate?.();
  main.appendChild(header);

  const wrap = document.createElement("div");
  wrap.className = "quiz-view";
  main.appendChild(wrap);

  const summarySlot = document.createElement("div");
  wrap.appendChild(summarySlot);

  const answers = new Array(questions.length).fill(null); // user choices

  questions.forEach((q, i) => {
    const card = document.createElement("div");
    card.className = "mcq-card";
    const diffClass = q.difficulty === "NBME" ? "nbme" : "l1";
    card.innerHTML = `
      <div class="mcq-number">
        Question ${i + 1}
        <span class="difficulty-badge ${diffClass}">${q.difficulty || "L1"}</span>
      </div>
      <div class="mcq-question">${escapeHtml(q.question)}</div>
      <div class="choices"></div>
      <div class="explanation-slot"></div>
    `;
    const choicesEl = card.querySelector(".choices");
    const explSlot = card.querySelector(".explanation-slot");
    q.choices.forEach((c, ci) => {
      const btn = document.createElement("button");
      btn.className = "choice";
      btn.innerHTML = `<span class="letter">${String.fromCharCode(65 + ci)}</span><span>${escapeHtml(c)}</span>`;
      btn.onclick = () => {
        if (btn.disabled) return;
        const correct = ci === q.correct_index;
        answers[i] = correct;
        $$(".choice", choicesEl).forEach((b, bi) => {
          b.disabled = true;
          if (bi === q.correct_index) b.classList.add("correct");
          else if (bi === ci) b.classList.add("incorrect");
        });
        explSlot.innerHTML = `
          <div class="explanation ${correct ? "correct" : "incorrect"}">
            <span class="explanation-label">${correct ? "Correct" : "Not quite"}</span>
            ${escapeHtml(q.explanation || "")}
          </div>
        `;
        if (!correct && state.currentLectureId) {
          api(`/api/lectures/${state.currentLectureId}/wrong-answers`, {
            method: "POST",
            body: JSON.stringify({ question: q, source: opts.source }),
          }).catch(() => {});
        }
        updateSummary();
      };
      choicesEl.appendChild(btn);
    });
    wrap.appendChild(card);
  });

  function updateSummary() {
    const answered = answers.filter(a => a !== null).length;
    const correct = answers.filter(a => a === true).length;
    summarySlot.innerHTML = `
      <div class="quiz-summary">
        <h2>${opts.title}</h2>
        <div class="score">${correct} / ${questions.length}</div>
        <div class="meta">${answered} of ${questions.length} answered</div>
        <div class="quiz-summary-actions">
          <button class="btn" id="restart-quiz">Restart</button>
        </div>
      </div>
    `;
    summarySlot.querySelector("#restart-quiz").onclick = () => renderQuiz(questions, opts);
  }
  updateSummary();
}

// =============================================================================
// Dashboard / cram / history
// =============================================================================
async function renderDashboard() {
  state.view = { type: "dashboard" };
  renderSidebar();
  const main = $("#main");
  main.innerHTML = `<div class="loading-overlay"><div class="spinner"></div></div>`;
  try {
    const ws = await api("/api/weak-spots");
    main.innerHTML = `
      <div class="dashboard">
        <h2>Weak Spots</h2>
        <p class="dashboard-sub">Sections where you've missed questions or rated low confidence. Click to revisit.</p>

        <div class="dashboard-section">
          <h3>Sections needing attention <span class="count">${ws.by_section.length}</span></h3>
          ${ws.by_section.length === 0
            ? `<div class="empty-state">No weak spots yet — keep going.</div>`
            : `<ul class="weak-spot-list">${ws.by_section.map(s => `
                <li class="weak-spot-item" data-lec="${s.lecture_id}" data-sec="${s.section_index}">
                  <div style="flex:1">
                    <div class="weak-spot-name">${escapeHtml(s.section_title || "Section " + s.section_index)}</div>
                    <div class="weak-spot-lec">${escapeHtml(s.lecture_name)}</div>
                  </div>
                  ${s.confidence === "low" ? `<span class="confidence-pill low">low</span>` : ""}
                  ${s.miss_count > 0 ? `<span class="miss-badge">${s.miss_count} miss${s.miss_count > 1 ? "es" : ""}</span>` : ""}
                </li>`).join("")}</ul>`
          }
        </div>

        <div class="dashboard-section">
          <h3>Lectures by total misses <span class="count">${ws.by_lecture.length}</span></h3>
          ${ws.by_lecture.length === 0
            ? `<div class="empty-state">Nothing yet.</div>`
            : `<ul class="weak-spot-list">${ws.by_lecture.map(l => `
                <li class="weak-spot-item" data-lec="${l.lecture_id}">
                  <div class="weak-spot-name" style="flex:1">${escapeHtml(l.lecture_name)}</div>
                  <span class="miss-badge">${l.total_misses}</span>
                </li>`).join("")}</ul>`
          }
        </div>
      </div>
    `;
    $$(".weak-spot-item[data-sec]").forEach(item => {
      item.onclick = async () => {
        await openLecture(item.dataset.lec);
        openSection(parseInt(item.dataset.sec));
      };
    });
    $$(".weak-spot-item:not([data-sec])").forEach(item => {
      item.onclick = () => openLecture(item.dataset.lec);
    });
  } catch (e) { toast("Couldn't load dashboard: " + e.message, "error"); }
}

async function renderCram() {
  state.view = { type: "cram" };
  renderSidebar();
  const main = $("#main");
  main.innerHTML = `<div class="loading-overlay"><div class="spinner"></div></div>`;
  try {
    const data = await api("/api/cram");
    main.innerHTML = `
      <div class="dashboard">
        <h2>Cram Mode</h2>
        <p class="dashboard-sub">What needs attention right now — based on misses, low-confidence sections, and spaced-repetition due dates.</p>

        <div class="cram-stat-grid">
          <div class="cram-stat">
            <div class="cram-stat-num">${data.due_wrong_answers.length}</div>
            <div class="cram-stat-label">Wrong answers due</div>
          </div>
          <div class="cram-stat">
            <div class="cram-stat-num">${data.due_flashcards.length}</div>
            <div class="cram-stat-label">Cards due</div>
          </div>
          <div class="cram-stat">
            <div class="cram-stat-num">${data.due_clozes.length}</div>
            <div class="cram-stat-label">Clozes due</div>
          </div>
          <div class="cram-stat">
            <div class="cram-stat-num">${data.low_confidence_sections.length}</div>
            <div class="cram-stat-label">Low confidence</div>
          </div>
        </div>

        <div class="dashboard-section">
          <h3>Wrong answers to review</h3>
          ${data.due_wrong_answers.length === 0
            ? `<div class="empty-state">Nothing due. Nice.</div>`
            : `<div id="cram-wrong-list"></div>`}
        </div>

        <div class="dashboard-section">
          <h3>Low-confidence sections</h3>
          ${data.low_confidence_sections.length === 0
            ? `<div class="empty-state">No low-confidence sections.</div>`
            : `<ul class="weak-spot-list">${data.low_confidence_sections.map(s => `
                <li class="weak-spot-item" data-lec="${s.lecture_id}" data-sec="${s.section_index}">
                  <div style="flex:1">
                    <div class="weak-spot-name">${escapeHtml(s.section_title || "Section " + s.section_index)}</div>
                    <div class="weak-spot-lec">${escapeHtml(s.lecture_name)}</div>
                  </div>
                </li>`).join("")}</ul>`}
        </div>
      </div>
    `;

    if (data.due_wrong_answers.length) {
      const wrap = $("#cram-wrong-list");
      data.due_wrong_answers.forEach((entry, i) => {
        const q = entry.entry.question;
        const card = document.createElement("div");
        card.className = "mcq-card";
        card.style.marginBottom = "12px";
        card.innerHTML = `
          <div class="mcq-number">From: ${escapeHtml(entry.lecture_name)}</div>
          <div class="mcq-question">${escapeHtml(q.question)}</div>
          <div class="choices"></div>
          <div class="explanation-slot"></div>
        `;
        const choicesEl = card.querySelector(".choices");
        const explSlot = card.querySelector(".explanation-slot");
        q.choices.forEach((c, ci) => {
          const btn = document.createElement("button");
          btn.className = "choice";
          btn.innerHTML = `<span class="letter">${String.fromCharCode(65 + ci)}</span><span>${escapeHtml(c)}</span>`;
          btn.onclick = () => {
            if (btn.disabled) return;
            const correct = ci === q.correct_index;
            $$(".choice", choicesEl).forEach((b, bi) => {
              b.disabled = true;
              if (bi === q.correct_index) b.classList.add("correct");
              else if (bi === ci) b.classList.add("incorrect");
            });
            explSlot.innerHTML = `
              <div class="explanation ${correct ? "correct" : "incorrect"}">
                <span class="explanation-label">${correct ? "Correct" : "Not quite"}</span>
                ${escapeHtml(q.explanation || "")}
              </div>
              <div class="flashcard-rating" style="margin-top: 12px;">
                <button class="rating-btn again" data-r="0">Again</button>
                <button class="rating-btn hard" data-r="1">Hard</button>
                <button class="rating-btn good" data-r="2">Good</button>
                <button class="rating-btn easy" data-r="3">Easy</button>
              </div>
            `;
            explSlot.querySelectorAll("[data-r]").forEach(b => {
              b.onclick = () => {
                api(`/api/lectures/${entry.lecture_id}/wrong-answers/${entry.entry.id}/rate`, {
                  method: "POST",
                  body: JSON.stringify({ rating: parseInt(b.dataset.r) }),
                }).catch(() => {});
                explSlot.innerHTML += `<div style="color: var(--sage-700); margin-top: 8px;">✓ Rescheduled</div>`;
              };
            });
          };
          choicesEl.appendChild(btn);
        });
        wrap.appendChild(card);
      });
    }

    $$(".weak-spot-item[data-sec]").forEach(item => {
      item.onclick = async () => {
        await openLecture(item.dataset.lec);
        openSection(parseInt(item.dataset.sec));
      };
    });
  } catch (e) { toast("Couldn't load cram: " + e.message, "error"); }
}

async function renderHistory() {
  state.view = { type: "history" };
  renderSidebar();
  const main = $("#main");
  try {
    const data = await api("/api/history?limit=100");
    main.innerHTML = `
      <div class="dashboard">
        <h2>History</h2>
        <p class="dashboard-sub">Your recent activity. Streak: <strong>${data.streak} day${data.streak === 1 ? "" : "s"}</strong></p>
        <div class="dashboard-section">
          <h3>Recent activity</h3>
          ${data.history.length === 0
            ? `<div class="empty-state">Nothing yet.</div>`
            : `<ul class="history-list">${data.history.map(h => `
                <li class="history-item">
                  <span class="history-time">${formatTime(h.ts)}</span>
                  <span class="history-kind">
                    <strong>${escapeHtml(historyTitle(h))}</strong>
                    <span>${escapeHtml(historySubtitle(h))}</span>
                  </span>
                </li>`).join("")}</ul>`
          }
        </div>
      </div>
    `;
  } catch (e) { toast("Couldn't load history: " + e.message, "error"); }
}

function historyTitle(event) {
  const detail = event.detail || {};
  const sectionLabel = event.section_title
    ? `section ${event.section_index}: ${event.section_title}`
    : detail.section
      ? `section ${detail.section}`
      : detail.section_index
        ? `section ${detail.section_index}`
        : "";
  const labels = {
    view_section: sectionLabel ? `Opened ${sectionLabel}` : "Opened section",
    confidence: `Rated confidence ${detail.rating || ""}`.trim(),
    generate_flashcards: sectionLabel ? `Generated flashcards for ${sectionLabel}` : "Generated flashcards",
    rate_flashcard: `Reviewed flashcard${detail.rating != null ? ` · rating ${detail.rating}` : ""}`,
    generate_clozes: sectionLabel ? `Generated clozes for ${sectionLabel}` : "Generated clozes",
    rate_cloze: `Reviewed cloze${detail.rating != null ? ` · rating ${detail.rating}` : ""}`,
    regenerate_reading: sectionLabel ? `Regenerated reading for ${sectionLabel}` : "Regenerated reading",
  };
  return labels[event.kind] || event.kind.replace(/_/g, " ");
}

function historySubtitle(event) {
  const parts = [];
  if (event.lecture_name) parts.push(event.lecture_name);
  if (event.exam_name) parts.push(event.exam_name);
  if ((event.detail || {}).card_id) parts.push(`card ${event.detail.card_id.slice(0, 8)}`);
  if ((event.detail || {}).cloze_id) parts.push(`cloze ${(event.detail || {}).cloze_id.slice(0, 8)}`);
  return parts.join(" · ");
}

// =============================================================================
// Modals — add lecture, add exam
// =============================================================================
function openModal(id) { $(`#${id}`).hidden = false; }
function closeModal(id) { $(`#${id}`).hidden = true; }

function bindClearableFileInputs(root = document) {
  $$("input[type='file']", root).forEach(input => {
    const clearBtn = root.querySelector(`[data-clear-file="${input.id}"]`);
    if (!clearBtn) return;
    const sync = () => { clearBtn.hidden = input.files.length === 0; };
    input.addEventListener("change", sync);
    clearBtn.onclick = () => {
      input.value = "";
      sync();
    };
    sync();
  });
}

function bindNetworkStatus() {
  networkState.online = navigator.onLine;
  window.addEventListener("online", () => {
    networkState.online = true;
    renderNetworkStatus();
    toast("Internet connection restored", "success");
  });
  window.addEventListener("offline", () => {
    networkState.online = false;
    renderNetworkStatus();
    toast("Offline: loaded pages stay visible, new AI calls may fail", "error");
  });
  setInterval(renderNetworkStatus, 1000);
  renderNetworkStatus();
}

function bindModals() {
  const librarySearch = $("#library-search");
  if (librarySearch) {
    librarySearch.value = state.searchQuery;
    librarySearch.oninput = async () => {
      state.searchQuery = librarySearch.value;
      if (!state.searchQuery.trim()) {
        state.pendingSearchHighlight = "";
        clearSearchHighlights();
      }
      await refreshSearchIndex();
      renderSidebar();
      if (state.view.type === "section" && state.currentStage === "reading") renderSection();
    };
  }

  const providerSelect = $("#provider-select");
  const modelSelect = $("#model-select");
  const anthropicField = $("#anthropic-key-field");
  const openaiField = $("#openai-key-field");
  const anthropicInput = $("#anthropic-key-input");
  const openaiInput = $("#openai-key-input");
  const rememberKey = $("#remember-provider-key");
  const clearKey = $("#clear-provider-key");
  const validateKey = $("#validate-provider-key");
  const anthropicToggle = $("#toggle-anthropic-key");
  const openaiToggle = $("#toggle-openai-key");
  let providerValidationTimer = null;

  function clearProviderValidationTimer() {
    if (providerValidationTimer) {
      clearTimeout(providerValidationTimer);
      providerValidationTimer = null;
    }
  }

  function queueProviderValidation(provider, apiKey) {
    clearProviderValidationTimer();
    if (!apiKey.trim() || provider !== getSelectedProvider()) return;
    providerValidationTimer = setTimeout(() => {
      if (provider === getSelectedProvider() && normalizeApiKeyForCompare(getProviderApiKey(provider)) === normalizeApiKeyForCompare(apiKey)) {
        validateProviderKey({ silent: true, renderMissing: false });
      }
    }, 900);
  }

  function populateModelSelect() {
    if (!modelSelect) return;
    const provider = getSelectedProvider();
    modelSelect.innerHTML = "";
    PROVIDER_MODELS[provider].forEach(model => {
      const opt = document.createElement("option");
      opt.value = model.id;
      opt.textContent = model.label;
      modelSelect.appendChild(opt);
    });
    modelSelect.value = getSelectedModel();
  }

  function currentProviderKeyInput() {
    return getSelectedProvider() === "openai" ? openaiInput : anthropicInput;
  }

  function syncProviderFields() {
    const provider = getSelectedProvider();
    if (providerSelect) providerSelect.value = provider;
    populateModelSelect();
    if (anthropicField) anthropicField.hidden = provider !== "anthropic";
    if (openaiField) openaiField.hidden = provider !== "openai";
    if (anthropicInput) anthropicInput.value = getAnthropicApiKey();
    if (openaiInput) openaiInput.value = getOpenAIApiKey();
    if (rememberKey) rememberKey.checked = isRememberingProviderApiKey(provider);
    if (clearKey) {
      const input = currentProviderKeyInput();
      clearKey.hidden = !input?.value.trim() && !getProviderApiKey(provider);
    }
    syncProviderWarning();
    syncProviderValidationFromCache();
  }

  $("#btn-ai-settings").onclick = () => {
    clearProviderValidationTimer();
    syncProviderFields();
    openModal("modal-ai-settings");
  };

  if (providerSelect) {
    providerSelect.value = getSelectedProvider();
    providerSelect.onchange = () => {
      clearProviderValidationTimer();
      setSelectedProvider(providerSelect.value);
      syncProviderFields();
      toast("Provider updated", "success");
    };
  }

  if (modelSelect) {
    populateModelSelect();
    modelSelect.onchange = () => {
      clearProviderValidationTimer();
      setSelectedModel(modelSelect.value);
      syncProviderValidationFromCache();
      toast("Model updated", "success");
    };
  }

  if (anthropicInput && openaiInput && rememberKey && clearKey && validateKey && anthropicToggle && openaiToggle) {
    const syncKeyControls = () => {
      const input = currentProviderKeyInput();
      clearKey.hidden = !input?.value.trim() && !getProviderApiKey();
    };
    syncProviderFields();
    syncKeyControls();

    const onKeyInput = input => {
      const provider = input === openaiInput ? "openai" : "anthropic";
      setProviderApiKey(provider, input.value, provider === getSelectedProvider() && rememberKey.checked);
      if (provider === getSelectedProvider()) syncProviderValidationFromCache();
      syncKeyControls();
      syncProviderWarning();
      queueProviderValidation(provider, input.value);
    };
    const onKeyChange = input => {
      clearProviderValidationTimer();
      const provider = input === openaiInput ? "openai" : "anthropic";
      setProviderApiKey(provider, input.value, provider === getSelectedProvider() && rememberKey.checked);
      if (provider === getSelectedProvider()) syncProviderValidationFromCache();
      syncKeyControls();
      syncProviderWarning();
      const providerName = provider === "openai" ? "OpenAI" : "Anthropic";
      toast(input.value.trim() ? `${providerName} key set` : `Using server ${providerName} key`, "success");
    };
    anthropicInput.oninput = () => onKeyInput(anthropicInput);
    openaiInput.oninput = () => onKeyInput(openaiInput);
    anthropicInput.onchange = () => onKeyChange(anthropicInput);
    openaiInput.onchange = () => onKeyChange(openaiInput);

    rememberKey.onchange = () => {
      clearProviderValidationTimer();
      const provider = getSelectedProvider();
      const input = currentProviderKeyInput();
      if (input?.value.trim()) {
        const previousKey = normalizeApiKeyForCompare(getProviderApiKey(provider));
        const nextKey = normalizeApiKeyForCompare(input.value);
        setProviderApiKey(provider, input.value, rememberKey.checked);
        if (previousKey !== nextKey) syncProviderValidationFromCache();
        toast(rememberKey.checked ? "Key remembered on this device" : "Key kept for this tab only", "success");
      }
    };
    clearKey.onclick = () => {
      clearProviderValidationTimer();
      const provider = getSelectedProvider();
      const input = currentProviderKeyInput();
      if (input) input.value = "";
      rememberKey.checked = false;
      setProviderApiKey(provider, "");
      syncProviderValidationFromCache();
      syncKeyControls();
      syncProviderWarning();
      toast(`${provider === "openai" ? "OpenAI" : "Anthropic"} key cleared`, "success");
    };
    validateKey.onclick = () => validateProviderKey();
    const bindReveal = (input, toggle) => {
      toggle.onclick = () => {
        const showing = input.type === "text";
        input.type = showing ? "password" : "text";
        toggle.classList.toggle("revealed", !showing);
        toggle.setAttribute("aria-label", showing ? "Show API key" : "Hide API key");
        toggle.title = showing ? "Show API key" : "Hide API key";
      };
    };
    bindReveal(anthropicInput, anthropicToggle);
    bindReveal(openaiInput, openaiToggle);
  }

  $("#btn-export-project").onclick = async () => {
    try {
      const project = await syncLocalProjectSnapshot();
      downloadJson(`studybuddy-${timestampForFilename()}.studybuddy.json`, project);
      toast("Project saved", "success");
    } catch (e) {
      const localProject = await getLocalProjectSnapshot().catch(() => null);
      if (!localProject) {
        toast("Couldn't save project: " + e.message, "error");
        return;
      }
      downloadJson(`studybuddy-${timestampForFilename()}.studybuddy.json`, localProject);
      toast("Saved local browser snapshot", "success");
    }
  };

  $("#btn-import-project").onclick = () => $("#project-import-file").click();
  $("#project-import-file").onchange = async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    if (!confirm("Import this StudyBuddy project? It will replace the current local library.")) return;
    try {
      const project = JSON.parse(await file.text());
      const res = await api("/api/project/import", {
        method: "POST",
        body: JSON.stringify(project),
      });
      if (ALLOWED_PROVIDERS.has(project.settings?.selected_provider)) {
        setSelectedProvider(project.settings.selected_provider);
        const providerSelect = $("#provider-select");
        if (providerSelect) providerSelect.value = project.settings.selected_provider;
      }
      if (ALLOWED_MODELS.has(project.settings?.selected_model)) {
        setSelectedModel(project.settings.selected_model);
        const modelSelect = $("#model-select");
        if (modelSelect) modelSelect.value = project.settings.selected_model;
      }
      await saveLocalProjectSnapshot(makeProjectSnapshot(res.library));
      await refreshLibrary();
      showWelcome();
      toast("Project imported", "success");
    } catch (err) {
      toast("Import failed: " + err.message, "error");
    }
  };

  $("#btn-add-exam").onclick = () => openModal("modal-add-exam");
  $("#btn-add-lecture").onclick = async () => {
    // Populate exam select
    const sel = $("#lecture-exam");
    const examNameField = $("#lecture-exam-name-field");
    const examNameInput = $("#lecture-exam-name");
    function syncExamNameField() {
      const creating = sel.value === "__new__";
      examNameField.hidden = !creating;
      examNameInput.required = creating;
      if (!creating) examNameInput.value = "";
    }

    sel.innerHTML = "";
    if (!state.library.exams.length) {
      sel.innerHTML = `<option value="__new__">Create a new exam</option>`;
    } else {
      for (const e of state.library.exams) {
        const opt = document.createElement("option");
        opt.value = e.id;
        opt.textContent = e.name;
        sel.appendChild(opt);
      }
      const newOpt = document.createElement("option");
      newOpt.value = "__new__";
      newOpt.textContent = "+ Create new exam";
      sel.appendChild(newOpt);
    }
    sel.onchange = () => {
      syncExamNameField();
      const creating = sel.value === "__new__";
      if (creating) setTimeout(() => examNameInput.focus(), 0);
    };
    syncExamNameField();
    $("#submit-lecture").disabled = false;
    $("#progress-note").hidden = true;
    bindClearableFileInputs($("#modal-add-lecture"));
    openModal("modal-add-lecture");
  };
  $$("[data-close]").forEach(el => el.onclick = () => {
    clearProviderValidationTimer();
    el.closest(".modal-backdrop").hidden = true;
  });
  $("#form-add-exam").onsubmit = async (e) => {
    e.preventDefault();
    const name = $("#exam-name").value.trim();
    if (!name) return;
    try {
      await api("/api/exams", { method: "POST", body: JSON.stringify({ name }) });
      $("#exam-name").value = "";
      closeModal("modal-add-exam");
      await refreshLibrary();
      toast("Exam created", "success");
    } catch (err) { toast(err.message, "error"); }
  };
  $("#form-add-lecture").onsubmit = async (e) => {
    e.preventDefault();
    const examId = $("#lecture-exam").value;
    const examName = $("#lecture-exam-name").value.trim();
    const lectureName = $("#lecture-name").value.trim();
    const creatingExam = examId === "__new__";
    if ((!creatingExam && !examId) || (creatingExam && !examName) || !lectureName) {
      toast("Need an exam and lecture name", "error");
      return;
    }

    const fd = new FormData();
    if (creatingExam) fd.append("exam_name", examName);
    else fd.append("exam_id", examId);
    fd.append("lecture_name", lectureName);
    fd.append("provider", getSelectedProvider());
    fd.append("model", getSelectedModel());
    const videoSource = $("#video-source").value.trim();
    const videoFile = $("#video-file").files[0];
    const notesFile = $("#notes-file").files[0];
    const notesText = $("#notes-text").value.trim();
    if (!videoSource && !videoFile) {
      toast("Add a YouTube URL, paste a transcript, or upload a transcript/video/PPTX file", "error");
      return;
    }
    await refreshSettings();
    if (!hasProviderKeyAvailable()) {
      const providerName = getSelectedProvider() === "openai" ? "OpenAI" : "Anthropic";
      toast(`Add a ${providerName} key in AI Provider Settings before generating`, "error");
      syncProviderWarning();
      openModal("modal-ai-settings");
      return;
    }
    const providerValidation = await validateProviderKey({ silent: true });
    if (!providerValidation.ok) {
      toast(providerValidation.message, "error");
      openModal("modal-ai-settings");
      return;
    }
    if (videoSource) fd.append("video_source", videoSource);
    if (videoFile) fd.append("video_file", videoFile);
    if (notesFile) fd.append("notes_file", notesFile);
    if (notesText) fd.append("notes_text", notesText);
    if (getSelectedProvider() === "openai" && getOpenAIApiKey()) fd.append("openai_api_key", getOpenAIApiKey());
    if (getSelectedProvider() === "anthropic" && getAnthropicApiKey()) fd.append("anthropic_api_key", getAnthropicApiKey());

    const submitBtn = $("#submit-lecture");
    const progressNote = $("#progress-note");
    submitBtn.disabled = true;
    progressNote.hidden = false;
    progressNote.querySelector("span").textContent = "Uploading materials...";
    try {
      const started = await api("/api/lectures", { method: "POST", body: fd });
      const res = started.job_id
        ? await waitForJob(started.job_id, job => {
            progressNote.querySelector("span").textContent = describeJobProgress(job);
          })
        : started;
      closeModal("modal-add-lecture");
      $("#form-add-lecture").reset();
      await refreshLibrary();
      await openLecture(res.lecture.id);
      toast("Lecture generated", "success");
    } catch (err) {
      toast("Failed: " + err.message, "error");
    } finally {
      submitBtn.disabled = false;
      progressNote.hidden = true;
    }
  };
}

// =============================================================================
// Utilities
// =============================================================================
function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatProse(s) {
  return escapeHtml(s).split(/\n\s*\n/).map(p => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) {
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function showInlineLoader(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<div style="display:flex;gap:10px;align-items:center"><div class="spinner"></div>${escapeHtml(text)}</div>`;
  document.body.appendChild(el);
  return el;
}

// =============================================================================
// Init
// =============================================================================
async function init() {
  bindNetworkStatus();
  bindModals();
  await refreshSettings();
  await refreshLibrary();
  showWelcome();
}
init();
