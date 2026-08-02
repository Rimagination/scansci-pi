const state = {
  workspace: null,
  notebook: null,
  settings: null,
  presets: { providers: [], local_models: [] },
  localModelMarket: { installed: [], catalog: [], source: "", query: "", loading: false },
  localModelInstall: { jobs: [], active: null },
  localRuntime: { installed: false, install_available: false, mode: "missing" },
  downloadStatusError: "",
  onboardingOpen: false,
  onboardingStep: "resources",
  onboardingPersisting: false,
  capabilities: null,
  activeView: "home",
  activeMode: "tools",
  activeSettings: "general",
  activeExtensions: "skills",
  extensionDetail: null,
  composerImages: { home: [], chat: [] },
  composerSources: { home: [], chat: [] },
  selectedProviderId: "",
  providerQuery: "",
  modelQuery: "",
  draggedProviderId: "",
  editingModelIndex: -1,
  sourceQuery: "",
  historyQuery: "",
  historyCollapsed: window.localStorage.getItem("scansci.history.collapsed") === "true",
  historyView: window.localStorage.getItem("scansci.history.view") === "archived" ? "archived" : "active",
  historyMenuRunId: "",
  historySearchOpen: false,
  directMessages: [],
  runs: [],
  activeTaskId: "",
  sessionId: window.localStorage.getItem("scansci.active.session") || null,
  sessionTokens: 0,
  contextUsagePercent: 0,
  sessionStats: null,
  contextStatsOpen: false,
  streaming: false,
  conversationAutoFollow: true,
  activeStreamRunId: "",
  toolProgress: null,
  reviewDocument: null,
  contextPanel: "sources",
  contextPanelPreset: "research",
  contextPanelCollapsed: window.localStorage.getItem("scansci.context-panel.collapsed") !== "false",
  evidenceReturnPanel: "sources",
  activeEvidence: null,
  evidencePanelExpanded: false,
  contextPanelWidth: Math.max(280, Number(window.localStorage.getItem("scansci.context-panel.width")) || 335),
  expandedEvidencePanelWidth: Math.max(420, Number(window.localStorage.getItem("scansci.evidence-panel.width")) || 560),
  citationPreviewTimer: 0,
  extensions: { skills: null, libraryPath: "", marketplace: [], marketplaceOffline: false, marketplaceLoaded: false },
  marketplaceQuery: "",
  mcpMarketplace: { items: [], disciplines: [], source: null, synced_at: "", cached_count: 0, loaded: false, loading: false },
  mcpMarketplaceQuery: "",
  mcpMarketplaceDiscipline: "all",
  mcpMarketplaceSort: "hot",
  mcpMarketplaceTab: "public",
  mcpManualOpen: false,
  mcpCreateMode: "",
  libraryImportKind: "folder",
  libraryImportGuided: false,
  libraryImportJob: null,
  libraryImportAppliedJobId: "",
  knowledgeSubscope: null,
  knowledgeScopeIds: [],
  knowledgePreviewSourceId: "",
  knowledgeQuery: "",
  knowledgeSearchOpen: false,
  knowledgeVisibleLimit: 200,
  knowledgeIndexStatuses: {},
  knowledgeScopeRefreshing: false,
  knowledgePreviewCollapsed: window.localStorage.getItem("scansci.knowledge.preview.collapsed") === "true",
  knowledgeTreeExpanded: window.localStorage.getItem("scansci.knowledge.tree.expanded") !== "false",
  downloadStrategy: ["oa_first", "gray_oa", "legal_only"].includes(window.localStorage.getItem("scansci.download.strategy"))
    ? window.localStorage.getItem("scansci.download.strategy")
    : "oa_first",
  downloadStrategyOpen: false,
  pendingBatchIdentifiers: [],
  pendingBatchFilename: "",
  useTor: false,
  torRotateEvery: 3,
  torTransport: "snowflake",
  torTransportOpen: false,
  slideTemplates: [],
  slideTemplatesAvailable: false,
  slideTemplatesPlugin: {},
  selectedSlideTemplateId: window.localStorage.getItem("scansci.slides.template") || "",
  previewSlideTemplateId: "",
  previewSlidePage: "",
  inlineSlidePreviewTemplateId: "",
  inlineSlidePreviewPage: "",
  slideTemplateQuery: "",
  lastRunRenderKey: "",
  sidebarCollapsed: window.localStorage.getItem("scansci.sidebar.collapsed") === "true",
  sidebarWidth: Math.max(260, Math.min(520, Number(window.localStorage.getItem("scansci.sidebar.width")) || 352)),
  thinkingLevel: ["auto", "low", "medium", "high"].includes(window.localStorage.getItem("scansci.thinking.level"))
    ? window.localStorage.getItem("scansci.thinking.level")
    : "auto",
  webSearchMode: ["auto", "on", "off"].includes(window.localStorage.getItem("scansci.web-search.mode"))
    ? window.localStorage.getItem("scansci.web-search.mode")
    : "auto",
  researchWorkflow: "",
  // “证据综述” is a delivery choice inside evidence Q&A, not a new
  // restrictive top-level mode. Normal free-form use remains untouched.
  evidenceOutputMode: "answer",
  academicSearchPlanDraft: null,
  profileAvatar: window.localStorage.getItem("scansci.profile.avatar") === "female" ? "female" : "male",
  navigationHistory: [{ view: "home", mode: "tools", settings: "general", task: "" }],
  navigationIndex: 0,
  update: {
    state: "checking",
    available: false,
    current_version: "",
    latest_version: "",
    release_title: "ScanSci",
    release_notes: [],
    message: "正在检查更新",
    checked_at: "",
  },
  updateCardOpen: false,
  updateNative: false,
  autoCheckUpdates: window.localStorage.getItem("scansci.update.auto-check") !== "false",
};

const byId = (id) => document.getElementById(id);
const sourceList = byId("sourceList");
let directConversationRenderFrame = 0;
let activeDirectChatController = null;
let confirmDialogResolve = null;
let confirmDialogPreviousFocus = null;
let localModelInstallPollTimer = 0;
let localRuntimeInstallPollTimer = 0;
let notionWizardResolve = null;

const applicationCopy = Object.freeze({
  "zh-CN": {
    brand: "ScanSci | 搜索科学",
    newResearch: "新建研究",
    knowledgeBase: "知识库",
    extensions: "插件和技能",
    mcpServers: "MCP 服务器",
    history: "历史对话",
    localWorkspace: "本地工作区",
    backToWorkspace: "返回工作区",
    general: "常规",
    resources: "资源配置",
    modelServices: "模型服务",
    localModels: "本地模型",
    documentProcessing: "文档处理",
    about: "关于搜索科学",
    settingsLocal: "配置仅保存在此电脑",
    settingsTitle: "设置",
    settingsDescription: "此设备上的工作区与应用设置。",
    localSaved: "本地保存",
    appearanceTitle: "界面与外观",
    appearanceDescription: "语言、明暗与强调色会立即预览，并仅保存在这台电脑上。",
    interfaceLanguage: "界面语言",
    interfaceLanguageHint: "主要导航与设置会立即切换；研究材料与第三方内容保持原文。",
    appearanceTheme: "外观主题",
    appearanceThemeHint: "可跟随系统，也可固定为浅色或深色。",
    accentColor: "强调色",
    accentColorHint: "用于选中状态、进度和主要操作。",
    system: "跟随系统",
    light: "浅色",
    dark: "深色",
    systemDetail: "自动",
    lightDetail: "浅色",
    darkDetail: "深色",
    jade: "松绿",
    ocean: "深海",
    plum: "墨紫",
    amber: "琥珀",
    saveAppearance: "保存界面偏好",
    appearanceSaved: "界面偏好已保存",
    currentWorkspace: "当前工作区",
    noWorkspace: "未打开资料库",
    sources: "资料来源",
    citations: "已保存引文",
    layers: "标注图层",
    currentModel: "当前模型",
    modelKeyNote: "模型密钥不会写入工作区文件。",
    runtimeStatus: "运行状态",
    readyTools: "个工具可用。模型与本地模型的配置可分别在对应页面查看。",
  },
  en: {
    brand: "ScanSci | Research Science",
    newResearch: "New research",
    knowledgeBase: "Knowledge",
    extensions: "Plugins & skills",
    mcpServers: "MCP servers",
    history: "History",
    localWorkspace: "Local workspace",
    backToWorkspace: "Back to workspace",
    general: "General",
    resources: "Resources",
    modelServices: "Model services",
    localModels: "Local models",
    documentProcessing: "Documents",
    about: "About ScanSci",
    settingsLocal: "Preferences stay on this computer",
    settingsTitle: "Settings",
    settingsDescription: "Workspace and application preferences for this device.",
    localSaved: "Saved locally",
    appearanceTitle: "Language & appearance",
    appearanceDescription: "Preview language, light and dark modes, and accent colour instantly. They stay on this computer.",
    interfaceLanguage: "Interface language",
    interfaceLanguageHint: "Primary navigation and settings switch immediately; research material and third-party content stay in their original language.",
    appearanceTheme: "Appearance",
    appearanceThemeHint: "Follow your system or keep ScanSci light or dark.",
    accentColor: "Accent colour",
    accentColorHint: "Used for selected states, progress, and primary actions.",
    system: "System",
    light: "Light",
    dark: "Dark",
    systemDetail: "Auto",
    lightDetail: "Light",
    darkDetail: "Dark",
    jade: "Jade",
    ocean: "Ocean",
    plum: "Plum",
    amber: "Amber",
    saveAppearance: "Save preferences",
    appearanceSaved: "Appearance preferences saved",
    currentWorkspace: "Current workspace",
    noWorkspace: "No knowledge library open",
    sources: "Sources",
    citations: "Saved citations",
    layers: "Annotation layers",
    currentModel: "Current model",
    modelKeyNote: "Model credentials are never written to workspace files.",
    runtimeStatus: "Runtime status",
    readyTools: "tools available. Configure cloud and local models on their respective pages.",
  },
});

function appearancePreferences() {
  const source = state.settings?.appearance || {};
  return {
    locale: source.locale === "en" ? "en" : "zh-CN",
    theme: ["system", "light", "dark"].includes(source.theme) ? source.theme : "system",
    accent: ["jade", "ocean", "plum", "amber"].includes(source.accent) ? source.accent : "jade",
  };
}

function copy(key) {
  const locale = appearancePreferences().locale;
  return applicationCopy[locale]?.[key] || applicationCopy["zh-CN"][key] || key;
}

function resolvedTheme(preference = appearancePreferences().theme) {
  if (preference !== "system") return preference;
  return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
}

function applyAppearancePreferences() {
  const preferences = appearancePreferences();
  const root = document.documentElement;
  const theme = resolvedTheme(preferences.theme);
  root.lang = preferences.locale;
  root.dataset.theme = theme;
  root.dataset.themePreference = preferences.theme;
  root.dataset.accent = preferences.accent;
  root.style.colorScheme = theme;
  document.title = copy("brand");
  document.querySelector('meta[name="application-name"]')?.setAttribute("content", copy("brand"));
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const value = copy(element.dataset.i18n || "");
    if (value) element.textContent = value;
  });
  refreshEvidenceReaderTheme();
}

function collectAppearanceForm() {
  const form = byId("generalPreferencesForm");
  if (!form || !state.settings) return appearancePreferences();
  state.settings.appearance = {
    locale: form.elements["appearance-locale"]?.value === "en" ? "en" : "zh-CN",
    theme: ["system", "light", "dark"].includes(form.elements["appearance-theme"]?.value) ? form.elements["appearance-theme"].value : "system",
    accent: ["jade", "ocean", "plum", "amber"].includes(form.elements["appearance-accent"]?.value) ? form.elements["appearance-accent"].value : "jade",
  };
  applyAppearancePreferences();
  return state.settings.appearance;
}

window.matchMedia?.("(prefers-color-scheme: dark)")?.addEventListener?.("change", () => {
  if (appearancePreferences().theme === "system") applyAppearancePreferences();
});

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.error?.message || `Request failed (${response.status})`);
  return payload;
}

async function streamChat(payload, onEvent, { signal } = {}) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error?.error?.message || `Request failed (${response.status})`);
  }
  if (!response.body) throw new Error("This browser does not support streaming responses.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const dispatch = (frame) => {
    let eventType = "message";
    const dataLines = [];
    frame.split(/\r?\n/).forEach((line) => {
      if (line.startsWith("event:")) eventType = line.slice(6).trim() || "message";
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    });
    if (!dataLines.length) return;
    const event = JSON.parse(dataLines.join("\n"));
    if (eventType === "error" || eventType === "RUN_ERROR") {
      const failure = new Error(event.message || "The streaming response could not be completed.");
      failure.code = event.code || "chat_failed";
      failure.failure = event.failure || null;
      throw failure;
    }
    onEvent(eventType, event);
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let match = buffer.match(/\r?\n\r?\n/);
      while (match && match.index !== undefined) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        dispatch(frame);
        match = buffer.match(/\r?\n\r?\n/);
      }
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
  } finally {
    reader.releaseLock();
  }
}

function scheduleDirectConversationRender() {
  if (directConversationRenderFrame) return;
  directConversationRenderFrame = window.requestAnimationFrame(() => {
    directConversationRenderFrame = 0;
    renderDirectConversation();
  });
}

const conversationFollowThreshold = 72;

function conversationScrollSnapshot() {
  const answerArea = byId("answerArea");
  if (!answerArea) return { top: 0, shouldFollow: true };
  const distanceFromBottom = answerArea.scrollHeight - answerArea.scrollTop - answerArea.clientHeight;
  const shouldFollow = distanceFromBottom < 72;
  const followsThreshold = state.conversationAutoFollow && distanceFromBottom < conversationFollowThreshold;
  return {
    top: answerArea.scrollTop,
    shouldFollow: shouldFollow && followsThreshold,
  };
}

function updateConversationScrollAffordance() {
  const answerArea = byId("answerArea");
  const button = byId("conversationJumpLatest");
  if (!answerArea || !button) return;
  const distanceFromBottom = Math.max(0, answerArea.scrollHeight - answerArea.scrollTop - answerArea.clientHeight);
  button.hidden = state.activeView !== "conversation"
    || state.conversationAutoFollow
    || distanceFromBottom < conversationFollowThreshold;
}

function restoreConversationScroll(snapshot, { forceFollow = false } = {}) {
  const answerArea = byId("answerArea");
  if (!answerArea) return;
  if (forceFollow || snapshot?.shouldFollow) {
    answerArea.scrollTop = answerArea.scrollHeight;
    state.conversationAutoFollow = true;
  } else {
    const maximum = Math.max(0, answerArea.scrollHeight - answerArea.clientHeight);
    answerArea.scrollTop = Math.min(Math.max(0, Number(snapshot?.top || 0)), maximum);
  }
  updateConversationScrollAffordance();
}

function followLatestConversationMessage({ smooth = false } = {}) {
  const answerArea = byId("answerArea");
  if (!answerArea) return;
  state.conversationAutoFollow = true;
  answerArea.scrollTo({ top: answerArea.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  updateConversationScrollAffordance();
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character]));
}

const localResourceKinds = {
  pdf: new Set(["pdf"]),
  spreadsheet: new Set(["xls", "xlsx", "xlsm", "xlsb", "csv", "tsv", "ods"]),
  document: new Set(["doc", "docx", "odt", "rtf"]),
  presentation: new Set(["ppt", "pptx", "odp", "key"]),
  image: new Set(["png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "tif", "tiff", "heic"]),
  markdown: new Set(["md", "markdown"]),
  text: new Set(["txt", "log"]),
  archive: new Set(["zip", "7z", "rar", "tar", "gz", "bz2", "xz"]),
  audio: new Set(["mp3", "wav", "m4a", "flac", "aac", "ogg"]),
  video: new Set(["mp4", "mov", "mkv", "avi", "webm", "wmv"]),
  data: new Set(["json", "jsonl", "xml", "yaml", "yml", "parquet", "feather", "sqlite", "sqlite3", "db"]),
  code: new Set(["py", "r", "rmd", "ipynb", "js", "mjs", "ts", "tsx", "jsx", "html", "css", "sql", "sh", "ps1"]),
};

function localResourceExtension(path = "") {
  const leaf = localPathLeaf(String(path).replace(/[\\/]+$/, ""));
  const match = leaf.match(/\.([^.\\/]+)$/);
  return match ? match[1].toLowerCase() : "";
}

function localResourceKind(path = "", { folder = false } = {}) {
  const value = String(path || "").trim();
  const extension = localResourceExtension(value);
  if (folder || /[\\/]$/.test(value) || !extension) return "folder";
  return Object.entries(localResourceKinds).find(([, extensions]) => extensions.has(extension))?.[0] || "file";
}

function localResourceIcon(kind = "file") {
  const icons = {
    folder: "folder-open",
    pdf: "file-text",
    spreadsheet: "file-spreadsheet",
    document: "file-text",
    presentation: "presentation",
    image: "image",
    markdown: "file-text",
    text: "file-text",
    archive: "archive",
    audio: "file-audio",
    video: "file-video",
    data: "database",
    code: "file-code",
    file: "file",
  };
  return icons[kind] || "file";
}

function renderAssistantInline(value = "") {
  const localResources = [];
  const rememberLocalResource = (path, label = "") => {
    const cleanPath = String(path || "").trim().replace(/^[<"'“‘]+|[>"'”’]+$/g, "");
    if (!/^(?:[a-zA-Z]:[\\/]|\\\\)/.test(cleanPath)) return path;
    const token = `SCANSCI_LOCAL_RESOURCE_${localResources.length}_TOKEN`;
    localResources.push({ token, path: cleanPath, label: String(label || "").trim() });
    return token;
  };
  let source = String(value);
  source = source.replace(/\[([^\]]+)\]\(((?:[a-zA-Z]:[\\/]|\\\\)[^)]+)\)/g, (_match, label, path) => rememberLocalResource(path, label));
  source = source.replace(/`((?:[a-zA-Z]:[\\/]|\\\\)[^`\r\n]+)`/g, (_match, path) => rememberLocalResource(path));
  source = source.replace(/(["“‘])((?:[a-zA-Z]:[\\/]|\\\\)[^"”’\r\n]+)(["”’])/g, (_match, _open, path) => rememberLocalResource(path));
  source = source.replace(/(^|[^a-zA-Z0-9])((?:[a-zA-Z]:[\\/]|\\\\)[^\s<>"'`，。；、！？）》】}]+)/g, (_match, prefix, path) => {
    const cleanPath = path.replace(/[),.;:]+$/g, "");
    return `${prefix}${rememberLocalResource(cleanPath)}${path.slice(cleanPath.length)}`;
  });
  let markup = escapeHtml(source)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  localResources.forEach(({ token, path, label }) => {
    const folder = localResourceKind(path) === "folder";
    markup = markup.replace(token, localFileLinkMarkup(path, label || localPathLeaf(path), { folder, inline: true }));
  });
  return markup;
}

function renderAssistantContent(value = "") {
  const lines = String(value).replace(/\r\n/g, "\n").split("\n");
  const output = [];
  let listType = "";
  let paragraph = [];
  let quote = [];
  let code = null;
  const flushParagraph = () => {
    if (!paragraph.length) return;
    output.push(`<p>${renderAssistantInline(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`);
    paragraph = [];
  };
  const flushQuote = () => {
    if (!quote.length) return;
    output.push(`<blockquote>${renderAssistantContent(quote.join("\n"))}</blockquote>`);
    quote = [];
  };
  const closeList = () => {
    if (!listType) return;
    output.push(`</${listType}>`);
    listType = "";
  };
  const isTableRow = (line) => /^\s*\|?.+\|.+\|?\s*$/.test(line);
  const isTableDivider = (line) => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const splitTableRow = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  const renderTable = (rows) => {
    if (rows.length < 2 || !isTableDivider(rows[1])) return false;
    const header = splitTableRow(rows[0]);
    const divider = splitTableRow(rows[1]);
    if (!header.length || divider.length !== header.length) return false;
    const body = rows.slice(2).map(splitTableRow).filter((row) => row.length === header.length);
    const cells = (row, tag) => row.map((cell) => `<${tag}>${renderAssistantInline(cell)}</${tag}>`).join("");
    output.push(`<div class="assistant-table-wrap"><table class="assistant-table"><thead><tr>${cells(header, "th")}</tr></thead><tbody>${body.map((row) => `<tr>${cells(row, "td")}</tr>`).join("")}</tbody></table></div>`);
    return true;
  };
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (code) {
      if (line.trim().startsWith("```")) {
        output.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
        code = null;
      } else code.push(line);
      continue;
    }
    if (/^\s*```/.test(line)) {
      flushParagraph(); flushQuote(); closeList(); code = [];
      continue;
    }
    if (isTableRow(line) && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      flushParagraph(); flushQuote(); closeList();
      const rows = [line];
      index += 1;
      rows.push(lines[index]);
      while (index + 1 < lines.length && isTableRow(lines[index + 1]) && !isTableDivider(lines[index + 1])) {
        index += 1;
        rows.push(lines[index]);
      }
      if (!renderTable(rows)) paragraph.push(...rows);
      continue;
    }
    const quoteLine = line.match(/^\s*>\s?(.*)$/);
    if (quoteLine) {
      flushParagraph(); closeList(); quote.push(quoteLine[1]);
      continue;
    }
    if (quote.length) flushQuote();
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (/^\s*(?:---+|\*\s*\*\s*\*|___+)\s*$/.test(line)) {
      flushParagraph(); closeList(); output.push("<hr>");
    } else if (heading) {
      flushParagraph(); closeList();
      const level = Math.min(4, heading[1].length + 1);
      output.push(`<h${level}>${renderAssistantInline(heading[2])}</h${level}>`);
    } else if (unordered || ordered) {
      flushParagraph();
      const nextType = unordered ? "ul" : "ol";
      if (listType !== nextType) { closeList(); listType = nextType; output.push(`<${listType}>`); }
      output.push(`<li>${renderAssistantInline((unordered || ordered)[1])}</li>`);
    } else if (!line.trim()) {
      flushParagraph(); closeList();
    } else {
      closeList(); paragraph.push(line);
    }
  }
  flushParagraph(); flushQuote(); closeList();
  if (code) output.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
  return output.join("");
}

function extractSkillMentions(text = "") {
  return [...String(text).matchAll(/(?:^|\s)\$([a-zA-Z0-9._-]+)/g)].map((match) => match[1]);
}

function enabledSkillCatalog() {
  return (state.extensions.skills || []).filter((item) => item.available !== false && item.enabled !== false && !item.uninstalled);
}

function currentSkillMention(input) {
  if (!input) return null;
  const cursor = Number.isInteger(input.selectionStart) ? input.selectionStart : input.value.length;
  const before = input.value.slice(0, cursor);
  const match = before.match(/(^|\s)\$([a-zA-Z0-9._-]*)$/);
  if (!match) return null;
  return { query: match[2].toLowerCase(), start: cursor - match[2].length - 1, end: cursor };
}

function closeSkillSuggestions() {
  document.querySelectorAll(".skill-suggestions").forEach((item) => item.remove());
}

function closeContextUsagePopovers() {
  state.contextStatsOpen = false;
  document.querySelectorAll("[data-context-usage].is-open").forEach((control) => {
    control.classList.remove("is-open");
    control.querySelector(".context-usage-trigger")?.setAttribute("aria-expanded", "false");
  });
}

function toggleContextUsagePopover(element) {
  const control = element.closest("[data-context-usage]");
  if (!control) return;
  const willOpen = !control.classList.contains("is-open");
  closeContextUsagePopovers();
  if (!willOpen) return;
  state.contextStatsOpen = true;
  control.classList.add("is-open");
  element.setAttribute("aria-expanded", "true");
  renderContextUsage();
}

function renderSkillSuggestions(input) {
  closeSkillSuggestions();
  const mention = currentSkillMention(input);
  if (!mention) return;
  const candidates = enabledSkillCatalog().filter((item) => {
    const searchable = `${item.id || ""} ${item.name || ""} ${item.description || ""}`.toLowerCase();
    return !mention.query || searchable.includes(mention.query);
  }).slice(0, 8);
  if (!candidates.length) return;
  const popover = document.createElement("div");
  popover.className = "skill-suggestions";
  popover.setAttribute("role", "listbox");
  popover.innerHTML = `<div class="skill-suggestions-label">选择 Skill</div>${candidates.map((item, index) => `<button type="button" class="skill-suggestion ${index === 0 ? "is-active" : ""}" data-action="select-skill-suggestion" data-skill-id="${escapeHtml(item.id)}" data-input-id="${escapeHtml(input.id)}" role="option" aria-selected="${index === 0 ? "true" : "false"}"><span><strong>$${escapeHtml(item.id)}</strong><small>${escapeHtml(item.description || item.name || "已安装 Skill")}</small></span>${item.builtin ? '<em>内置</em>' : ""}</button>`).join("")}`;
  input.closest("form")?.appendChild(popover);
}

function selectSkillSuggestion(input, skillId) {
  const mention = currentSkillMention(input);
  if (!mention || !skillId) return;
  input.setRangeText(`$${skillId} `, mention.start, mention.end, "end");
  closeSkillSuggestions();
  input.focus();
}

function moveSkillSuggestion(direction) {
  const options = [...document.querySelectorAll(".skill-suggestion")];
  if (!options.length) return false;
  const current = Math.max(0, options.findIndex((item) => item.classList.contains("is-active")));
  const next = (current + direction + options.length) % options.length;
  options.forEach((item, index) => {
    item.classList.toggle("is-active", index === next);
    item.setAttribute("aria-selected", String(index === next));
  });
  return true;
}

// A local adapter for the official Lucide SVG paths used by ScanSci. Keeping
// the small used subset in the application makes the desktop build
// deterministic: no icon font, CDN, or operating-system fallback is needed.
const uiIconPaths = {
  "circle-plus": '<circle cx="12" cy="12" r="8.5"></circle><path d="M12 8v8M8 12h8"></path>',
  library: '<path d="M4.5 4.5h15v15h-15z"></path><path d="M8.5 4.5v15M12 9h4M12 12h4"></path>',
  wand: '<path d="m6 18 10.5-10.5M13.5 4.5l.7 1.8L16 7l-1.8.7-.7 1.8-.7-1.8L11 7l1.8-.7.7-1.8ZM5 6l.5 1.3L7 8l-1.5.7L5 10l-.5-1.3L3 8l1.5-.7L5 6ZM18 15l.5 1.3L20 17l-1.5.7L18 19l-.5-1.3L16 17l1.5-.7L18 15Z"></path>',
  puzzle: '<path d="M9 4.5H6.5a2 2 0 0 0-2 2V9h2a2 2 0 1 1 0 4h-2v2.5a2 2 0 0 0 2 2H9v-2a2 2 0 1 1 4 0v2h2.5a2 2 0 0 0 2-2V13h-2a2 2 0 1 1 0-4h2V6.5a2 2 0 0 0-2-2H13v2a2 2 0 1 1-4 0v-2Z"></path>',
  folder: '<path d="M3.5 6.5h6l2 2h9v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2Z"></path>',
  // Lucide "settings" — kept verbatim so the application settings affordance
  // is the familiar upstream icon rather than a hand-drawn approximation.
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.09a2 2 0 0 1-1-1.74v-.51a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2Z"></path><circle cx="12" cy="12" r="3"></circle>',
  "panel-left": '<rect x="3.5" y="4" width="17" height="16" rx="2.5"></rect><path d="M10 4v16"></path>',
  "panel-right": '<rect x="3.5" y="4" width="17" height="16" rx="2.5"></rect><path d="M14 4v16"></path>',
  "arrow-left": '<path d="m11 6-6 6 6 6M5.5 12h13"></path>',
  "arrow-right": '<path d="m13 6 6 6-6 6M18.5 12h-13"></path>',
  "chevron-down": '<path d="m7 9 5 5 5-5"></path>',
  "chevron-right": '<path d="m9 7 5 5-5 5"></path>',
  plus: '<path d="M12 5v14M5 12h14"></path>',
  minus: '<path d="M5 12h14"></path>',
  check: '<path d="m5.5 12 4.1 4 8.9-8.5"></path>',
  x: '<path d="m7 7 10 10M17 7 7 17"></path>',
  refresh: '<path d="M19 8.5A7.5 7.5 0 1 0 19.5 14"></path><path d="M19.5 4.5v4.8h-4.8"></path>',
  "triangle-alert": '<path d="m21.7 18.2-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-2.8Z"></path><path d="M12 9v4M12 17h.01"></path>',
  "loader-circle": '<path d="M12 3a9 9 0 1 0 9 9"></path>',
  "map-pin": '<path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"></path><circle cx="12" cy="10" r="2.5"></circle>',
  "git-branch": '<circle cx="6" cy="5" r="2"></circle><circle cx="18" cy="6" r="2"></circle><circle cx="6" cy="19" r="2"></circle><path d="M6 7v10M8 11h4a6 6 0 0 0 6-3"></path>',
  send: '<path d="M12 20V4"></path><path d="m6 10 6-6 6 6"></path>',
  file: '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"></path><path d="M14 2v5a1 1 0 0 0 1 1h5"></path>',
  "file-text": '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"></path><path d="M14 2v5a1 1 0 0 0 1 1h5"></path><path d="M10 9H8"></path><path d="M16 13H8"></path><path d="M16 17H8"></path>',
  "file-spreadsheet": '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"></path><path d="M14 2v5a1 1 0 0 0 1 1h5"></path><path d="M8 13h2"></path><path d="M14 13h2"></path><path d="M8 17h2"></path><path d="M14 17h2"></path>',
  "file-audio": '<path d="M4 6.835V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.706.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2h-.343"></path><path d="M14 2v5a1 1 0 0 0 1 1h5"></path><path d="M2 19a2 2 0 0 1 4 0v1a2 2 0 0 1-4 0v-4a6 6 0 0 1 12 0v4a2 2 0 0 1-4 0v-1a2 2 0 0 1 4 0"></path>',
  "file-video": '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"></path><path d="M14 2v5a1 1 0 0 0 1 1h5"></path><path d="M15.033 13.44a.647.647 0 0 1 0 1.12l-4.065 2.352a.645.645 0 0 1-.968-.56v-4.704a.645.645 0 0 1 .967-.56z"></path>',
  "file-code": '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"></path><path d="M14 2v5a1 1 0 0 0 1 1h5"></path><path d="M10 12.5 8 15l2 2.5"></path><path d="m14 12.5 2 2.5-2 2.5"></path>',
  "file-plus": '<path d="M6 3.5h7l4.5 4.5v12H6z"></path><path d="M13 3.5V8h4.5M11.5 12v5M9 14.5h5"></path>',
  "folder-open": '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"></path>',
  image: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><circle cx="9" cy="9" r="2"></circle><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"></path>',
  book: '<path d="M4.5 5.5A2.5 2.5 0 0 1 7 3h11v16H7a2.5 2.5 0 0 0-2.5 2.5v-16Z"></path><path d="M4.5 18.5A2.5 2.5 0 0 1 7 16h11"></path>',
  "message-circle": '<path d="M19.5 11.5a7.5 7.5 0 0 1-8 7.5 8.4 8.4 0 0 1-3.5-.8L4.5 19l.9-3a7.5 7.5 0 1 1 14.1-4.5Z"></path>',
  link: '<path d="M10 13.8 8.2 15.6a3.4 3.4 0 1 1-4.8-4.8l3-3a3.4 3.4 0 0 1 4.8 0"></path><path d="m14 10.2 1.8-1.8a3.4 3.4 0 1 1 4.8 4.8l-3 3a3.4 3.4 0 0 1-4.8 0"></path><path d="m8.5 15.5 7-7"></path>',
  pen: '<path d="m5 19 1.4-4.5L15.8 5a2.1 2.1 0 0 1 3 3l-9.4 9.5L5 19Z"></path><path d="m13.8 7 3.2 3.2"></path>',
  presentation: '<path d="M2 3h20"></path><path d="M21 3v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V3"></path><path d="m7 21 5-5 5 5"></path>',
  layout: '<rect x="3.5" y="4" width="17" height="16" rx="2"></rect><path d="M3.5 9h17M9 9v11"></path>',
  search: '<circle cx="10.7" cy="10.7" r="5.8"></circle><path d="m15 15 4.5 4.5"></path>',
  filter: '<path d="M4 5h16l-6.2 7v5.2L10.2 19v-7L4 5Z"></path>',
  info: '<circle cx="12" cy="12" r="8.5"></circle><path d="M12 10.5V16M12 7.7h.01"></path>',
  sliders: '<path d="M4 6h16M4 12h16M4 18h16"></path><circle cx="9" cy="6" r="1.6"></circle><circle cx="15" cy="12" r="1.6"></circle><circle cx="11" cy="18" r="1.6"></circle>',
  server: '<rect x="4" y="4.5" width="16" height="6" rx="1.5"></rect><rect x="4" y="13.5" width="16" height="6" rx="1.5"></rect><path d="M7.5 7.5h.01M7.5 16.5h.01M11 7.5h5M11 16.5h5"></path>',
  terminal: '<polyline points="4 17 10 11 4 5"></polyline><line x1="12" x2="20" y1="19" y2="19"></line>',
  globe: '<circle cx="12" cy="12" r="8.5"></circle><path d="M3.8 12h16.4M12 3.5c2.2 2.2 3.3 5 3.3 8.5S14.2 18.3 12 20.5C9.8 18.3 8.7 15.5 8.7 12S9.8 5.7 12 3.5Z"></path>',
  sun: '<circle cx="12" cy="12" r="4"></circle><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"></path>',
  moon: '<path d="M20.5 14.8A8.5 8.5 0 1 1 9.2 3.5a6.7 6.7 0 0 0 11.3 11.3Z"></path>',
  "shield-check": '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3v5"></path><path d="m9 12 2 2 4-4"></path>',
  "lock-keyhole": '<rect width="18" height="11" x="3" y="10" rx="2"></rect><path d="M7 10V7a5 5 0 0 1 10 0v3"></path><circle cx="12" cy="15.5" r="1"></circle><path d="M12 16.5v1.6"></path>',
  brain: '<path d="M9.2 5.3A3 3 0 0 0 4.5 7.8a3 3 0 0 0 .3 5.7 3.2 3.2 0 0 0 4.7 3.2 3.1 3.1 0 0 0 5 0 3.2 3.2 0 0 0 4.7-3.2 3 3 0 0 0 .3-5.7 3 3 0 0 0-4.7-2.5 3.1 3.1 0 0 0-5.6 0Z"></path><path d="M12 5.5v12.7M8 9.5a2.2 2.2 0 0 0 2.2 2.2M16 9.5a2.2 2.2 0 0 1-2.2 2.2M8 14a2.2 2.2 0 0 1 2.2 2.2M16 14a2.2 2.2 0 0 0-2.2 2.2"></path>',
  eye: '<path d="M3.5 12s3-5.2 8.5-5.2 8.5 5.2 8.5 5.2-3 5.2-8.5 5.2S3.5 12 3.5 12Z"></path><circle cx="12" cy="12" r="2.3"></circle>',
  "eye-off": '<path d="m4 4 16 16"></path><path d="M10.6 6.9A9.7 9.7 0 0 1 12 6.8c5.5 0 8.5 5.2 8.5 5.2a14.4 14.4 0 0 1-2.1 2.7M14.3 14.4a3.2 3.2 0 0 1-4.7-4.3M7.1 8.2A14.7 14.7 0 0 0 3.5 12s3 5.2 8.5 5.2c1.3 0 2.5-.3 3.5-.7"></path>',
  "arrow-up-right": '<path d="M7 17 17 7M9 7h8v8"></path>',
  "arrow-up-down": '<path d="m8 6 4-4 4 4M16 18l-4 4-4-4M12 2v20"></path>',
  wrench: '<path d="M14.5 6a4 4 0 0 0-5 5l-5 5a2 2 0 1 0 2.8 2.8l5-5a4 4 0 0 0 5-5L14 12l-2-2 2.5-4Z"></path>',
  code: '<path d="m8.5 7-4 5 4 5M15.5 7l4 5-4 5"></path>',
  audio: '<path d="M4 13h2M8 9v6M12 6v12M16 9v6M20 13h-2"></path>',
  video: '<path d="m16 13 5.223 3.482A.5.5 0 0 0 22 16.066V7.87a.5.5 0 0 0-.752-.432L16 10.5"></path><rect x="2" y="6" width="14" height="12" rx="2"></rect>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5V19A9 3 0 0 0 21 19V5"></path><path d="M3 12A9 3 0 0 0 21 12"></path>',
  "grip-vertical": '<path d="M9 7h.01M15 7h.01M9 12h.01M15 12h.01M9 17h.01M15 17h.01"></path>',
  square: '<rect x="6" y="6" width="12" height="12" rx="1.5"></rect>',
  copy: '<rect x="8" y="8" width="10" height="10" rx="1.5"></rect><path d="M6 15H5.5A1.5 1.5 0 0 1 4 13.5v-8A1.5 1.5 0 0 1 5.5 4h8A1.5 1.5 0 0 1 15 5.5V6"></path>',
  download: '<path d="M12 4v10M8 11l4 4 4-4M5 19.5h14"></path>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"></rect><rect x="9" y="9" width="6" height="6" rx="1"></rect><path d="M9 2v2M15 2v2M9 20v2M15 20v2M20 9h2M20 14h2M2 9h2M2 14h2"></path>',
  "wifi-off": '<path d="M12.3 9.2a10.5 10.5 0 0 1 6.8 2.9M5 12.6a10.8 10.8 0 0 1 2.1-1.4M8.7 16.4a5 5 0 0 1 6.6 0M12 20h.01M2 2l20 20"></path>',
  expand: '<path d="M8 4H4v4M16 4h4v4M20 16v4h-4M4 16v4h4"></path>',
  archive: '<rect width="20" height="5" x="2" y="3" rx="1"></rect><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"></path><path d="M10 12h4"></path>',
  "archive-restore": '<path d="M4 7h16v13H4zM3 4h18v3H3zM8 13a4 4 0 1 1 1.2 2.9M8 13v4h4"></path>',
  "more-horizontal": '<path d="M5 12h.01M12 12h.01M19 12h.01"></path>',
  trash: '<path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"></path>',
};

function uiIcon(name, className = "") {
  const path = uiIconPaths[name] || uiIconPaths.info;
  const classes = ["ui-icon", className].filter(Boolean).join(" ");
  return `<svg class="${classes}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${path}</svg>`;
}

function iconElement(name, className = "") {
  const template = document.createElement("template");
  template.innerHTML = uiIcon(name, className);
  return template.content.firstElementChild;
}

const legacyIconNames = new Map([
  ["⊕", "circle-plus"], ["▤", "library"], ["⌁", "wand"], ["✦", "puzzle"], ["⌑", "folder"],
  ["⚙", "settings"], ["←", "arrow-left"], ["→", "arrow-right"], ["⌄", "chevron-down"], ["›", "chevron-right"],
  ["＋", "plus"], ["+", "plus"], ["↑", "send"], ["✓", "check"], ["×", "x"], ["↻", "refresh"],
  ["⌕", "search"], ["ⓘ", "info"], ["⌘", "sliders"], ["◫", "layout"], ["▧", "file-plus"],
  ["⇄", "arrow-up-down"], ["↗", "arrow-up-right"], ["↓", "download"], ["⧉", "copy"], ["−", "minus"],
  ["⠿", "grip-vertical"], ["◌", "circle-plus"], ["◇", "brain"], ["◉", "eye"], ["‹›", "code"], ["∿", "audio"],
]);

function hydrateIcons(root = document) {
  root.querySelectorAll?.("[data-ui-icon]").forEach((placeholder) => {
    placeholder.replaceWith(iconElement(placeholder.dataset.uiIcon, placeholder.dataset.iconClass || ""));
  });
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    const parent = node.parentElement;
    if (!parent || parent.closest("script, style, textarea, option, code, pre, .provider-logo, [data-icon-preserve]")) return;
    const value = node.nodeValue || "";
    const trimmed = value.trim();
    const exactName = legacyIconNames.get(trimmed);
    if (exactName) {
      node.replaceWith(iconElement(exactName));
      return;
    }
    const match = value.match(/^(\s*)([↻↗])(\s+)/);
    if (!match) return;
    const name = legacyIconNames.get(match[2]);
    if (!name) return;
    const fragment = document.createDocumentFragment();
    if (match[1]) fragment.append(document.createTextNode(match[1]));
    fragment.append(iconElement(name, "ui-icon-inline"));
    fragment.append(document.createTextNode(value.slice(match[0].length)));
    node.replaceWith(fragment);
  });
}

function observeIcons() {
  hydrateIcons();
  const observer = new MutationObserver((records) => {
    records.forEach((record) => record.addedNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE) hydrateIcons(node);
      else if (node.nodeType === Node.TEXT_NODE && node.parentElement) hydrateIcons(node.parentElement);
    }));
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

function compact(value = "", max = 110) {
  const text = String(value).replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

function readerUrl(docId, anchor = "") {
  return `/api/sources/${encodeURIComponent(docId)}/reader${anchor ? `#${encodeURIComponent(anchor)}` : ""}`;
}

function evidenceReaderFrameUrl(value = "") {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const [route, anchor = ""] = raw.split("#", 2);
  const separator = route.includes("?") ? "&" : "?";
  const preferences = appearancePreferences();
  const query = new URLSearchParams({ theme: resolvedTheme(preferences.theme), accent: preferences.accent });
  return `${route}${separator}${query.toString()}${anchor ? `#${anchor}` : ""}`;
}

function refreshEvidenceReaderTheme() {
  const frame = byId("evidenceReaderFrame");
  const reader = state.activeEvidence?.reader_url;
  if (frame && reader && state.contextPanel === "evidence") frame.src = evidenceReaderFrameUrl(reader);
}

function citationMarkerMarkup(citationId) {
  const marker = escapeHtml(citationId);
  return `<button class="citation-marker" type="button" data-citation-id="${marker}" aria-label="查看引用 ${marker}" aria-haspopup="dialog">[${marker}]</button>`;
}

function safeReaderUrl(record = {}) {
  const supplied = String(record.reader_url || "");
  // Task-scoped Deep Research evidence lives under /api/runs.  Both routes
  // are local, application-controlled readers; reject every other URL here.
  if (supplied.startsWith("/api/sources/") || supplied.startsWith("/api/runs/")) return supplied;
  const docId = String(record.doc_id || "").trim();
  if (docId.startsWith("external:")) return "";
  return docId ? readerUrl(docId, String(record.html_anchor || "")) : "";
}

function safeEvidenceSourceUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return ["https:", "http:"].includes(url.protocol) ? url.href : "";
  } catch (_) {
    return "";
  }
}

function sourceTitle(record = {}) {
  return String(record.paper || record.title || record.doc_id || "未命名来源");
}

function evidenceMeta(record = {}) {
  return [record.section, record.doi, record.evidence_id].filter(Boolean).map(String).join(" · ");
}

function clearCitationPreviewTimer() {
  window.clearTimeout(state.citationPreviewTimer);
  state.citationPreviewTimer = 0;
}

function hideCitationPreview() {
  clearCitationPreviewTimer();
  const preview = byId("citationPreview");
  if (!preview) return;
  preview.classList.remove("is-visible");
  preview.setAttribute("aria-hidden", "true");
}

function deferCitationPreviewHide() {
  clearCitationPreviewTimer();
  state.citationPreviewTimer = window.setTimeout(hideCitationPreview, 130);
}

function showCitationPreview(citation, marker) {
  const preview = byId("citationPreview");
  if (!preview || !citation || !marker) return;
  clearCitationPreviewTimer();
  const quote = compact(citation.exact_quote || "当前引用未保存原文摘录。", 460);
  const meta = evidenceMeta(citation);
  preview.innerHTML = `<div class="citation-preview-kicker">证据 ${escapeHtml(citation.citation_id || "")}</div><h3>${escapeHtml(sourceTitle(citation))}</h3>${meta ? `<p class="citation-preview-meta">${escapeHtml(meta)}</p>` : ""}<blockquote>${escapeHtml(quote)}</blockquote><p class="citation-preview-hint">点击脚标可在本应用中查看全文与高亮原文。</p>`;
  preview.classList.add("is-visible");
  preview.setAttribute("aria-hidden", "false");
  const rect = marker.getBoundingClientRect();
  const width = Math.min(360, Math.max(240, window.innerWidth - 32));
  preview.style.width = `${width}px`;
  const previewHeight = preview.offsetHeight;
  const left = Math.min(Math.max(16, rect.left), Math.max(16, window.innerWidth - width - 16));
  const below = rect.bottom + 9;
  const top = below + previewHeight <= window.innerHeight - 16 ? below : Math.max(16, rect.top - previewHeight - 9);
  preview.style.left = `${left}px`;
  preview.style.top = `${top}px`;
}

function openSourceReader(source) {
  if (!source?.doc_id) return;
  if (state.activeView !== "conversation") setView("conversation");
  showEvidenceReader({
    paper: source.title,
    doc_id: source.doc_id,
    doi: source.doi || "",
    reader_url: readerUrl(source.doc_id),
    original_url: `/api/sources/${encodeURIComponent(source.doc_id)}/original`,
    exact_quote: "已打开此来源的全文。选择回答中的脚标可直接定位至对应证据。",
  }, { returnPanel: "sources", sourceOnly: true });
}

function showEvidenceReader(citation, options = {}) {
  const target = byId("evidenceReaderPanel");
  const reader = safeReaderUrl(citation);
  if (!target || !reader) {
    toast("该引用缺少可读取的本地来源。", true);
    return;
  }
  const current = state.contextPanel === "evidence" ? state.evidenceReturnPanel : state.contextPanel;
  state.evidenceReturnPanel = options.returnPanel || (["review", "none"].includes(current) ? current : "sources");
  state.activeEvidence = { ...citation, reader_url: reader, sourceOnly: Boolean(options.sourceOnly) };
  const quote = String(citation.exact_quote || "已打开来源全文；被回答使用的原文会以高亮显示。") || "已打开来源全文。";
  const meta = evidenceMeta(citation);
  const anchorNote = citation.html_anchor ? "已定位至该回答使用的原文片段" : "正在显示来源全文";
  const original = String(citation.original_url || "");
  const tabs = original ? `<div class="evidence-reader-tabs"><button type="button" class="is-active" data-action="show-evidence-blocks">证据定位</button><button type="button" data-action="show-evidence-original" data-original-url="${escapeHtml(original)}">原始文件</button></div>` : "";
  target.innerHTML = `<header class="evidence-reader-head"><button type="button" class="evidence-reader-back" data-action="close-evidence-reader" aria-label="返回来源列表">←</button><div><span>${options.sourceOnly ? "来源全文" : "引用证据"}</span><h2>${escapeHtml(sourceTitle(citation))}</h2><p>${escapeHtml(meta || anchorNote)}</p></div></header>${tabs}<div class="evidence-reader-summary"><span>${escapeHtml(anchorNote)}</span><blockquote>${escapeHtml(compact(quote, 680))}</blockquote></div><div class="evidence-reader-frame-wrap"><iframe class="evidence-reader-frame" id="evidenceReaderFrame" title="${escapeHtml(sourceTitle(citation))} 的来源全文" src="${escapeHtml(evidenceReaderFrameUrl(reader))}" sandbox="allow-same-origin"></iframe></div>`;
  setContextPanel("evidence");
}

function closeEvidenceReader() {
  const returnPanel = state.evidenceReturnPanel === "review" && state.reviewDocument
    ? "review"
    : state.evidenceReturnPanel === "none" ? "none" : "sources";
  state.activeEvidence = null;
  setContextPanel(returnPanel);
}

function bindCitationInteractions(result, scope = byId("answerArea")) {
  const reader = result.reader_answer || {};
  const citationMap = new Map((reader.citations || []).map((citation) => [String(citation.citation_id), citation]));
  if (!scope) return;
  scope.querySelectorAll("[data-citation-id]").forEach((marker) => {
    const citation = citationMap.get(String(marker.dataset.citationId));
    if (!citation) return;
    marker.addEventListener("pointerenter", () => showCitationPreview(citation, marker));
    marker.addEventListener("pointerleave", deferCitationPreviewHide);
    marker.addEventListener("focus", () => showCitationPreview(citation, marker));
    marker.addEventListener("blur", deferCitationPreviewHide);
    marker.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideCitationPreview();
    });
    marker.addEventListener("click", (event) => {
      event.preventDefault();
      hideCitationPreview();
      showEvidenceReader(citation);
    });
  });
  const preview = byId("citationPreview");
  if (preview) {
    preview.onpointerenter = clearCitationPreviewTimer;
    preview.onpointerleave = deferCitationPreviewHide;
  }
}

function toast(message, isError = false) {
  const target = byId("toast");
  target.textContent = message;
  target.classList.toggle("is-error", isError);
  target.classList.add("is-visible");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => target.classList.remove("is-visible"), 2800);
}

function closeNotionWizard(result = null) {
  if (!notionWizardResolve) return;
  const resolve = notionWizardResolve;
  notionWizardResolve = null;
  byId("confirmDialogHost")?.replaceChildren();
  document.body.classList.remove("has-confirm-dialog");
  resolve(result);
}

function openNotionWizard() {
  if (notionWizardResolve) closeNotionWizard(null);
  const host = byId("confirmDialogHost");
  if (!host) return Promise.resolve(null);
  const wizard = { step: 1, token: "", rootPageId: "", title: "Notion 知识库", verified: false };
  host.innerHTML = `<div class="confirm-dialog-backdrop" data-notion-wizard-cancel><section class="confirm-dialog-card notion-wizard-card" role="dialog" aria-modal="true" aria-labelledby="notionWizardTitle"><div class="confirm-dialog-icon notion-brand-icon" aria-hidden="true"><img src="/notion-logo.png" alt="" /></div><div class="confirm-dialog-copy"><p class="confirm-dialog-eyebrow">Notion 知识库接入</p><div class="notion-wizard-progress"><span>01</span><i></i><span>02</span><i></i><span>03</span></div><div id="notionWizardBody"></div></div><footer class="confirm-dialog-actions"><button type="button" class="secondary-button" data-notion-wizard-cancel>取消</button><button type="button" class="secondary-button" id="notionWizardBack">上一步</button><button type="button" class="primary-button" id="notionWizardNext">下一步</button></footer></section></div>`;
  document.body.classList.add("has-confirm-dialog");
  const body = byId("notionWizardBody");
  const setStatus = (message, error = false) => { const status = byId("notionWizardStatus"); if (status) { status.textContent = message; status.classList.toggle("is-error", error); } };
  const saveInputs = () => { wizard.token = byId("notionWizardToken")?.value.trim() || wizard.token; wizard.rootPageId = byId("notionWizardRoot")?.value.trim() || wizard.rootPageId; wizard.title = byId("notionWizardTitleInput")?.value.trim() || wizard.title; };
  const render = () => {
    saveInputs();
    body.innerHTML = wizard.step === 1
      ? `<h2 id="notionWizardTitle">第 1 步：拿到 Notion 密钥</h2><p class="notion-wizard-lead">只做两件事：打开创建页，复制一串以 <b>ntn_</b> 开头的密钥。不要打开笔记，也不要点笔记里的“…”。</p><a class="notion-wizard-open" href="https://app.notion.com/developers/tokens" target="_blank" rel="noreferrer">打开 Notion 密钥创建页 ↗</a><div class="notion-wizard-action-card"><strong>在 Notion 页面里这样点</strong><span>1. 点击 <b>New token</b></span><span>2. 选择你的工作区</span><span>3. 点击 <b>Create token</b></span><span>4. 复制出现的 <b>ntn_…</b> 密钥</span></div><p class="notion-wizard-wrong">如果你看到“新连接 / Internal connection”，说明进错页面了，返回后点击上面的“密钥创建页”。</p><label class="notion-wizard-label">把密钥粘贴到这里<input id="notionWizardToken" type="password" autocomplete="off" value="${escapeHtml(wizard.token)}" placeholder="粘贴 ntn_…" /></label><p class="notion-wizard-status" id="notionWizardStatus">${wizard.verified ? "密钥验证成功，点击下一步。" : "密钥只显示一次；复制后回到这里粘贴。"}</p>`
      : wizard.step === 2
        ? `<h2 id="notionWizardTitle">第 2 步：确认同步全部资料</h2><p class="notion-wizard-lead">PAT 会按照你的 Notion 用户权限读取全部可访问内容。你不需要打开任何单篇笔记，也不需要寻找“连接”菜单。</p><div class="notion-wizard-scope-card"><strong>同步范围：你的全部 Notion 内容</strong><span>包括你能看到的页面、子页面、数据库、数据库条目和文件。ScanSci 会自动搜索它们。</span></div><label class="notion-wizard-label">知识库名称<input id="notionWizardTitleInput" type="text" value="${escapeHtml(wizard.title)}" /></label><p class="notion-wizard-tip">如果以后 Notion 中新增内容，再次同步即可更新。ScanSci 不会修改你的 Notion 原文。</p>`
        : `<h2 id="notionWizardTitle">第 3 步：开始同步</h2><p class="notion-wizard-lead">PAT 已验证。点击下面的按钮后，ScanSci 会把你当前 Notion 用户能够访问的全部内容建立为一个固定知识库。</p><div class="notion-wizard-summary"><span>Token</span><strong>已验证</strong><span>同步范围</span><strong>全部可访问内容</strong><span>知识库</span><strong>${escapeHtml(wizard.title || "Notion 知识库")}</strong></div><p class="notion-wizard-tip">点击“连接并同步”后，Notion 会出现在知识库左侧列表中。</p>`;
    byId("notionWizardBack").disabled = wizard.step === 1;
    byId("notionWizardNext").textContent = wizard.step === 1 && !wizard.verified ? "验证 Token" : wizard.step === 3 ? "连接并同步" : "下一步";
    host.querySelectorAll(".notion-wizard-progress span").forEach((item, index) => item.classList.toggle("is-active", index + 1 === wizard.step));
  };
  host.querySelectorAll("[data-notion-wizard-cancel]").forEach((item) => item.addEventListener("click", (event) => {
    if (event.target === item) closeNotionWizard(null);
  }));
  byId("notionWizardBack").addEventListener("click", () => { saveInputs(); if (wizard.step > 1) { wizard.step -= 1; render(); } });
  byId("notionWizardNext").addEventListener("click", async () => {
    saveInputs();
    if (wizard.step === 1) {
      if (!wizard.token) return setStatus("请先粘贴 Integration Token。", true);
      if (!wizard.verified) {
        setStatus("正在验证 Token…");
        try { const result = await request("/api/notion/test", { method: "POST", body: JSON.stringify({ token: wizard.token }) }); wizard.verified = true; setStatus(`Token 验证成功：${result.name || "Notion Integration"}。点击下一步授权全部资料。`); render(); } catch (error) { setStatus(`${error.message}。请检查 Token 是否完整，并确认它以 secret_ 或 ntn_ 开头。`, true); }
        return;
      }
      wizard.step = 2; render(); return;
    }
    if (wizard.step === 2) { wizard.step = 3; render(); return; }
    closeNotionWizard({ token: wizard.token, rootPageId: wizard.rootPageId, title: wizard.title });
  });
  render();
  return new Promise((resolve) => { notionWizardResolve = resolve; });
}

function settleConfirmation(confirmed) {
  if (!confirmDialogResolve) return;
  const resolve = confirmDialogResolve;
  const previousFocus = confirmDialogPreviousFocus;
  confirmDialogResolve = null;
  confirmDialogPreviousFocus = null;
  byId("confirmDialogHost")?.replaceChildren();
  document.body.classList.remove("has-confirm-dialog");
  resolve(Boolean(confirmed));
  window.requestAnimationFrame(() => previousFocus?.focus?.({ preventScroll: true }));
}

function requestConfirmation({
  eyebrow = "请确认操作",
  title = "继续此操作？",
  subject = "",
  message = "",
  confirmLabel = "确认",
  cancelLabel = "取消",
  danger = false,
} = {}) {
  if (confirmDialogResolve) settleConfirmation(false);
  const host = byId("confirmDialogHost");
  if (!host) return Promise.resolve(false);
  confirmDialogPreviousFocus = document.activeElement;
  host.innerHTML = `
    <div class="confirm-dialog-backdrop" data-action="cancel-confirm-dialog">
      <section class="confirm-dialog-card" data-action="confirm-dialog-content" role="dialog" aria-modal="true" aria-labelledby="confirmDialogTitle" aria-describedby="confirmDialogMessage">
        <div class="confirm-dialog-icon${danger ? " is-danger" : ""}" aria-hidden="true">${uiIcon(danger ? "trash" : "info")}</div>
        <div class="confirm-dialog-copy">
          <p class="confirm-dialog-eyebrow">${escapeHtml(eyebrow)}</p>
          <h2 id="confirmDialogTitle">${escapeHtml(title)}</h2>
          ${subject ? `<p class="confirm-dialog-subject">${escapeHtml(subject)}</p>` : ""}
          ${message ? `<p class="confirm-dialog-message" id="confirmDialogMessage">${escapeHtml(message)}</p>` : '<p class="visually-hidden" id="confirmDialogMessage">请确认是否继续。</p>'}
        </div>
        <footer class="confirm-dialog-actions">
          <button type="button" class="confirm-dialog-button is-cancel" data-action="cancel-confirm-dialog">${escapeHtml(cancelLabel)}</button>
          <button type="button" class="confirm-dialog-button${danger ? " is-danger" : " is-primary"}" data-action="accept-confirm-dialog">${escapeHtml(confirmLabel)}</button>
        </footer>
      </section>
    </div>`;
  document.body.classList.add("has-confirm-dialog");
  return new Promise((resolve) => {
    confirmDialogResolve = resolve;
    window.requestAnimationFrame(() => host.querySelector('[data-action="cancel-confirm-dialog"]')?.focus());
  });
}

function trapConfirmationFocus(event) {
  const dialog = byId("confirmDialogHost")?.querySelector(".confirm-dialog-card");
  if (!dialog || event.key !== "Tab") return false;
  const controls = [...dialog.querySelectorAll("button:not(:disabled)")];
  if (!controls.length) return false;
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    first.focus();
  }
  return true;
}

function updateNoteMarkup(sections = []) {
  return sections.map((section) => {
    const items = (section.items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    return items ? `<section class="app-update-note-section"><h3>${escapeHtml(section.title || "更新内容")}</h3><ul>${items}</ul></section>` : "";
  }).join("");
}

function formatUpdateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `检查于 ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
}

function renderAppUpdate() {
  const update = state.update || {};
  state.updateNative = state.updateNative || Boolean(window.pywebview?.api?.install_update);
  const root = byId("appUpdate");
  const status = ["checking", "installing", "restarting"].includes(update.state) ? update.state : (update.available ? "available" : update.state || "current");
  const shouldShowNotice = Boolean(update.available || ["installing", "restarting"].includes(status));
  root.hidden = !shouldShowNotice;
  document.querySelector(".workbench")?.classList.toggle("has-app-update", shouldShowNotice);
  if (!shouldShowNotice && state.updateCardOpen) {
    state.updateCardOpen = false;
    byId("appUpdateCard").hidden = true;
    document.querySelector("[data-action='toggle-app-update']")?.setAttribute("aria-expanded", "false");
  }
  root.dataset.state = status;
  const labels = {
    checking: "检查更新",
    installing: "正在更新",
    restarting: "正在重启",
    available: "有可用更新",
    current: `v${update.current_version || "0.2.0"}`,
    idle: `v${update.current_version || "0.2.0"}`,
    error: "版本信息",
  };
  byId("appUpdateLabel").textContent = labels[status] || "版本信息";
  byId("appUpdateKicker").textContent = update.channel || "稳定版";
  byId("appUpdateTitle").textContent = update.available
    ? (update.release_title || `ScanSci ${update.latest_version}`)
    : (status === "current" ? "ScanSci 已是最新版" : `ScanSci ${update.current_version || ""}`.trim());
  byId("appUpdateSummary").textContent = update.message || (update.available ? "发现新的 ScanSci 桌面版本。" : "当前已是最新版本。 ");
  byId("appUpdateCurrentVersion").textContent = `v${update.current_version || "—"}`;
  byId("appUpdateLatestVersion").textContent = `v${update.latest_version || update.current_version || "—"}`;
  byId("appUpdateNotes").innerHTML = updateNoteMarkup(update.release_notes || []);
  byId("appUpdateCheckedAt").textContent = formatUpdateTime(update.checked_at);
  byId("appUpdateProgress").hidden = !["installing", "restarting"].includes(status);

  const primary = byId("appUpdatePrimary");
  primary.disabled = ["checking", "installing", "restarting"].includes(status);
  if (update.available && update.can_install) {
    primary.dataset.action = "install-app-update";
    primary.textContent = state.updateNative ? "立即更新" : "在桌面端更新";
  } else if (update.available) {
    primary.dataset.action = "check-app-update";
    primary.textContent = "安装包准备中";
    primary.disabled = true;
  } else {
    primary.dataset.action = "check-app-update";
    primary.textContent = status === "checking" ? "检查中" : "再次检查";
  }
}

function toggleAppUpdateCard(force) {
  if (byId("appUpdate")?.hidden) return;
  const card = byId("appUpdateCard");
  const trigger = document.querySelector("[data-action='toggle-app-update']");
  state.updateCardOpen = typeof force === "boolean" ? force : !state.updateCardOpen;
  card.hidden = !state.updateCardOpen;
  trigger?.setAttribute("aria-expanded", String(state.updateCardOpen));
}

function renderUpdateSurfaces() {
  renderAppUpdate();
  if (state.activeView === "settings" && state.activeSettings === "about" && state.settings) renderSettings();
}

async function refreshAppUpdate({ quiet = false } = {}) {
  if (!quiet) {
    state.update = { ...state.update, state: "checking", message: "正在检查 ScanSci 更新。" };
    renderUpdateSurfaces();
  }
  try {
    state.update = await request("/api/app/update/check", { method: "POST", body: "{}" });
    renderUpdateSurfaces();
  } catch (error) {
    state.update = { ...state.update, state: "error", message: "暂时无法检查更新", error: error.message };
    renderUpdateSurfaces();
    if (!quiet) toast(error.message, true);
  }
}

async function installAppUpdate() {
  if (!window.pywebview?.api?.install_update) {
    toast("请在 ScanSci 桌面应用中完成更新。", true);
    return;
  }
  state.update = { ...state.update, state: "installing", message: "正在下载并校验更新包，请不要关闭 ScanSci。" };
  renderUpdateSurfaces();
  try {
    state.update = await window.pywebview.api.install_update();
    renderUpdateSurfaces();
  } catch (error) {
    state.update = { ...state.update, state: "error", message: "更新没有安装", error: error.message };
    renderUpdateSurfaces();
    toast(error.message || "更新失败", true);
  }
}

async function restoreSessionStats(fallbackStats = null) {
  if (fallbackStats) updateSessionStats(fallbackStats);
  const sessionId = String(state.sessionId || "").trim();
  if (!sessionId) return;
  try {
    const payload = await request(`/api/chat/stats?session_id=${encodeURIComponent(sessionId)}`);
    if (payload?.stats && typeof payload.stats === "object") updateSessionStats(payload.stats);
  } catch (_error) {
    // A stale session registry should not prevent the rest of the workspace
    // from loading; the next direct-chat response will refresh these stats.
  }
}

async function initialize() {
  try {
    const [workspace, settings, presets, capabilities, runsPayload, slideTemplatesPayload, localInstalled, localCatalog, localInstall, localRuntime, skillsPayload] = await Promise.all([
      request("/api/workspace"),
      request("/api/settings"),
      request("/api/settings/presets"),
      request("/api/capabilities"),
      request("/api/runs?view=all&limit=200"),
      request("/api/slides/templates").catch(() => ({ available: false, templates: [] })),
      request("/api/local-models/installed").catch(() => ({ models: [] })),
      request("/api/local-models/market").catch(() => ({ items: [] })),
      request("/api/local-models/install-status").catch(() => ({ jobs: [], active: null })),
      request("/api/local-runtime").catch(() => ({ installed: false, install_available: false, mode: "missing" })),
      request("/api/skills").catch(() => ({ skills: [], library_path: "" })),
    ]);
    state.workspace = workspace;
    const rememberedNotebookId = window.localStorage.getItem("scansci.knowledge.scope") || "";
    const rememberedKnowledgeIds = (() => {
      try {
        const values = JSON.parse(window.localStorage.getItem("scansci.knowledge.scopes") || "[]");
        return Array.isArray(values) ? values.map(String) : [];
      } catch (_error) {
        return [];
      }
    })();
    const searchableNotebookIds = new Set((workspace.notebooks || [])
      .filter(notebookHasSearchableContent)
      .map((item) => String(item.notebook_id)));
    state.knowledgeScopeIds = rememberedKnowledgeIds.filter((id) => searchableNotebookIds.has(id));
    if (!state.knowledgeScopeIds.length && rememberedNotebookId && searchableNotebookIds.has(rememberedNotebookId)) {
      state.knowledgeScopeIds = [rememberedNotebookId];
    }
    state.notebook = (workspace.notebooks || []).find((item) => item.notebook_id === rememberedNotebookId)
      || (workspace.notebooks || [])[0]
      || null;
    state.settings = settings;
    applyAppearancePreferences();
    state.onboardingOpen = !Boolean(settings?.onboarding?.welcome_dismissed);
    state.presets = presets;
    state.capabilities = capabilities;
    state.runs = runsPayload.runs || [];
    state.slideTemplates = slideTemplatesPayload.templates || [];
    state.slideTemplatesPlugin = slideTemplatesPayload.plugin || {};
    state.localModelMarket = { installed: localInstalled.models || [], catalog: localCatalog.items || [], source: localCatalog.source || "", loading: false };
    state.localModelInstall = localInstall || { jobs: [], active: null };
    state.localRuntime = localRuntime || { installed: false, install_available: false, mode: "missing" };
    state.extensions.skills = skillsPayload.skills || [];
    state.extensions.libraryPath = skillsPayload.library_path || "";
    state.slideTemplatesAvailable = Boolean(slideTemplatesPayload.available && state.slideTemplates.length);
    const legacySlideTemplateIds = {
      nsfc_purple_semantic: "nsfc_defense",
      nsfc_semantic: "nsfc_defense",
      nsfc_purple: "nsfc_defense",
    };
    if (legacySlideTemplateIds[state.selectedSlideTemplateId]) {
      state.selectedSlideTemplateId = legacySlideTemplateIds[state.selectedSlideTemplateId];
      window.localStorage.setItem("scansci.slides.template", state.selectedSlideTemplateId);
    }
    if (!state.slideTemplates.some((item) => item.id === state.selectedSlideTemplateId)) {
      state.selectedSlideTemplateId = state.slideTemplates[0]?.id || "";
      if (state.selectedSlideTemplateId) window.localStorage.setItem("scansci.slides.template", state.selectedSlideTemplateId);
    }
    state.previewSlideTemplateId = state.selectedSlideTemplateId;
    state.selectedProviderId = settings.active_model?.provider_id || settings.providers?.[0]?.id || "";
    renderWorkspace();
    renderResourceOnboarding();
    void restoreSessionStats();
    void ensureActiveKnowledgeIndex();
    if (state.localModelInstall?.active) scheduleLocalModelInstallPoll();
    if (["queued", "installing"].includes(state.localRuntime?.install_job?.state)) scheduleLocalRuntimeInstallPoll();

    // Restore the last opened task after a reload.  The history list is loaded
    // asynchronously, so relying on the in-memory activeTaskId would leave
    // the conversation looking open while the composer silently fell back to
    // a fresh direct chat.  Persist only the task id; the authoritative run
    // (including messages and artifacts) is fetched from the API below.
    const rememberedTaskId = window.localStorage.getItem("scansci.active.task") || "";
    if (rememberedTaskId && state.runs.some((item) => item.run_id === rememberedTaskId)) {
      await openTask(rememberedTaskId, { record: false });
    }
  } catch (error) {
    const homeSubline = byId("homeSubline");
    if (homeSubline) homeSubline.textContent = `无法加载本地工作区：${error.message}`;
    toast(error.message, true);
  }
}

async function ensureActiveKnowledgeIndex(requestedNotebookId = "") {
  const notebookId = String(requestedNotebookId || state.notebook?.notebook_id || "").trim();
  if (!notebookId) return;
  try {
    const result = await request(`/api/notebooks/${encodeURIComponent(notebookId)}/evidence-index`, {
      method: "POST",
      body: "{}",
    });
    if (result?.status) {
      state.knowledgeIndexStatuses[notebookId] = result.status;
      syncKnowledgeIndexBadge(notebookId);
    }
    if (result?.model_install) {
      mergeLocalModelInstall(result.model_install);
      if (["queued", "downloading"].includes(result.model_install.state)) {
        scheduleLocalModelInstallPoll();
      }
    }
    if (result?.run) {
      upsertRun(result.run);
      watchRun(result.run.run_id, (run) => {
        const previous = state.knowledgeIndexStatuses[notebookId] || {};
        state.knowledgeIndexStatuses[notebookId] = {
          ...previous,
          state: ["failed", "cancelled"].includes(run.status) ? "failed" : "indexing",
          progress: Math.max(Number(previous.progress || 0), Number(run.progress || 0)),
          error: run.status === "failed" ? runFailureSummary(run) : "",
          run,
        };
        syncKnowledgeIndexBadge(notebookId);
        if (["completed", "failed", "cancelled", "paused"].includes(run.status)) {
          void refreshKnowledgeIndexStatus(notebookId);
        }
      });
    }
  } catch (_error) {
    // Index migration is a background optimization. Retrieval remains usable
    // through lexical search while the next explicit import can retry it.
  }
}

function mergeLocalModelInstall(job) {
  if (!job?.job_id) return;
  const jobs = [...(state.localModelInstall?.jobs || [])].filter((item) => item.job_id !== job.job_id);
  jobs.unshift(job);
  state.localModelInstall = {
    jobs,
    active: ["queued", "downloading"].includes(job.state) ? job : jobs.find((item) => ["queued", "downloading"].includes(item.state)) || null,
  };
}

function formatDownloadBytes(value) {
  const bytes = Math.max(0, Number(value || 0));
  if (!bytes) return "0 B";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(bytes >= 100 * 1024 ** 2 ? 0 : 1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${Math.round(bytes)} B`;
}

function formatDownloadDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value || 0)));
  if (!seconds) return "";
  if (seconds < 60) return `约 ${seconds} 秒`;
  if (seconds < 3600) return `约 ${Math.ceil(seconds / 60)} 分钟`;
  return `约 ${(seconds / 3600).toFixed(seconds >= 7200 ? 0 : 1)} 小时`;
}

function downloadJobTitle(job, kind = "model") {
  if (kind === "runtime") return "本地运行组件";
  if (job?.job_id === "retrieval-core") return "研究检索组件";
  const models = Array.isArray(job?.models) ? job.models : [];
  return models.length === 1 ? models[0] : models.length ? `${models.length} 个本地模型` : "本地模型";
}

function downloadJobStatus(job) {
  const stateName = String(job?.state || "idle");
  if (job?.stalled) return { label: "进度停滞", tone: "warning", detail: `已 ${formatDownloadDuration(job.last_update_seconds).replace("约 ", "")} 没有收到新数据，可能是网络受阻。` };
  if (["failed", "cancelled"].includes(stateName)) return { label: "下载失败", tone: "error", detail: job?.error || job?.message || "下载没有完成。" };
  if (stateName === "interrupted") return { label: "下载已中断", tone: "warning", detail: job?.message || "重新开始后会续传已有内容。" };
  if (stateName === "ready") return { label: "已完成", tone: "ready", detail: job?.message || "下载和校验已完成。" };
  if (stateName === "queued") return { label: "等待下载", tone: "active", detail: job?.message || "正在连接下载源。" };
  return { label: "正在下载", tone: "active", detail: job?.message || "正在接收文件。" };
}

function downloadJobTelemetry(job) {
  const completed = Number(job?.completed_bytes || 0);
  const total = Number(job?.total_bytes || 0);
  const parts = [];
  if (completed || total) parts.push(total ? `${formatDownloadBytes(completed)} / ${formatDownloadBytes(total)}` : formatDownloadBytes(completed));
  const speed = Number(job?.speed_bytes_per_second || 0);
  if (speed > 0) parts.push(`${formatDownloadBytes(speed)}/s`);
  const eta = formatDownloadDuration(job?.eta_seconds);
  if (eta) parts.push(`剩余 ${eta}`);
  if (job?.current_file) parts.push(compact(pathLeaf(job.current_file), 42));
  return parts.join(" · ");
}

function downloadTaskEntries({ includeReady = false } = {}) {
  const entries = [];
  const runtimeJob = state.localRuntime?.install_job;
  if (runtimeJob?.state && runtimeJob.state !== "idle" && (includeReady || runtimeJob.state !== "ready")) {
    entries.push({ kind: "runtime", job: runtimeJob });
  }
  for (const job of state.localModelInstall?.jobs || []) {
    if (!includeReady && job.state === "ready") continue;
    entries.push({ kind: "model", job });
  }
  return entries.sort((left, right) => Number(right.job.updated_at || 0) - Number(left.job.updated_at || 0));
}

function downloadTaskRow(entry) {
  const job = entry.job || {};
  const status = downloadJobStatus(job);
  const progress = Math.max(0, Math.min(100, Math.round(Number(job.progress || 0) * 100)));
  const telemetry = downloadJobTelemetry(job);
  return `<article class="download-task-row is-${escapeHtml(status.tone)}"><span class="download-task-icon">${uiIcon(entry.kind === "runtime" ? "cpu" : "download")}</span><div class="download-task-copy"><header><strong>${escapeHtml(downloadJobTitle(job, entry.kind))}</strong><b>${escapeHtml(status.label)}${["queued", "downloading", "installing"].includes(job.state) ? ` · ${progress}%` : ""}</b></header><p>${escapeHtml(status.detail)}</p>${telemetry ? `<small>${escapeHtml(telemetry)}</small>` : ""}<div class="download-task-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}"><span class="${progressWidthClass(progress)}"></span></div></div></article>`;
}

function renderDownloadActivity() {
  let host = byId("downloadActivity");
  if (!host) {
    host = document.createElement("aside");
    host.id = "downloadActivity";
    host.className = "download-activity";
    host.setAttribute("aria-live", "polite");
    document.body.appendChild(host);
  }
  const entries = downloadTaskEntries().filter((entry) => ["queued", "downloading", "installing", "failed", "cancelled", "interrupted"].includes(entry.job.state));
  if (!entries.length && !state.downloadStatusError) {
    host.hidden = true;
    host.innerHTML = "";
    return;
  }
  host.hidden = false;
  const primary = entries[0];
  const count = entries.length;
  host.innerHTML = `<button type="button" class="download-activity-card ${state.downloadStatusError ? "has-connection-error" : ""}" data-action="open-download-center"><span class="download-activity-symbol">${uiIcon(state.downloadStatusError ? "wifi-off" : primary?.kind === "runtime" ? "cpu" : "download")}</span><span class="download-activity-copy"><strong>${state.downloadStatusError ? "暂时无法读取下载进度" : escapeHtml(downloadJobTitle(primary.job, primary.kind))}</strong><small>${state.downloadStatusError ? "ScanSci 正在重试连接，下载任务不会因此被删除。" : escapeHtml([downloadJobStatus(primary.job).label, `${Math.round(Number(primary.job.progress || 0) * 100)}%`, downloadJobTelemetry(primary.job)].filter(Boolean).join(" · "))}</small></span>${count > 1 ? `<b>${count}</b>` : ""}<span class="download-activity-open">${uiIcon("chevron-right")}</span><span class="download-activity-progress"><i class="${progressWidthClass(Math.round(Number(primary?.job?.progress || 0) * 100))}"></i></span></button>`;
  hydrateIcons(host);
}

function scheduleLocalModelInstallPoll(delay = 900) {
  if (localModelInstallPollTimer) return;
  localModelInstallPollTimer = window.setTimeout(async () => {
    localModelInstallPollTimer = 0;
    try {
      const previousRetrieval = (state.localModelInstall?.jobs || []).find((item) => item.job_id === "retrieval-core");
      const status = await request("/api/local-models/install-status");
      state.downloadStatusError = "";
      state.localModelInstall = status || { jobs: [], active: null };
      const retrieval = (status.jobs || []).find((item) => item.job_id === "retrieval-core");
      if (state.activeView === "settings" && ["local-models", "resources"].includes(state.activeSettings)) renderSettings();
      if (state.onboardingOpen) renderResourceOnboarding();
      renderDownloadActivity();
      if (retrieval && retrieval.state !== previousRetrieval?.state) {
        for (const notebook of state.workspace?.notebooks || []) {
          void refreshKnowledgeIndexStatus(notebook.notebook_id);
        }
      }
      if (status.active) {
        scheduleLocalModelInstallPoll(900);
      } else if ((status.jobs || []).some((item) => item.state === "ready")) {
        await refreshLocalModelMarket();
      }
    } catch (error) {
      state.downloadStatusError = error?.message || "无法读取模型下载进度";
      renderDownloadActivity();
      scheduleLocalModelInstallPoll(2500);
    }
  }, delay);
}

function scheduleLocalRuntimeInstallPoll(delay = 700) {
  if (localRuntimeInstallPollTimer) return;
  localRuntimeInstallPollTimer = window.setTimeout(async () => {
    localRuntimeInstallPollTimer = 0;
    try {
      const job = await request("/api/local-runtime/install-status");
      state.downloadStatusError = "";
      state.localRuntime = { ...(state.localRuntime || {}), install_job: job };
      if (state.activeView === "settings" && ["local-models", "resources"].includes(state.activeSettings)) renderSettings();
      if (state.onboardingOpen) renderResourceOnboarding();
      renderDownloadActivity();
      if (["queued", "installing"].includes(job.state)) {
        scheduleLocalRuntimeInstallPoll(700);
      } else if (job.state === "ready") {
        state.localRuntime = await request("/api/local-runtime");
        await refreshLocalModelMarket();
        toast("ScanSci 本地运行能力已就绪；现在可以按需下载模型。");
      } else if (job.state === "failed") {
        toast(job.error || "本地运行能力安装未完成", true);
      }
    } catch (error) {
      state.downloadStatusError = error?.message || "无法读取运行组件安装进度";
      renderDownloadActivity();
      scheduleLocalRuntimeInstallPoll(2200);
    }
  }, delay);
}

async function refreshKnowledgeIndexStatus(notebookId = state.notebook?.notebook_id || "") {
  const id = String(notebookId || "").trim();
  if (!id) return null;
  try {
    const status = await request(`/api/notebooks/${encodeURIComponent(id)}/evidence-index`);
    state.knowledgeIndexStatuses[id] = status;
    syncKnowledgeIndexBadge(id);
    return status;
  } catch (_error) {
    return null;
  }
}

function renderWorkspace() {
  const title = state.notebook?.title || state.notebook?.notebook_id || "未打开资料库";
  const sidebarTitle = byId("sidebarNotebookTitle");
  if (sidebarTitle) sidebarTitle.textContent = title;
  const sourceCount = state.notebook?.counts?.sources || 0;
  const homeSubline = byId("homeSubline");
  if (homeSubline) homeSubline.textContent = sourceCount ? "直接描述任务，也可引用本地资料" : "直接描述你想完成的事";
  renderKnowledgeScopeSurfaces();
  renderModelSelectors();
  syncSlideTemplateDocks();
  renderSources();
  renderTasks();
  renderDownloadActivity();
}

function knowledgeKind(notebook = state.notebook) {
  const kind = String(notebook?.metadata?.library_kind || "folder");
  if (kind === "zotero") return { key: kind, label: "Zotero", icon: "library" };
  if (kind === "obsidian") return { key: kind, label: "Obsidian", icon: "book" };
  if (kind === "notion") return { key: kind, label: "Notion", icon: "book" };
  if (kind === "empty") return { key: kind, label: "自建知识库", icon: "file-plus" };
  if (kind === "files") return { key: kind, label: "本地文件", icon: "file-plus" };
  return { key: "folder", label: "本地文件夹", icon: "folder-open" };
}

function knowledgeScopeTitle(notebook = state.notebook) {
  const base = notebook?.title || pathLeaf(notebook?.root_path) || "未命名知识库";
  if (notebook?.notebook_id === state.notebook?.notebook_id && state.knowledgeSubscope?.name) {
    return `${base} / ${state.knowledgeSubscope.name}`;
  }
  return base;
}

function notebookHasSearchableContent(notebook) {
  return Number(notebook?.counts?.sources || 0) > 0;
}

function sanitizeKnowledgeScopeIds(ids = state.knowledgeScopeIds || []) {
  const searchableIds = new Set((state.workspace?.notebooks || [])
    .filter(notebookHasSearchableContent)
    .map((notebook) => String(notebook.notebook_id)));
  return [...new Set((ids || []).map(String))].filter((id) => searchableIds.has(id));
}

function unavailableKnowledgeAction(notebook) {
  switch (knowledgeSourceKind(notebook)) {
    case "zotero": return "choose-zotero-library";
    case "obsidian": return "choose-obsidian-vault";
    case "notion": return "connect-notion";
    default: return "choose-library-files";
  }
}

function unavailableKnowledgeLabel(notebook) {
  switch (knowledgeSourceKind(notebook)) {
    case "zotero": return "连接 Zotero";
    case "obsidian": return "选择 Vault";
    case "notion": return "连接 Notion";
    default: return "添加资料";
  }
}

function selectedKnowledgeNotebooks() {
  const selected = new Set(sanitizeKnowledgeScopeIds());
  return (state.workspace?.notebooks || []).filter((notebook) => selected.has(String(notebook.notebook_id)));
}

function persistKnowledgeScopes() {
  window.localStorage.setItem("scansci.knowledge.scopes", JSON.stringify(state.knowledgeScopeIds || []));
}

function setKnowledgeScope(notebook, { close = true, toggle = false } = {}) {
  if (!notebook) {
    state.knowledgeScopeIds = [];
    state.knowledgeSubscope = null;
    persistKnowledgeScopes();
  } else {
    if (!notebookHasSearchableContent(notebook)) {
      state.knowledgeScopeIds = sanitizeKnowledgeScopeIds();
      persistKnowledgeScopes();
      renderWorkspace();
      if (state.activeView === "mode" && state.activeMode === "library") renderMode();
      if (byId("knowledgeScopeDialog")?.open) renderKnowledgeScopeDialog();
      return;
    }
    const notebookId = String(notebook.notebook_id);
    const selected = new Set(state.knowledgeScopeIds || []);
    if (toggle && selected.has(notebookId)) selected.delete(notebookId);
    else selected.add(notebookId);
    state.knowledgeScopeIds = [...selected];
    state.notebook = notebook;
    state.knowledgeSubscope = null;
    window.localStorage.setItem("scansci.knowledge.scope", notebookId);
    persistKnowledgeScopes();
  }
  renderWorkspace();
  if (state.activeView === "mode" && state.activeMode === "library") renderMode();
  if (byId("knowledgeScopeDialog")?.open) renderKnowledgeScopeDialog();
  if (close) closeKnowledgeScopeDialog();
}

function removeKnowledgeScope(notebookId) {
  state.knowledgeScopeIds = (state.knowledgeScopeIds || []).filter((id) => id !== notebookId);
  persistKnowledgeScopes();
  renderKnowledgeScopeSurfaces();
  if (byId("knowledgeScopeDialog")?.open) renderKnowledgeScopeDialog();
}

function setZoteroCollectionScope(notebook, key, name) {
  if (!notebookHasSearchableContent(notebook)) return;
  state.notebook = notebook;
  state.knowledgeSubscope = { type: "zotero-collection", key, name };
  if (!state.knowledgeScopeIds.includes(notebook.notebook_id)) state.knowledgeScopeIds.push(notebook.notebook_id);
  window.localStorage.setItem("scansci.knowledge.scope", notebook.notebook_id);
  persistKnowledgeScopes();
  renderWorkspace();
  renderKnowledgeScopeDialog();
  closeKnowledgeScopeDialog();
}

function activeKnowledgeScopePayload() {
  const notebook = selectedKnowledgeNotebooks()[0];
  if (!notebook) return null;
  return {
    notebook_id: notebook.notebook_id,
    library_kind: String(notebook.metadata?.library_kind || "folder"),
    ...(state.knowledgeSubscope || {}),
  };
}

function activeKnowledgeScopePayloads() {
  return selectedKnowledgeNotebooks().map((notebook) => ({
    notebook_id: notebook.notebook_id,
    library_kind: String(notebook.metadata?.library_kind || "folder"),
  }));
}

function renderKnowledgeScopeSurfaces() {
  const notebooks = selectedKnowledgeNotebooks();
  // Academic discovery and deep research are standalone web workflows.  A
  // selected knowledge library may remain available for evidence Q&A, but it
  // must never look like a prerequisite or be silently attached to an
  // external search request.
  const usesExternalResearch = ["academic", "deep-research"].includes(state.researchWorkflow);
  ["home", "chat"].forEach((key) => {
    const target = byId(`${key}KnowledgeScope`);
    if (!target) return;
    target.hidden = true;
    target.innerHTML = "";
  });
  document.querySelectorAll("[data-knowledge-menu-status]").forEach((target) => {
    target.textContent = notebooks.length ? `${notebooks.length} 个` : "未选择";
    target.classList.toggle("is-active", Boolean(notebooks.length));
  });
  document.querySelectorAll(".composer-knowledge-button").forEach((button) => {
    button.hidden = usesExternalResearch;
    button.classList.toggle("is-active", Boolean(notebooks.length));
    const scopeLabel = notebooks.length === 1
      ? `@${compact(knowledgeScopeTitle(notebooks[0]), 22)}`
      : notebooks.length > 1 ? `@${notebooks.length} 个知识库` : "知识库";
    const detail = notebooks.length
      ? `本轮将检索：${notebooks.map((notebook) => knowledgeScopeTitle(notebook)).join("、")}`
      : "选择本轮要检索的知识库";
    const label = button.querySelector(".composer-knowledge-button-label");
    if (label) label.textContent = scopeLabel;
    button.setAttribute("aria-label", detail);
    button.setAttribute("title", detail);
  });
  document.querySelectorAll(".composer-external-research-status").forEach((status) => {
    status.hidden = !usesExternalResearch;
  });
}

function openKnowledgeScopeDialog() {
  closeAttachmentMenus();
  renderKnowledgeScopeDialog();
  const dialog = byId("knowledgeScopeDialog");
  if (dialog && !dialog.open) dialog.showModal();
}

function closeKnowledgeScopeDialog() {
  const dialog = byId("knowledgeScopeDialog");
  if (dialog?.open) dialog.close();
}

function syncKnowledgeScopeRefreshButton() {
  const button = byId("knowledgeScopeRefresh");
  if (!button) return;
  const refreshing = Boolean(state.knowledgeScopeRefreshing);
  button.disabled = refreshing;
  button.classList.toggle("is-loading", refreshing);
  button.setAttribute("aria-label", refreshing ? "正在刷新资料数量" : "刷新可检索资料数量");
  button.setAttribute("title", refreshing ? "正在刷新资料数量" : "刷新可检索资料数量");
}

async function refreshKnowledgeScopeCounts() {
  if (state.knowledgeScopeRefreshing) return;
  state.knowledgeScopeRefreshing = true;
  syncKnowledgeScopeRefreshButton();
  try {
    const activeNotebookId = String(state.notebook?.notebook_id || "");
    const workspace = await request("/api/workspace");
    const notebooks = workspace?.notebooks || [];
    state.workspace = workspace;
    state.knowledgeScopeIds = sanitizeKnowledgeScopeIds();
    state.notebook = notebooks.find((notebook) => String(notebook.notebook_id) === activeNotebookId)
      || notebooks[0]
      || null;
    persistKnowledgeScopes();
    renderWorkspace();
    if (state.activeView === "mode" && state.activeMode === "library") renderMode();
    if (byId("knowledgeScopeDialog")?.open) renderKnowledgeScopeDialog();
    toast("已更新可检索资料数量");
  } catch (error) {
    toast(`无法刷新资料数量：${error.message}`, true);
  } finally {
    state.knowledgeScopeRefreshing = false;
    syncKnowledgeScopeRefreshButton();
  }
}

function renderKnowledgeScopeDialog() {
  const target = byId("knowledgeScopeContent");
  if (!target) return;
  syncKnowledgeScopeRefreshButton();
  const notebooks = state.workspace?.notebooks || [];
  const selected = new Set(state.knowledgeScopeIds || []);
  const rows = notebooks.map((notebook) => {
    const kind = knowledgeKind(notebook);
    const ready = notebookHasSearchableContent(notebook);
    const active = ready && selected.has(String(notebook.notebook_id));
    const count = Number(notebook.counts?.sources || 0);
    const action = ready ? "toggle-notebook-scope" : unavailableKnowledgeAction(notebook);
    const label = ready ? `${count} 篇` : unavailableKnowledgeLabel(notebook);
    // Selection is intentionally the only right-side affordance.  An
    // unavailable or unselected library must not render a placeholder or
    // navigation glyph here: it looks like a selected state at a glance.
    const selectionMark = active
      ? `<span class="knowledge-scope-selected" aria-label="已选中">${uiIcon("check")}</span>`
      : "";
    return `<button type="button" class="knowledge-scope-row ${active ? "is-active" : ""} ${ready ? "" : "is-unavailable"}" data-action="${action}" data-notebook-id="${escapeHtml(notebook.notebook_id)}" aria-label="${escapeHtml(ready ? `选择 ${knowledgeScopeTitle(notebook)}` : `${unavailableKnowledgeLabel(notebook)}：${knowledgeScopeTitle(notebook)}`)}"><img src="${knowledgeLogoUrl(kind.key)}" alt="" /><span>${escapeHtml(knowledgeScopeTitle(notebook))}</span><small title="${escapeHtml(ready ? `${count} 篇可检索资料` : "尚无可检索内容")}">${escapeHtml(label)}</small>${selectionMark}</button>`;
  }).join("");
  target.innerHTML = `<section class="knowledge-scope-connect"><button type="button" data-action="create-empty-library"><img src="/knowledge-personal.svg" alt="" /><span>个人知识库</span>${uiIcon("plus")}</button><button type="button" data-action="choose-zotero-library"><img src="/zotero-logo.svg" alt="" /><span>Zotero</span>${uiIcon("plus")}</button><button type="button" data-action="choose-obsidian-vault"><img src="/obsidian-logo.svg" alt="" /><span>Obsidian</span>${uiIcon("plus")}</button></section><section class="knowledge-scope-list"><header><h3>选择知识库</h3><span>可多选</span></header>${rows || `<div class="knowledge-scope-empty">先链接一个本地知识库</div>`}</section>`;
  hydrateIcons(target);
  target.querySelector(".knowledge-scope-connect")?.insertAdjacentHTML("beforeend", `<button type="button" data-action="connect-notion"><img src="/notion-logo.png" alt="" /><span>Notion</span>${uiIcon("plus")}</button>`);
  hydrateIcons(target);
}

function knowledgeLogoUrl(kind) {
  if (kind === "zotero") return "/zotero-logo.svg";
  if (kind === "obsidian") return "/obsidian-logo.svg";
  if (kind === "notion") return "/notion-logo.png";
  return "/knowledge-personal.svg";
}

function activeModel() {
  const active = state.settings?.active_model || {};
  const provider = (state.settings?.providers || []).find((item) => item.id === active.provider_id) || state.settings?.providers?.[0];
  const model = provider?.models?.find((item) => item.id === active.model_id) || provider?.models?.[0];
  return { provider, model };
}

function activeModelLabel() {
  const { provider, model } = activeModel();
  if (!provider || !model || !isConversationModel(model)) return "选择模型";
  return model.name;
}

function isConversationModel(model) {
  const capabilities = new Set(model?.capabilities || []);
  return !capabilities.has("embedding") && !capabilities.has("reranking");
}

function isSelectableConversationModel(model) {
  return isConversationModel(model) && String(model?.readiness || "production") === "production";
}

function parseTokenCapacity(value) {
  if (typeof value === "number" && Number.isFinite(value)) return Math.max(0, Math.round(value));
  const text = String(value || "").trim().toLowerCase().replace(/,/g, "");
  const match = text.match(/^(\d+(?:\.\d+)?)\s*(k|m|b|涓|万)?$/i);
  if (!match) return 0;
  const base = Number(match[1]);
  if (!Number.isFinite(base)) return 0;
  const multiplier = ({ k: 1e3, m: 1e6, b: 1e9, "涓": 1e4, "万": 1e4 })[match[2] || ""] || 1;
  return Math.round(base * multiplier);
}

function modelContextWindow() {
  const model = activeModel().model || {};
  return parseTokenCapacity(model.context_window || model.contextWindow || model.context_length);
}

function modelContextWindowFor(providerId, modelId) {
  const providers = [...(state.settings?.providers || []), ...(state.presets?.providers || [])];
  const provider = providers.find((item) => String(item.id) === String(providerId || ""));
  const model = provider?.models?.find((item) => String(item.id) === String(modelId || ""));
  return parseTokenCapacity(model?.context_window || model?.contextWindow || model?.context_length) || modelContextWindow();
}

function normalizeSessionStats(raw) {
  if (!raw || typeof raw !== "object") return null;
  const sourceTokens = raw.tokens && typeof raw.tokens === "object" ? raw.tokens : raw;
  const contextSource = raw.contextUsage || raw.context_usage || {};
  const tokens = {
    input: Number(sourceTokens.input ?? sourceTokens.input_tokens ?? sourceTokens.prompt_tokens ?? 0) || 0,
    output: Number(sourceTokens.output ?? sourceTokens.output_tokens ?? sourceTokens.completion_tokens ?? 0) || 0,
    cacheRead: Number(sourceTokens.cacheRead ?? sourceTokens.cache_read ?? sourceTokens.cache_read_tokens ?? 0) || 0,
    cacheWrite: Number(sourceTokens.cacheWrite ?? sourceTokens.cache_write ?? sourceTokens.cache_write_tokens ?? 0) || 0,
    total: Number(sourceTokens.total ?? sourceTokens.total_tokens ?? 0) || 0,
  };
  const categoryTotal = tokens.input + tokens.output + tokens.cacheRead + tokens.cacheWrite;
  if (!tokens.total) tokens.total = categoryTotal;
  const contextWindow = parseTokenCapacity(contextSource.contextWindow ?? contextSource.context_window) || modelContextWindow();
  const contextTokens = Number(contextSource.tokens ?? contextSource.token_count ?? 0) || 0;
  const percent = Math.max(0, Math.min(100, Number(contextSource.percent) || (contextWindow ? contextTokens / contextWindow * 100 : 0)));
  const rawBreakdown = raw.contextBreakdown && typeof raw.contextBreakdown === "object" ? raw.contextBreakdown : null;
  const contextBreakdown = rawBreakdown ? {
    message: Number(rawBreakdown.message || 0) || 0,
    systemTools: Number(rawBreakdown.systemTools || 0) || 0,
    mcpTools: Number(rawBreakdown.mcpTools || 0) || 0,
    skills: Number(rawBreakdown.skills || 0) || 0,
    systemPrompt: Number(rawBreakdown.systemPrompt || 0) || 0,
    other: Number(rawBreakdown.other || 0) || 0,
    total: Number(rawBreakdown.total || contextTokens) || contextTokens,
  } : null;
  return {
    ...raw,
    tokens,
    contextUsage: { ...contextSource, tokens: contextTokens, contextWindow, percent },
    contextBreakdown,
    toolInventory: raw.toolInventory && typeof raw.toolInventory === "object" ? raw.toolInventory : null,
    skillInventory: raw.skillInventory && typeof raw.skillInventory === "object" ? raw.skillInventory : null,
  };
}

function updateSessionStats(raw) {
  const normalized = normalizeSessionStats(raw);
  if (!normalized) return;
  state.sessionStats = normalized;
  state.contextUsagePercent = Math.round(normalized.contextUsage.percent || 0);
  state.sessionTokens = Number(normalized.tokens.total || 0);
  renderContextUsage();
}

function formatTokenShort(value) {
  const count = Number(value || 0);
  if (!Number.isFinite(count) || count <= 0) return "0";
  if (count >= 1e8) return `${(count / 1e8).toFixed(count >= 1e9 ? 0 : 1).replace(/\.0$/, "")}亿`;
  if (count >= 1e4) return `${(count / 1e4).toFixed(count >= 1e5 ? 0 : 1).replace(/\.0$/, "")}万`;
  if (count >= 1e3) return `${(count / 1e3).toFixed(1).replace(/\.0$/, "")}K`;
  return formatTokenCount(count);
}

function contextUsagePopoverMarkup(stats) {
  const usage = stats?.contextUsage || {};
  const tokens = stats?.tokens || {};
  const contextTokens = Number(usage.tokens || 0);
  const contextWindow = Number(usage.contextWindow || modelContextWindow() || 0);
  const percent = Math.max(0, Math.min(100, Number(usage.percent || 0)));
  const breakdown = stats?.contextBreakdown && typeof stats.contextBreakdown === "object"
    ? stats.contextBreakdown
    : null;
  const legacyRows = [
    ["消息输入", Number(tokens.input || 0), "is-input"],
    ["模型输出", Number(tokens.output || 0), "is-output"],
    ["缓存读取", Number(tokens.cacheRead || 0), "is-cache-read"],
    ["缓存写入", Number(tokens.cacheWrite || 0), "is-cache-write"],
  ];
  const rows = breakdown
    ? [
      ["消息", Number(breakdown.message || 0), "is-input"],
      ["系统工具", Number(breakdown.systemTools || 0), "is-output"],
      ["MCP 工具", Number(breakdown.mcpTools || 0), "is-cache-read"],
      ["技能", Number(breakdown.skills || 0), "is-cache-write"],
      ["系统提示词", Number(breakdown.systemPrompt || 0), "is-system-prompt"],
      ["其他", Number(breakdown.other || 0), "is-other"],
    ]
    : legacyRows;
  const breakdownTotal = Number(breakdown?.total || 0);
  const total = Math.max(0, Number(contextTokens || breakdownTotal || tokens.total || rows.reduce((sum, row) => sum + row[1], 0) || 0));
  if (!breakdown && total > rows.reduce((sum, row) => sum + row[1], 0)) {
    rows.push(["其他", total - rows.reduce((sum, row) => sum + row[1], 0), "is-other"]);
  }
  const rowsMarkup = rows.map(([label, value, colorClass]) => {
    const share = total > 0 ? (value / total) * 100 : 0;
    return `<div class="context-usage-row ${colorClass}"><i></i><span>${label}</span><strong>${share >= 0.1 ? `${share.toFixed(1)}%` : "0%"}</strong></div>`;
  }).join("");
  // Match Pi's own cache report: the prompt consists of uncached input,
  // cache reads, and cache writes.
  const cacheBase = Number(tokens.input || 0) + Number(tokens.cacheRead || 0) + Number(tokens.cacheWrite || 0);
  const cacheHit = cacheBase > 0 ? Math.round(Number(tokens.cacheRead || 0) / cacheBase * 100) : 0;
  const hasRuntimeStats = Boolean(stats && (contextTokens || total || stats.totalMessages || stats.userMessages));
  const progressClass = `context-progress-pct-${Math.round(percent / 5) * 5}`;
  return `<div class="context-usage-head"><strong>上下文容量${stats?.estimated ? " · 历史估算" : ""}</strong><span>${formatTokenShort(contextTokens)} / ${formatTokenShort(contextWindow)}（${Math.round(percent)}%）</span></div><div class="context-usage-progress ${progressClass}"><i></i></div>${hasRuntimeStats ? `<div class="context-usage-rows">${rowsMarkup}</div><div class="context-usage-foot"><span>平均缓存命中率</span><strong>${cacheHit}%</strong></div>` : `<p class="context-usage-empty">开始一次对话后，这里会显示当前会话的实时 Token 和上下文占用。</p>`}`;
}

function renderContextUsage() {
  const stats = state.sessionStats;
  const usage = stats?.contextUsage || {};
  const contextTokens = Number(usage.tokens || 0);
  const contextWindow = Number(usage.contextWindow || modelContextWindow() || 0);
  const percent = Math.max(0, Math.min(100, Number(usage.percent || 0)));
  document.querySelectorAll("[data-context-usage]").forEach((control) => {
    const ring = control.querySelector("[data-context-ring]");
    if (ring) {
      const progressCircle = ring.querySelector(".context-usage-ring-progress");
      if (progressCircle) ring.style.setProperty("--context-ring-offset", `${100 - percent}`);
      ring.setAttribute("aria-valuenow", `${Math.round(percent)}`);
      ring.classList.toggle("is-warn", percent >= 70 && percent < 90);
      ring.classList.toggle("is-danger", percent >= 90);
      const percentLabel = ring.querySelector("[data-context-percent]");
      if (percentLabel) percentLabel.textContent = stats ? `${Math.round(percent)}` : "—";
    }
    const trigger = control.querySelector(".context-usage-trigger");
    if (trigger) {
      const label = contextWindow ? `上下文容量 ${formatTokenShort(contextTokens)} / ${formatTokenShort(contextWindow)}（${Math.round(percent)}%）` : "查看上下文容量";
      trigger.setAttribute("aria-label", label);
      trigger.title = label;
    }
    const popover = control.querySelector(".context-usage-popover");
    if (popover) popover.innerHTML = contextUsagePopoverMarkup(stats);
  });
}

function renderModelSelectors() {
  const current = state.settings?.active_model || {};
  const label = activeModelLabel();
  ["homeModelLabel", "chatModelLabel"].forEach((id) => {
    const target = byId(id);
    if (target) target.textContent = label;
  });
  const menu = composerModelMenuMarkup(current);
  ["homeModelMenu", "chatModelMenu"].forEach((id) => {
    const target = byId(id);
    if (target) target.innerHTML = menu;
  });
  renderThinkingSelectors();
  setWebSearchMode(state.webSearchMode, { announce: false });
  renderContextUsage();
}

const thinkingLevels = [
  { value: "auto", label: "\u81ea\u52a8", detail: "\u7531\u6a21\u578b\u548c Agent \u6309\u95ee\u9898\u590d\u6742\u5ea6\u5206\u914d" },
  { value: "low", label: "\u4f4e", detail: "\u66f4\u5feb\u54cd\u5e94\uff0c\u8f83\u5c11\u68c0\u7d22\u4e0e\u5de5\u5177\u9884\u7b97" },
  { value: "medium", label: "\u4e2d", detail: "\u5e73\u8861\u63a8\u7406\u3001\u68c0\u7d22\u8303\u56f4\u4e0e\u54cd\u5e94\u901f\u5ea6" },
  { value: "high", label: "\u9ad8", detail: "\u66f4\u5927\u7684 Agent \u8bc1\u636e\u9884\u7b97\u4e0e\u539f\u751f\u63a8\u7406\u5f3a\u5ea6" },
];

function currentThinkingLevel() {
  return thinkingLevels.some((item) => item.value === state.thinkingLevel) ? state.thinkingLevel : "auto";
}

function currentThinkingLabel() {
  return thinkingLevels.find((item) => item.value === currentThinkingLevel())?.label || "\u81ea\u52a8";
}

function activeModelSupportsReasoning() {
  return Boolean(activeModel().model?.capabilities?.includes("reasoning"));
}

function renderThinkingSelectors() {
  const supported = activeModelSupportsReasoning();
  const menu = thinkingMenuMarkup({ disabled: !supported });
  document.querySelectorAll("[data-composer-thinking]").forEach((picker) => {
    const trigger = picker.querySelector("[data-action='toggle-composer-thinking']");
    picker.querySelector("[data-thinking-label]")?.replaceChildren(document.createTextNode(currentThinkingLabel()));
    const options = picker.querySelector(".composer-thinking-popover");
    if (options) options.innerHTML = menu;
    picker.classList.toggle("is-unavailable", !supported);
    if (!trigger) return;
    trigger.disabled = !supported;
    trigger.setAttribute("aria-label", supported ? `${label}\uff0c\u8c03\u6574\u63a8\u7406\u7b49\u7ea7` : "\u5f53\u524d\u6a21\u578b\u4e0d\u652f\u6301\u601d\u8003\u9884\u7b97");
    if (!supported) {
      picker.classList.remove("is-open");
      trigger.setAttribute("aria-expanded", "false");
    }
  });
}

function thinkingMenuMarkup({ disabled = false } = {}) {
  const current = currentThinkingLevel();
  const options = thinkingLevels.map((item) => {
    const selected = item.value === current;
    return `<button type="button" class="composer-thinking-option ${selected ? "is-selected" : ""}" data-action="select-composer-thinking" data-thinking-value="${item.value}" role="option" aria-selected="${selected ? "true" : "false"}" title="${escapeHtml(item.detail)}" ${disabled ? "disabled" : ""}><span>${item.label}</span><span class="composer-thinking-check" aria-hidden="true">${uiIcon("check")}</span></button>`;
  }).join("");
  return options;
}

function setComposerThinkingLevel(value) {
  if (!thinkingLevels.some((item) => item.value === value)) return;
  state.thinkingLevel = value;
  window.localStorage.setItem("scansci.thinking.level", value);
  renderThinkingSelectors();
  closeComposerThinkingPickers();
  toast(`\u601d\u8003\u7b49\u7ea7\u5df2\u8bbe\u4e3a\u300c${currentThinkingLabel()}\u300d`);
}

function composerModelMenuMarkup(current = {}) {
  const providers = (state.settings?.providers || []).filter(isProviderUsable);
  const groups = providers.map((provider) => {
    const models = (provider.models || []).filter(isSelectableConversationModel);
    if (!models.length) return "";
    const rows = models.map((model) => {
      const selected = provider.id === current.provider_id && model.id === current.model_id;
      const tags = model.capabilities?.includes("vision") ? '<span class="composer-model-tag">视觉</span>' : "";
      return `<button type="button" class="composer-model-option ${selected ? "is-selected" : ""}" data-action="select-composer-model" data-model-value="${escapeHtml(`${provider.id}::${model.id}`)}" role="option" aria-selected="${selected ? "true" : "false"}"><span class="composer-model-option-name">${escapeHtml(model.name || model.id)}</span>${tags}<span class="composer-model-check" aria-hidden="true">${uiIcon("check")}</span></button>`;
    }).join("");
    return `<section class="composer-model-group"><span>${escapeHtml(provider.name)}</span>${rows}</section>`;
  }).join("");
  const empty = groups || '<div class="composer-model-empty">尚未配置可用模型</div>';
  const webMode = Object.hasOwn(webSearchLabels, state.webSearchMode) ? state.webSearchMode : "auto";
  const webOptions = [
    ["auto", "自动"],
    ["on", "开启"],
    ["off", "关闭"],
  ].map(([value, label]) => `<button type="button" class="web-search-option ${webMode === value ? "is-selected" : ""}" data-action="select-web-search" data-web-search-value="${value}" role="option" aria-selected="${webMode === value ? "true" : "false"}">${label}</button>`).join("");
  return `<div class="composer-settings-panel">
    <section class="composer-settings-section web-search-picker" data-web-search-picker>
      <header><span data-ui-icon="globe"></span><span>联网搜索</span></header>
      <div class="composer-segmented-control" role="listbox" aria-label="联网搜索策略">${webOptions}</div>
    </section>
    <section class="composer-settings-section composer-thinking" data-composer-thinking>
      <header><span data-ui-icon="brain"></span><span>思考模式</span></header>
      <div class="composer-thinking-popover composer-segmented-control" role="listbox" aria-label="调整思考等级"></div>
    </section>
    <section class="composer-settings-models">
      <header><span>可用模型</span></header>
      ${empty}
      <div class="composer-model-manage"><button type="button" data-action="open-settings" data-settings-panel="models">${uiIcon("plus")}管理模型</button></div>
    </section>
  </div>`;
}

async function setActiveComposerModel(value) {
  const [providerId, modelId] = String(value || "").split("::");
  if (!providerId || !modelId) return;
  state.settings.active_model = { provider_id: providerId, model_id: modelId };
  renderModelSelectors();
  closeComposerModelPickers();
  await persistSettings("当前模型已切换");
}

function isProviderUsable(provider) {
  return Boolean(provider?.enabled) && (provider.kind === "local" || provider.auth_mode === "managed" || Boolean(provider.api_key_configured));
}

const COMPOSER_IMAGE_LIMIT = 4;
const COMPOSER_IMAGE_MAX_BYTES = 4 * 1024 * 1024;
const COMPOSER_IMAGE_TOTAL_BYTES = 10 * 1024 * 1024;
const COMPOSER_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
const COMPOSER_SOURCE_LIMIT = 8;
const COMPOSER_SOURCE_MAX_BYTES = 50 * 1024 * 1024;
const COMPOSER_SOURCE_TOTAL_BYTES = 120 * 1024 * 1024;
const COMPOSER_SOURCE_SUFFIXES = new Set([
  ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".csv", ".json", ".xml", ".html", ".htm",
  ".md", ".markdown", ".txt", ".rtf", ".epub", ".zip", ".png", ".jpg", ".jpeg", ".webp",
  ".gif", ".wav", ".mp3", ".m4a", ".flac",
]);

function composerKey(inputId) {
  return inputId === "homeQuestionInput" ? "home" : "chat";
}

function currentModelSupportsVision() {
  return Boolean(activeModel().model?.capabilities?.includes("vision"));
}

function composerImagePreviewMarkup(images = []) {
  if (!images.length) return "";
  return `<div class="user-image-preview-list">${images.map((image) => {
    const src = image.preview_url || image.data_url || "";
    return src ? `<img src="${escapeHtml(src)}" alt="${escapeHtml(image.name || "用户图片")}" />` : "";
  }).join("")}</div>`;
}

function composerSourcePreviewMarkup(sources = []) {
  if (!sources.length) return "";
  return `<div class="user-source-preview">${sources.map((source) => {
    const label = `${uiIcon("file-plus")}${escapeHtml(source.name || "附件")}`;
    return source.file_url
      ? `<button type="button" data-action="open-ingestion-source" data-source-url="${escapeHtml(source.file_url)}" data-source-name="${escapeHtml(source.name || "附件")}">${label}</button>`
      : `<span>${label}</span>`;
  }).join("")}</div>`;
}

function renderComposerImages(key) {
  const target = byId(`${key}ImageAttachments`);
  if (!target) return;
  const images = state.composerImages[key] || [];
  target.hidden = !images.length;
  target.innerHTML = images.map((image) => `<figure class="composer-image-card"><img src="${escapeHtml(image.data_url)}" alt="${escapeHtml(image.name)}" /><figcaption>${escapeHtml(image.name)}</figcaption><button type="button" data-action="remove-composer-image" data-composer-key="${key}" data-image-id="${escapeHtml(image.id)}" aria-label="移除 ${escapeHtml(image.name)}">×</button></figure>`).join("");
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("无法读取图片"));
    reader.readAsDataURL(file);
  });
}

async function addComposerImages(key, files) {
  const incoming = [...files].filter(Boolean);
  if (!incoming.length) return;
  const existing = state.composerImages[key] || [];
  if (existing.length + incoming.length > COMPOSER_IMAGE_LIMIT) {
    toast(`一次最多可添加 ${COMPOSER_IMAGE_LIMIT} 张图片`, true);
    return;
  }
  const accepted = [];
  let totalBytes = existing.reduce((sum, image) => sum + Number(image.size || 0), 0);
  for (const file of incoming) {
    if (!COMPOSER_IMAGE_TYPES.has(file.type)) {
      toast("仅支持 PNG、JPG、WebP 或 GIF 图片", true);
      continue;
    }
    if (file.size > COMPOSER_IMAGE_MAX_BYTES) {
      toast("单张图片不能超过 4 MB", true);
      continue;
    }
    totalBytes += file.size;
    if (totalBytes > COMPOSER_IMAGE_TOTAL_BYTES) {
      toast("本次图片总大小不能超过 10 MB", true);
      break;
    }
    accepted.push({
      id: `image-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      name: file.name || `粘贴图片 ${existing.length + accepted.length + 1}`,
      mime_type: file.type,
      size: file.size,
      data_url: await fileToDataUrl(file),
    });
  }
  if (!accepted.length) return;
  state.composerImages[key] = [...existing, ...accepted];
  renderComposerImages(key);
}

function removeComposerImage(key, imageId) {
  state.composerImages[key] = (state.composerImages[key] || []).filter((image) => image.id !== imageId);
  renderComposerImages(key);
}

function clearComposerImages(key) {
  state.composerImages[key] = [];
  renderComposerImages(key);
}

function imagePayloadForComposer(key) {
  return (state.composerImages[key] || []).map((image) => ({
    name: image.name,
    mime_type: image.mime_type,
    data_url: image.data_url,
  }));
}

function sourceSuffix(name = "") {
  const match = String(name).toLowerCase().match(/\.[a-z0-9]+$/);
  return match ? match[0] : "";
}

function sourceTypeLabel(name = "") {
  return ({
    ".pdf": "PDF", ".docx": "Word", ".pptx": "PowerPoint", ".xlsx": "Excel", ".xls": "Excel",
    ".csv": "CSV", ".json": "JSON", ".xml": "XML", ".md": "Markdown", ".markdown": "Markdown",
    ".txt": "文本", ".rtf": "RTF", ".html": "HTML", ".htm": "HTML", ".epub": "EPUB", ".zip": "ZIP",
    ".png": "图片", ".jpg": "图片", ".jpeg": "图片", ".webp": "图片", ".gif": "图片",
    ".wav": "音频", ".mp3": "音频", ".m4a": "音频", ".flac": "音频",
  })[sourceSuffix(name)] || "文档";
}

function formatFileSize(size) {
  const bytes = Number(size || 0);
  if (!bytes) return "本地文件";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function renderComposerSources(key) {
  const target = byId(`${key}SourceAttachments`);
  if (!target) return;
  const sources = state.composerSources[key] || [];
  target.hidden = !sources.length;
  const cards = sources.map((source) => `<article class="composer-source-card ${sourceSuffix(source.name) === ".pdf" ? "is-pdf" : ""}"><img src="${sourceSuffix(source.name) === ".pdf" ? "/pdf-document.svg" : "/knowledge-personal.svg"}" alt="" /><span><strong>${escapeHtml(source.name)}</strong><small>${escapeHtml(sourceTypeLabel(source.name))} · ${escapeHtml(formatFileSize(source.size))}</small></span><button type="button" data-action="remove-composer-source" data-composer-key="${escapeHtml(key)}" data-source-id="${escapeHtml(source.id)}" aria-label="移除 ${escapeHtml(source.name)}">×</button></article>`).join("");
  const firstName = sources[0]?.name || "当前文件";
  const suggestions = sources.length === 1
    ? `<nav class="composer-file-suggestions" aria-label="基于文件继续"><button type="button" data-action="use-file-suggestion" data-composer-key="${escapeHtml(key)}" data-file-name="${escapeHtml(firstName)}" data-suggestion="总结">总结</button><button type="button" data-action="use-file-suggestion" data-composer-key="${escapeHtml(key)}" data-file-name="${escapeHtml(firstName)}" data-suggestion="提取要点">提取要点</button><button type="button" data-action="use-file-suggestion" data-composer-key="${escapeHtml(key)}" data-file-name="${escapeHtml(firstName)}" data-suggestion="生成综述">生成综述</button></nav>`
    : "";
  target.innerHTML = `<div class="composer-source-cards">${cards}</div>${suggestions}`;
}

function useFileSuggestion(key, fileName, suggestion) {
  const input = byId(key === "home" ? "homeQuestionInput" : "chatQuestionInput");
  if (!input) return;
  const prompts = {
    "总结": `请总结《${fileName}》的核心内容，并列出关键结论。`,
    "提取要点": `请从《${fileName}》中提取研究问题、方法、数据、主要发现与局限。`,
    "生成综述": `请以《${fileName}》为起点生成一份结构化文献综述，并区分原文证据与延伸判断。`,
  };
  input.value = prompts[suggestion] || `请阅读《${fileName}》。`;
  input.focus();
}

async function addComposerSources(key, files) {
  const incoming = [...files].filter(Boolean);
  if (!incoming.length) return;
  const existing = state.composerSources[key] || [];
  if (existing.length + incoming.length > COMPOSER_SOURCE_LIMIT) {
    toast(`一次最多可添加 ${COMPOSER_SOURCE_LIMIT} 个文件`, true);
    return;
  }
  const accepted = [];
  let totalBytes = existing.reduce((sum, item) => sum + Number(item.size || 0), 0);
  for (const file of incoming) {
    const suffix = sourceSuffix(file.name);
    if (!COMPOSER_SOURCE_SUFFIXES.has(suffix)) {
      toast("暂不支持这个文件格式", true);
      continue;
    }
    if (!file.size || file.size > COMPOSER_SOURCE_MAX_BYTES || totalBytes + file.size > COMPOSER_SOURCE_TOTAL_BYTES) {
      toast("单个附件不能超过 50 MB，本次附件总大小不能超过 120 MB", true);
      break;
    }
    totalBytes += file.size;
    accepted.push({
      id: `source-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      name: file.name || "未命名材料",
      size: file.size,
      data_url: await fileToDataUrl(file),
    });
  }
  if (!accepted.length) return;
  state.composerSources[key] = [...existing, ...accepted];
  renderComposerSources(key);
}

function addComposerSourcePaths(key, paths) {
  const incoming = Array.from(paths || []).map(String).filter(Boolean);
  if (!incoming.length) return;
  const existing = state.composerSources[key] || [];
  const remaining = COMPOSER_SOURCE_LIMIT - existing.length;
  if (remaining <= 0) {
    toast(`一次最多可添加 ${COMPOSER_SOURCE_LIMIT} 个文件`, true);
    return;
  }
  const accepted = incoming.slice(0, remaining).filter((path) => COMPOSER_SOURCE_SUFFIXES.has(sourceSuffix(path))).map((path, index) => ({
    id: `source-${Date.now()}-${index}`,
    name: path.split(/[\\/]/).pop() || "未命名材料",
    path,
    size: 0,
  }));
  if (!accepted.length) {
    toast("暂不支持所选文件格式", true);
    return;
  }
  state.composerSources[key] = [...existing, ...accepted];
  renderComposerSources(key);
}

function removeComposerSource(key, sourceId) {
  state.composerSources[key] = (state.composerSources[key] || []).filter((source) => source.id !== sourceId);
  renderComposerSources(key);
}

function clearComposerSources(key) {
  state.composerSources[key] = [];
  renderComposerSources(key);
}

function sourcePayloadForComposer(key) {
  return (state.composerSources[key] || []).map((source) => ({
    name: source.name,
    ...(source.path ? { path: source.path } : { data_url: source.data_url }),
  }));
}

function isBuiltInProvider(provider) {
  return (state.presets?.providers || []).some((preset) => preset.id === provider?.id);
}

const modelCapabilityDefinitions = [
  ["reasoning", "推理", "brain"], ["vision", "视觉", "eye"], ["embedding", "嵌入", "arrow-up-right"],
  ["reranking", "重排", "arrow-up-down"], ["tool", "工具", "wrench"], ["coding", "代码", "code"],
  ["image", "图像", "image"], ["audio", "音频", "audio"],
];

function providerLogo(provider, large = false) {
  const iconAssets = {
    "scansci-managed": "/scansci-mark.png",
    openai: "openai.png", anthropic: "anthropic.png", gemini: "gemini.png", "vertex-ai": "google.png",
    openrouter: "openrouter.png", nvidia: "nvidia.png", deepseek: "deepseek.png", dashscope: "qwen.png",
    zai: "zhipu.png", zhipu: "zhipu.png", moonshot: "moonshot.webp", minimax: "minimax.png",
    "xiaomi-mimo": "mimo.svg", modelscope: "modelscope.png", volcengine: "volcengine.png",
    "new-api": "new-api.png", aihubmix: "aihubmix.webp", ocoolai: "ocoolai.png", alaya: "alaya.webp",
    dmxapi: "dmxapi.webp", aionly: "aionly.webp", burncloud: "burncloud.png", cherryin: "cherryin.png",
    "github-copilot": "github-copilot.webp",
  };
  const marks = {
    openai: "◎", anthropic: "A", gemini: "✦", "vertex-ai": "V", openrouter: "◌", nvidia: "N",
    deepseek: "DS", dashscope: "Q", zai: "Z", zhipu: "Z", moonshot: "K", minimax: "M", "xiaomi-mimo": "mi",
    siliconflow: "SF", modelscope: "MS", ppio: "P", volcengine: "V", "huawei-cloud": "H", infinigence: "∞",
    "qiniu-ai": "7", modal: "M", "new-api": "N", "one-api": "1", aihubmix: "AH", ocoolai: "oc",
    alaya: "A", dmxapi: "D", aionly: "AI", burncloud: "B", cherryai: "C", cherryin: "CI",
    "github-copilot": "GH", wuwen: "W", "local-evidence": "S",
  };
  const rawKey = String(provider?.logo || provider?.id || "custom").toLowerCase();
  const key = rawKey.replace(/[^a-z0-9-]/g, "-");
  const mark = marks[rawKey] || String(provider?.name || "+").trim().slice(0, 2).toUpperCase();
  const iconAsset = iconAssets[rawKey];
  const iconUrl = iconAsset?.startsWith("/") ? iconAsset : `/provider-icons/${iconAsset || ""}`;
  const content = iconAsset
    ? `<img src="${escapeHtml(iconUrl)}" alt="" loading="lazy" />`
    : escapeHtml(mark);
  return `<span class="provider-logo provider-logo-${escapeHtml(key)} ${iconAsset ? "has-brand-image" : ""} ${large ? "is-large" : ""}" aria-label="${escapeHtml(provider?.name || "服务商")} 品牌标识">${content}</span>`;
}

function modelCapabilityChips(model, index, options = {}) {
  const enabled = new Set(Array.isArray(model?.capabilities) ? model.capabilities : []);
  const showAll = Boolean(options.showAll);
  const definitions = showAll ? modelCapabilityDefinitions : modelCapabilityDefinitions.filter(([id]) => enabled.has(id));
  const empty = !definitions.length && !showAll ? '<span class="model-capability-empty">未标注</span>' : "";
  return `<div class="model-capabilities ${showAll ? "is-picker" : ""}" aria-label="模型能力">${definitions.map(([id, label, iconName]) => `<button type="button" class="model-capability-chip ${enabled.has(id) ? "is-active" : ""}" data-action="toggle-model-capability" data-model-index="${index}" data-capability="${id}" title="${enabled.has(id) ? `移除${label}能力` : `添加${label}能力`}"><i>${uiIcon(iconName)}</i><span>${label}</span></button>`).join("")}${empty}</div>`;
}

function modelEditorMarkup(provider) {
  const index = Number(state.editingModelIndex);
  const model = provider?.models?.[index];
  if (!model || index < 0) return "";
  return `<div class="cherry-model-editor-backdrop" role="presentation"><section class="cherry-model-editor" role="dialog" aria-modal="true" aria-labelledby="modelEditorTitle"><header><h2 id="modelEditorTitle">编辑模型</h2><button type="button" class="cherry-icon-button" data-action="close-model-editor" aria-label="关闭">${uiIcon("x")}</button></header><div class="cherry-editor-body"><label><span><b>*</b> 模型 ID</span><input data-model-id="${index}" value="${escapeHtml(model.id)}" placeholder="例如 gpt-5.2" required /></label><label><span>模型名称</span><input data-model-name="${index}" value="${escapeHtml(model.name || model.id)}" placeholder="例如 GPT-5.2" /></label><label><span>分组名称</span><input data-model-group="${index}" value="${escapeHtml(model.group || "默认模型")}" placeholder="例如 GPT" /></label><label><span>上下文窗口</span><input data-model-context="${index}" value="${escapeHtml(model.context_window || "")}" placeholder="例如 128K" /></label><section class="cherry-capability-editor"><div><strong>更多设置</strong><span>模型能力</span></div>${modelCapabilityChips(model, index, { showAll: true })}</section></div><footer><button type="button" class="cherry-text-button" data-action="close-model-editor">取消</button><button type="button" class="cherry-save-button" data-action="save-model-editor">保存</button></footer></section></div>`;
}

function providerConnectionLabel(provider) {
  if (provider?.kind === "local") return "内置";
  if (provider?.auth_mode === "managed") return "ScanSci 托管";
  return provider?.api_key_configured ? "已连接" : "未连接";
}

function navigationLocation() {
  return {
    view: state.activeView,
    mode: state.activeMode,
    settings: state.activeSettings,
    extensions: state.activeExtensions,
    task: state.activeTaskId,
  };
}

function navigationKey(location) {
  return [location.view, location.mode, location.settings, location.extensions, location.task].join("::");
}

function updateChromeControls() {
  document.querySelectorAll('[data-history-direction="back"]').forEach((button) => {
    button.disabled = state.navigationIndex <= 0;
  });
  document.querySelectorAll('[data-history-direction="forward"]').forEach((button) => {
    button.disabled = state.navigationIndex >= state.navigationHistory.length - 1;
  });
}

function recordNavigation() {
  const location = navigationLocation();
  const current = state.navigationHistory[state.navigationIndex];
  if (current && navigationKey(current) === navigationKey(location)) {
    updateChromeControls();
    return;
  }
  state.navigationHistory = state.navigationHistory.slice(0, state.navigationIndex + 1);
  state.navigationHistory.push(location);
  state.navigationIndex = state.navigationHistory.length - 1;
  updateChromeControls();
}

function moveNavigation(delta) {
  const nextIndex = state.navigationIndex + delta;
  if (nextIndex < 0 || nextIndex >= state.navigationHistory.length) return;
  state.navigationIndex = nextIndex;
  const location = state.navigationHistory[nextIndex];
  state.activeMode = location.mode;
  state.activeSettings = location.settings;
  state.activeExtensions = location.extensions || "skills";
  state.activeTaskId = location.task;
  setView(location.view, { record: false });
  if (location.view === "conversation" && location.task) {
    const run = state.runs.find((item) => item.run_id === location.task);
    if (run) openTask(run.run_id, { record: false });
  }
  renderTasks();
  updateChromeControls();
}

function maxSidebarWidth() {
  return Math.max(300, Math.min(520, window.innerWidth - 480));
}

function clampSidebarWidth(value) {
  return Math.round(Math.max(260, Math.min(maxSidebarWidth(), Number(value) || 352)));
}

function applySidebarWidth({ persist = false } = {}) {
  state.sidebarWidth = clampSidebarWidth(state.sidebarWidth);
  const workbench = byId("workbench");
  const resizer = byId("sidebarResizer");
  workbench.style.setProperty("--sidebar-width", `${state.sidebarWidth}px`);
  if (resizer) {
    resizer.setAttribute("aria-valuemax", String(maxSidebarWidth()));
    resizer.setAttribute("aria-valuenow", String(state.sidebarWidth));
  }
  if (persist) window.localStorage.setItem("scansci.sidebar.width", String(state.sidebarWidth));
}

function applySidebarState() {
  const workbench = byId("workbench");
  workbench.classList.toggle("is-sidebar-collapsed", state.sidebarCollapsed);
  applySidebarWidth();
  document.querySelectorAll('[data-action="toggle-sidebar"]').forEach((button) => {
    button.setAttribute("aria-expanded", String(!state.sidebarCollapsed));
    button.setAttribute("aria-label", state.sidebarCollapsed ? "展开侧栏" : "折叠侧栏");
  });
}

function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  window.localStorage.setItem("scansci.sidebar.collapsed", String(state.sidebarCollapsed));
  applySidebarState();
}

function installSidebarResizer() {
  const resizer = byId("sidebarResizer");
  if (!resizer) return;
  let startX = 0;
  let startWidth = 0;
  let resizing = false;
  const finish = (event) => {
    if (!resizing) return;
    resizing = false;
    byId("workbench").classList.remove("is-resizing-sidebar");
    if (event?.pointerId !== undefined && resizer.hasPointerCapture(event.pointerId)) resizer.releasePointerCapture(event.pointerId);
    applySidebarWidth({ persist: true });
  };
  resizer.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || state.sidebarCollapsed || state.activeView === "settings") return;
    event.preventDefault();
    startX = event.clientX;
    startWidth = state.sidebarWidth;
    resizing = true;
    resizer.focus({ preventScroll: true });
    resizer.setPointerCapture(event.pointerId);
    byId("workbench").classList.add("is-resizing-sidebar");
  });
  resizer.addEventListener("pointermove", (event) => {
    if (!resizing) return;
    state.sidebarWidth = clampSidebarWidth(startWidth + event.clientX - startX);
    applySidebarWidth();
  });
  resizer.addEventListener("pointerup", finish);
  resizer.addEventListener("pointercancel", finish);
  resizer.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 32 : 12;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      state.sidebarWidth -= step;
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      state.sidebarWidth += step;
    } else if (event.key === "Home") {
      event.preventDefault();
      state.sidebarWidth = 260;
    } else if (event.key === "End") {
      event.preventDefault();
      state.sidebarWidth = maxSidebarWidth();
    } else return;
    applySidebarWidth({ persist: true });
  });
  window.addEventListener("resize", () => applySidebarWidth());
}

function maxContextPanelWidth() {
  const layout = byId("conversationLayout");
  const availableWidth = Number(layout?.getBoundingClientRect().width || 0);
  const fallbackAvailableWidth = Math.max(0, window.innerWidth - (state.sidebarCollapsed ? 0 : state.sidebarWidth));
  return Math.max(320, Math.floor((availableWidth || fallbackAvailableWidth) - 370));
}

function contextPanelWidthKey() {
  return state.evidencePanelExpanded ? "scansci.evidence-panel.width" : "scansci.context-panel.width";
}

function currentContextPanelWidth() {
  return state.evidencePanelExpanded ? state.expandedEvidencePanelWidth : state.contextPanelWidth;
}

function setCurrentContextPanelWidth(value) {
  const width = Math.round(Math.max(280, Math.min(maxContextPanelWidth(), Number(value) || 335)));
  if (state.evidencePanelExpanded) state.expandedEvidencePanelWidth = width;
  else state.contextPanelWidth = width;
  return width;
}

function applyContextPanelWidth({ persist = false } = {}) {
  const layout = byId("conversationLayout");
  const resizer = byId("contextPanelResizer");
  if (!layout) return;
  const width = setCurrentContextPanelWidth(currentContextPanelWidth());
  layout.style.setProperty("--context-panel-width", `${width}px`);
  if (resizer) {
    resizer.setAttribute("aria-valuemax", String(maxContextPanelWidth()));
    resizer.setAttribute("aria-valuenow", String(width));
    resizer.setAttribute("aria-label", state.contextPanel === "evidence" ? "调整全文证据栏宽度" : "调整右侧资料栏宽度");
  }
  if (persist) window.localStorage.setItem(contextPanelWidthKey(), String(width));
}

function canResizeContextPanel() {
  const layout = byId("conversationLayout");
  const panel = byId("contextPanel");
  return Boolean(
    layout
    && panel
    && window.innerWidth > 960
    && state.contextPanel !== "none"
    && !panel.classList.contains("is-hidden")
    && !layout.classList.contains("is-review-workbench"),
  );
}

function installContextPanelResizer() {
  const resizer = byId("contextPanelResizer");
  if (!resizer) return;
  let startX = 0;
  let startWidth = 0;
  let resizing = false;
  const finish = (event) => {
    if (!resizing) return;
    resizing = false;
    byId("conversationLayout")?.classList.remove("is-resizing-context-panel");
    if (event?.pointerId !== undefined && resizer.hasPointerCapture(event.pointerId)) resizer.releasePointerCapture(event.pointerId);
    applyContextPanelWidth({ persist: true });
  };
  resizer.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !canResizeContextPanel()) return;
    event.preventDefault();
    startX = event.clientX;
    startWidth = currentContextPanelWidth();
    resizing = true;
    resizer.focus({ preventScroll: true });
    resizer.setPointerCapture(event.pointerId);
    byId("conversationLayout")?.classList.add("is-resizing-context-panel");
  });
  resizer.addEventListener("pointermove", (event) => {
    if (!resizing) return;
    setCurrentContextPanelWidth(startWidth - (event.clientX - startX));
    applyContextPanelWidth();
  });
  resizer.addEventListener("pointerup", finish);
  resizer.addEventListener("pointercancel", finish);
  resizer.addEventListener("keydown", (event) => {
    if (!canResizeContextPanel()) return;
    const step = event.shiftKey ? 32 : 12;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setCurrentContextPanelWidth(currentContextPanelWidth() + step);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setCurrentContextPanelWidth(currentContextPanelWidth() - step);
    } else if (event.key === "Home") {
      event.preventDefault();
      setCurrentContextPanelWidth(280);
    } else if (event.key === "End") {
      event.preventDefault();
      setCurrentContextPanelWidth(maxContextPanelWidth());
    } else return;
    applyContextPanelWidth({ persist: true });
  });
  window.addEventListener("resize", () => applyContextPanelWidth());
}

async function controlDesktopWindow(method) {
  const api = window.pywebview?.api;
  if (!api || typeof api[method] !== "function") return;
  const result = await api[method]();
  if (method !== "toggle_maximize_window" || !result?.ok) return;
  const button = document.querySelector('[data-action="toggle-maximize-window"]');
  if (!button) return;
  const maximized = Boolean(result.maximized);
  button.setAttribute("aria-label", maximized ? "还原窗口" : "最大化窗口");
  button.setAttribute("title", maximized ? "还原窗口" : "最大化窗口");
}

const profileAvatars = {
  male: { label: "男熊猫", src: "/avatar-panda-male-tight.png" },
  female: { label: "女熊猫", src: "/avatar-panda-female-tight.png" },
};

function renderProfileAvatar() {
  const avatar = profileAvatars[state.profileAvatar] || profileAvatars.male;
  document.querySelectorAll("[data-profile-avatar-image]").forEach((image) => {
    image.src = avatar.src;
  });
  document.querySelectorAll("[data-avatar-value]").forEach((option) => {
    const selected = option.dataset.avatarValue === state.profileAvatar;
    option.classList.toggle("is-selected", selected);
    option.setAttribute("aria-checked", String(selected));
  });
}

function closeProfileAvatarPicker() {
  document.querySelectorAll("[data-profile-picker]").forEach((picker) => {
    picker.classList.remove("is-open");
    picker.querySelector("[data-action='toggle-profile-avatar']")?.setAttribute("aria-expanded", "false");
  });
}

function toggleProfileAvatarPicker(trigger) {
  const picker = trigger.closest("[data-profile-picker]");
  if (!picker) return;
  const open = !picker.classList.contains("is-open");
  closeProfileAvatarPicker();
  picker.classList.toggle("is-open", open);
  trigger.setAttribute("aria-expanded", String(open));
}

function selectProfileAvatar(value) {
  if (!profileAvatars[value]) return;
  state.profileAvatar = value;
  window.localStorage.setItem("scansci.profile.avatar", value);
  renderProfileAvatar();
  closeProfileAvatarPicker();
}

function setView(name, { record = true } = {}) {
  state.activeView = name;
  byId("workbench").classList.toggle("is-settings", name === "settings");
  updateSidebarNavigation();
  document.querySelectorAll(".app-view").forEach((view) => view.classList.toggle("is-active", view.dataset.view === name));
  document.documentElement.scrollTop = 0;
  if (name === "settings") renderSettings();
  if (name === "mode") renderMode();
  if (name === "extensions") renderExtensions();
  if (name === "mcp") renderMcpMarketplaceView();
  if (record) recordNavigation();
}

function updateSidebarNavigation() {
  document.querySelectorAll(".sidebar-action").forEach((button) => {
    const action = button.dataset.action;
    const mode = button.dataset.mode;
    const isActive = (action === "open-extensions" && state.activeView === "extensions")
      || (action === "open-mcp-marketplace" && state.activeView === "mcp")
      || (action === "open-mode" && state.activeView === "mode" && mode === state.activeMode);
    button.classList.toggle("is-active", isActive);
    if (isActive) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function openMode(mode) {
  state.activeMode = mode;
  setView("mode");
}

function openSettings(panel = "general") {
  // Routing is automatic. Keep old deep links/history entries from reopening
  // the retired manual model-role screen.
  state.activeSettings = panel === "routing" ? "general" : panel;
  if (panel === "models" && state.settings?.active_model?.provider_id) {
    state.selectedProviderId = state.settings.active_model.provider_id;
  }
  setView("settings");
}

function openExtensions(tab = "skills") {
  state.activeExtensions = ["plugins", "skills", "market"].includes(tab) ? tab : "skills";
  setView("extensions");
  refreshExtensions({ quiet: true, includeMarket: state.activeExtensions === "market" }).catch((error) => toast(error.message, true));
}

function openMcpMarketplace() {
  setView("mcp");
  loadMcpMarketplace().catch((error) => toast(error.message, true));
}

function startTask() {
  state.activeTaskId = "";
  state.sessionId = null;
  state.sessionTokens = 0;
  state.contextUsagePercent = 0;
  state.sessionStats = null;
  state.streaming = false;
  closeContextUsagePopovers();
  renderContextUsage();
  window.localStorage.removeItem("scansci.active.task");
  window.localStorage.removeItem("scansci.active.session");
  state.directMessages = [];
  setComposerMode("general");
  applyContextPanelPreset("none");
  setView("home");
  window.setTimeout(() => byId("homeQuestionInput").focus(), 0);
}

const contextPanelPresets = Object.freeze({
  research: {
    kind: "sources",
    eyebrow: "研究上下文",
    title: "研究资料",
    countUnit: " 个来源",
    toggleLabel: "研究资料",
    landmarkLabel: "研究资料上下文",
  },
  knowledge: {
    kind: "sources",
    eyebrow: "当前回答",
    title: "知识来源",
    countUnit: " 个可用来源",
    toggleLabel: "知识来源",
    landmarkLabel: "知识问答来源",
  },
  evidence: {
    kind: "sources",
    eyebrow: "可核验上下文",
    title: "证据来源",
    countUnit: " 个来源",
    toggleLabel: "证据来源",
    landmarkLabel: "证据与来源",
  },
  review: {
    kind: "review",
    toggleLabel: "研究稿件",
    landmarkLabel: "研究稿件",
  },
  none: {
    kind: "none",
    toggleLabel: "上下文",
    landmarkLabel: "任务上下文",
  },
});

const contextPanelWorkflowPresets = Object.freeze({
  evidence_index: "evidence",
  ask: "evidence",
  literature_review: "review",
  academic_search: "research",
  deep_research: "review",
  research_idea: "none",
  novelty_check: "evidence",
  ppt_outline: "none",
  ppt_project: "none",
  pdf_to_ppt: "none",
  paper_download: "none",
  paper_download_batch: "none",
  paper_search_download: "none",
});

function contextPanelPresetForRun(run = {}) {
  return contextPanelWorkflowPresets[String(run.workflow_type || "")] || "none";
}

function applyContextPanelPreset(name = "none") {
  const safeName = contextPanelPresets[name] ? name : "none";
  const preset = contextPanelPresets[safeName];
  state.contextPanelPreset = safeName;
  const panel = byId("contextPanel");
  if (panel) {
    panel.dataset.context = safeName;
    panel.setAttribute("aria-label", preset.landmarkLabel);
  }
  const sourceView = byId("sourcePanelView");
  if (sourceView && preset.title) sourceView.setAttribute("aria-label", preset.title);
  const eyebrow = byId("contextPanelEyebrow");
  if (eyebrow && preset.eyebrow) eyebrow.textContent = preset.eyebrow;
  const title = byId("contextPanelTitle");
  if (title && preset.title) title.textContent = preset.title;
  const countUnit = byId("sourceCountUnit");
  if (countUnit && preset.countUnit) countUnit.textContent = preset.countUnit;
  setContextPanel(preset.kind);
}

function setContextPanel(kind = "sources") {
  const safeKind = ["sources", "evidence", "review", "none"].includes(kind) ? kind : "sources";
  const preset = contextPanelPresets[state.contextPanelPreset] || contextPanelPresets.research;
  const review = safeKind === "review";
  const evidence = safeKind === "evidence";
  const unavailable = safeKind === "none";
  const userCollapsed = safeKind === "sources" && state.contextPanelCollapsed;
  const hidden = unavailable || userCollapsed;
  state.contextPanel = safeKind;
  byId("sourcePanelView")?.classList.toggle("is-active", safeKind === "sources");
  byId("evidenceReaderPanel")?.classList.toggle("is-active", evidence);
  byId("reviewDocumentPanel")?.classList.toggle("is-active", review);
  const panel = byId("contextPanel");
  panel?.classList.toggle("is-hidden", hidden);
  if (panel) panel.setAttribute("aria-label", evidence ? "引用证据" : review ? "研究稿件" : preset.landmarkLabel);
  byId("conversationLayout")?.classList.toggle("is-review-workbench", review);
  byId("conversationLayout")?.classList.toggle("is-direct-conversation", unavailable);
  byId("conversationLayout")?.classList.toggle("is-context-collapsed", userCollapsed);
  const toggle = byId("contextPanelToggle");
  if (toggle) {
    const expanded = !hidden;
    const label = evidence ? "引用证据" : preset.toggleLabel;
    toggle.hidden = unavailable || review;
    toggle.classList.toggle("is-active", expanded);
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.setAttribute("aria-label", `${expanded ? "隐藏" : "显示"}${label}`);
    toggle.title = `${expanded ? "隐藏" : "显示"}${label}`;
  }
  syncEvidencePanelExpansion();
  if (!review) byId("conversationLayout")?.classList.remove("is-review-focus");
}

function syncEvidencePanelExpansion() {
  const panel = byId("contextPanel");
  const canExpand = state.contextPanel === "evidence" && !panel?.classList.contains("is-hidden");
  if (!canExpand) state.evidencePanelExpanded = false;
  const expanded = canExpand && state.evidencePanelExpanded;
  byId("conversationLayout")?.classList.toggle("is-evidence-expanded", expanded);
  applyContextPanelWidth();
  const control = byId("evidencePanelExpand");
  if (!control) return;
  control.hidden = !canExpand;
  control.classList.toggle("is-active", expanded);
  control.setAttribute("aria-expanded", String(expanded));
  control.setAttribute("aria-label", expanded ? "收起全文证据面板" : "展开全文证据面板");
  control.title = expanded ? "收起全文证据面板" : "展开全文证据面板";
}

function toggleEvidencePanelExpanded() {
  const panel = byId("contextPanel");
  if (state.contextPanel !== "evidence" || panel?.classList.contains("is-hidden")) return;
  state.evidencePanelExpanded = !state.evidencePanelExpanded;
  if (state.evidencePanelExpanded && !window.localStorage.getItem("scansci.evidence-panel.width")) {
    setCurrentContextPanelWidth(Math.max(state.contextPanelWidth + 160, Math.round(maxContextPanelWidth() * 0.72)));
  }
  syncEvidencePanelExpansion();
}

function toggleContextPanel() {
  if (state.contextPanel === "review" || state.contextPanel === "none") return;
  if (state.contextPanel === "evidence" && state.evidenceReturnPanel !== "sources") {
    closeEvidenceReader();
    return;
  }
  state.contextPanelCollapsed = !byId("contextPanel")?.classList.contains("is-hidden");
  window.localStorage.setItem("scansci.context-panel.collapsed", String(state.contextPanelCollapsed));
  setContextPanel("sources");
}

function renderTasks() {
  const target = byId("taskList");
  renderHistoryControls();
  const query = state.historyQuery.trim().toLowerCase();
  const archived = state.historyView === "archived";
  const availableRuns = state.runs.filter((run) => Boolean(run.archived) === archived);
  const runs = availableRuns.filter((run) => [run.title, run.status, run.updated_at].join(" ").toLowerCase().includes(query));
  if (!availableRuns.length) {
    target.innerHTML = `<p class="history-empty">${archived ? "暂无归档对话" : "暂无对话"}</p>`;
    return;
  }
  if (!runs.length) {
    target.innerHTML = '<p class="history-empty">没有匹配的历史对话</p>';
    return;
  }
  target.innerHTML = runs.slice(0, 80).map((run) => {
    const open = state.historyMenuRunId === run.run_id;
    const manageDisabled = Boolean(run.cancellable || run.status === "needs_confirmation");
    const organizeAction = archived ? "restore-task" : "archive-task";
    const organizeLabel = archived ? "恢复到历史对话" : "归档对话";
    const organizeIcon = archived ? "archive-restore" : "archive";
    return `<div class="task-row ${open ? "has-open-menu" : ""}" data-task-id="${escapeHtml(run.run_id)}"><button type="button" class="task-item ${run.run_id === state.activeTaskId ? "is-active" : ""}" data-action="open-task" data-task-id="${escapeHtml(run.run_id)}"><span>${escapeHtml(compact(runDisplayTitle(run), 28))}</span><time class="task-status ${escapeHtml(run.status)}">${escapeHtml(runStatusLabel(run))}</time></button><button type="button" class="task-more" data-action="toggle-task-menu" data-task-id="${escapeHtml(run.run_id)}" aria-expanded="${open}" aria-label="管理对话" title="管理对话">${uiIcon("more-horizontal")}</button>${open ? `<div class="task-menu" role="menu"><button type="button" data-action="${organizeAction}" data-task-id="${escapeHtml(run.run_id)}" ${manageDisabled ? "disabled" : ""}>${uiIcon(organizeIcon)}<span>${organizeLabel}</span></button><button type="button" class="is-danger" data-action="delete-task" data-task-id="${escapeHtml(run.run_id)}" ${manageDisabled ? "disabled" : ""}>${uiIcon("trash")}<span>删除对话</span></button>${manageDisabled ? '<small>运行结束后可整理</small>' : ""}</div>` : ""}</div>`;
  }).join("");
}

function renderHistoryControls() {
  const area = byId("historyArea");
  const collapse = byId("historyCollapse");
  const searchTrigger = byId("historySearchTrigger");
  const searchPanel = byId("historySearchPanel");
  const search = byId("historySearch");
  const archiveTrigger = byId("historyArchiveTrigger");
  const historyTitle = byId("historyTitle");
  const archived = state.historyView === "archived";
  area?.classList.toggle("is-collapsed", state.historyCollapsed);
  collapse?.setAttribute("aria-expanded", String(!state.historyCollapsed));
  if (historyTitle) historyTitle.textContent = archived ? "已归档" : "历史对话";
  archiveTrigger?.classList.toggle("is-active", archived);
  archiveTrigger?.setAttribute("aria-pressed", String(archived));
  archiveTrigger?.setAttribute("aria-label", archived ? "返回历史对话" : "查看已归档对话");
  archiveTrigger?.setAttribute("title", archived ? "返回历史对话" : "查看已归档对话");
  if (searchPanel) searchPanel.hidden = state.historyCollapsed || !state.historySearchOpen;
  searchTrigger?.setAttribute("aria-expanded", String(!state.historyCollapsed && state.historySearchOpen));
  if (search && search.value !== state.historyQuery) search.value = state.historyQuery;
}

function toggleHistoryCollapse() {
  state.historyCollapsed = !state.historyCollapsed;
  if (state.historyCollapsed) state.historySearchOpen = false;
  window.localStorage.setItem("scansci.history.collapsed", String(state.historyCollapsed));
  renderTasks();
}

function toggleHistorySearch() {
  if (state.historyCollapsed) state.historyCollapsed = false;
  state.historySearchOpen = !state.historySearchOpen;
  if (!state.historySearchOpen) state.historyQuery = "";
  window.localStorage.setItem("scansci.history.collapsed", String(state.historyCollapsed));
  renderTasks();
  if (state.historySearchOpen) window.setTimeout(() => byId("historySearch")?.focus(), 0);
}

function toggleHistoryView() {
  state.historyView = state.historyView === "archived" ? "active" : "archived";
  state.historyMenuRunId = "";
  state.historyQuery = "";
  state.historySearchOpen = false;
  window.localStorage.setItem("scansci.history.view", state.historyView);
  renderTasks();
}

function toggleTaskMenu(runId) {
  state.historyMenuRunId = state.historyMenuRunId === runId ? "" : runId;
  renderTasks();
  if (state.historyMenuRunId) {
    positionTaskMenu();
    window.requestAnimationFrame(positionTaskMenu);
    window.setTimeout(positionTaskMenu, 0);
  }
}

function positionTaskMenu() {
  const list = byId("taskList");
  const row = list?.querySelector(".task-row.has-open-menu");
  const menu = row?.querySelector(".task-menu");
  if (!list || !row || !menu) return;
  const rowRect = row.getBoundingClientRect();
  const width = Math.max(220, Math.round(rowRect.width - 10));
  menu.style.width = `${Math.min(width, window.innerWidth - 24)}px`;
  menu.style.left = `${Math.max(12, Math.round(rowRect.left + 10))}px`;
  const neededHeight = menu.offsetHeight + 8;
  const opensDownward = rowRect.top < neededHeight + 12;
  menu.classList.toggle("opens-downward", opensDownward);
  menu.style.top = `${Math.round(opensDownward ? rowRect.bottom + 6 : rowRect.top - menu.offsetHeight - 6)}px`;
}

async function archiveTask(runId) {
  state.historyMenuRunId = "";
  const run = await request(`/api/runs/${encodeURIComponent(runId)}/archive`, { method: "POST", body: "{}" });
  upsertRun(run);
  if (state.activeTaskId === runId) startTask();
  toast("对话已归档");
}

async function restoreTask(runId) {
  state.historyMenuRunId = "";
  const run = await request(`/api/runs/${encodeURIComponent(runId)}/restore`, { method: "POST", body: "{}" });
  upsertRun(run);
  toast("对话已恢复");
}

async function deleteTask(runId) {
  const run = state.runs.find((item) => item.run_id === runId);
  const title = compact(runDisplayTitle(run || {}), 36);
  const confirmed = await requestConfirmation({
    eyebrow: "永久删除",
    title: "删除这条对话？",
    subject: title,
    message: "此操作不可撤销，但已经导出的 PPTX、Markdown 和下载的论文文件会保留。",
    confirmLabel: "删除对话",
    danger: true,
  });
  if (!confirmed) return;
  state.historyMenuRunId = "";
  await request(`/api/runs/${encodeURIComponent(runId)}/delete`, { method: "POST", body: "{}" });
  state.runs = state.runs.filter((item) => item.run_id !== runId);
  if (state.activeTaskId === runId) startTask();
  else renderTasks();
  toast("对话已删除");
}

function runStatusLabel(run) {
  if (run.cancel_requested) return "停止中";
  return ({ queued: "排队中", planning: "规划中", running: "执行中", verifying: "核验中", needs_confirmation: "待确认", waiting_input: "等待回答", paused: "已暂停", completed: "已完成", failed: "失败", cancelled: "已停止" })[run.status] || run.status;
}

function progressWidthClass(value) {
  const percent = Math.max(0, Math.min(100, Math.round(Number(value || 0))));
  return `progress-pct-${Math.round(percent / 5) * 5}`;
}

function upsertRun(run) {
  const index = state.runs.findIndex((item) => item.run_id === run.run_id);
  if (index >= 0) state.runs[index] = run;
  else state.runs.unshift(run);
  state.runs.sort((left, right) => String(right.updated_at).localeCompare(String(left.updated_at)));
  renderTasks();
}

function renderSources() {
  const query = state.sourceQuery.toLowerCase();
  const sources = (state.notebook?.sources || []).filter((source) => [source.title, source.doi, source.doc_id].join(" ").toLowerCase().includes(query));
  byId("sourceCount").textContent = state.notebook?.counts?.sources || 0;
  if (!sources.length) {
    sourceList.innerHTML = `<div class="source-empty">${query ? "未找到文献" : "暂无来源"}</div>`;
    return;
  }
  sourceList.innerHTML = "";
  const template = byId("sourceTemplate");
  sources.forEach((source) => {
    const item = template.content.cloneNode(true);
    item.querySelector("strong").textContent = compact(source.title || source.doc_id, 110);
    item.querySelector("small").textContent = source.doi || source.publication_year || source.doc_id;
    item.querySelector(".source-open").addEventListener("click", () => openSourceReader(source));
    sourceList.appendChild(item);
  });
}

async function legacyAskQuestion(event, inputId) {
  event.preventDefault();
  const input = byId(inputId);
  const key = composerKey(inputId);
  const images = imagePayloadForComposer(key);
  const sourceFiles = sourcePayloadForComposer(key);
  const question = input.value.trim() || (sourceFiles.length ? `请将「${sourceFiles[0].name}」制作成一份科研幻灯片。` : images.length ? "请分析我粘贴的图片，并结合当前资料库回答。" : "");
  if (!question) return;
  const mode = composerMode(inputId);
  const isDirectConversation = !state.notebook && mode === "general";
  const isStandaloneSlides = mode === "slides" && sourceFiles.length > 0;
  if (!state.notebook && !isDirectConversation && !isStandaloneSlides) {
    toast("写作需要先打开资料库；制作幻灯片可直接添加 PDF、Word、Markdown、TXT 或 HTML。", true);
    return;
  }
  if (sourceFiles.length && mode !== "slides") {
    toast("文档附件用于制作幻灯片，已切换到“幻灯片”模式", true);
    setComposerMode("slides");
    return;
  }
  if (mode === "slides" && !state.notebook && !sourceFiles.length) {
    toast("请先添加 PDF、Word、Markdown、TXT 或 HTML；制作幻灯片不需要资料库。", true);
    return;
  }
  if (isDirectConversation && images.length) {
    toast("图片对话请先打开资料库后再使用。", true);
    return;
  }
  if (images.length && mode !== "general") {
    toast("图片提问目前仅支持“通用”模式", true);
    return;
  }
  if (images.length && !currentModelSupportsVision()) {
    toast("请先在模型菜单选择带“视觉”标签的模型", true);
    return;
  }
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  let streamingMessage = null;
  byId("conversationTitle").textContent = compact(question, 80);
  applyContextPanelPreset(isDirectConversation || isStandaloneSlides ? "none" : ["writing", "deep-research"].includes(mode) ? "review" : "evidence");
  setView("conversation");
  byId("answerArea").innerHTML = `<div class="conversation-thread"><div class="user-turn"><div class="user-turn-bubble">${composerSourcePreviewMarkup(sourceFiles)}${composerImagePreviewMarkup(images)}<p>${escapeHtml(question)}</p></div></div><p class="loading-line">${isDirectConversation ? "正在生成回复…" : isStandaloneSlides ? "正在解析材料并制作可编辑 PPTX…" : "正在建立研究任务…"}</p></div>`;
  if (["writing", "deep-research"].includes(mode)) renderReviewDocument({ title: question, status: "planning", progress: 0 }, null);
  try {
    if (isDirectConversation) {
      const messages = [...state.directMessages, { role: "user", content: question, created_at: new Date().toISOString() }].slice(-16);
      const startedAt = performance.now();
      streamingMessage = { role: "assistant", content: "", streaming: true, created_at: new Date().toISOString() };
      state.directMessages = [...messages, streamingMessage].slice(-16);
      renderDirectConversation();
      let completed = false;
      await streamChat({ messages, thinking_level: currentThinkingLevel() }, (eventType, event) => {
        if (eventType === "delta") {
          streamingMessage.content += String(event.content || "");
          scheduleDirectConversationRender();
          return;
        }
        if (eventType === "done") {
          const message = {
            ...event.message,
            usage: event.message?.usage || streamingMessage.usage,
            created_at: event.message?.created_at || new Date().toISOString(),
            processing_ms: Math.max(0, Math.round(performance.now() - startedAt)),
          };
          const messageIndex = state.directMessages.indexOf(streamingMessage);
          if (messageIndex >= 0) state.directMessages[messageIndex] = message;
          completed = true;
          // B1: context usage %
          updateSessionStats(event.stats || null);
          scheduleDirectConversationRender();
          return;
        }
        // A1: track session ID for compaction/resume
        if (eventType === "session") {
          state.sessionId = String(event.session_id || "");
          if (state.sessionId) window.localStorage.setItem("scansci.active.session", state.sessionId);
          return;
        }
        // A2: tool execution progress
        if (eventType === "tool.completed" || eventType === "tool.failed") {
          state.toolProgress = { name: event.name, status: eventType === "tool.completed" ? "done" : "error", result: event.result };
          scheduleDirectConversationRender();
          return;
        }
        if (eventType === "status" && event.tool_name) {
          state.toolProgress = { name: event.tool_name, status: "running" };
          scheduleDirectConversationRender();
          return;
        }
        // B2: auto-retry notification
        if (eventType === "status" && event.subtype === "retry") {
          const attempt = Number(event.attempt || 1);
          const delay = Math.round(Number(event.delay_ms || 0) / 1000);
          toast(delay ? `正在重试（第 ${attempt} 次，${delay}s 后）…` : `正在重试（第 ${attempt} 次）…`);
          return;
        }
        if (eventType === "compaction") {
          if (event.status === "started") toast("上下文过长，正在自动压缩…");
          else if (event.status === "completed") {
            const before = Number(event.tokens_before || 0);
            const after = Number(event.tokens_after || 0);
            toast(before && after ? `上下文已压缩：${formatTokenCount(before)} → ${formatTokenCount(after)} tokens` : "上下文已压缩");
          }
          return;
        }
        // B3: compatibility fallback
        if (eventType === "compatibility.fallback") {
          toast("Pi Agent 当前不可用，已回退到直连模型——回答质量可能受限");
          return;
        }
      });
      if (!completed) throw new Error("The model stream ended before a final response was received.");
      input.value = "";
      return;
    }
    const { workflowType, workflowInput } = composerRun(mode, question, images, sourceFiles);
    const run = await createResearchRun(workflowType, workflowInput);
    state.activeTaskId = run.run_id;
    window.localStorage.setItem("scansci.active.task", run.run_id);
    upsertRun(run);
    if (mode === "download") {
      state.pendingBatchIdentifiers = [];
      state.pendingBatchFilename = "";
      renderHomeBatchAttachment();
    }
    renderRun(run);
    watchRun(run.run_id, (next) => {
      if (state.activeView === "conversation" && state.activeTaskId === next.run_id) renderRun(next);
    });
    input.value = "";
    clearComposerImages(key);
    clearComposerSources(key);
  } catch (error) {
    if (isDirectConversation && streamingMessage) {
      streamingMessage.streaming = false;
      streamingMessage.content ||= "生成回复时发生错误。";
      streamingMessage.error = error.message;
      renderDirectConversation();
      toast(error.message, true);
    } else {
      byId("answerArea").innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
    }
  } finally {
    button.disabled = false;
  }
}

async function askQuestion(event, inputId) {
  event.preventDefault();
  // `Event.currentTarget` is only guaranteed while the synchronous submit
  // handler is running. General mode may await the route preview below; by
  // then browsers reset `currentTarget` to null. Capture the form/button
  // before the first await so click-to-send and Enter-to-send share a stable
  // submission path.
  const form = event.currentTarget;
  const button = form?.querySelector?.("button[type=submit]");
  const input = byId(inputId);
  if (!input || !button) {
    console.error("ScanSci composer submission is missing its input or submit button", { inputId });
    toast("发送控件未准备好，请刷新后重试。", true);
    return;
  }
  const key = composerKey(inputId);
  const selectedMode = composerMode(inputId);
  const images = imagePayloadForComposer(key);
  const sourceFiles = sourcePayloadForComposer(key);
  const activeRun = state.runs.find((item) => item.run_id === state.activeTaskId);
  // The selected historical task is the source of truth.  `activeView` can
  // briefly be `home` during navigation/refresh even though the task id is
  // already restored, which previously routed a follow-up to a brand-new
  // direct chat and silently dropped the task context.
  const isTaskConversation = inputId === "chatQuestionInput" && Boolean(activeRun);
  let question = input.value.trim() || (selectedMode === "download" && state.pendingBatchIdentifiers.length
    ? state.pendingBatchIdentifiers.join("\n")
    : sourceFiles.length
    ? selectedMode === "slides"
      ? `请将《${sourceFiles[0].name}》制作成一份科研幻灯片。`
      : `请阅读《${sourceFiles[0].name}》并概括最重要的信息。`
    : images.length ? "请分析我粘贴的图片。" : "");
  if (!question) return;
  let mode = ["research", "academic"].includes(selectedMode) ? resolveResearchComposerMode(question) : selectedMode;

  // An open historical task is a chat thread. Composer modes only affect new
  // tasks; changing the mode must never fork an already-open conversation.
  const isTaskFollowUp = isTaskConversation;
  if (isTaskFollowUp && (sourceFiles.length || images.length)) {
    toast("当前对话暂不支持追加附件，请先发送文字反馈。", true);
    return;
  }
  const isReviewWorkflow = inputId === "reviewQuestionInput";
  const selectedKnowledge = selectedKnowledgeNotebooks();
  const searchableKnowledgeSelected = selectedKnowledge.some((notebook) => Number(notebook.counts?.sources || 0) > 0);
  let routedTask = null;
  // General input stays general by default.  For an explicit, multi-step
  // product request the host may offer a durable route; the server repeats
  // this decision when creating the run, so this preview is never authority.
  if (selectedMode === "general" && !isTaskFollowUp && !isReviewWorkflow && !images.length && !sourceFiles.length) {
    try {
      const decision = await previewFreeformTask(question);
      if (decision?.route === "durable_run" && decision?.workflow_type) {
        routedTask = decision;
        mode = String(decision.presentation_mode || mode);
      }
    } catch (error) {
      // A routing preview is an enhancement, not a gate for normal chat.
      console.warn("Freeform task preview unavailable", error);
    }
  }
  const isDirectConversation = !isReviewWorkflow && !routedTask && (mode === "general" || mode === "writing");
  const directChatMode = isDirectConversation && searchableKnowledgeSelected ? "knowledge" : mode;
  const isStandaloneSlides = mode === "slides" && sourceFiles.length > 0;
  if (mode === "knowledge" && !selectedKnowledge.length && !isTaskFollowUp) {
    toast("知识库问答需要先选择一个知识库；通用和写作模式可直接使用。", true);
    return;
  }
  if (isDirectConversation && selectedKnowledge.length && !searchableKnowledgeSelected && !isTaskFollowUp) {
    toast("所选知识库还没有可检索内容。请等待导入或索引完成，或改选其他知识库。", true);
    return;
  }
  if (["novelty", "idea"].includes(mode) && !state.notebook && !isTaskFollowUp) {
    const workflowLabel = mode === "novelty" ? "证据查新" : "研究构思";
    toast(`${workflowLabel}需要一个知识库来保存全文和句级证据；请先新建或选择知识库。`, true);
    return;
  }
  // A topic alone is sufficient to start a presentation project.  Source
  // material enriches the result but is not a precondition: shortcuts are
  // aids for getting started, not permission gates.
  if (images.length && mode !== "general") {
    toast("图片提问目前仅支持通用模式。", true);
    return;
  }
  if (images.length && !currentModelSupportsVision()) {
    toast("请先选择带有视觉能力的模型。", true);
    return;
  }
  if (mode === "academic" && !isTaskFollowUp && !routedTask) {
    try {
      await openAcademicSearchPlan(question, { inputId, key, sourceFiles, images });
    } catch (error) {
      toast(`无法生成检索计划：${error.message}`, true);
    }
    return;
  }

  button.disabled = true;
  let streamingMessage = null;
  byId("conversationTitle").textContent = compact(question, 80);
  applyContextPanelPreset(directChatMode === "knowledge" ? "knowledge" : mode === "deep-research" ? "review" : "none");
  setView("conversation");
  if (isTaskFollowUp) {
    renderPendingTaskFollowUp(activeRun, question);
  } else {
    state.conversationAutoFollow = true;
    byId("answerArea").innerHTML = `<div class="conversation-thread"><div class="user-turn"><div class="user-turn-bubble">${composerSourcePreviewMarkup(sourceFiles)}${composerImagePreviewMarkup(images)}<p>${escapeHtml(question)}</p></div></div><p class="loading-line">${isDirectConversation ? "正在生成回复…" : isStandaloneSlides ? "正在解析材料并制作可编辑 PPTX…" : "正在建立研究任务…"}</p></div>`;
    followLatestConversationMessage();
  }
  if (mode === "deep-research" || (mode === "knowledge" && state.evidenceOutputMode === "review")) renderReviewDocument({ title: question, status: "planning", progress: 0 }, null);
  try {
    if (isTaskFollowUp) {
      // Clear the composer before waiting for the task endpoint.  Follow-up
      // requests can take several seconds while the task is queued; keeping
      // the submitted text in the input makes a still-connected thread look
      // like the message was never sent (and invites duplicate submissions).
      input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      const result = await continueTaskConversation(activeRun.run_id, question);
      const run = result.run;
      state.activeTaskId = run.run_id;
      window.localStorage.setItem("scansci.active.task", run.run_id);
      upsertRun(run);
      state.lastRunRenderKey = "";
      renderRun(run);
      state.sessionId = `research-run-${run.run_id}`;
      window.localStorage.setItem("scansci.active.session", state.sessionId);
      void restoreSessionStats(estimateRunSessionStats(run));
      if (["queued", "planning", "running", "verifying"].includes(String(run.status || ""))) {
        watchRun(run.run_id, (next) => {
          if (state.activeView === "conversation" && state.activeTaskId === next.run_id) renderRun(next);
        });
      }
      return;
    }
    if (isDirectConversation) {
      const knowledgeScopes = selectedKnowledge.map((notebook) => ({
        notebook_id: String(notebook.notebook_id),
        title: knowledgeScopeTitle(notebook),
      }));
      const userMessage = { role: "user", content: question, sources: sourceFiles, images, created_at: new Date().toISOString() };
      const messages = [...state.directMessages, userMessage].filter((message) => !message.streaming).slice(-16);
      const startedAt = performance.now();
      streamingMessage = { role: "assistant", content: "", streaming: true, mode: directChatMode, trace: [], knowledgeScopes, created_at: new Date().toISOString() };
      state.directMessages = [...messages, streamingMessage].slice(-16);
      state.conversationAutoFollow = true;
      renderDirectConversation({ forceFollow: true });
      let completed = false;
      state.streaming = true;
      activeDirectChatController = new AbortController();
      await streamChat(
        {
          messages,
          images,
          source_files: sourceFiles,
          thinking_level: currentThinkingLevel(),
          chat_mode: directChatMode,
          web_search: state.webSearchMode,
          ...(selectedKnowledge[0] ? { notebook_id: selectedKnowledge[0].notebook_id } : {}),
          ...(selectedKnowledge.length ? { notebook_ids: selectedKnowledge.map((notebook) => notebook.notebook_id) } : {}),
          ...(activeKnowledgeScopePayload() ? { knowledge_scope: activeKnowledgeScopePayload() } : {}),
          ...(selectedKnowledge.length ? { knowledge_scopes: activeKnowledgeScopePayloads() } : {}),
          skills: extractSkillMentions(question),
        },
        (eventType, payload) => {
          if (eventType === "RUN_STARTED") {
            const controlRunId = String(payload.runId || payload.run_id || "");
            state.activeStreamRunId = controlRunId;
            streamingMessage.control_run_id = controlRunId;
            return;
          }
          if (eventType === "delta" || eventType === "TEXT_MESSAGE_CONTENT") {
            streamingMessage.content += String(payload.content || payload.delta || "");
            scheduleDirectConversationRender();
            return;
          }
          if (eventType === "STEP_FINISHED" && payload.stepName === "ingest_attachments" && payload.result?.sources) {
            userMessage.sources = payload.result.sources;
            scheduleDirectConversationRender();
            return;
          }
          if (eventType === "CUSTOM" && payload.name === "usage") {
            streamingMessage.usage = payload.value || {};
            return;
          }
          if (eventType === "CUSTOM" && payload.name === "session_stats") {
            updateSessionStats(payload.value || {});
            return;
          }
          if (eventType === "CUSTOM" && payload.name === "process_trace") {
            streamingMessage.trace = Array.isArray(payload.value) ? payload.value : [];
            scheduleDirectConversationRender();
            return;
          }
          if (eventType === "CUSTOM" && payload.name === "interaction") {
            streamingMessage.interaction = payload.value || null;
            scheduleDirectConversationRender();
            return;
          }
          if (eventType === "done" || eventType === "RUN_FINISHED") {
            const result = payload.result || payload;
            const message = {
              ...result.message,
              mode: directChatMode,
              knowledgeScopes,
              usage: result.message?.usage || streamingMessage.usage,
              created_at: result.message?.created_at || new Date().toISOString(),
              processing_ms: Math.max(0, Math.round(performance.now() - startedAt)),
            };
            updateSessionStats(result.stats || result.agent_runtime?.session_stats || payload.stats || null);
            if (result.agent_runtime?.session?.session_id) {
              state.sessionId = String(result.agent_runtime.session.session_id);
              window.localStorage.setItem("scansci.active.session", state.sessionId);
            }
            const messageIndex = state.directMessages.indexOf(streamingMessage);
            if (messageIndex >= 0) state.directMessages[messageIndex] = message;
            completed = true;
            scheduleDirectConversationRender();
          }
        },
        { signal: activeDirectChatController.signal },
      );
      if (!completed) throw new Error("模型流在最终回复到达前结束。");
      input.value = "";
      clearComposerImages(key);
      clearComposerSources(key);
      return;
    }

    const { workflowType, workflowInput } = routedTask
      ? {
          workflowType: "auto",
          workflowInput: { question, task_origin: "freeform" },
        }
      : composerRun(mode, question, images, sourceFiles);
    if (isReviewWorkflow) Object.assign(workflowInput, reviewWorkflowPreferences());
    const run = await createResearchRun(workflowType, workflowInput);
    state.activeTaskId = run.run_id;
    window.localStorage.setItem("scansci.active.task", run.run_id);
    upsertRun(run);
    state.sessionId = `research-run-${run.run_id}`;
    window.localStorage.setItem("scansci.active.session", state.sessionId);
    updateSessionStats(estimateRunSessionStats(run));
    renderRun(run);
    watchRun(run.run_id, (next) => {
      if (state.activeView === "conversation" && state.activeTaskId === next.run_id) renderRun(next);
    });
    input.value = "";
    clearComposerImages(key);
    clearComposerSources(key);
  } catch (error) {
    if (error?.name === "AbortError") {
      if (streamingMessage) {
        streamingMessage.streaming = false;
        streamingMessage.error = "已停止生成";
        renderDirectConversation();
      }
      return;
    }
    if (isTaskFollowUp && activeRun) {
      renderFailedTaskFollowUp(activeRun, question, error);
      toast(error.message, true);
    } else if (isDirectConversation && streamingMessage) {
      streamingMessage.streaming = false;
      streamingMessage.content ||= "生成回复时发生错误。";
      streamingMessage.error = error.message;
      streamingMessage.failure = error.failure || null;
      renderDirectConversation();
      toast(error.message, true);
    } else {
      byId("answerArea").innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
    }
  } finally {
    activeDirectChatController = null;
    state.activeStreamRunId = "";
    state.streaming = false;
    button.disabled = false;
  }
}

function formatProcessingDuration(milliseconds) {
  const totalSeconds = Math.max(0, Number(milliseconds || 0)) / 1000;
  if (totalSeconds < 1) return "不足 1 秒";
  if (totalSeconds >= 60) {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = Math.round(totalSeconds % 60);
    return `${minutes}分 ${seconds}秒`;
  }
  return `${totalSeconds < 10 ? totalSeconds.toFixed(1) : Math.round(totalSeconds)} 秒`;
}

function formatTokenCount(value) {
  const count = Number(value);
  if (!Number.isFinite(count) || count < 0) return "";
  return new Intl.NumberFormat("zh-CN").format(Math.round(count));
}

function estimateTokenCount(text) {
  const value = String(text || "");
  if (!value) return 0;
  const cjk = (value.match(/[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]/g) || []).length;
  const remainder = value.length - cjk;
  return Math.max(1, Math.ceil(cjk * 0.92 + remainder / 3.8));
}

function formatMessageTime(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "";
  const pad = (part) => String(part).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function providerForId(providerId) {
  const id = String(providerId || "");
  return (state.settings?.providers || []).find((item) => String(item.id) === id)
    || (state.presets?.providers || []).find((item) => String(item.id) === id)
    || activeModel().provider
    || { id: id || "scansci-managed", name: "ScanSci" };
}

function messageModelIdentity(model = null) {
  const active = activeModel();
  const providerId = String(model?.provider_id || active.provider?.id || "scansci-managed");
  const modelId = String(model?.model_id || active.model?.id || "");
  const provider = providerForId(providerId);
  const configuredModel = provider?.models?.find((item) => String(item.id) === modelId);
  return {
    provider,
    providerId,
    modelId,
    modelName: configuredModel?.name || modelId || "ScanSci",
  };
}

function messageUsageValues(usage) {
  const source = usage && typeof usage === "object" ? usage : {};
  const tokens = source.tokens && typeof source.tokens === "object" ? source.tokens : source;
  const provided = [
    "prompt_tokens",
    "input_tokens",
    "input",
    "completion_tokens",
    "output_tokens",
    "output",
    "total_tokens",
    "total",
  ].some((key) => Object.prototype.hasOwnProperty.call(tokens, key));
  const prompt = Number(tokens.prompt_tokens ?? tokens.input_tokens ?? tokens.input ?? 0) || 0;
  const completion = Number(tokens.completion_tokens ?? tokens.output_tokens ?? tokens.output ?? 0) || 0;
  const hasDirectional = [
    "prompt_tokens",
    "input_tokens",
    "input",
    "completion_tokens",
    "output_tokens",
    "output",
  ].some((key) => Object.prototype.hasOwnProperty.call(tokens, key));
  const providerTotal = Number(tokens.total_tokens ?? tokens.total ?? 0) || 0;
  const total = hasDirectional ? prompt + completion : providerTotal;
  return { prompt, completion, total, provided };
}

function messageUsageMarkup(role, content, usage, promptContent = "") {
  const measured = messageUsageValues(usage);
  const prompt = measured.provided ? measured.prompt : (role === "assistant" ? estimateTokenCount(promptContent) : 0);
  const completion = measured.provided ? measured.completion : (role === "assistant" ? estimateTokenCount(content) : 0);
  const total = measured.provided
    ? measured.total
    : (role === "assistant" ? prompt + completion : estimateTokenCount(content));
  if (!measured.provided && !total) return "";
  const detail = role === "assistant"
    ? ` <span aria-label="输入 Tokens">↑${formatTokenCount(prompt)}</span> <span aria-label="输出 Tokens">↓${formatTokenCount(completion)}</span>`
    : "";
  return `<p class="message-usage">Tokens: ${formatTokenCount(total)}${detail}</p>`;
}

function messageFooterMarkup(content, usageMarkup, isUser) {
  const copyText = String(content || "");
  const copyAction = copyText.trim()
    ? `<div class="message-hover-actions"><button type="button" class="message-copy-button" data-action="copy-conversation-message" data-copy-text="${escapeHtml(copyText)}" aria-label="复制消息" title="复制消息">${uiIcon("copy")}</button></div>`
    : "";
  if (!copyAction && !usageMarkup) return "";
  return `<footer class="message-footer">${isUser ? `${usageMarkup}${copyAction}` : `${copyAction}${usageMarkup}`}</footer>`;
}

function userAvatarMarkup() {
  const avatar = profileAvatars[state.profileAvatar] || profileAvatars.male;
  return `<span class="message-avatar is-user"><img src="${escapeHtml(avatar.src)}" alt="" /></span>`;
}

function conversationMessageMarkup({
  role,
  content = "",
  contentMarkup = "",
  createdAt = "",
  usage = null,
  model = null,
  label = "",
  processing = "",
  extra = "",
  classes = "",
  promptContent = "",
} = {}) {
  const isUser = role === "user";
  const identity = messageModelIdentity(model);
  const body = contentMarkup || (isUser
    ? `<div class="user-turn-bubble"><p>${escapeHtml(content)}</p></div>`
    : `<div class="answer-sentence">${renderAssistantContent(content)}</div>`);
  const avatar = isUser ? userAvatarMarkup() : `<span class="message-avatar is-assistant">${providerLogo(identity.provider)}</span>`;
  const name = isUser ? "你" : (identity.modelName ? `${identity.modelName} | ${identity.provider?.name || "ScanSci"}` : "ScanSci");
  const badge = label ? `<b>${escapeHtml(label)}</b>` : "";
  const time = `<time datetime="${escapeHtml(createdAt || "")}">${escapeHtml(formatMessageTime(createdAt))}</time>`;
  const usageMarkup = messageUsageMarkup(role, content, usage, promptContent);
  const footer = messageFooterMarkup(content, usageMarkup, isUser);
  return `<div class="conversation-message ${isUser ? "user-turn is-user" : "assistant-turn is-assistant"} ${escapeHtml(classes)}">${isUser ? "" : avatar}<div class="message-body"><header class="message-meta"><strong>${escapeHtml(name)}</strong>${badge}${time}</header>${processing}${body}${extra}${footer}</div>${isUser ? avatar : ""}</div>`;
}

function processTraceMarkup(message, duration) {
  const trace = Array.isArray(message.trace) ? message.trace : [];
  if (!trace.length) return "";
  const status = duration > 0 ? `已处理 <time>${formatProcessingDuration(duration)}</time>` : "正在处理";
  const rows = trace.map((item) => `<li><strong>${escapeHtml(item.title || "处理步骤")}</strong><span>${escapeHtml(item.detail || "")}</span></li>`).join("");
  return `<details class="answer-processing" aria-label="本次对话处理过程"><summary>${status}${uiIcon("chevron-right", "answer-processing-chevron")}</summary>${rows ? `<ol>${rows}</ol>` : ""}</details>`;
}

const knowledgeRetrievalToolNames = new Set([
  "search_local_evidence",
  "catalog_library_documents",
  "kb_search",
  "zotero_search",
  "zotero_fulltext",
  "obsidian_search",
  "obsidian_read",
  "notion_search",
  "notion_read",
]);

function traceToolNames(message) {
  const trace = Array.isArray(message.trace) ? message.trace : [];
  return trace.map((item) => {
    const explicitName = item?.tool_name || item?.tool || item?.name;
    if (explicitName) return String(explicitName);
    const detail = String(item?.detail || "");
    return detail.match(/(?:ScanSci 工具：|^)([a-z][a-z0-9_-]*)/i)?.[1] || "";
  }).filter(Boolean);
}

function directKnowledgeReceiptMarkup(message) {
  const scopes = Array.isArray(message.knowledgeScopes) ? message.knowledgeScopes : [];
  if (!scopes.length) return "";
  const names = scopes.map((scope) => String(scope.title || "知识库")).filter(Boolean);
  if (!names.length) return "";
  const reader = message.reader_answer || {};
  const catalog = reader.presentation === "catalog" ? (reader.catalog || {}) : null;
  const catalogIsList = catalog?.operation === "list";
  const retrieved = traceToolNames(message).some((name) => knowledgeRetrievalToolNames.has(name));
  const citationCount = Number(reader.citation_count || (reader.citations || []).length || 0);
  const citationsVerified = Boolean(message.citation_verification?.passed);
  const stateLabel = catalog ? (catalogIsList ? "已检索题录" : "已统计") : (retrieved ? "已检索" : "已选择");
  const scopeLabel = names.join("、");
  const description = catalog
    ? (catalogIsList ? `已在 ${scopeLabel} 中检索题录` : `已对 ${scopeLabel} 进行文献去重统计`)
    : (retrieved
    ? `本次回答已检索：${scopeLabel}`
    : `本次回答已选择：${scopeLabel}`);
  const evidenceCount = catalog
    ? `<em title="按文献记录去重，不是原文片段数">${Number(catalog.document_count || 0)} 篇</em>`
    : (citationsVerified && citationCount
    ? `<em title="每个脚标均可回跳到原文片段">${citationCount} 处原文</em>`
    : "");
  return `<div class="direct-knowledge-receipt ${retrieved ? "is-retrieved" : ""}" title="${escapeHtml(description)}" aria-label="${escapeHtml(description)}">${uiIcon("library")}<strong>${stateLabel}</strong><span>${escapeHtml(scopeLabel)}</span>${evidenceCount}</div>`;
}

function interactionMarkup(interaction) {
  if (!interaction || interaction.resolved) return "";
  const payload = interaction.payload || {};
  const kind = interaction.kind || "ask_user";
  const question = payload.question || payload.summary || (kind === "plan" ? "请确认执行计划" : "需要你的选择");
  const planSteps = Array.isArray(payload.steps)
    ? `<ol>${payload.steps.map((step) => `<li><strong>${escapeHtml(step.title || step.id || "步骤")}</strong>${step.description ? `<span>${escapeHtml(step.description)}</span>` : ""}</li>`).join("")}</ol>`
    : "";
  const options = kind === "plan"
    ? [
      { id: "approve", label: "批准并继续" },
      { id: "revise", label: "需要修改" },
      { id: "cancel", label: "取消" },
    ]
    : (Array.isArray(payload.options) ? payload.options : []);
  const optionButtons = options.map((option) => `<button type="button" data-action="respond-agent-interaction" data-run-id="${escapeHtml(interaction.run_id || "")}" data-interaction-id="${escapeHtml(interaction.interaction_id || "")}" data-interaction-kind="${escapeHtml(kind)}" data-response-id="${escapeHtml(option.id || option.label || "")}">${escapeHtml(option.label || option.id || "选择")}</button>`).join("");
  const freeform = kind !== "plan" && (payload.allow_freeform !== false || !options.length)
    ? `<div class="agent-interaction-freeform"><input type="text" data-interaction-input placeholder="输入你的回答" /><button type="button" data-action="respond-agent-interaction" data-run-id="${escapeHtml(interaction.run_id || "")}" data-interaction-id="${escapeHtml(interaction.interaction_id || "")}" data-interaction-kind="${escapeHtml(kind)}" data-freeform="true">继续</button></div>`
    : "";
  return `<section class="agent-interaction-card ${kind === "plan" ? "is-plan" : "is-question"}"><header><span>${kind === "plan" ? "执行计划" : "需要你的决定"}</span><b>任务已安全暂停</b></header><h3>${escapeHtml(question)}</h3>${payload.reason ? `<p>${escapeHtml(payload.reason)}</p>` : ""}${planSteps}<div class="agent-interaction-actions">${optionButtons}</div>${freeform}</section>`;
}

function renderPendingTaskFollowUp(run, question) {
  state.conversationAutoFollow = true;
  state.lastRunRenderKey = "";
  renderRun(run);
  const answerArea = byId("answerArea");
  const runShell = answerArea?.querySelector(".run-shell");
  if (!answerArea || !runShell) return;
  let thread = runShell.querySelector(".task-conversation .conversation-thread");
  if (!thread) {
    runShell.insertAdjacentHTML("beforeend", '<section class="task-conversation is-pending" aria-label="任务消息"><div class="conversation-thread"></div></section>');
    thread = runShell.querySelector(".task-conversation .conversation-thread");
  }
  const userMessage = conversationMessageMarkup({
    role: "user",
    content: question,
    createdAt: new Date().toISOString(),
    classes: "is-pending-follow-up",
  });
  const pendingAnswer = conversationMessageMarkup({
    role: "assistant",
    content: "",
    contentMarkup: '<div class="answer-sentence"></div>',
    createdAt: new Date().toISOString(),
    label: "自动",
    extra: '<div class="generation-indicator" role="status" aria-label="正在生成回复"><span class="generation-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>',
    classes: "is-pending-follow-up",
    promptContent: question,
  });
  thread?.insertAdjacentHTML("beforeend", `${userMessage}${pendingAnswer}`);
  followLatestConversationMessage();
}

function renderFailedTaskFollowUp(run, question, error) {
  const scrollSnapshot = conversationScrollSnapshot();
  state.lastRunRenderKey = "";
  renderRun(run);
  const answerArea = byId("answerArea");
  const runShell = answerArea?.querySelector(".run-shell");
  if (!answerArea || !runShell) return;
  let thread = runShell.querySelector(".task-conversation .conversation-thread");
  if (!thread) {
    runShell.insertAdjacentHTML("beforeend", '<section class="task-conversation" aria-label="任务消息"><div class="conversation-thread"></div></section>');
    thread = runShell.querySelector(".task-conversation .conversation-thread");
  }
  const userMessage = conversationMessageMarkup({
    role: "user",
    content: question,
    createdAt: new Date().toISOString(),
  });
  const failedAnswer = conversationMessageMarkup({
    role: "assistant",
    content: "这次追问没有完成，原有对话和任务结果仍然保留。",
    createdAt: new Date().toISOString(),
    label: "未完成",
    extra: `<p class="stream-error">${escapeHtml(error?.message || "请求失败，请稍后重试。")}</p>`,
    promptContent: question,
  });
  thread?.insertAdjacentHTML("beforeend", `${userMessage}${failedAnswer}`);
  restoreConversationScroll(scrollSnapshot);
}

function directEvidenceAnswerMarkup(message, index, cursor = "") {
  const reader = message.reader_answer || {};
  const sentences = Array.isArray(reader.sentences) ? reader.sentences : [];
  if (reader.presentation === "catalog") {
    const catalog = reader.catalog || {};
    const isList = catalog.operation === "list";
    const documentCount = Number(catalog.document_count || 0);
    const totalDocuments = Number(catalog.total_documents || 0);
    const terms = Array.isArray(catalog.match_terms) ? catalog.match_terms.filter(Boolean) : [];
    const items = Array.isArray(catalog.items) ? catalog.items : [];
    const hiddenCount = Number(catalog.hidden_count || 0);
    const termsMarkup = terms.length
      ? `<span class="knowledge-catalog-terms">${terms.map((term) => `<code>${escapeHtml(term)}</code>`).join("")}</span>`
      : "";
    const itemRows = items.map((item) => {
      const title = String(item.title || item.doc_id || "未命名文献");
      const year = item.publication_year ? `<time>${escapeHtml(String(item.publication_year))}</time>` : "";
      const href = String(item.reader_url || "");
      const label = href
        ? `<a href="${escapeHtml(href)}" title="打开原文阅读器">${escapeHtml(title)}</a>`
        : `<span>${escapeHtml(title)}</span>`;
      return `<li>${label}${year}</li>`;
    }).join("");
    const results = itemRows
      ? `<details class="knowledge-catalog-results"><summary>查看命中的题录 <span>${items.length}${hiddenCount ? "+" : ""} 篇</span></summary><ol>${itemRows}</ol>${hiddenCount ? `<p>为保持对话简洁，另外 ${hiddenCount} 篇可在资料库中继续筛选。</p>` : ""}</details>`
      : "";
    const scopeNote = reader.scope_note
      ? `<p class="direct-evidence-scope">${escapeHtml(reader.scope_note)}</p>`
      : "";
    return `<section class="direct-evidence-answer knowledge-catalog-answer" data-direct-evidence-answer="${index}"><header><div><small>${isList ? "题录检索" : "目录统计"} · 已索引文献</small><strong>${documentCount}<em>篇</em></strong></div><span>共 ${totalDocuments} 篇</span></header>${termsMarkup}${scopeNote}${results}${cursor}</section>`;
  }
  if (reader.presentation === "article") {
    const knownCitationIds = new Set((reader.citations || []).map((citation) => String(citation.citation_id || "")));
    const tokenized = String(reader.text || message.content || "").replace(/\[(\d+)\]/g, (marker, citationId) => (
      knownCitationIds.has(citationId) ? `§§SCANSCI_CITATION_${citationId}§§` : marker
    ));
    const article = renderAssistantContent(tokenized).replace(/§§SCANSCI_CITATION_(\d+)§§/g, (_token, citationId) => citationMarkerMarkup(citationId));
    const scopeNote = reader.scope_note
      ? `<p class="direct-evidence-scope">${escapeHtml(reader.scope_note)}</p>`
      : "";
    return `<div class="direct-evidence-answer evidence-grounded-article" data-direct-evidence-answer="${index}">${scopeNote}<div class="answer-sentence">${article}${cursor}</div></div>`;
  }
  if (!sentences.length) {
    return message.content
      ? `<div class="answer-sentence">${renderAssistantContent(message.content)}${cursor}</div>`
      : "";
  }
  const body = sentences.map((sentence) => {
    const citations = (sentence.citation_ids || []).map(citationMarkerMarkup).join("");
    return `<p class="answer-sentence">${escapeHtml(sentence.text || "")} ${citations}</p>`;
  }).join("");
  const scopeNote = reader.presentation === "synthesis" && reader.scope_note
    ? `<p class="direct-evidence-scope">${escapeHtml(reader.scope_note)}</p>`
    : "";
  return `<div class="direct-evidence-answer" data-direct-evidence-answer="${index}">${scopeNote}${body}${cursor}</div>`;
}

function renderDirectConversation({ forceFollow = false } = {}) {
  const scrollSnapshot = conversationScrollSnapshot();
  const turns = state.directMessages.map((message, index) => {
    if (message.role === "user") {
      return conversationMessageMarkup({
        role: "user",
        content: message.content,
        contentMarkup: `<div class="user-turn-bubble">${composerSourcePreviewMarkup(message.sources || [])}${composerImagePreviewMarkup(message.images || [])}<p>${escapeHtml(message.content)}</p></div>`,
        createdAt: message.created_at,
      });
    }
    const duration = Number(message.processing_ms || 0);
    const processing = `${directKnowledgeReceiptMarkup(message)}${processTraceMarkup(message, duration)}`;
    const cursor = message.streaming && message.content ? '<span class="stream-caret" aria-label="正在生成"></span>' : "";
    const answer = message.reader_answer
      ? directEvidenceAnswerMarkup(message, index, cursor)
      : (message.content ? `<div class="answer-sentence">${renderAssistantContent(message.content)}${cursor}</div>` : "");
    const generation = message.streaming ? '<div class="generation-indicator" role="status" aria-label="正在生成回复"><span class="generation-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>' : "";
    const error = message.error ? `<p class="stream-error">${escapeHtml(message.error)}</p>` : "";
    const interaction = interactionMarkup(message.interaction);
    const modeLabel = composerModeLabels[message.mode] || "通用对话";
    const promptContent = [...state.directMessages.slice(0, index)]
      .reverse()
      .find((item) => item.role === "user")?.content || "";
    return conversationMessageMarkup({
      role: "assistant",
      content: message.content,
      contentMarkup: answer,
      createdAt: message.created_at,
      usage: message.usage,
      label: modeLabel,
      processing,
      extra: `${interaction}${generation}${error}`,
      classes: "direct-answer",
      promptContent,
    });
  }).join("");
  byId("answerArea").innerHTML = `<article class="conversation-thread">${turns}</article>`;
  state.directMessages.forEach((message, index) => {
    if (message.role !== "assistant" || !message.reader_answer?.citations?.length) return;
    const scope = byId("answerArea")?.querySelector(`[data-direct-evidence-answer="${index}"]`);
    if (scope) bindCitationInteractions({ reader_answer: message.reader_answer }, scope);
  });
  restoreConversationScroll(scrollSnapshot, { forceFollow });
}

function composerMode(inputId) {
  if (inputId === "reviewQuestionInput") return "writing";
  const selectId = inputId === "homeQuestionInput" ? "homeModeSelect" : "chatModeSelect";
  return byId(selectId)?.value || "general";
}

function resolveResearchComposerMode(text) {
  if (["academic", "deep-research"].includes(state.researchWorkflow)) return state.researchWorkflow;
  const query = String(text || "");
  if (/(深度|系统综述|研究进展|证据分歧|争议|开放问题|全面调研|deep research)/i.test(query)) return "deep-research";
  return "academic";
}

function composerRun(mode, text, images = [], sourceFiles = []) {
  // Keep routing lazy.  Building an object containing parseNoveltyPrompt(text)
  // eagerly ran the novelty validator for writing, slides, and general chat as
  // well, which made every mode show the same two-part novelty error.
  if (mode === "writing") return { workflowType: "literature_review", workflowInput: { question: text } };
  if (mode === "academic") return { workflowType: "academic_search", workflowInput: { ...parseAcademicSearchPrompt(text), limit: 24, per_source: 10 } };
  if (mode === "deep-research") {
    return { workflowType: "deep_research", workflowInput: { question: text, limit: 36, max_search_rounds: 2, max_fulltext: 4 } };
  }
  if (mode === "idea") {
    return { workflowType: "research_idea", workflowInput: { ...parseResearchIdeaPrompt(text), limit: 40, max_search_rounds: 2, max_fulltext: 6, retrieval_quality: "precision" } };
  }
  if (mode === "novelty") {
    return { workflowType: "novelty_check", workflowInput: { ...parseNoveltyPrompt(text), limit: 40, max_search_rounds: 2, max_fulltext: 6, retrieval_quality: "precision" } };
  }
  if (mode === "knowledge") {
    if (state.evidenceOutputMode === "review") {
      return {
        workflowType: "literature_review",
        workflowInput: {
          question: text,
          writing_brief: {
            audience: "researcher",
            tone: "academic",
            length: "long",
            focus: "按主题组织不同来源的共同发现、分歧、证据边界与开放问题",
          },
        },
      };
    }
    return { workflowType: "ask", workflowInput: { question: text, task_mode: "evidence" } };
  }
  if (mode === "slides") {
    return sourceFiles.length
      ? { workflowType: "pdf_to_ppt", workflowInput: { topic: text, source_files: sourceFiles, template_id: state.selectedSlideTemplateId } }
      : { workflowType: "ppt_project", workflowInput: { topic: text, template_id: state.selectedSlideTemplateId } };
  }
  if (mode === "download") {
    const identifiers = extractBatchIdentifiers(text);
    if (identifiers.length > 1) {
      return { workflowType: "paper_download_batch", workflowInput: { identifiers, strategy: state.downloadStrategy } };
    }
    if (identifiers.length === 1) {
      return { workflowType: "paper_download", workflowInput: { identifier: identifiers[0], strategy: state.downloadStrategy } };
    }
    return { workflowType: "paper_search_download", workflowInput: { ...parsePaperSearchDownloadPrompt(text), strategy: state.downloadStrategy } };
  }
  return { workflowType: "ask", workflowInput: { question: text, ...(images.length ? { images } : {}) } };
}

function parseAcademicSearchPrompt(text) {
  const rawQuery = String(text || "").trim();
  const labelledTopic = rawQuery.match(/(?:^|\n)\s*(?:研究主题|检索主题|主题|topic|research\s+topic)\s*[:：]\s*([^\n]+)/i);
  const query = String(labelledTopic?.[1] || rawQuery).trim();
  if (!query) throw new Error("请填写研究主题");
  // `raw_query` preserves the user's request in the task history. The backend
  // independently re-extracts `query` before it contacts any academic API.
  return { query, raw_query: rawQuery };
}

const academicProviderLabels = Object.freeze({
  openalex: "OpenAlex",
  "semantic-scholar": "Semantic Scholar",
  crossref: "Crossref",
  pubmed: "PubMed",
  "europe-pmc": "Europe PMC",
  arxiv: "arXiv",
  openreview: "OpenReview",
  dblp: "DBLP",
});

function closeAcademicSearchPlanDialog({ clear = true } = {}) {
  const dialog = byId("academicSearchPlanDialog");
  if (dialog?.open) dialog.close();
  if (clear) state.academicSearchPlanDraft = null;
}

function renderAcademicSearchPlanDialog() {
  const draft = state.academicSearchPlanDraft;
  if (!draft) return;
  const plan = draft.plan || {};
  const topic = String(plan.normalized_topic || plan.topic || draft.request.query || "—");
  const variants = Array.isArray(plan.query_variants) ? plan.query_variants : [];
  const selected = new Set(Array.isArray(plan.providers) ? plan.providers : []);
  byId("academicSearchPlanTopic").textContent = topic;
  byId("academicSearchPlanQueries").value = variants.join("\n");
  byId("academicSearchPlanYear").value = draft.yearFrom || "";
  byId("academicSearchPlanLimit").value = String(draft.limit || 24);
  const sourceContainer = byId("academicSearchPlanSources");
  sourceContainer.innerHTML = Object.entries(academicProviderLabels).map(([id, label]) => `<label class="academic-search-plan-source"><input type="checkbox" name="academic-search-provider" value="${escapeHtml(id)}" ${selected.has(id) ? "checked" : ""} /><span>${escapeHtml(label)}</span></label>`).join("");
}

async function openAcademicSearchPlan(question, { inputId, key, sourceFiles = [], images = [] } = {}) {
  const requestPayload = parseAcademicSearchPrompt(question);
  const plan = await request("/api/academic-search/plan", {
    method: "POST",
    body: JSON.stringify(requestPayload),
  });
  state.academicSearchPlanDraft = {
    request: requestPayload,
    plan,
    inputId,
    key,
    sourceFiles,
    images,
    limit: 24,
    // Preserve a temporal constraint inferred by the host planner.  The
    // dialog remains editable, but a request such as "2022 年以来" must not
    // silently become an unbounded provider search after confirmation.
    yearFrom: plan.year_from ?? "",
  };
  renderAcademicSearchPlanDialog();
  const dialog = byId("academicSearchPlanDialog");
  if (dialog && !dialog.open) dialog.showModal();
  window.setTimeout(() => byId("academicSearchPlanQueries")?.focus(), 0);
}

function reviewedAcademicSearchInput() {
  const draft = state.academicSearchPlanDraft;
  if (!draft) throw new Error("检索计划已失效，请重新提交问题。");
  const queryVariants = [...new Set(String(byId("academicSearchPlanQueries")?.value || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean))].slice(0, 3);
  const providers = [...document.querySelectorAll('input[name="academic-search-provider"]:checked')]
    .map((input) => String(input.value || ""))
    .filter(Boolean);
  if (!queryVariants.length) throw new Error("请至少保留一条检索式。");
  if (!providers.length) throw new Error("请至少选择一个公开学术来源。");
  const yearValue = String(byId("academicSearchPlanYear")?.value || "").trim();
  const year = yearValue ? Number(yearValue) : null;
  if (year !== null && (!Number.isInteger(year) || year < 1800 || year > 2100)) {
    throw new Error("起始年份需要在 1800 到 2100 之间。");
  }
  const limit = Math.max(1, Math.min(50, Number(byId("academicSearchPlanLimit")?.value || draft.limit || 24)));
  return {
    query: draft.request.query,
    raw_query: draft.request.raw_query,
    providers,
    limit,
    per_source: limit > 24 ? 18 : 10,
    ...(year !== null ? { year_from: year } : {}),
    search_plan: {
      query_variants: queryVariants,
      providers,
      reviewed_by_user: true,
    },
  };
}

async function startReviewedAcademicSearch() {
  const draft = state.academicSearchPlanDraft;
  const submit = byId("academicSearchPlanSubmit");
  if (!draft || !submit) return;
  submit.disabled = true;
  try {
    const input = reviewedAcademicSearchInput();
    const run = await createResearchRun("academic_search", input);
    closeAcademicSearchPlanDialog();
    state.activeTaskId = run.run_id;
    window.localStorage.setItem("scansci.active.task", run.run_id);
    state.sessionId = `research-run-${run.run_id}`;
    window.localStorage.setItem("scansci.active.session", state.sessionId);
    state.conversationAutoFollow = true;
    byId("conversationTitle").textContent = compact(draft.request.raw_query, 80);
    applyContextPanelPreset("none");
    setView("conversation");
    upsertRun(run);
    updateSessionStats(estimateRunSessionStats(run));
    renderRun(run);
    watchRun(run.run_id, (next) => {
      if (state.activeView === "conversation" && state.activeTaskId === next.run_id) renderRun(next);
    });
    const sourceInput = byId(draft.inputId);
    if (sourceInput) sourceInput.value = "";
    clearComposerImages(draft.key);
    clearComposerSources(draft.key);
  } finally {
    submit.disabled = false;
  }
}

function parsePaperSearchDownloadPrompt(text) {
  const clean = String(text || "").trim();
  const authorLabel = clean.match(/(?:^|\n)\s*(?:作者|author)\s*[:：]\s*([^\n]+)/i);
  const peterReich = /Peter\s+B\.?\s+Reich/i.test(clean) ? "Peter B. Reich" : "";
  const topicLabel = clean.match(/(?:^|\n)\s*(?:主题|topic)\s*[:：]\s*([^\n]+)/i);
  const limitMatch = clean.match(/(?:TOP\s*|前\s*|数量\s*[:：]?\s*)(\d{1,2})/i);
  const yearMatch = clean.match(/(19\d{2}|20\d{2})\s*年?\s*(?:以来|之后|至今)/);
  const author = String(authorLabel?.[1] || peterReich).trim();
  const query = String(topicLabel?.[1] || (author ? "" : clean)).trim();
  if (!query && !author) throw new Error("请给出检索主题或作者姓名");
  return {
    query,
    author,
    limit: Math.max(1, Math.min(50, Number(limitMatch?.[1] || 20))),
    sort: /(?:TOP\s*\d+|高被引|被引量|引用量|most[- ]cited)/i.test(clean) ? "cited_by_count" : "relevance",
    ...(yearMatch ? { year_from: Number(yearMatch[1]) } : {}),
  };
}

function parseResearchIdeaPrompt(text) {
  const clean = String(text || "").trim();
  if (!clean) throw new Error("研究构思需要一个明确的研究方向。");
  const labeled = clean.match(/(?:^|\n)\s*(?:方向|研究方向|direction)\s*[：:]\s*([\s\S]*?)(?=\n\s*(?:约束|限制|constraints?)\s*[：:]|$)(?:[\s\S]*?\n\s*(?:约束|限制|constraints?)\s*[：:]\s*([\s\S]+))?$/i);
  if (labeled) return { direction: labeled[1].trim(), constraints: String(labeled[2] || "").trim() };
  return { direction: clean, constraints: "" };
}

function parseNoveltyPrompt(text) {
  const clean = String(text || "").trim();
  const labeled = clean.match(/(?:^|\n)\s*(?:问题|研究问题|problem)\s*[：:]\s*([\s\S]*?)(?=\n\s*(?:新颖性|创新点|主张|novelty)\s*[：:]|$)[\s\S]*?\n\s*(?:新颖性|创新点|主张|novelty)\s*[：:]\s*([\s\S]+)$/i);
  if (labeled) return { problem: labeled[1].trim(), novelty: labeled[2].trim() };
  const blocks = clean.split(/\n\s*\n/).map((value) => value.trim()).filter(Boolean);
  if (blocks.length >= 2) return { problem: blocks[0], novelty: blocks.slice(1).join("\n\n") };
  throw new Error("证据查新需要两部分：先写“问题：…”，再写“新颖性：…”。");
}

function reviewWorkflowPreferences() {
  const sourceDocIds = [...document.querySelectorAll("[data-review-source]:checked")]
    .map((item) => String(item.value || "").trim())
    .filter(Boolean);
  if (sourceDocIds.length < 2) throw new Error("文献综述请至少选择两篇用于比较和写作的来源。");
  return {
    source_doc_ids: sourceDocIds,
    writing_brief: {
      audience: byId("reviewAudience")?.value || "researcher",
      tone: byId("reviewTone")?.value || "academic",
      length: byId("reviewLength")?.value || "standard",
      focus: byId("reviewFocus")?.value?.trim() || "",
    },
  };
}

function setReviewSourceSelection(checked) {
  document.querySelectorAll("[data-review-source]").forEach((item) => { item.checked = checked; });
  updateReviewSourceCount();
}

function updateReviewSourceCount() {
  const target = document.querySelector("[data-review-selected-count]");
  if (target) target.textContent = String(document.querySelectorAll("[data-review-source]:checked").length);
}

function setEvidenceOutputMode(value) {
  const next = value === "review" ? "review" : "answer";
  if (state.evidenceOutputMode === next) return;
  state.evidenceOutputMode = next;
  renderHomeModeWorkbench("knowledge");
  const placeholder = next === "review"
    ? "输入综述主题；将组织原文证据并逐句引用"
    : "基于已选知识库提问，关键结论会附原文证据";
  for (const id of ["homeQuestionInput", "chatQuestionInput"]) {
    const composer = byId(id);
    if (composer && composerMode(id) === "knowledge") composer.placeholder = placeholder;
  }
}

const composerModeLabels = { general: "自由输入", academic: "学术搜索", knowledge: "证据问答", research: "研究", writing: "学术写作", slides: "学术 PPT", download: "文献下载" };
const composerModeIcons = { general: "wand", academic: "search", knowledge: "message-circle", research: "search", writing: "pen", slides: "presentation", download: "download" };
const modeWorkbenchContent = {
  academic: {
    title: "学术搜索",
    description: "从问题出发：先找关键论文；需要系统调研时，启动外部深度研究。",
    hint: "选择一种方式，填写问题后发送",
    tools: [],
    examples: [
      { id: "find-papers", workflow: "academic", icon: "search", title: "快速找到关键论文", text: "多源检索、去重和 DOI 核验，先得到可继续筛选的论文集合。", prompt: "请检索 2022 年以来关于「检索增强生成中的事实一致性评估」的关键论文，优先方法论文与公开基准。", tags: ["多源检索", "DOI 核验", "结果去重"] },
      { id: "deep-research", workflow: "deep-research", icon: "book", title: "深度研究", text: "自动拆解问题、分轮检索、追踪证据缺口，并交付带来源的研究报告。", prompt: "请围绕以下问题进行深度研究：先制定检索计划，再执行多轮学术检索与来源对照；只依据可追溯的公开学术来源输出结论，并清楚标记证据不足处。\n\n研究问题：", tags: ["多轮检索", "来源对照", "研究报告"] },
    ],
  },
  knowledge: {
    title: "证据问答",
    description: "只基于已选择的本地知识库回答；每个可验证结论都可回到对应原文证据。",
    tools: [
      { id: "evidence-answer", evidenceOutput: "answer", label: "问答", icon: "message-circle" },
      { id: "evidence-review", evidenceOutput: "review", label: "证据综述", icon: "book-open" },
    ],
    examples: [
      { id: "compare-sources", icon: "message-circle", title: "比较不同来源的结论", text: "区分共同发现、分歧之处和证据强弱；答案中的关键句可定位到原文。", prompt: "请比较已选择知识库中不同文献对以下问题的结论，说明一致观点、分歧与证据局限，并为每个关键结论标注原文证据：\n\n问题：", tags: ["仅本地资料", "原文证据", "观点比较"] },
      { id: "find-evidence", icon: "search", title: "从资料中找依据", text: "把一个具体判断拆成可验证的证据片段，并指出现有资料是否足够支持。", prompt: "请在已选择知识库中查找支持或反驳以下判断的原文证据；如果资料不足，请明确说明缺少什么：\n\n判断：", tags: ["支持 / 反驳", "证据片段", "不足提示"] },
    ],
  },
  writing: {
    title: "写作起步",
    description: "选择一个常见结构，或直接写下你的要求。",
    tools: [
      { id: "review", label: "文献综述", icon: "book", prompt: "请围绕以下主题撰写一篇有逐句证据引用的中文文献综述：\n\n研究主题：\n时间范围：近 5 年\n重点：研究进展、方法差异、争议与未来方向" },
      { id: "draft", label: "论文初稿", icon: "file-plus", prompt: "请根据我的研究问题和现有资料起草论文初稿。\n\n研究问题：\n核心发现：\n目标读者或期刊：" },
      { id: "polish", label: "改写润色", icon: "wand", prompt: "请在不改变事实与引用的前提下，润色下面这段学术文字，使论证更紧凑、术语更一致：\n\n" },
      { id: "citation", label: "引用格式", icon: "copy", prompt: "请检查并统一以下内容的文内引用和参考文献格式。\n\n目标格式：GB/T 7714（作者-出版年）\n内容：\n" },
    ],
    examples: [
      { id: "topic-review", icon: "wand", title: "我只有一个主题", text: "从研究主题出发，梳理进展、技术路线、挑战和未来方向。", prompt: "请写一篇关于「钙钛矿太阳能电池稳定性提升策略」的中文综述初稿，重点梳理研究进展、技术路线、挑战和未来方向。", tags: ["中文初稿", "研究进展", "未来方向"] },
      { id: "target-journal", icon: "book", title: "我有目标期刊", text: "按目标期刊的读者、篇幅和结构组织综述。", prompt: "请写一篇关于「单细胞测序在肿瘤微环境研究中的应用」的综述，目标投稿期刊为 Nature Reviews Cancer。", tags: ["目标期刊", "投稿要求", "生成配图"] },
      { id: "bounded-sources", icon: "filter", title: "我想限定文献范围", text: "只使用指定年代、期刊或资料库中的证据。", prompt: "请写一篇关于「机器学习在材料性能预测中的应用」的中文综述初稿，只参考近 5 年英文论文，并逐句标注证据来源。", tags: ["近 5 年", "英文论文", "逐句引用"] },
      { id: "outline-writing", icon: "sliders", title: "我想按指定大纲写", text: "把已有章节结构转成可继续编辑的证据化初稿。", prompt: "请按以下大纲撰写「固态锂电池界面稳定性研究进展」的中文综述：\n1. 电解质材料\n2. 界面反应机制\n3. 表征方法\n4. 改性策略\n5. 开放问题", tags: ["指定大纲", "章节写作", "证据化"] },
    ],
  },
  slides: {
    title: "选择幻灯片的起点",
    description: "可以从文件、研究主题或现成大纲生成可编辑演示文稿。",
    tools: [
      { id: "source", label: "从文件生成", icon: "file-plus", action: "upload" },
      { id: "outline", label: "从大纲生成", icon: "sliders", prompt: "请根据以下大纲制作一套学术汇报幻灯片：\n\n汇报主题：\n听众：\n时长：\n大纲：\n" },
      { id: "template", label: "选择模板", icon: "layout", action: "template" },
      { id: "speaker-notes", label: "演讲者备注", icon: "message-circle", prompt: "请为下面的学术汇报生成幻灯片，并为每页补充简洁的演讲者备注：\n\n主题：\n听众：\n预计时长：" },
    ],
    examples: [
      { id: "paper-talk", icon: "file-plus", title: "把论文做成汇报", text: "提取论文问题、方法、结果和局限，生成组会或答辩演示。", prompt: "请把我添加的论文制作成 12 页组会汇报，重点解释研究问题、方法、主要发现与局限。", tags: ["组会汇报", "12 页", "保留引用"] },
      { id: "proposal", icon: "presentation", title: "制作开题答辩", text: "围绕研究背景、问题、方案、创新点和计划组织叙事。", prompt: "请制作一套硕士开题答辩幻灯片。主题：\n研究问题：\n拟采用方法：\n预期创新：\n研究计划：", tags: ["开题答辩", "研究方案", "时间计划"] },
      { id: "conference", icon: "audio", title: "准备学术会议报告", text: "按限定时长压缩内容，突出贡献并生成讲稿提示。", prompt: "请制作一套 15 分钟学术会议报告幻灯片，突出工作的核心贡献、关键证据和可复现细节，并生成演讲者备注。", tags: ["15 分钟", "核心贡献", "讲稿提示"] },
      { id: "teaching", icon: "book", title: "制作课程讲义", text: "从概念到案例组织教学节奏，并加入回顾问题。", prompt: "请制作一套面向研究生的课程幻灯片。主题：Transformer 的注意力机制。要求包含直观解释、公式、示例和课后思考题。", tags: ["研究生课程", "概念图解", "思考题"] },
    ],
  },
  download: {
    title: "批量下载论文",
    description: "提供清单，或让 ScanSci 先检索再获取可用全文。",
    guides: [
      { id: "list", icon: "file-plus", index: "01", title: "我已有文献清单", text: "添加 TXT、BIB 或 CSV，自动识别 DOI 与 arXiv ID。" },
      { id: "topic", icon: "search", index: "02", title: "按主题检索后下载", text: "写明主题、年份、数量等限制，先筛选再批量获取。", prompt: "主题：\n限制：近 5 年、开放获取优先\n数量：20" },
      { id: "peter-reich", icon: "book", index: "03", title: "按学者高被引论文下载", text: "直接运行一个作者与被引量排序的完整示例。", prompt: "作者：Peter B. Reich\n排序：被引量\n数量：20" },
    ],
  },
};

function homePromptFromWorkbench(prompt, message = "已填入输入框，可继续修改") {
  const input = byId("homeQuestionInput");
  if (!input || !prompt) return;
  input.value = prompt;
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  toast(message);
}

function renderHomeBatchAttachment() {
  const attachment = byId("homePaperBatchAttachment");
  if (!attachment) return;
  const count = state.pendingBatchIdentifiers.length;
  attachment.hidden = !count;
  attachment.innerHTML = count
    ? `${uiIcon("file-plus")}<span><strong>${escapeHtml(state.pendingBatchFilename || "文献清单")}</strong><small>已识别 ${count} 个 DOI / arXiv ID</small></span><button type="button" data-action="clear-home-batch" aria-label="移除文献清单">${uiIcon("x")}</button>`
    : "";
  hydrateIcons(attachment);
}

function renderDownloadGuides(content) {
  const count = state.pendingBatchIdentifiers.length;
  const cards = content.guides.map((guide) => {
    const isList = guide.id === "list";
    const action = isList ? (count ? "start-home-batch-download" : "pick-home-batch-file") : "apply-download-guide";
    const useLabel = isList ? (count ? `下载已识别的 ${count} 篇` : "添加清单") : guide.id === "peter-reich" ? "使用这个示例" : "填写检索条件";
    return `<button type="button" class="download-guide-card ${isList && count ? "has-attachment" : ""}" data-action="${action}" ${isList ? "" : `data-download-guide="${escapeHtml(guide.id)}"`}><span class="download-guide-index">${escapeHtml(guide.index)}</span><span class="download-guide-icon">${uiIcon(guide.icon)}</span><strong>${escapeHtml(guide.title)}</strong><p>${escapeHtml(guide.text)}</p><span class="download-guide-use">${escapeHtml(useLabel)} ${uiIcon(isList && !count ? "plus" : "arrow-up-right")}</span></button>`;
  }).join("");
  return `<header class="mode-workbench-head download-workbench-head"><div><h2>${escapeHtml(content.title)}</h2><p>${escapeHtml(content.description)}</p></div><span>PDF 保存到本地下载目录</span></header><div class="download-guide-grid">${cards}</div>`;
}

function renderInlineSlideTemplateGallery() {
  const selected = selectedSlideTemplate();
  const plugin = state.slideTemplatesPlugin || {};
  const pluginVersion = String(plugin.version_label || plugin.version || "").trim();
  const pipelineLabel = plugin.latest_pipeline ? "最新版链路" : "兼容链路";
  const pluginLabel = `EasySlides${pluginVersion ? ` ${pluginVersion}` : ""} · ${pipelineLabel}`;
  if (!state.slideTemplatesAvailable || !state.slideTemplates.length) {
    return `<header class="mode-workbench-head slide-template-gallery-head"><div><h2>选择演示模板</h2><p>模板库暂不可用。连接 EasySlides 后，可在这里直接选择模板。</p></div><span class="slide-template-gallery-selection is-unavailable">模板库未连接</span></header>`;
  }
  const cards = state.slideTemplates.map((template) => {
    const isSelected = template.id === selected?.id;
    const isNative = ["easyslides-semantic", "easyslides-classic"].includes(template.generation_mode);
    const rendererBadge = `<span class="slide-template-renderer ${isNative ? "is-native" : "is-compat"}">${uiIcon(isNative ? "sparkles" : "layers")} ${isNative ? "EasySlides 原生" : "兼容模板"}</span>`;
    const description = compact(template.description || template.use_cases || template.summary || "用于学术汇报", 52);
    return `<article class="slide-template-gallery-card ${isSelected ? "is-selected" : ""}"><button type="button" class="slide-template-gallery-select" data-action="select-inline-slide-template" data-template-id="${escapeHtml(template.id)}" aria-pressed="${String(isSelected)}" aria-label="使用 ${escapeHtml(template.name)} 模板"><span class="slide-template-gallery-preview"><img src="${escapeHtml(template.preview_url)}" alt="${escapeHtml(template.name)} 模板封面" loading="lazy" />${isSelected ? `<span class="slide-template-gallery-check">${uiIcon("check")}</span>` : ""}</span><span class="slide-template-gallery-copy"><strong>${escapeHtml(template.name)}</strong>${rendererBadge}<small>${escapeHtml(description)}</small></span></button><button type="button" class="slide-template-gallery-preview-action" data-action="preview-inline-slide-template" data-template-id="${escapeHtml(template.id)}" aria-label="预览 ${escapeHtml(template.name)} 模板">${uiIcon("eye")}<span>预览</span></button></article>`;
  }).join("");
  return `<header class="mode-workbench-head slide-template-gallery-head"><div><h2>选择演示模板</h2><p>点击模板即可选用；需要查看完整风格时，点击卡片右上角的“预览”。</p></div><span class="slide-template-gallery-selection" title="${escapeHtml(pluginLabel)}">${uiIcon("presentation")}已选 · ${escapeHtml(selected?.name || "模板")} · ${escapeHtml(pluginLabel)}</span></header><div class="slide-template-gallery" role="group" aria-label="学术 PPT 模板">${cards}</div>`;
}

function evidenceReviewWorkbenchContent() {
  const baseContent = modeWorkbenchContent.knowledge;
  return {
    ...baseContent,
    title: "证据综述",
    description: "把当前资料库整理成一篇带原文引用的长篇综述。",
    hint: "先确认资料范围，再输入主题；引用可回到原文",
    examples: [
      { id: "evidence-review-progress", icon: "book-open", title: "梳理研究进展", text: "组织关键路线、共同发现、分歧与证据边界。", prompt: "请基于已选择知识库撰写一篇证据综述，主题是：\n\n", tags: ["原文证据", "逐句引用", "研究进展"] },
      { id: "evidence-review-compare", icon: "git-compare", title: "比较不同研究", text: "按问题、方法、发现和局限组织多篇资料。", prompt: "请基于已选择知识库撰写一篇证据综述，比较以下主题中的不同研究、共同发现、分歧与开放问题：\n\n", tags: ["跨文献比较", "证据分歧", "开放问题"] },
    ],
  };
}

function currentModeWorkbenchContent(mode) {
  return mode === "knowledge" && state.evidenceOutputMode === "review"
    ? evidenceReviewWorkbenchContent()
    : modeWorkbenchContent[mode];
}

function renderEvidenceReviewMethodGuide() {
  const notebooks = selectedKnowledgeNotebooks();
  const sourceCount = notebooks.reduce((sum, notebook) => sum + Number(notebook.counts?.sources || 0), 0);
  const scopeLabel = notebooks.length
    ? `${notebooks.map((notebook) => compact(knowledgeScopeTitle(notebook), 20)).join("、")} · ${sourceCount} 篇可检索资料`
    : "先在输入框下方选择要使用的知识库";
  return `<section class="evidence-review-method" aria-label="证据综述使用方法"><header><div><span>HOW IT WORKS</span><h3>三步完成证据综述</h3></div><p>只依据当前资料库，不补写没有来源的结论。</p></header><ol><li><b>1</b><div><strong>确认资料范围</strong><small>${escapeHtml(scopeLabel)}</small></div><button type="button" data-action="open-knowledge-scope">更改</button></li><li><b>2</b><div><strong>输入综述主题</strong><small>说明对象、比较维度或时间范围即可。</small></div></li><li><b>3</b><div><strong>阅读并核验</strong><small>关键结论附引用；点击可查看原文片段。</small></div></li></ol><footer><span>${uiIcon("shield-check")} 输出：摘要、主题章节、共识与分歧、开放问题、原文引用</span><button type="button" data-action="apply-mode-example" data-mode-example="evidence-review-progress">填入示例 ${uiIcon("arrow-up-right")}</button></footer></section>`;
}

function renderHomeModeWorkbench(mode) {
  const workbench = byId("homeModeWorkbench");
  const landing = workbench?.closest(".home-landing");
  const isEvidenceReview = mode === "knowledge" && state.evidenceOutputMode === "review";
  const content = currentModeWorkbenchContent(mode);
  const title = byId("homeLandingTitle");
  if (title) title.textContent = mode === "academic" ? "想检索哪些论文？" : mode === "knowledge" ? (isEvidenceReview ? "想整理什么证据？" : "想从资料中验证什么？") : mode === "writing" ? "今天写点什么？" : mode === "slides" ? "今天讲点什么？" : mode === "research" ? "今天研究什么？" : mode === "download" ? "想获取哪些论文？" : "今天想做什么？";
  if (!workbench || !landing) return;
  landing.classList.toggle("has-mode-workbench", Boolean(content));
  workbench.hidden = !content;
  if (!content) {
    workbench.replaceChildren();
    renderHomeBatchAttachment();
    return;
  }
  if (mode === "download") {
    workbench.innerHTML = renderDownloadGuides(content);
    renderHomeBatchAttachment();
    hydrateIcons(workbench);
    return;
  }
  if (mode === "slides") {
    workbench.innerHTML = renderInlineSlideTemplateGallery();
    renderHomeBatchAttachment();
    hydrateIcons(workbench);
    return;
  }
  const tools = content.tools.map((tool) => {
    const selected = tool.evidenceOutput
      ? mode === "knowledge" && tool.evidenceOutput === state.evidenceOutputMode
      : tool.workflow && tool.workflow === state.researchWorkflow;
    return `<button type="button" class="mode-workbench-tool ${selected ? "is-selected" : ""}" data-action="apply-mode-tool" data-mode-tool="${escapeHtml(tool.id)}" aria-pressed="${String(Boolean(selected))}">${uiIcon(tool.icon)}<span>${escapeHtml(tool.label)}</span></button>`;
  }).join("");
  const examples = content.examples.map((item) => `<button type="button" class="mode-example-card" data-action="apply-mode-example" data-mode-example="${escapeHtml(item.id)}"><span class="mode-example-icon">${uiIcon(item.icon)}</span><span class="mode-example-title">${escapeHtml(item.title)}</span><span class="mode-example-copy">${escapeHtml(item.text)}</span><span class="mode-example-tags">${item.tags.map((tag) => `<em>${escapeHtml(tag)}</em>`).join("")}</span><span class="mode-example-use">使用案例 ${uiIcon("arrow-up-right")}</span></button>`).join("");
  const toolRow = tools ? `<div class="mode-workbench-tools" aria-label="${escapeHtml(composerModeLabels[mode])}功能">${tools}</div>` : "";
  const guide = isEvidenceReview ? renderEvidenceReviewMethodGuide() : "";
  workbench.innerHTML = `<header class="mode-workbench-head"><div><h2>${escapeHtml(content.title)}</h2><p>${escapeHtml(content.description)}</p></div><span>${escapeHtml(content.hint || "点击案例会填入输入框，可继续修改")}</span></header>${toolRow}${guide}<div class="mode-example-grid">${examples}</div>`;
  renderHomeBatchAttachment();
  hydrateIcons(workbench);
}

function closeComposerModePickers() {
  document.querySelectorAll("[data-mode-picker]").forEach((picker) => {
    picker.classList.remove("is-open");
    picker.querySelector("[data-action='toggle-composer-mode']")?.setAttribute("aria-expanded", "false");
  });
}

const webSearchLabels = { auto: "联网：自动", on: "联网：开启", off: "联网：关闭" };

function closeWebSearchPickers(except = null) {
  document.querySelectorAll("[data-web-search-picker]").forEach((picker) => {
    if (picker === except) return;
    picker.classList.remove("is-open");
    picker.querySelector("[data-action='toggle-web-search']")?.setAttribute("aria-expanded", "false");
  });
}

function toggleWebSearchPicker(trigger) {
  const picker = trigger.closest("[data-web-search-picker]");
  if (!picker) return;
  const shouldOpen = !picker.classList.contains("is-open");
  closeAttachmentMenus();
  closeComposerModePickers();
  closeComposerModelPickers();
  closeComposerThinkingPickers();
  closeWebSearchPickers();
  if (shouldOpen) {
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
  }
}

function setWebSearchMode(mode, { announce = true } = {}) {
  const safeMode = Object.hasOwn(webSearchLabels, mode) ? mode : "auto";
  state.webSearchMode = safeMode;
  window.localStorage.setItem("scansci.web-search.mode", safeMode);
  document.querySelectorAll("[data-web-search-picker]").forEach((picker) => {
    const trigger = picker.querySelector("[data-action='toggle-web-search']");
    const label = picker.querySelector("[data-web-search-label]");
    if (label) label.textContent = webSearchLabels[safeMode];
    trigger?.setAttribute("aria-label", `联网搜索：${({ auto: "自动", on: "开启", off: "关闭" })[safeMode]}`);
    trigger?.classList.toggle("is-on", safeMode === "on");
    trigger?.classList.toggle("is-off", safeMode === "off");
    picker.querySelectorAll("[data-web-search-value]").forEach((option) => {
      const selected = option.dataset.webSearchValue === safeMode;
      option.classList.toggle("is-selected", selected);
      option.setAttribute("aria-selected", String(selected));
    });
  });
  if (announce) {
    const message = safeMode === "on"
      ? "联网搜索已开启：下一轮将先检索外部学术来源。"
      : safeMode === "off"
        ? "联网搜索已关闭：查询不会发送给外部检索服务。"
        : "联网搜索设为自动：由 Pi 根据问题决定是否检索。";
    toast(message);
  }
}

function closeComposerModelPickers(except = null) {
  document.querySelectorAll("[data-composer-model]").forEach((picker) => {
    if (picker === except) return;
    picker.classList.remove("is-open");
    picker.querySelector("[data-action='toggle-composer-model']")?.setAttribute("aria-expanded", "false");
  });
}

function closeComposerThinkingPickers(except = null) {
  document.querySelectorAll("[data-composer-thinking]").forEach((picker) => {
    if (picker === except) return;
    picker.classList.remove("is-open");
    picker.querySelector("[data-action='toggle-composer-thinking']")?.setAttribute("aria-expanded", "false");
  });
}

function toggleComposerModelPicker(trigger) {
  const picker = trigger.closest("[data-composer-model]");
  if (!picker) return;
  const shouldOpen = !picker.classList.contains("is-open");
  closeComposerModePickers();
  closeAttachmentMenus();
  closeComposerThinkingPickers();
  closeWebSearchPickers();
  closeComposerModelPickers();
  if (shouldOpen) {
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
  }
}

function toggleComposerThinkingPicker(trigger) {
  if (trigger.disabled) return;
  const picker = trigger.closest("[data-composer-thinking]");
  if (!picker) return;
  const shouldOpen = !picker.classList.contains("is-open");
  closeComposerModePickers();
  closeAttachmentMenus();
  closeComposerModelPickers();
  closeWebSearchPickers();
  closeComposerThinkingPickers();
  if (shouldOpen) {
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
  }
}

function closeAttachmentMenus(except = null) {
  document.querySelectorAll("[data-attachment-picker]").forEach((picker) => {
    if (picker === except) return;
    picker.classList.remove("is-open");
    picker.querySelector("[data-action='toggle-attachment-menu']")?.setAttribute("aria-expanded", "false");
  });
}

function toggleAttachmentMenu(trigger) {
  const picker = trigger.closest("[data-attachment-picker]");
  if (!picker) return;
  const shouldOpen = !picker.classList.contains("is-open");
  closeComposerModePickers();
  closeWebSearchPickers();
  closeAttachmentMenus();
  if (shouldOpen) {
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
  }
}

function openLibraryPathDialog(kind = "folder") {
  const dialog = byId("libraryPathDialog");
  const input = byId("libraryPathInput");
  if (!dialog || !input) return;
  const descriptors = {
    files: {
      title: "链接本地文件",
      label: "文件路径（每行一个）",
      hint: "原文件保留在原位置；ScanSci 只生成本地解析结果与可重建索引。",
      placeholder: "例如 D:\\Research\\paper.html",
    },
    folder: {
      title: "链接本地文件夹",
      label: "文件夹路径",
      hint: "文件夹保留在原位置；ScanSci 会递归读取支持的文件并建立本地索引。",
      placeholder: "例如 D:\\Research\\papers",
    },
    obsidian: {
      title: "链接 Obsidian Vault",
      label: "Vault 文件夹路径",
      hint: "递归读取 Markdown 笔记；.obsidian 配置与附件不会写入搜索科学。",
      placeholder: "例如 D:\\Notes\\Research Vault",
    },
    zotero: {
      title: "连接 Zotero 文献库",
      label: "Zotero storage 文件夹路径",
      hint: "会连接本机 PDF 书架并保留原文件位置；需在“文档处理”启用解析后，PDF 正文才会加入问答。",
      placeholder: "例如 C:\\Users\\你\\Zotero\\storage",
    },
    empty: {
      title: "创建空知识库",
      label: "知识库名称",
      hint: "只创建一个本地检索容器；之后添加的文件仍保留原位置，ScanSci 仅保存索引。",
      placeholder: "例如 博士论文核心文献",
    },
  };
  state.libraryImportKind = Object.hasOwn(descriptors, kind) ? kind : "folder";
  const descriptor = descriptors[state.libraryImportKind];
  byId("libraryPathTitle").textContent = descriptor.title;
  byId("libraryPathLabel").textContent = descriptor.label;
  byId("libraryPathHint").textContent = descriptor.hint;
  byId("libraryPathSubmit").textContent = state.libraryImportKind === "empty" ? "创建" : "链接";
  input.placeholder = descriptor.placeholder;
  input.value = state.libraryImportKind === "files" ? "" : state.libraryImportKind === "folder" ? String(state.notebook?.root_path || "") : "";
  if (!dialog.open) dialog.showModal();
  window.setTimeout(() => input.focus(), 0);
}

function closeLibraryPathDialog() {
  const dialog = byId("libraryPathDialog");
  if (dialog?.open) dialog.close();
}

async function chooseLibraryFolder(kind = "folder", notebookId = "") {
  state.libraryImportGuided = false;
  closeAttachmentMenus();
  const nativePicker = window.pywebview?.api?.choose_library_folder;
  if (typeof nativePicker !== "function") {
    await chooseBrowserLibraryFolder(kind, notebookId);
    return;
  }
  const path = String(await nativePicker() || "").trim();
  if (!path) return;
  if (kind === "zotero") await registerZoteroLibrary(path);
  else await bindLibraryFolder(path, kind, notebookId);
}

async function chooseOnboardingLibraryFolder(kind = "folder") {
  closeAttachmentMenus();
  const nativePicker = window.pywebview?.api?.choose_library_folder;
  if (typeof nativePicker !== "function") {
    await chooseBrowserLibraryFolder(kind);
    return;
  }
  const path = String(await nativePicker() || "").trim();
  if (path) await bindLibraryFolder(path, kind);
}

function promptBrowserForFolder() {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.setAttribute("webkitdirectory", "");
    input.setAttribute("directory", "");
    input.tabIndex = -1;
    input.style.cssText = "position:fixed;inset:0;opacity:0;pointer-events:none;width:1px;height:1px;";
    const finish = () => {
      const files = Array.from(input.files || []);
      input.remove();
      resolve(files);
    };
    input.addEventListener("change", finish, { once: true });
    document.body.append(input);
    input.click();
  });
}

async function chooseBrowserLibraryFolder(kind = "folder", notebookId = "") {
  const files = await promptBrowserForFolder();
  if (!files.length) return;
  // A browser's directory picker deliberately withholds the original absolute
  // path.  Prefer the desktop bridge when it exists, and never pretend that a
  // browser-only preview has created an original-location binding.
  const sourcePath = files.map((file) => String(file?.path || "").trim()).find(Boolean);
  if (sourcePath) {
    await bindLibraryFolder(sourcePath, kind, notebookId);
    return;
  }
  const folderName = String(files[0]?.webkitRelativePath || "").split("/")[0] || "所选文件夹";
  toast(`已选择“${folderName}”。浏览器预览不能读取原始文件夹路径；请在桌面应用中完成原位置绑定。`, true);
}

async function chooseLibraryFiles(notebookId = state.notebook?.notebook_id || "") {
  closeAttachmentMenus();
  const nativePicker = window.pywebview?.api?.choose_library_files;
  if (typeof nativePicker !== "function") {
    openLibraryPathDialog("files");
    return;
  }
  const paths = Array.from(await nativePicker() || []).map(String).filter(Boolean);
  if (paths.length) await importLibraryFiles(paths, notebookId);
}

async function chooseComposerSources(key = "home") {
  closeAttachmentMenus();
  const safeKey = key === "home" ? "home" : "chat";
  const nativePicker = window.pywebview?.api?.choose_library_files;
  if (typeof nativePicker === "function") {
    const paths = Array.from(await nativePicker() || []).map(String).filter(Boolean);
    addComposerSourcePaths(safeKey, paths);
    return;
  }
  byId(`${safeKey}SourceFileInput`)?.click();
}

async function choosePresentationSources(key = "home") {
  closeAttachmentMenus();
  const safeKey = key === "home" ? "home" : "chat";
  const nativePicker = window.pywebview?.api?.choose_presentation_sources;
  if (typeof nativePicker === "function") {
    const paths = Array.from(await nativePicker() || []).map(String).filter(Boolean);
    addComposerSourcePaths(safeKey, paths);
    return;
  }
  byId(`${safeKey}SourceFileInput`)?.click();
}

async function bindLibraryFolder(path, kind = "folder", notebookId = "") {
  toast(kind === "obsidian" ? "Vault 已绑定，正在后台读取笔记…" : "文件夹已绑定，正在后台建立索引…");
  const result = await request("/api/library/bind-folder", {
    method: "POST",
    body: JSON.stringify({ notebook_id: notebookId, path, library_kind: kind }),
  });
  await applyLibraryImport(result, kind === "obsidian" ? "Obsidian Vault 已绑定" : "文件夹已绑定");
  return result;
}

function guidedImportJobMarkup() {
  const job = state.libraryImportJob;
  if (!job) return "";
  const progress = Math.max(0, Math.min(100, Math.round(Number(job.progress || 0) * 100)));
  const failed = job.state === "failed";
  const completed = job.state === "completed";
  const icon = failed ? "triangle-alert" : completed ? "check" : "loader-circle";
  const action = failed
    ? `<button type="button" data-action="retry-guided-library-import">${uiIcon("refresh")}重试</button>`
    : "";
  return `<section class="data-import-progress ${failed ? "is-failed" : completed ? "is-complete" : "is-running"}" aria-live="polite"><span>${uiIcon(icon)}</span><div><strong>${escapeHtml(job.phase || "正在接入资料")}</strong><p>${escapeHtml(job.detail || "正在建立本地可检索索引")}</p><div class="data-import-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}"><i class="${progressWidthClass(progress)}"></i></div><small>${failed ? escapeHtml(job.error || "资料未能完成解析") : completed ? "已完成 · 资料仍保留在原位置" : `${progress}% · 可留在此页查看进度`}</small></div>${action}</section>`;
}

async function startGuidedLibraryImport(path, kind = "folder", notebookId = "") {
  return bindLibraryFolder(path, kind, notebookId);
}

async function pollGuidedLibraryImport() {
  const jobId = state.libraryImportJob?.job_id;
  if (!jobId) return;
  try {
    const job = await request(`/api/library/import-jobs/${encodeURIComponent(jobId)}`);
    state.libraryImportJob = job;
    if (job.state === "completed" && job.result && state.libraryImportAppliedJobId !== jobId) {
      state.libraryImportAppliedJobId = jobId;
      await applyLibraryImport(job.result, "资料接入完成");
    }
    const notebookId = String(job.notebook_id || state.notebook?.notebook_id || "");
    if (notebookId && ["queued", "running"].includes(job.state)) {
      state.knowledgeIndexStatuses[notebookId] = {
        state: "importing",
        progress: Number(job.progress || 0),
        error: "",
      };
    }
    if (notebookId && job.state === "failed") {
      state.knowledgeIndexStatuses[notebookId] = {
        state: "failed",
        progress: Number(job.progress || 0),
        error: String(job.error || "资料索引未完成"),
      };
    }
    if (notebookId && job.state === "completed") {
      await refreshKnowledgeIndexStatus(notebookId);
    }
    if (state.activeView === "mode" && state.activeMode === "library") renderMode();
    renderWorkspace();
    renderResourceOnboarding();
    if (["queued", "running"].includes(job.state)) window.setTimeout(pollGuidedLibraryImport, 650);
  } catch (error) {
    state.libraryImportJob = {
      ...state.libraryImportJob,
      state: "failed",
      phase: "无法读取接入状态",
      detail: "原文件没有被修改；请在设置中重新开始接入。",
      error: error.message || "资料接入状态请求失败",
    };
    renderResourceOnboarding();
  }
}

async function importLibraryFiles(paths, notebookId = state.notebook?.notebook_id || "") {
  toast(`正在链接 ${paths.length} 个文件并建立本地索引…`);
  const result = await request("/api/library/files", {
    method: "POST",
    body: JSON.stringify({ notebook_id: notebookId, paths }),
  });
  await applyLibraryImport(result, `已链接 ${result.added_files || paths.length} 个文件`);
}

async function importLibraryDroppedFiles(files, notebookId) {
  const usable = Array.from(files || []).filter((file) => file?.name).slice(0, 12);
  if (!usable.length) return;
  const paths = usable.map((file) => String(file.path || "")).filter(Boolean);
  if (paths.length === usable.length) {
    await importLibraryFiles(paths, notebookId);
    return;
  }
  toast(`正在从拖入的 ${usable.length} 个文件建立索引…`);
  const payloadFiles = [];
  for (const file of usable) payloadFiles.push({ name: file.name, data_url: await fileToDataUrl(file) });
  const result = await request("/api/library/uploads", {
    method: "POST",
    body: JSON.stringify({ notebook_id: notebookId, files: payloadFiles }),
  });
  await applyLibraryImport(result, `已添加 ${result.added_files || usable.length} 个文件`);
}

async function createEmptyLibrary(title) {
  const result = await request("/api/library", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
  await applyLibraryImport(result, `已创建「${result.notebook?.title || title}」`);
}

async function deletePersonalLibrary(notebookId) {
  const notebook = (state.workspace?.notebooks || []).find((item) => String(item.notebook_id) === String(notebookId));
  if (!notebook || knowledgeSourceKind(notebook) !== "personal") {
    toast("只能从这里移除个人知识库。", true);
    return;
  }
  const title = knowledgeScopeTitle(notebook);
  const confirmed = await requestConfirmation({
    eyebrow: "移除个人知识库",
    title: "移除这个个人知识库？",
    subject: title,
    message: "这会移除 ScanSci 中的资料记录和本地检索索引；原文件和文件夹不会被删除，之后仍可重新链接。",
    confirmLabel: "移除知识库",
    cancelLabel: "保留",
    danger: true,
  });
  if (!confirmed) return;
  const result = await request(`/api/library/${encodeURIComponent(String(notebook.notebook_id))}/delete`, {
    method: "POST",
    body: "{}",
  });
  state.workspace = result.workspace || { ...state.workspace, notebooks: (state.workspace?.notebooks || []).filter((item) => item.notebook_id !== notebook.notebook_id) };
  state.knowledgeScopeIds = (state.knowledgeScopeIds || []).filter((id) => String(id) !== String(notebook.notebook_id));
  persistKnowledgeScopes();
  delete state.knowledgeIndexStatuses[String(notebook.notebook_id)];
  const remaining = state.workspace?.notebooks || [];
  state.notebook = remaining.find((item) => String(item.notebook_id) !== String(notebook.notebook_id)) || null;
  state.knowledgeSubscope = null;
  state.knowledgeQuery = "";
  state.knowledgePreviewSourceId = "";
  window.localStorage.setItem("scansci.knowledge.scope", String(state.notebook?.notebook_id || ""));
  renderWorkspace();
  renderMode();
  if (state.notebook) void ensureActiveKnowledgeIndex(state.notebook.notebook_id);
  toast(`已移除「${title}」；原文件未删除。`);
}

async function registerZoteroLibrary(path) {
  toast("正在连接 Zotero 文献书架…");
  const result = await request("/api/library/zotero", {
    method: "POST",
    body: JSON.stringify({ notebook_id: state.notebook?.notebook_id || "", path }),
  });
  await applyLibraryImport(result, `已连接 Zotero 文献库 · ${result.zotero?.pdf_count || 0} 篇 PDF`);
}

async function connectLocalZotero(notebookId = "") {
  toast("正在读取本机 Zotero 文献元数据…");
  const result = await request("/api/library/zotero/local", {
    method: "POST",
    body: JSON.stringify({ notebook_id: notebookId }),
  });
  const indexedCount = Number(result.notebook?.counts?.sources || 0);
  const itemCount = Number(result.zotero?.item_count || 0);
  const message = indexedCount
    ? `已连接本机 Zotero · 已建立 ${indexedCount} 篇可检索资料`
    : itemCount
      ? `已读取 Zotero 的 ${itemCount} 条文献，但未找到可检索的 PDF 正文`
      : "未读取到 Zotero 文献，请确认本机资料库中已有条目";
  await applyLibraryImport(result, message);
}

async function connectNotion(notebookId = "") {
  const setup = await openNotionWizard();
  if (!setup) return;
  const { token, rootPageId, title } = setup;
  toast("正在连接 Notion 并同步页面…");
  const result = await request("/api/library/notion", {
    method: "POST",
    body: JSON.stringify({ notebook_id: notebookId, token, root_page_id: rootPageId, title }),
  });
  await applyLibraryImport(result, `Notion 已同步 · ${result.page_count || 0} 个页面`);
}

async function applyLibraryImport(result, message) {
  state.workspace = result.workspace || await request("/api/workspace");
  const notebookId = result.notebook?.notebook_id || state.notebook?.notebook_id;
  state.notebook = (state.workspace.notebooks || []).find((item) => item.notebook_id === notebookId) || result.notebook || null;
  state.knowledgeQuery = "";
  state.knowledgeVisibleLimit = 200;
  state.knowledgePreviewSourceId = "";
  state.knowledgeScopeIds = sanitizeKnowledgeScopeIds();
  if (state.notebook?.notebook_id && notebookHasSearchableContent(state.notebook) && !state.knowledgeScopeIds.includes(state.notebook.notebook_id)) {
    state.knowledgeScopeIds.push(state.notebook.notebook_id);
  }
  persistKnowledgeScopes();
  state.capabilities = await request("/api/capabilities");
  closeLibraryPathDialog();
  renderWorkspace();
  if (state.onboardingOpen) renderResourceOnboarding();
  if (state.activeView === "mode" && state.activeMode === "library") renderMode();
  if (result.index_run) {
    upsertRun(result.index_run);
    watchRun(result.index_run.run_id);
  }
  if (result.model_install) {
    mergeLocalModelInstall(result.model_install);
    if (["queued", "downloading"].includes(result.model_install.state)) {
      scheduleLocalModelInstallPoll();
    }
  }
  if (result.import_job?.job_id) {
    state.libraryImportJob = result.import_job;
    state.libraryImportAppliedJobId = "";
    const jobNotebookId = String(result.import_job.notebook_id || notebookId || "");
    if (jobNotebookId) {
      state.knowledgeIndexStatuses[jobNotebookId] = {
        state: "importing",
        progress: Number(result.import_job.progress || 0),
        error: "",
      };
    }
    window.setTimeout(pollGuidedLibraryImport, 250);
  }
  const indexing = result.index_run
    ? " · 正在后台构建本地语义索引"
    : result.import_job
      ? " · 正在后台读取 PDF 并建立可检索证据"
    : ["queued", "downloading"].includes(result.model_install?.state)
      ? " · 正在通过国内源安装高质量检索组件，完成后会自动索引"
      : "";
  toast(`${message} · ${state.notebook?.counts?.sources || 0} 篇来源${indexing}`);
}

function toggleComposerModePicker(trigger) {
  const picker = trigger.closest("[data-mode-picker]");
  if (!picker) return;
  const shouldOpen = !picker.classList.contains("is-open");
  closeAttachmentMenus();
  closeWebSearchPickers();
  closeComposerModePickers();
  if (shouldOpen) {
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
  }
}

function setComposerMode(mode, { preserveResearchWorkflow = false } = {}) {
  const safeMode = composerModeLabels[mode] ? mode : "general";
  // A research sub-workflow is a one-mode constraint, not a global user
  // preference.  Never let a previous novelty/deep-research selection leak
  // into writing, slides, general chat, or a newly selected research session.
  if (!["research", "academic"].includes(safeMode) || !preserveResearchWorkflow) {
    state.researchWorkflow = safeMode === "academic" ? "academic" : "";
  }
  if (safeMode !== "knowledge") state.evidenceOutputMode = "answer";
  for (const id of ["homeModeSelect", "chatModeSelect"]) {
    const input = byId(id);
    if (input) input.value = safeMode;
  }
  document.querySelectorAll("[data-composer-mode-shortcut]").forEach((button) => {
    const selected = button.dataset.modeValue === safeMode;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  const placeholders = {
    academic: "输入论文主题、论文标题、DOI 或 arXiv ID",
    knowledge: state.evidenceOutputMode === "review" ? "输入综述主题；将组织原文证据并逐句引用" : "基于已选知识库提问，关键结论会附原文证据",
    research: "输入研究问题；Pi 会自动选择搜索、深研、查新或构思流程",
    writing: "写下主题、材料范围和要求",
    slides: "描述汇报主题，或添加论文、文档与现成大纲",
    download: "输入 DOI 或 arXiv ID，例如 10.1038/...",
  };
  for (const id of ["homeQuestionInput", "chatQuestionInput"]) {
    const composer = byId(id);
    if (composer) composer.placeholder = placeholders[safeMode] || "描述你想完成的事";
  }
  renderHomeModeWorkbench(safeMode);
  renderKnowledgeScopeSurfaces();
  syncSlideTemplateDocks();
}

function selectedSlideTemplate() {
  return state.slideTemplates.find((item) => item.id === state.selectedSlideTemplateId) || state.slideTemplates[0] || null;
}

function previewSlideTemplate() {
  return state.slideTemplates.find((item) => item.id === state.previewSlideTemplateId) || selectedSlideTemplate();
}

function inlineSlidePreviewTemplate() {
  return state.slideTemplates.find((item) => item.id === state.inlineSlidePreviewTemplateId) || selectedSlideTemplate();
}

function renderInlineSlidePreview() {
  const template = inlineSlidePreviewTemplate();
  const title = byId("inlineSlidePreviewTitle");
  const description = byId("inlineSlidePreviewDescription");
  const stage = byId("inlineSlidePreviewStage");
  const pages = byId("inlineSlidePreviewPages");
  if (!template || !title || !description || !stage || !pages) return;
  if (!state.inlineSlidePreviewPage || !(template.pages || []).some((page) => page.file === state.inlineSlidePreviewPage)) {
    state.inlineSlidePreviewPage = template.pages?.[0]?.file || "";
  }
  const activePage = (template.pages || []).find((page) => page.file === state.inlineSlidePreviewPage) || template.pages?.[0];
  const selected = template.id === selectedSlideTemplate()?.id;
  title.textContent = template.name;
  description.textContent = template.description || template.tone || template.summary || "学术演示模板";
  stage.innerHTML = `<img src="${escapeHtml(activePage?.preview_url || template.preview_url)}" alt="${escapeHtml(template.name)} · ${escapeHtml(activePage?.label || "模板预览")}" />`;
  pages.innerHTML = (template.pages || []).map((page) => `<button type="button" class="inline-slide-preview-page ${page.file === activePage?.file ? "is-active" : ""}" data-action="preview-inline-slide-page" data-template-page="${escapeHtml(page.file)}"><img src="${escapeHtml(page.preview_url)}" alt="" /><span>${escapeHtml(page.label)}</span></button>`).join("");
  const useButton = byId("inlineSlidePreviewUse");
  if (useButton) {
    useButton.querySelector("[data-inline-slide-preview-use-label]").textContent = selected ? "正在使用此模板" : "使用此模板";
    useButton.disabled = selected;
  }
}

function openInlineSlidePreview(templateId) {
  const template = state.slideTemplates.find((item) => item.id === templateId);
  if (!template) {
    toast("未找到所选模板", true);
    return;
  }
  state.inlineSlidePreviewTemplateId = template.id;
  state.inlineSlidePreviewPage = "";
  renderInlineSlidePreview();
  const dialog = byId("inlineSlidePreviewDialog");
  if (dialog && !dialog.open) dialog.showModal();
}

function closeInlineSlidePreview() {
  const dialog = byId("inlineSlidePreviewDialog");
  if (dialog?.open) dialog.close();
}

function selectInlinePreviewedSlideTemplate() {
  const template = inlineSlidePreviewTemplate();
  if (!template) return;
  selectSlideTemplate(template.id);
  closeInlineSlidePreview();
}

function syncSlideTemplateDocks() {
  const template = selectedSlideTemplate();
  document.querySelectorAll("[data-slide-template-dock]").forEach((dock) => {
    const key = dock.dataset.composerKey || "home";
    const mode = byId(`${key}ModeSelect`)?.value || "general";
    // Source-to-PPT is a first-class presentation flow as well: choosing a
    // source must not make template selection disappear.
    // The landing page exposes templates as an immediate visual gallery.
    // Keep this compact trigger for the chat composer, where the dialog is
    // still useful without taking over the conversation.
    dock.hidden = mode !== "slides" || key === "home";
    const label = dock.querySelector("[data-slide-template-label]");
    if (label) label.textContent = template?.name || (state.slideTemplatesAvailable ? "选择模板" : "EasySlides 未连接");
    const button = dock.querySelector("[data-action='open-slide-templates']");
    if (button) button.disabled = !state.slideTemplatesAvailable;
  });
}

function openSlideTemplateDialog() {
  if (!state.slideTemplatesAvailable) {
    toast("未找到 EasySlides 模板库", true);
    return;
  }
  state.previewSlideTemplateId = state.selectedSlideTemplateId || state.slideTemplates[0].id;
  state.previewSlidePage = "";
  state.slideTemplateQuery = "";
  const search = byId("slideTemplateSearch");
  if (search) search.value = "";
  renderSlideTemplateBrowser();
  const dialog = byId("slideTemplateDialog");
  if (dialog && !dialog.open) dialog.showModal();
  window.setTimeout(() => search?.focus(), 0);
}

function closeSlideTemplateDialog() {
  const dialog = byId("slideTemplateDialog");
  if (dialog?.open) dialog.close();
}

function renderSlideTemplateBrowser() {
  const query = state.slideTemplateQuery.trim().toLocaleLowerCase("zh-CN");
  const templates = state.slideTemplates.filter((template) => {
    const haystack = [template.name, template.id, template.description, template.summary, template.use_cases, ...(template.keywords || [])].join(" ").toLocaleLowerCase("zh-CN");
    return !query || haystack.includes(query);
  });
  byId("slideTemplateCount").textContent = `${templates.length} 个模板`;
  byId("slideTemplateList").innerHTML = templates.length ? templates.map((template) => {
    const selected = template.id === state.selectedSlideTemplateId;
    const previewing = template.id === state.previewSlideTemplateId;
    return `<button type="button" class="slide-template-option ${previewing ? "is-previewing" : ""} ${selected ? "is-selected" : ""}" data-action="preview-slide-template" data-template-id="${escapeHtml(template.id)}" role="option" aria-selected="${previewing}"><img class="slide-template-option-thumb" src="${escapeHtml(template.preview_url)}" alt="" /><span class="slide-template-option-copy"><strong>${escapeHtml(template.name)}</strong><small>${escapeHtml(compact(template.description || template.use_cases || template.summary, 44))}</small></span><span class="slide-template-option-check">✓</span></button>`;
  }).join("") : '<div class="slide-template-empty">没有匹配模板</div>';

  const template = previewSlideTemplate();
  if (!template) {
    byId("slideTemplatePreview").innerHTML = '<div class="slide-template-empty">暂无可预览模板</div>';
    byId("slideTemplateSelection").textContent = "";
    return;
  }
  if (!state.previewSlidePage || !(template.pages || []).some((page) => page.file === state.previewSlidePage)) {
    state.previewSlidePage = template.pages?.[0]?.file || "";
  }
  const activePage = (template.pages || []).find((page) => page.file === state.previewSlidePage) || template.pages?.[0];
  byId("slideTemplatePreview").innerHTML = `<div class="slide-template-preview-head"><div><h3>${escapeHtml(template.name)}</h3><p>${escapeHtml(template.description || template.tone || template.summary)}</p></div><svg class="slide-template-color" viewBox="0 0 18 18" role="img" aria-label="主色 ${escapeHtml(template.primary_color)}"><circle cx="9" cy="9" r="7" fill="${escapeHtml(template.primary_color)}"></circle></svg></div><div class="slide-template-stage"><img src="${escapeHtml(activePage?.preview_url || template.preview_url)}" alt="${escapeHtml(template.name)} · ${escapeHtml(activePage?.label || "模板预览")}" /></div><div class="slide-template-pages">${(template.pages || []).map((page) => `<button type="button" class="slide-template-page ${page.file === activePage?.file ? "is-active" : ""}" data-action="preview-slide-page" data-template-page="${escapeHtml(page.file)}"><img src="${escapeHtml(page.preview_url)}" alt="" /><span>${escapeHtml(page.label)}</span></button>`).join("")}</div>`;
  byId("slideTemplateSelection").textContent = `${template.name} · 16:9`;
}

function selectPreviewedSlideTemplate() {
  const template = previewSlideTemplate();
  if (!template) return;
  selectSlideTemplate(template.id, { closeDialog: true });
}

function selectSlideTemplate(templateId, { closeDialog = false } = {}) {
  const template = state.slideTemplates.find((item) => item.id === templateId);
  if (!template) {
    toast("未找到所选模板", true);
    return;
  }
  state.selectedSlideTemplateId = template.id;
  window.localStorage.setItem("scansci.slides.template", template.id);
  syncSlideTemplateDocks();
  if (closeDialog) closeSlideTemplateDialog();
  if (byId("homeModeSelect")?.value === "slides") renderHomeModeWorkbench("slides");
  if (state.activeView === "mode" && state.activeMode === "ppt") renderMode();
  toast(`已选择「${template.name}」`);
}

async function createResearchRun(workflowType, input = {}) {
  const usesExternalResearch = workflowType === "academic_search" || workflowType === "deep_research";
  const isHostRouted = workflowType === "auto";
  const standalone = isHostRouted || usesExternalResearch || workflowType === "pdf_to_ppt" || workflowType === "paper_download" || workflowType === "paper_download_batch" || workflowType === "paper_search_download";
  if (!state.notebook && !standalone) throw new Error("请先打开一个资料库");
  const knowledgePayload = usesExternalResearch
    ? {}
    : {
        ...(state.notebook ? { notebook_id: state.notebook.notebook_id } : {}),
        ...(activeKnowledgeScopePayload() ? { knowledge_scope: activeKnowledgeScopePayload() } : {}),
      };
  return request("/api/runs", {
    method: "POST",
    body: JSON.stringify({ workflow_type: workflowType, ...knowledgePayload, ...input, thinking_level: currentThinkingLevel() }),
  });
}

async function previewFreeformTask(question) {
  return request("/api/task-routing/preview", {
    method: "POST",
    body: JSON.stringify({
      question,
      ...(state.notebook ? { notebook_id: state.notebook.notebook_id } : {}),
    }),
  });
}

async function continueTaskConversation(runId, content) {
  return request(`/api/runs/${encodeURIComponent(runId)}/messages`, {
    method: "POST",
    body: JSON.stringify({
      content,
      thinking_level: currentThinkingLevel(),
      chat_mode: composerMode("chatQuestionInput"),
      skills: extractSkillMentions(content),
    }),
  });
}

async function watchRun(runId, onUpdate = () => {}) {
  let run = state.runs.find((item) => item.run_id === runId);
  const terminal = new Set(["completed", "failed", "cancelled", "paused", "needs_confirmation", "waiting_input"]);
  for (let attempt = 0; attempt < 1800 && (!run || !terminal.has(run.status)); attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, attempt < 4 ? 180 : 650));
    try {
      run = await request(`/api/runs/${encodeURIComponent(runId)}`);
      upsertRun(run);
      onUpdate(run);
    } catch (error) {
      toast(error.message, true);
      return;
    }
  }
}

function renderAnswer(result) {
  const scrollSnapshot = conversationScrollSnapshot();
  applyContextPanelPreset("evidence");
  const reader = result.reader_answer || {};
  const sentences = reader.sentences || [];
  const answerMarkup = sentences.length ? sentences.map((sentence) => {
    const citations = (sentence.citation_ids || []).map(citationMarkerMarkup).join("");
    return `<p class="answer-sentence">${escapeHtml(sentence.text)} ${citations}</p>`;
  }).join("") : '<p class="answer-sentence">当前资料不足以生成可核验回答。</p>';
  const limitations = (result.answer?.limitations || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const sufficient = result.adequacy?.is_sufficient;
  const now = result.created_at || new Date().toISOString();
  const userMessage = conversationMessageMarkup({ role: "user", content: result.question, createdAt: now });
  const answerText = sentences.map((sentence) => sentence.text).join("\n") || "当前资料不足以生成可核验回答。";
  const assistantMessage = conversationMessageMarkup({
    role: "assistant",
    content: answerText,
    contentMarkup: answerMarkup,
    createdAt: result.completed_at || now,
    usage: result.usage,
    model: result.model,
    label: sufficient ? "资料可支持" : "资料不足",
    extra: limitations ? `<div class="answer-limitations"><strong>限制</strong><ul>${limitations}</ul></div>` : "",
    promptContent: result.question,
  });
  byId("answerArea").innerHTML = `<article class="conversation-thread">${userMessage}${assistantMessage}</article>`;
  bindCitationInteractions(result);
  restoreConversationScroll(scrollSnapshot);
}

function runUserPromptText(run) {
  if (run.workflow_type === "academic_search") return String(run.input?.raw_query || run.input?.query || run.title || "");
  if (run.workflow_type === "novelty_check") {
    return `研究问题：${run.input?.problem || ""}\n\n主张的新颖性：${run.input?.novelty || ""}`.trim();
  }
  if (run.workflow_type === "research_idea") {
    return `研究方向：${run.input?.direction || ""}${run.input?.constraints ? `\n\n现实约束：${run.input.constraints}` : ""}`.trim();
  }
  if (run.workflow_type === "paper_download") return String(run.input?.identifier || run.title || "");
  if (run.workflow_type === "paper_download_batch") {
    return `文献清单 · ${(run.input?.identifiers || []).length} 篇\n${(run.input?.identifiers || []).join("\n")}`;
  }
  if (run.workflow_type === "paper_search_download") {
    return [
      run.input?.author ? `作者：${run.input.author}` : "",
      run.input?.query ? `主题：${run.input.query}` : "",
      `数量：${run.input?.limit || 20} 篇`,
    ].filter(Boolean).join("\n\n");
  }
  return String(run.input?.question || run.input?.query || run.title || "");
}

function runUserPromptMarkup(run) {
  const text = runUserPromptText(run);
  if (run.workflow_type === "novelty_check") {
    return `<strong>研究问题</strong><br>${escapeHtml(run.input?.problem || "")}<br><br><strong>主张的新颖性</strong><br>${escapeHtml(run.input?.novelty || "")}`;
  }
  if (run.workflow_type === "research_idea") {
    return `<strong>研究方向</strong><br>${escapeHtml(run.input?.direction || "")}${run.input?.constraints ? `<br><br><strong>现实约束</strong><br>${escapeHtml(run.input.constraints)}` : ""}`;
  }
  if (run.workflow_type === "paper_download_batch") {
    return `<strong>文献清单 · ${escapeHtml(String((run.input?.identifiers || []).length))} 篇</strong><br>${escapeHtml((run.input?.identifiers || []).slice(0, 8).join("\n"))}`;
  }
  if (run.workflow_type === "paper_search_download") {
    return `${run.input?.author ? `<strong>作者</strong><br>${escapeHtml(run.input.author)}<br><br>` : ""}${run.input?.query ? `<strong>主题</strong><br>${escapeHtml(run.input.query)}<br><br>` : ""}<strong>数量</strong><br>${escapeHtml(String(run.input?.limit || 20))} 篇`;
  }
  return escapeHtml(text);
}

function runAggregateUsage(run) {
  return (run.messages || []).reduce((total, message) => {
    const usage = messageUsageValues(message.usage);
    total.prompt_tokens += usage.prompt;
    total.completion_tokens += usage.completion;
    total.total_tokens += usage.total;
    total.cache_read_tokens += Number(message.usage?.cache_read_tokens || message.usage?.cacheRead || 0) || 0;
    total.cache_write_tokens += Number(message.usage?.cache_write_tokens || message.usage?.cacheWrite || 0) || 0;
    return total;
  }, { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 });
}

function estimateRunSessionStats(run) {
  const messages = Array.isArray(run.messages) ? run.messages : [];
  const messageTokens = estimateTokenCount(runUserPromptText(run))
    + messages.reduce((sum, message) => sum + estimateTokenCount(message.content), 0);
  const artifactText = run.output_artifact
    ? `${run.output_artifact.title || ""}\n${run.output_artifact.summary || ""}\n${JSON.stringify(run.output_artifact.payload || {})}`
    : "";
  const artifactTokens = Math.min(12000, estimateTokenCount(artifactText));
  const systemTools = Math.max(120, (run.stages || []).length * 54 + (run.tool_calls || []).length * 92);
  const systemPrompt = 620;
  const other = artifactTokens;
  const contextTokens = Math.max(1, messageTokens + systemTools + systemPrompt + other);
  const usage = runAggregateUsage(run);
  const totalTokens = usage.total_tokens || contextTokens;
  const contextWindow = modelContextWindowFor(run.model?.provider_id, run.model?.model_id) || 128000;
  return {
    estimated: true,
    tokens: {
      input: usage.prompt_tokens || messageTokens + systemTools + systemPrompt,
      output: usage.completion_tokens || artifactTokens,
      cacheRead: usage.cache_read_tokens,
      cacheWrite: usage.cache_write_tokens,
      total: totalTokens,
    },
    contextUsage: {
      tokens: contextTokens,
      contextWindow,
      percent: contextWindow ? Math.min(100, contextTokens / contextWindow * 100) : 0,
    },
    contextBreakdown: {
      message: messageTokens,
      systemTools,
      mcpTools: 0,
      skills: 0,
      systemPrompt,
      other,
      total: contextTokens,
    },
    totalMessages: Math.max(1, messages.length + 1),
    userMessages: messages.filter((message) => message.role === "user").length + 1,
  };
}

function runFailureSummary(run) {
  const raw = String(run.error?.message || run.recovery?.detail || "").trim();
  if (/scansci-pdf.*(?:json|检索结果)|(?:json|检索结果).*scansci-pdf/i.test(raw)) {
    return "文献检索服务返回了无法读取的结果，下载尚未开始。";
  }
  if (/Publisher-declared PDF|已找到全文入口.*(?:下载失败|不可访问)|公开存档回退失败/i.test(raw)) {
    return "已找到全文入口，但出版商或机构代理未允许下载可校验的 PDF。";
  }
  if (/ERR_CONNECTION_CLOSED|ECONNRESET|ECONNREFUSED|connection (?:closed|reset|refused)/i.test(raw)) {
    return "访问出版商或机构代理时连接中断，尚未取得可校验的文件。";
  }
  if (/timed?\s*out|TimeoutExpired|ETIMEDOUT|超时/i.test(raw)) {
    return "外部服务响应超时；当前进度已经保留，可以从未完成处继续。";
  }
  if (/(?:^|\D)(?:401|403)(?:\D|$)|unauthori[sz]ed|forbidden|invalid api key|api key.*(?:invalid|missing)/i.test(raw)) {
    return "模型或外部服务拒绝了当前凭据，请检查对应服务的连接配置。";
  }
  if (/(?:^|\D)429(?:\D|$)|rate.?limit|too many requests|限流/i.test(raw)) {
    return "外部服务触发了限流；当前进度已经保留，稍后可以从未完成处继续。";
  }
  if (/empty response|空响应|returned no (?:content|text)/i.test(raw)) {
    return "模型返回了空响应，ScanSci 已保留上下文，可改用兼容模型或从当前步骤重试。";
  }
  if (/ENOENT|file not found|no such file|文件不存在/i.test(raw)) {
    return "任务需要的本地文件不存在或已经移动，请检查文件位置后继续。";
  }
  return String(run.recovery?.message || "执行阶段未能完成；此前成功的进度和本地结果已经保留。");
}

function runCompletionSummary(run) {
  const artifact = run.output_artifact;
  const payload = artifact?.payload || {};
  const items = Array.isArray(payload.items) ? payload.items : [];
  const completed = items.filter((item) => item.status === "completed").length
    || Number(payload.completed || 0)
    || (Array.isArray(payload.files) && payload.files.length ? 1 : 0);
  const failed = items.filter((item) => item.status === "failed").length;
  if (run.status === "completed" && String(run.workflow_type || "").startsWith("paper_")) {
    const indexStageCompleted = (run.stages || []).some((stage) => stage.status === "completed" && /index|索引/i.test(`${stage.key || ""} ${stage.title || ""}`));
    const indexed = Number(payload.indexed || payload.indexed_count || (indexStageCompleted ? completed : 0));
    return `完成了。我按要求获取并校验了 ${completed || Number(payload.completed || 0)} 篇全文${indexed ? `，其中 ${indexed} 篇已完成全文索引` : ""}${failed ? `；另有 ${failed} 篇未能获取` : ""}。下面的文件图标可以直接打开文献，文件夹图标可以定位到本地位置。`;
  }
  if (run.status === "completed" && ["slide_outline", "slide_deck_project", "presentation_deck"].includes(artifact?.artifact_type)) {
    const slides = payload.outline?.slides || payload.slides || [];
    return `已经完成这份演示文稿${slides.length ? `，共 ${slides.length} 页` : ""}。成品保存在本地，你可以点击下面的文件图标直接打开。`;
  }
  if (run.status === "completed" && ["literature_review", "deep_research_report"].includes(artifact?.artifact_type)) {
    return `综述已经完成。我保留了可核验的证据引用、研究比较和证据边界；你可以继续在这条对话里要求我压缩、改写或补充某一节。`;
  }
  if (run.status === "completed") {
    return String(artifact?.summary || payload.message || "已经完成这项任务，结果和可继续追问的上下文都保留在当前对话中。");
  }
  if (run.status === "failed") {
    return "";
  }
  const retained = completed ? `，并保留了 ${completed} 个已经落盘的结果` : "";
  if (run.status === "paused") {
    return `任务暂时停在这里${retained}。当前进度没有丢失；继续这条对话后，我会从未完成的阶段接着处理。`;
  }
  if (run.status === "cancelled") return `任务已经停止，已完成的阶段和本地文件仍然保留。`;
  return "";
}

function runArtifactFiles(run) {
  const artifact = run.output_artifact || {};
  const payload = artifact.payload || {};
  const itemFiles = (Array.isArray(payload.items) ? payload.items : [])
    .flatMap((item) => Array.isArray(item.files) ? item.files : [])
    .filter(Boolean);
  const files = [
    ...itemFiles,
    ...(Array.isArray(payload.files) ? payload.files : []),
    payload.pptx_path,
    payload.project_path,
    artifact.file_path,
  ].filter(Boolean).map(String);
  return [...new Set(files)].slice(0, 8);
}

function runCompletionMessageMarkup(run) {
  const content = runCompletionSummary(run);
  if (!content) return "";
  const artifact = run.output_artifact || {};
  const payload = artifact.payload || {};
  const resources = runArtifactFiles(run);
  const files = resources.filter((path) => localResourceKind(path) !== "folder");
  const folders = [
    payload.output_dir,
    payload.output_directory,
    payload.folder_path,
    artifact.folder_path,
    ...resources.filter((path) => localResourceKind(path) === "folder"),
    ...files.map(localPathParent),
  ].filter(Boolean).map(String);
  const uniqueFolders = [...new Set(folders)];
  const resourceLinks = files.length || uniqueFolders.length
    ? `<div class="delivery-resources" aria-label="本地交付文件">
        ${files.length ? `<div class="delivery-resource-line"><span>文件</span><div>${files.map((file) => localFileLinkMarkup(file, "", { inline: true })).join("")}</div></div>` : ""}
        ${uniqueFolders.length ? `<div class="delivery-resource-line"><span>所在文件夹</span><div>${uniqueFolders.map((folder) => localFileLinkMarkup(folder, localPathLeaf(folder), { folder: true, inline: true })).join("")}</div></div>` : ""}
      </div>`
    : "";
  return conversationMessageMarkup({
    role: "assistant",
    content,
    createdAt: run.completed_at || run.updated_at,
    model: run.model,
    label: run.status === "completed" ? "任务交付" : "任务状态",
    extra: resourceLinks,
    classes: "run-delivery-message",
    promptContent: runUserPromptText(run),
  });
}

function runControlPlaneMarkup(run) {
  const interaction = run.interaction && Object.keys(run.interaction).length ? run.interaction : null;
  const recovery = run.recovery && Object.keys(run.recovery).length ? run.recovery : null;
  const recentEvents = Array.isArray(run.events) ? run.events.slice(-3).reverse() : [];
  const advisorEvent = Array.isArray(run.events)
    ? [...run.events].reverse().find((item) => item?.type === "advisor.reviewed")
    : null;
  const advisor = advisorEvent && typeof advisorEvent.payload === "object" ? advisorEvent.payload : null;
  const branchMeta = run.parent_run_id
    ? `<span class="run-control-chip">${uiIcon("git-branch")}分支任务</span>`
    : "";
  const background = run.background
    ? `<span class="run-control-chip">${uiIcon("refresh")}${escapeHtml(run.workflow_type === "evidence_index" ? evidenceIndexRunTitle(run) : "后台任务")}</span>`
    : "";
  let panel = "";
  if (interaction) {
    const interactionId = String(interaction.interaction_id || "");
    const summary = interaction.summary || interaction.payload?.summary || "需要你的决定";
    panel = `<section class="run-control-panel is-interaction"><header><strong>${interaction.kind === "plan" ? "计划确认" : "需要你的回答"}</strong><span>任务已安全暂停</span></header><p>${escapeHtml(summary)}</p><div><button type="button" data-action="respond-run-interaction" data-run-id="${escapeHtml(run.run_id)}" data-interaction-id="${escapeHtml(interactionId)}" data-decision="approve">批准并继续</button><button type="button" data-action="respond-run-interaction" data-run-id="${escapeHtml(run.run_id)}" data-interaction-id="${escapeHtml(interactionId)}" data-decision="cancel">取消</button></div></section>`;
  } else if (recovery) {
    const failedStage = (run.stages || []).find((stage) => stage.status === "failed");
    const primaryAction = (recovery.actions || []).find((action) => action.kind !== "branch") || (recovery.actions || [])[0];
    const button = primaryAction
      ? `<button type="button" data-action="recover-run" data-run-id="${escapeHtml(run.run_id)}" data-recovery-action="${escapeHtml(primaryAction.kind || primaryAction.id || "retry")}">${escapeHtml(primaryAction.label || "继续")}</button>`
      : "";
    panel = `<section class="run-control-panel is-recovery"><header><strong>${escapeHtml(runFailureSummary(run))}</strong><span>${escapeHtml(failedStage?.title || "未完成步骤")}</span></header><div>${button}</div></section>`;
  }
  if (advisor?.recommended_next_action && advisor.recommended_next_action !== "none") {
    const findings = Array.isArray(advisor.findings) ? advisor.findings : [];
    const nextAction = String(advisor.recommended_next_action);
    const finding = String(findings[0]?.message || "A durable completion check found a gap.");
    panel += `<section class="run-control-panel is-advisor"><header><strong>Research advisor</strong><span>${escapeHtml(String(advisor.verdict || "needs_review"))}</span></header><p>${escapeHtml(finding)}</p><div><button type="button" data-action="advisor-action" data-run-id="${escapeHtml(run.run_id)}" data-advisor-action="${escapeHtml(nextAction)}">Create evidence-safe follow-up</button></div></section>`;
  }
  const trace = recentEvents.length
    ? `<details class="run-event-trace"><summary>任务记录 · ${escapeHtml(String(run.event_count || recentEvents.length))}</summary><ol>${recentEvents.map((item) => `<li><span>${escapeHtml(item.summary || item.type || "任务更新")}</span><time>${escapeHtml(formatMessageTime(item.created_at))}</time></li>`).join("")}</ol></details>`
    : "";
  return `${branchMeta || background ? `<div class="run-control-chips">${background}${branchMeta}</div>` : ""}${panel}${trace}`;
}

function renderRun(run) {
  const renderKey = JSON.stringify({
    runId: run.run_id,
    status: run.status,
    progress: Math.round(Number(run.progress || 0) * 100),
    stages: (run.stages || []).map((stage) => [stage.stage_id, stage.status, stage.summary, stage.error_message]),
    artifact: run.output_artifact?.file_path || run.output_artifact?.summary || "",
    interaction: run.interaction || {},
    recovery: run.recovery || {},
    parent: run.parent_run_id || "",
    events: (run.events || []).map((item) => [item.event_id, item.type, item.summary, item.created_at]),
    messages: (run.messages || []).map((message) => [message.message_id, message.role, message.content, message.processing_ms, message.created_at, message.usage]),
  });
  if (state.lastRunRenderKey === renderKey) return;
  state.lastRunRenderKey = renderKey;
  const answerArea = byId("answerArea");
  const scrollSnapshot = conversationScrollSnapshot();
  byId("conversationTitle").textContent = ["literature_review", "deep_research"].includes(run.workflow_type) ? (run.workflow_type === "deep_research" ? "深度研究" : "证据综述") : compact(runDisplayTitle(run), 80);
  const percent = Math.round((run.progress || 0) * 100);
  const evidenceIndex = run.workflow_type === "evidence_index" ? evidenceIndexContext(run) : null;
  const stageCalls = new Map((run.tool_calls || []).map((call) => [call.stage_id, call]));
  const stages = (run.stages || []).map((stage) => {
    const call = stageCalls.get(stage.stage_id);
    const isIndexBuild = Boolean(evidenceIndex && stage.key === "build");
    const stageTitle = isIndexBuild
      ? `正在优化「${evidenceIndex.title}」的语义检索`
      : stage.title;
    const reuseDetail = evidenceIndex?.migrated
      ? ` · 已从旧索引迁移复用 ${evidenceIndex.migrated.toLocaleString("zh-CN")} 条向量`
      : evidenceIndex?.reused
        ? ` · 已复用 ${evidenceIndex.reused.toLocaleString("zh-CN")} 条缓存`
        : "";
    const indexDetail = evidenceIndex?.total
      ? `已处理 ${evidenceIndex.completed.toLocaleString("zh-CN")} / ${evidenceIndex.total.toLocaleString("zh-CN")} 条原文证据${reuseDetail}`
      : "正在准备原文证据的语义检索";
    const detail = isIndexBuild
      ? (stage.error_message || indexDetail)
      : (stage.error_message || stage.summary || (call ? `${call.tool_name}${call.status === "running" ? " · 调用中" : ""}` : "等待执行"));
    return `<li class="run-stage ${escapeHtml(stage.status)}"><span class="stage-node">${stage.status === "completed" ? "✓" : stage.status === "running" ? "·" : stage.status === "failed" ? "!" : stage.position + 1}</span><div><strong>${escapeHtml(stageTitle)}</strong><small>${escapeHtml(detail)}</small></div>${call ? `<code>${escapeHtml(call.tool_name)}</code>` : ""}</li>`;
  }).join("");
  const artifact = run.output_artifact;
  const partialDownloadMarkup = partialDownloadArtifactMarkup(run);
  let resultMarkup = "";
  if (artifact?.payload && artifact.artifact_type === "research_idea_card") {
    resultMarkup = researchIdeaCardMarkup(artifact.payload);
  } else if (artifact?.payload && artifact.artifact_type === "novelty_assessment") {
    resultMarkup = noveltyAssessmentMarkup(artifact.payload);
  } else if (artifact?.payload && artifact.artifact_type === "academic_search_result") {
    resultMarkup = academicSearchArtifactMarkup(artifact.payload);
  } else if (artifact?.payload && ["evidence_answer", "literature_review", "deep_research_report"].includes(artifact.artifact_type)) {
    resultMarkup = evidenceArtifactMarkup(artifact.payload);
  } else if (artifact?.payload && ["slide_outline", "slide_deck_project", "presentation_deck"].includes(artifact.artifact_type)) {
    resultMarkup = slideProjectArtifactMarkup(artifact.payload, run.run_id);
  } else if (artifact?.payload && artifact.artifact_type === "downloaded_paper") {
    resultMarkup = downloadedPaperArtifactMarkup(artifact);
  } else if (artifact) {
    resultMarkup = genericArtifactMarkup(artifact);
  } else if (run.workflow_type === "evidence_index" && run.status === "completed") {
    const cache = (run.stages || []).find((stage) => stage.key === "build")?.output?.vector_cache || {};
    const migrated = Math.max(0, Number(run?.input?.migrated_vectors || 0));
    const reuseNote = migrated
      ? `已从旧索引迁移复用 ${escapeHtml(String(migrated))} 条向量；`
      : "";
    resultMarkup = `<div class="run-state-message"><strong>「${escapeHtml(evidenceIndex?.title || "当前知识库")}」的语义检索已就绪</strong><p>${reuseNote}已索引 ${escapeHtml(String(cache.completed || 0))}/${escapeHtml(String(cache.total || 0))} 条原文证据，后续检索会直接复用持久缓存。</p></div>`;
  } else if (partialDownloadMarkup) {
    const stateMessage = run.status === "paused"
      ? `<div class="run-state-message"><strong>任务已暂停</strong><p>${escapeHtml(run.error?.message || "可以从当前阶段继续。")}</p></div>`
      : run.status === "failed"
        ? `<div class="run-state-message is-error"><strong>下载阶段未完成</strong><p>${escapeHtml(runFailureSummary(run))}</p></div>`
        : `<div class="run-live"><span></span><div><strong>${escapeHtml(runStatusLabel(run))}</strong><p>已保存中间结果，正在继续下载。</p></div></div>`;
    resultMarkup = `${partialDownloadMarkup}${stateMessage}`;
  } else if (run.status === "failed") {
    resultMarkup = "";
  } else if (run.status === "cancelled") {
    resultMarkup = '<div class="run-state-message"><strong>任务已停止</strong><p>已完成的阶段和工具记录仍然保留，可以继续。</p></div>';
  } else if (run.status === "paused") {
    resultMarkup = `<div class="run-state-message"><strong>任务已暂停</strong><p>${escapeHtml(run.error?.message || "可以从当前阶段继续。")}</p></div>`;
  } else {
    resultMarkup = `<div class="run-live"><span></span><div><strong>${escapeHtml(evidenceIndex ? evidenceIndexRunTitle(run) : runStatusLabel(run))}</strong><p>${escapeHtml(evidenceIndex?.total ? `已处理 ${evidenceIndex.completed.toLocaleString("zh-CN")} / ${evidenceIndex.total.toLocaleString("zh-CN")} 条原文证据` : (run.stages || []).find((stage) => stage.status === "running")?.title || "正在准备下一阶段")}</p></div></div>`;
  }
  const actions = [
    run.cancellable ? `<button type="button" class="run-action stop" data-action="cancel-run" data-run-id="${escapeHtml(run.run_id)}">停止</button>` : "",
    run.resumable && !run.interaction?.interaction_id ? `<button type="button" class="run-action" data-action="resume-run" data-run-id="${escapeHtml(run.run_id)}">${run.status === "needs_confirmation" ? "确认计划并执行" : run.workflow_type.startsWith("paper_") ? "继续下载并交付" : "继续"}</button>` : "",
    `<button type="button" class="run-action" data-action="branch-run" data-run-id="${escapeHtml(run.run_id)}">建立分支</button>`,
  ].join("");
  if (["literature_review", "deep_research"].includes(run.workflow_type)) {
    const reviewModel = artifact?.payload ? buildReviewDocumentModel(run, artifact) : null;
    state.reviewDocument = reviewModel;
    applyContextPanelPreset(contextPanelPresetForRun(run));
    renderReviewDocument(run, artifact, reviewModel);
    byId("answerArea").innerHTML = reviewTaskMarkup(run, reviewModel, { percent, stages, actions });
    if (run.status === "completed" && scrollSnapshot.top === 0) {
      byId("answerArea").scrollTop = 0;
      updateConversationScrollAffordance();
    } else {
      restoreConversationScroll(scrollSnapshot);
    }
    return;
  }
  state.reviewDocument = null;
  // The primary artifact owns the canvas. Only workflows whose normal use
  // depends on sources receive a persistent context panel; citations can
  // still open the evidence reader temporarily from every artifact.
  applyContextPanelPreset(contextPanelPresetForRun(run));
  const userPromptText = evidenceIndex ? evidenceIndexRunTitle(run) : runUserPromptText(run);
  const userPrompt = evidenceIndex ? evidenceIndexRunTitle(run) : runUserPromptMarkup(run);
  const userMessage = conversationMessageMarkup({
    role: "user",
    content: userPromptText,
    contentMarkup: `<div class="user-turn-bubble">${composerSourcePreviewMarkup(run.input?.source_files || [])}${composerImagePreviewMarkup(run.input?.images || [])}<p>${userPrompt}</p></div>`,
    createdAt: run.created_at,
  });
  const workflowLabel = ({ evidence_index: "语义检索", ask: "证据问答", literature_review: "证据综述", academic_search: "学术搜索", deep_research: "深度研究", research_idea: "研究构思", novelty_check: "证据查新", paper_download: "文献下载", paper_download_batch: "批量下载", paper_search_download: "检索并下载", ppt_outline: "幻灯片大纲", ppt_project: "EasySlides", pdf_to_ppt: "PPTX" })[run.workflow_type] || "科研任务";
  const active = !["completed", "failed", "cancelled", "paused"].includes(String(run.status || ""));
  const runResult = resultMarkup ? `<section class="run-result">${resultMarkup}</section>` : "";
  const executionTitle = active
    ? (evidenceIndex ? evidenceIndexRunTitle(run) : "正在执行")
    : "执行过程";
  const executionMeta = evidenceIndex?.total
    ? `${evidenceIndex.completed.toLocaleString("zh-CN")} / ${evidenceIndex.total.toLocaleString("zh-CN")} 条原文证据 · ${percent}%`
    : `${runStatusLabel(run)} · ${percent}%`;
  const indexContext = evidenceIndex
    ? `<p class="run-index-context">资料库：<strong>${escapeHtml(evidenceIndex.title)}</strong>${evidenceIndex.sourceCount ? ` · ${escapeHtml(String(evidenceIndex.sourceCount))} 篇资料` : ""}<span>原文件与原文证据无需重新导入</span></p>`
    : "";
  const executionLog = `${runControlPlaneMarkup(run)}<details class="run-execution-log ${evidenceIndex ? "is-evidence-index" : ""}" ${active ? "open" : ""}><summary><span>${uiIcon(active ? "refresh" : "check")}</span><div><strong>${escapeHtml(executionTitle)}</strong><small>${escapeHtml(executionMeta)}</small></div>${uiIcon("chevron-right", "run-execution-chevron")}</summary><section class="run-card"><header class="run-card-head"><div><span class="run-kind">${escapeHtml(workflowLabel)}</span><h2>${escapeHtml(runDisplayTitle(run))}</h2>${indexContext}</div><div class="run-head-actions"><span class="run-status ${escapeHtml(run.status)}">${escapeHtml(runStatusLabel(run))}</span>${actions}</div></header><div class="run-progress"><i class="${progressWidthClass(percent)}"></i></div><ol class="run-stage-list">${stages}</ol></section>${runResult}</details>`;
  byId("answerArea").innerHTML = `<article class="run-shell">${userMessage}${executionLog}${runCompletionMessageMarkup(run)}</article>`;
  const taskConversation = taskConversationMarkup(run);
  if (taskConversation) answerArea.querySelector(".run-shell")?.insertAdjacentHTML("beforeend", taskConversation);
  bindRunCitations(artifact?.payload || {});
  restoreConversationScroll(scrollSnapshot);
}

function taskConversationMarkup(run) {
  const messages = Array.isArray(run.messages) ? run.messages : [];
  if (!messages.length) return "";
  const turns = messages.map((message, index) => {
    const promptContent = message.role === "assistant"
      ? [...messages.slice(0, index)].reverse().find((item) => item.role === "user")?.content || runUserPromptText(run)
      : "";
    return conversationMessageMarkup({
      role: message.role,
      content: message.content,
      createdAt: message.created_at,
      usage: message.usage,
      model: run.model,
      processing: message.role === "assistant" ? processTraceMarkup(message, Number(message.processing_ms || 0)) : "",
      classes: message.role === "assistant" ? "direct-answer" : "",
      promptContent,
    });
  }).join("");
  return `<section class="task-conversation" aria-label="任务消息"><div class="conversation-thread">${turns}</div></section>`;
}

function evidenceArtifactMarkup(result) {
  const reader = result.reader_answer || {};
  const sentences = reader.sentences || [];
  const answerMarkup = sentences.length ? sentences.map((sentence) => {
    const citations = (sentence.citation_ids || []).map(citationMarkerMarkup).join("");
    return `<p class="answer-sentence">${escapeHtml(sentence.text)} ${citations}</p>`;
  }).join("") : '<p class="answer-sentence">当前资料不足以生成可核验回答。</p>';
  const limitations = (result.answer?.limitations || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const sufficient = result.adequacy?.is_sufficient;
  const vision = result.image_analysis?.text ? `<section class="vision-analysis"><header><span>◉</span><div><strong>用户图片分析</strong><small>${escapeHtml(result.image_analysis?.model || "视觉模型")}</small></div></header><p>${escapeHtml(result.image_analysis.text)}</p><footer>基于你上传的图片生成，不作为资料库引文。</footer></section>` : "";
  return `<div class="assistant-turn artifact-answer">${vision}<div class="answer-meta"><span>ScanSci</span><b>${sufficient ? "资料可支持" : "资料不足"}</b></div>${answerMarkup}${limitations ? `<div class="answer-limitations"><strong>限制</strong><ul>${limitations}</ul></div>` : ""}</div>`;
}

function slideProjectArtifactMarkup(payload, runId = "") {
  const outline = payload.outline || payload;
  const template = payload.template || outline.template || selectedSlideTemplate();
  const slides = outline.slides || [];
  const nativeEasySlides = payload.render_mode === "native" || String(payload.renderer || "").startsWith("easyslides");
  const slideCount = Number(payload.slide_count) || slides.length;
  const rendererName = payload.renderer_label || (nativeEasySlides ? "EasySlides" : "ScanSci 兼容排版器");
  const qualityPassed = payload.quality_gate?.status === "pass";
  state.activeSlidePlan = nativeEasySlides ? null : (payload.slide_plan || null);
  if (payload.pptx_path) {
    const download = runId ? `<button type="button" class="primary-button slide-download-button" data-action="save-presentation" data-presentation-path="${escapeHtml(payload.pptx_path)}" data-presentation-name="${escapeHtml(payload.download_name || "ScanSci-演示文稿.pptx")}">下载 PPTX</button>` : "";
    const enhancedDownload = !nativeEasySlides && payload.slide_plan ? '<button type="button" class="secondary-button slide-enhanced-button" data-action="export-pptxgenjs">重新排版导出</button>' : "";
    const sourceNames = (payload.sources || []).map((source) => source.name).filter(Boolean).join(" · ");
    const preview = runId
      ? `<img class="slide-project-cover" src="/api/runs/${encodeURIComponent(runId)}/preview" alt="${escapeHtml(outline.title || "演示文稿预览")}" />`
      : (template?.preview_url ? `<img class="slide-project-cover" src="${escapeHtml(template.preview_url)}" alt="${escapeHtml(template.name || "所选模板预览")}" />` : `<div class="slide-project-cover">${uiIcon("presentation")}<b>PPTX</b></div>`);
    const templateName = template?.name ? ` · ${template.name}` : "";
    const qualityLabel = qualityPassed ? " · 已通过质量检查" : nativeEasySlides ? " · 质量检查未通过" : "";
    const exportHint = nativeEasySlides
      ? "已由 EasySlides 生成原生可编辑 PPTX，可直接下载继续修改。"
      : "“下载 PPTX”保存当前成品；也可使用兼容排版器重新导出。";
    return `<div class="slide-project-artifact is-pptx">${preview}<div class="slide-project-copy"><span>${escapeHtml(rendererName)}${escapeHtml(qualityLabel)}</span><h3>${escapeHtml(outline.title || "科研幻灯片")}</h3><p>${escapeHtml(`${slideCount} 页${templateName} · ${payload.planning?.mode === "skill-aware-model" ? "已应用科研内容规划" : "基于源文件生成"}`)}</p>${sourceNames ? `<small>${escapeHtml(sourceNames)}</small>` : ""}${payload.pptx_path ? `<div class="artifact-file-link">${localFileLinkMarkup(payload.pptx_path, payload.download_name || localPathLeaf(payload.pptx_path), { inline: true })}</div>` : ""}<p class="slide-export-hint">${escapeHtml(exportHint)}</p><div class="slide-download-actions">${enhancedDownload}${download}</div></div></div>`;
  }
  const preview = template?.preview_url ? `<img class="slide-project-cover" src="${escapeHtml(template.preview_url)}" alt="${escapeHtml(template.name || "幻灯片模板")}" />` : '<div class="slide-project-cover"></div>';
  const slideSummary = slides.length ? `${slides.length} 页 · ${outline.evidence_linked ? "已绑定来源" : "待绑定来源"}` : "EasySlides 项目";
  return `<div class="slide-project-artifact">${preview}<div class="slide-project-copy"><span>EasySlides project</span><h3>${escapeHtml(template?.name || "学术幻灯片")}</h3><p>${escapeHtml(slideSummary)}</p>${payload.project_path ? `<div class="artifact-file-link">${localFileLinkMarkup(payload.project_path, "", { inline: true })}</div>` : ""}</div></div>`;
}

async function exportActiveSlidePlan(button) {
  if (!state.activeSlidePlan) throw new Error("当前任务没有可导出的幻灯片计划");
  if (!window.ScanSciPptxExporter) throw new Error("高质量 PPTX 导出组件尚未加载");
  const original = button?.textContent || "高质量导出";
  if (button) {
    button.disabled = true;
    button.textContent = "正在生成…";
  }
  try {
    const result = await window.ScanSciPptxExporter.export(state.activeSlidePlan, state.activeSlidePlan.title);
    const saved = await savePresentationToDevice(result.file_path, result.download_name);
    if (!saved.cancelled) toast(`已保存 ${saved.path || result.download_name}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

async function savePresentationToDevice(sourcePath, suggestedName) {
  const nativeSave = window.pywebview?.api?.save_presentation_copy;
  if (typeof nativeSave === "function") {
    const result = await nativeSave(String(sourcePath || ""), String(suggestedName || "ScanSci-演示文稿.pptx"));
    if (!result?.ok && !result?.cancelled) throw new Error(result?.message || "保存 PPTX 失败");
    return result || { ok: false, cancelled: true };
  }
  const response = await fetch(`/api/presentations/${encodeURIComponent(String(suggestedName || "").replace(/^.*[\\/]/, ""))}`);
  if (!response.ok) throw new Error("无法读取待下载的 PPTX");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = suggestedName || "ScanSci-演示文稿.pptx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 3000);
  return { ok: true, path: suggestedName };
}

function splitReviewSentences(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return [];
  return text.split(/(?<=[。！？!?])\s*|(?<=\.)(?=\s+[A-Z\u3400-\u9fff])/u).map((item) => item.trim()).filter(Boolean);
}

function normalizeReviewParagraph(value, index = 0) {
  if (typeof value === "string") {
    return {
      id: `paragraph-${index + 1}`,
      text: value,
      citation_ids: [],
      sentences: splitReviewSentences(value).map((text) => ({ text, citation_ids: [] })),
    };
  }
  const text = String(value?.text || value?.rendered_text || "");
  const citationIds = (value?.citation_ids || []).map(String);
  const suppliedSentences = Array.isArray(value?.sentences) ? value.sentences : [];
  const sentences = suppliedSentences.length
    ? suppliedSentences.map((sentence) => ({
      text: String(sentence?.text || ""),
      citation_ids: (sentence?.citation_ids || []).map(String),
    })).filter((sentence) => sentence.text)
    // Older artifacts only know which sources support the paragraph as a
    // whole. Keep that scope intact instead of guessing a sentence mapping.
    : (text ? [{ text, citation_ids: [...citationIds] }] : []);
  return {
    id: String(value?.id || `paragraph-${index + 1}`),
    text,
    citation_ids: citationIds,
    sentences,
  };
}

function reviewDisplayTitle(run, supplied = {}) {
  const question = String(run?.input?.question || run?.title || "").replace(/\s+/g, " ").trim();
  const candidate = String(supplied?.title || "").replace(/\s+/g, " ").trim();
  const folded = `${candidate} ${question}`.toLocaleLowerCase();
  if (folded.includes("transformer") && folded.includes("bert") && /\bgpt-?3\b/i.test(folded)) {
    return "Transformer、BERT 与 GPT-3：架构、训练与能力边界";
  }
  const compactQuestion = question.replace(/\s+/g, "").toLocaleLowerCase();
  const compactCandidate = candidate.replace(/\s+/g, "").toLocaleLowerCase();
  const instructionLike = /^(请|请你|帮我|基于)|必须|每个实质性段落|不得/.test(candidate);
  const replaysQuestion = compactQuestion && compactCandidate
    && (compactQuestion.includes(compactCandidate) || compactCandidate.includes(compactQuestion));
  if (candidate && candidate.length <= 72 && !instructionLike && !replaysQuestion) {
    return candidate.replace(/[。；;：:\s]+$/, "");
  }
  const comparison = question.match(/(?:比较|对比)\s*([^。；;]+?)(?=(?:，?必须|，?需要|，?请|，?每个|，?不得|。|；|;|$))/);
  if (comparison?.[1]) {
    const subject = comparison[1].replace(/^(?:一下|原始论文中的)/, "").replace(/^[\s，,：:]+|[\s，,：:。；;]+$/g, "");
    if (subject) return `${subject.slice(0, 52)}：比较综述`;
  }
  let topic = question;
  const colon = topic.search(/[：:]/);
  if (colon >= 0 && /请|帮我|基于|撰写|生成/.test(topic.slice(0, colon))) topic = topic.slice(colon + 1);
  topic = topic.split(/必须|每个实质性段落|不得|请分别|需要分别/, 1)[0]
    .replace(/^(?:请|请你|帮我|请基于[^，,。；;]{0,60})\s*/, "")
    .replace(/^(?:撰写|写|生成|整理)(?:一篇|一份)?(?:中文)?(?:文献)?综述[：:]?\s*/, "")
    .replace(/(?:有哪些|有什么)?(?:可用)?证据[？?]?$/, "")
    .replace(/^[\s，,：:。；;？?"'“”]+|[\s，,：:。；;？?"'“”]+$/g, "");
  return topic ? `${topic.slice(0, 52)}：证据综述` : "文献证据综述";
}

function evidenceIndexContext(run) {
  const notebookId = String(run?.notebook_id || "");
  const notebook = (state.workspace?.notebooks || []).find((item) => String(item.notebook_id) === notebookId);
  const buildStage = (run?.stages || []).find((stage) => stage.key === "build") || {};
  const output = buildStage.output || {};
  const total = Math.max(0, Number(output.total || run?.input?.total_vectors || 0));
  const reportedCompleted = Number(output.completed || 0);
  const completed = Math.min(
    total || Number.MAX_SAFE_INTEGER,
    Math.max(reportedCompleted, Math.round(Number(run?.progress || 0) * total)),
  );
  return {
    title: String(notebook?.title || run?.input?.notebook_title || "当前知识库"),
    sourceCount: Math.max(0, Number(notebook?.counts?.sources || 0)),
    completed,
    total,
    reused: Math.max(0, Number(run?.input?.cached_vectors || 0)),
    migrated: Math.max(0, Number(run?.input?.migrated_vectors || 0)),
  };
}

function evidenceIndexRunTitle(run) {
  const context = evidenceIndexContext(run);
  return `正在优化「${context.title}」的语义检索`;
}

function runDisplayTitle(run) {
  if (run?.workflow_type === "evidence_index") return evidenceIndexRunTitle(run);
  if (!["literature_review", "deep_research"].includes(run?.workflow_type)) return String(run?.title || "未命名研究");
  return reviewDisplayTitle(run, run?.output_artifact?.payload?.review_document || {});
}

function buildReviewDocumentModel(run, artifact) {
  const payload = artifact?.payload || {};
  const supplied = payload.review_document || {};
  const legacy = !payload.review_document;
  const reader = payload.reader_answer || {};
  const sentences = (reader.sentences || []).map(normalizeReviewParagraph).filter((item) => item.text);
  const citations = (supplied.references || reader.citations || []).map((citation, index) => ({
    ...citation,
    citation_id: String(citation.citation_id || index + 1),
    paper: citation.paper || citation.title || citation.doc_id || `来源 ${index + 1}`,
  }));
  const abstract = normalizeReviewParagraph(supplied.abstract || sentences[0] || artifact?.summary || "当前资料库尚未形成可展示的摘要。", 0);
  let sections = [];
  if (Array.isArray(supplied.sections) && supplied.sections.length) {
    sections = supplied.sections.map((section, index) => ({
      id: String(section.id || `review-section-${index + 1}`),
      title: String(section.title || `主题 ${index + 1}`),
      paragraphs: (section.paragraphs || section.content || []).map(normalizeReviewParagraph).filter((item) => item.text),
    }));
  } else {
    const synthesis = (sentences.length > 1 ? sentences.slice(1) : sentences).filter((item) => item.text);
    sections = [{ id: "review-synthesis", title: "证据综合", paragraphs: synthesis.length ? synthesis : [abstract] }];
  }
  const limitations = (supplied.limitations || payload.answer?.limitations || []).map(String);
  const comparisonTable = {
    columns: (supplied.comparison_table?.columns || []).map(String),
    rows: (supplied.comparison_table?.rows || []).map((row) => ({
      cells: (row?.cells || []).map(String),
      citation_ids: (row?.citation_ids || []).map(String),
    })).filter((row) => row.cells.length),
  };
  const controversies = (supplied.controversies || []).map(normalizeReviewParagraph).filter((item) => item.text);
  const openQuestions = (supplied.open_questions || []).map((item, index) => ({
    ...normalizeReviewParagraph(item, index),
    basis: String(item?.basis || ""),
  })).filter((item) => item.text);
  const scope = typeof supplied.scope === "string" ? supplied.scope : String(supplied.scope?.description || "");
  const discoveryLeads = (payload.discovery?.items || []).slice(0, 20).map((item) => ({
    title: String(item.title || "未命名文献"),
    doi: String(item.doi || ""),
    year: item.year || "",
    venue: String(item.venue || ""),
    url: String(item.url || item.oa_url || ""),
    sources: (item.sources || [item.source]).filter(Boolean).map(String),
    acquired: Boolean((payload.acquisition?.acquired || []).some((record) => String(record.doi || "").toLowerCase() === String(item.doi || "").toLowerCase() && item.doi)),
  }));
  const documentCount = Number(payload.adequacy?.document_count || new Set(citations.map((item) => item.doc_id).filter(Boolean)).size || 0);
  const evidenceNotice = String(payload.evidence_notice || "");
  const evidenceLevel = String(payload.evidence_level || payload.evidence_status || "");
  const researchTrace = payload.research_trace || {};
  const insufficientEvidence = Boolean(payload.answer?.insufficient_evidence || payload.adequacy?.is_sufficient === false);
  const verified = !legacy && !insufficientEvidence && Boolean(payload.citation_verification?.passed ?? payload.answer?.citation_verification?.passed ?? payload.verification?.supported_claims?.length);
  const title = reviewDisplayTitle(run, supplied);
  const model = {
    title,
    abstract,
    sections,
    scope,
    comparisonTable,
    controversies,
    openQuestions,
    limitations,
    citations,
    discoveryLeads,
    documentCount,
    citationCount: Number(reader.citation_count || citations.length || 0),
    evidenceNotice,
    evidenceLevel,
    researchTrace,
    verified,
    insufficientEvidence,
    legacy,
    generatedAt: artifact?.created_at || run.updated_at || "",
  };
  model.outline = [
    { id: "review-abstract", title: "摘要" },
    ...sections.map((section) => ({ id: section.id, title: section.title })),
    ...(comparisonTable.rows.length ? [{ id: "review-comparison", title: "研究对比" }] : []),
    ...(controversies.length ? [{ id: "review-controversies", title: "证据分歧与争议" }] : []),
    ...(openQuestions.length ? [{ id: "review-open-questions", title: "开放问题" }] : []),
    ...(discoveryLeads.length ? [{ id: "review-discovery", title: "检索候选" }] : []),
    { id: "review-limitations", title: "证据边界" },
    { id: "review-references", title: "参考文献" },
  ];
  model.markdown = reviewDocumentMarkdown(model);
  return model;
}

function reviewDocumentMarkdown(model) {
  const citationSuffix = (ids = []) => ids.length ? ` ${ids.map((id) => `[${id}]`).join("")}` : "";
  const citedText = (item) => (item.sentences?.length ? item.sentences : [item])
    .map((sentence) => `${sentence.text}${citationSuffix(sentence.citation_ids)}`)
    .join(" ");
  const lines = [
    `# ${model.title}`,
    "",
    "## 摘要",
    "",
    citedText(model.abstract),
  ];
  model.sections.forEach((section) => {
    lines.push("", `## ${section.title}`, "");
    section.paragraphs.forEach((paragraph) => lines.push(citedText(paragraph), ""));
  });
  if (model.comparisonTable.rows.length) {
    const escapeCell = (value) => String(value).replaceAll("|", "\\|").replaceAll("\n", " ");
    const tableHeaders = [...model.comparisonTable.columns, "证据"];
    lines.push("", "## 研究对比", "", `| ${tableHeaders.map(escapeCell).join(" | ")} |`, `| ${tableHeaders.map(() => "---").join(" | ")} |`);
    model.comparisonTable.rows.forEach((row) => lines.push(`| ${[...row.cells, citationSuffix(row.citation_ids).trim()].map(escapeCell).join(" | ")} |`));
  }
  if (model.controversies.length) {
    lines.push("", "## 证据分歧与争议", "");
    model.controversies.forEach((item) => lines.push(`- ${citedText(item)}`));
  }
  if (model.openQuestions.length) {
    lines.push("", "## 开放问题", "");
    model.openQuestions.forEach((item) => lines.push(`- ${citedText(item)}${item.basis ? `\n  - 依据：${item.basis}` : ""}`));
  }
  if (model.discoveryLeads.length) {
    lines.push("", "## 检索候选（尚未自动视为证据）", "");
    model.discoveryLeads.forEach((item) => lines.push(`- ${item.title}${item.year ? ` (${item.year})` : ""}${item.doi ? ` — ${item.doi}` : ""}${item.acquired ? " — 已获取全文" : ""}`));
  }
  lines.push("", "## 证据边界", "");
  if (model.limitations.length) model.limitations.forEach((item) => lines.push(`- ${item}`));
  else lines.push("- 本综述仅综合当前项目资料库中的可核验证据，未覆盖的研究方向不代表不存在相关工作。");
  lines.push("", "## 参考文献", "");
  model.citations.forEach((citation, index) => lines.push(`${citation.citation_id || index + 1}. ${citation.paper}${citation.doi ? ` — ${citation.doi}` : ""}`));
  return lines.join("\n").trim();
}

function reviewCitationButtons(ids = []) {
  return ids.map((id) => `<button type="button" class="review-inline-citation" data-action="open-review-citation" data-citation-id="${escapeHtml(id)}" aria-label="查看证据 ${escapeHtml(id)}">${escapeHtml(id)}</button>`).join("");
}

function reviewCitedTextMarkup(item) {
  const sentences = item?.sentences?.length ? item.sentences : [item || {}];
  return sentences.map((sentence) => `${escapeHtml(sentence.text || "")}${reviewCitationButtons(sentence.citation_ids || [])}`).join(" ");
}

function reviewDocumentProgressMarkup(run) {
  const stages = [...(run.stages || [])].sort((left, right) => Number(left.position || 0) - Number(right.position || 0));
  const percent = Math.max(0, Math.min(100, Math.round(Number(run.progress || 0) * 100)));
  const current = stages.find((stage) => stage.status === "running")
    || stages.find((stage) => stage.key === run.current_stage)
    || stages.find((stage) => stage.status === "pending")
    || null;
  const completed = stages.filter((stage) => stage.status === "completed").length;
  const currentOutput = current?.output || {};
  const partialCount = Number(currentOutput.completed || 0);
  const partialTotal = Number(currentOutput.total || 0);
  const currentDetail = current?.summary
    || (partialTotal > 0 ? `${partialCount} / ${partialTotal}` : "")
    || (current ? "正在处理此阶段" : "正在准备研究步骤");
  const rows = stages.map((stage) => {
    const output = stage.output || {};
    const done = Number(output.completed || 0);
    const total = Number(output.total || 0);
    const detail = stage.error_message
      || stage.summary
      || (total > 0 ? `${done} / ${total}` : stage.status === "running" ? "正在处理" : stage.status === "completed" ? "已完成" : "等待开始");
    const marker = stage.status === "completed" ? "✓" : stage.status === "failed" ? "!" : stage.status === "running" ? "" : String(Number(stage.position || 0) + 1);
    return `<li class="${escapeHtml(stage.status || "pending")}"><span>${escapeHtml(marker)}</span><div><strong>${escapeHtml(stage.title || "研究步骤")}</strong><small>${escapeHtml(detail)}</small></div></li>`;
  }).join("");
  return `<section class="review-document-progress" aria-live="polite"><header><div><span>研究进展</span><strong>${percent}%</strong></div><p>${escapeHtml(current?.title || runStatusLabel(run))}</p><small>${escapeHtml(currentDetail)}</small></header><div class="review-progress-track" role="progressbar" aria-label="深度研究进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><i class="${progressWidthClass(percent)}"></i></div>${rows ? `<ol>${rows}</ol>` : ""}<footer><span>已完成 ${completed} / ${stages.length || 1} 个步骤</span><span>${escapeHtml(runStatusLabel(run))}</span></footer></section>`;
}

function reviewTaskMarkup(run, model, { percent, stages, actions }) {
  const outline = model?.outline || [
    { id: "review-abstract", title: "摘要" },
    { id: "review-synthesis", title: "主题证据综合" },
    { id: "review-limitations", title: "证据边界与开放问题" },
    { id: "review-references", title: "参考文献" },
  ];
  const outlineMarkup = outline.map((item, index) => `<li><button type="button" data-action="scroll-review-section" data-section-id="${escapeHtml(item.id)}"><b>${String(index + 1).padStart(2, "0")}</b><span>${escapeHtml(item.title)}</span><i>›</i></button></li>`).join("");
  const completed = (run.stages || []).filter((stage) => stage.status === "completed").length;
  const total = (run.stages || []).length;
  const summary = run.status === "completed" ? "全部步骤已完成" : runStatusLabel(run);
  const failure = run.status === "failed" ? `<div class="review-workflow-error"><strong>证据综述没有生成</strong><p>${escapeHtml(runFailureSummary(run))}</p><button type="button" data-action="open-settings" data-settings-panel="models">配置写作模型</button></div>` : "";
  const userMessage = conversationMessageMarkup({
    role: "user",
    content: runUserPromptText(run),
    createdAt: run.created_at,
    classes: "review-conversation-message",
  });
  return `<article class="review-task-shell">${userMessage}<div class="review-agent-head"><div class="review-agent-identity"><img src="/scansci-mark.png" alt="" /><span>ScanSci 写作智能体</span></div><span class="review-agent-meta">${percent}% · ${escapeHtml(runStatusLabel(run))}</span></div>${failure}<section class="review-outline-card"><span>Review outline</span><h2>${escapeHtml(model?.title || runDisplayTitle(run))}</h2><ol class="review-outline-list">${outlineMarkup}</ol><div class="review-run-actions">${actions}<button type="button" class="review-open-document" data-action="open-review-document" ${model ? "" : "disabled"}>打开稿件</button></div></section><details class="review-steps"><summary>${escapeHtml(summary)}<span>${completed}/${total}</span></summary><ol class="run-stage-list">${stages}</ol></details>${runCompletionMessageMarkup(run)}${taskConversationMarkup(run)}</article>`;
}

function renderReviewDocument(run, artifact, model = null) {
  const target = byId("reviewDocumentPanel");
  if (!target) return;
  const ready = Boolean(model);
  const percent = Math.max(0, Math.min(100, Math.round(Number(run.progress || 0) * 100)));
  const currentStage = (run.stages || []).find((stage) => stage.status === "running")
    || (run.stages || []).find((stage) => stage.key === run.current_stage);
  const title = ready ? "证据综述稿件" : compact(runDisplayTitle(run) || "正在生成证据综述", 72);
  const summary = ready ? (model.legacy ? "旧版任务 · 仅包含证据摘录，请重新生成" : model.insufficientEvidence ? `证据不足 · ${model.discoveryLeads.length} 条检索线索` : `${model.documentCount} 篇来源 · ${model.citationCount} 个证据锚点${model.verified ? " · 引用已核验" : ""}`) : `${percent}% · ${currentStage?.title || runStatusLabel(run)}`;
  const tabButtons = `<nav class="review-document-tabs" aria-label="稿件视图"><button type="button" class="is-active" data-action="review-document-tab" data-review-tab="preview" ${ready ? "" : "disabled"}>预览</button><button type="button" data-action="review-document-tab" data-review-tab="source" ${ready ? "" : "disabled"}>Markdown</button></nav>`;
  const toolbar = `<header class="review-panel-toolbar"><div class="review-document-identity"><span class="review-file-icon">${uiIcon("file-plus")}</span><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(summary)}</small></div></div><div class="review-toolbar-cluster">${tabButtons}<div class="review-toolbar-actions"><button type="button" class="review-save-note" data-action="save-review-note" ${ready ? "" : "disabled"}>保存为笔记</button><button type="button" class="review-icon-button" data-action="copy-review-document" aria-label="复制稿件" title="复制稿件" ${ready ? "" : "disabled"}>${uiIcon("copy")}</button><button type="button" class="review-icon-button" data-action="refresh-review-document" aria-label="刷新稿件" title="刷新稿件">${uiIcon("refresh")}</button><button type="button" class="review-icon-button" data-action="download-review-document" aria-label="下载 Markdown" title="下载 Markdown" ${ready ? "" : "disabled"}>${uiIcon("download")}</button><button type="button" class="review-icon-button" data-action="close-review-document" aria-label="关闭稿件" title="关闭稿件">${uiIcon("x")}</button></div></div></header>`;
  if (!ready) {
    const failed = run.status === "failed";
    const body = failed
      ? `<div class="review-document-empty is-error"><div><strong>未生成稿件</strong><p>${escapeHtml(runFailureSummary(run))}</p></div></div>`
      : `<div class="review-document-progress-shell">${reviewDocumentProgressMarkup(run)}</div>`;
    target.innerHTML = `${toolbar}<div class="review-document-body">${body}</div>`;
    return;
  }
  const sections = model.sections.map((section) => `<section id="${escapeHtml(section.id)}"><h2>${escapeHtml(section.title)}</h2>${section.paragraphs.map((paragraph) => `<p>${reviewCitedTextMarkup(paragraph)}</p>`).join("")}</section>`).join("");
  const comparison = model.comparisonTable.rows.length ? `<section id="review-comparison"><h2>研究对比</h2><div class="review-table-wrap"><table class="review-comparison-table"><thead><tr>${model.comparisonTable.columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}<th>证据</th></tr></thead><tbody>${model.comparisonTable.rows.map((row) => `<tr>${row.cells.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}<td class="review-table-citations">${reviewCitationButtons(row.citation_ids)}</td></tr>`).join("")}</tbody></table></div></section>` : "";
  const controversies = model.controversies.length ? `<section id="review-controversies"><h2>证据分歧与争议</h2><div class="review-finding-list">${model.controversies.map((item, index) => `<article><span>${String(index + 1).padStart(2, "0")}</span><p>${reviewCitedTextMarkup(item)}</p></article>`).join("")}</div></section>` : "";
  const openQuestions = model.openQuestions.length ? `<section id="review-open-questions"><h2>开放问题</h2><div class="review-question-grid">${model.openQuestions.map((item, index) => `<article><span>Q${index + 1}</span><h3>${reviewCitedTextMarkup(item)}</h3>${item.basis ? `<p>${escapeHtml(item.basis)}</p>` : ""}</article>`).join("")}</div></section>` : "";
  const discovery = model.discoveryLeads.length ? `<section id="review-discovery"><h2>检索候选</h2><p class="review-discovery-notice">这些记录来自多源学术搜索；只有标记“已获取全文”的论文才可能进入上方句级证据链。</p><ol class="review-reference-list">${model.discoveryLeads.map((item) => `<li><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml([item.year, item.venue, item.doi].filter(Boolean).join(" · "))}</span><br /><small>${escapeHtml(item.sources.join(" + "))}${item.acquired ? " · 已获取全文" : " · 发现线索"}</small></li>`).join("")}</ol></section>` : "";
  const limitations = model.limitations.length ? model.limitations.map((item) => `<p>${escapeHtml(item)}</p>`).join("") : "<p>本综述仅综合当前项目资料库中的可核验证据；未覆盖的研究方向不代表不存在相关工作。</p>";
  const references = model.citations.length ? model.citations.map((citation) => `<li><strong>${escapeHtml(citation.paper)}</strong><span>${escapeHtml([citation.section, citation.doi].filter(Boolean).join(" · "))}</span><br /><button type="button" data-action="open-review-citation" data-citation-id="${escapeHtml(citation.citation_id)}">查看证据与原文锚点</button></li>`).join("") : "<li>当前稿件没有可回跳引用。</li>";
  const legacyNotice = model.legacy ? `<div class="review-legacy-notice"><strong>这不是完整综述</strong><p>该任务由旧版流程生成，只包含检索摘录。请回到写作模式重新生成，新的流程会完成章节检索、跨论文比较、争议分析和开放问题。</p></div>` : "";
  const evidenceNotice = model.evidenceNotice ? `<div class="review-evidence-notice"><strong>${model.evidenceLevel === "fulltext" ? "全文证据链" : "证据范围"}</strong><p>${escapeHtml(model.evidenceNotice)}</p></div>` : "";
  const preview = `<div class="review-document-view review-preview-view is-active" data-review-view="preview"><article class="review-paper"><div class="review-paper-kicker">证据综述 <span>${model.legacy ? "旧版摘录" : model.insufficientEvidence ? "证据不足" : model.verified ? "引用已核验" : "待人工复核"}</span></div><h1>${escapeHtml(model.title)}</h1><div class="review-paper-meta"><span><b>${model.documentCount}</b> 篇来源</span><span><b>${model.citationCount}</b> 个证据锚点</span><span>${model.insufficientEvidence ? "证据不足，未生成科学结论" : model.verified ? "引用核验通过" : model.legacy ? "旧版摘录" : "建议人工复核"}</span></div>${legacyNotice}${evidenceNotice}<section id="review-abstract"><h2>摘要</h2><p class="review-lead">${reviewCitedTextMarkup(model.abstract)}</p></section>${sections}${comparison}${controversies}${openQuestions}${discovery}<section id="review-limitations"><h2>证据边界</h2><div class="review-limitations">${limitations}</div></section><section id="review-references"><h2>参考文献</h2><ol class="review-reference-list">${references}</ol></section></article></div>`;
  const source = `<div class="review-document-view review-source-view" data-review-view="source"><pre><code>${escapeHtml(model.markdown)}</code></pre></div>`;
  target.innerHTML = `${toolbar}<div class="review-document-body">${preview}${source}<aside class="review-evidence-drawer" id="reviewEvidenceDrawer" aria-live="polite"></aside></div>`;
}

function researchIdeaCardMarkup(payload) {
  const candidate = payload.candidate || {};
  const bottleneck = payload.bottleneck || {};
  const coherence = payload.coherence_audit || {};
  const falsifiability = payload.falsifiability_audit || {};
  const implementability = payload.implementability_audit || {};
  const nextGate = payload.required_next_gate || {};
  const gates = payload.quality_gates || {};
  const gateLabels = [
    ["grounded_bottleneck", "证据瓶颈"],
    ["coherence", "机制连贯"],
    ["falsifiability", "可证伪"],
    ["implementability", "可实现"],
    ["novelty", "独立查新"],
  ];
  const gateStrip = gateLabels.map(([key, label]) => {
    const pending = key === "novelty" && !gates[key];
    const passed = Boolean(gates[key]);
    return `<span class="idea-gate ${passed ? "is-passed" : pending ? "is-pending" : "is-blocked"}"><i>${passed ? "✓" : pending ? "→" : "!"}</i><b>${escapeHtml(label)}</b><em>${passed ? "通过" : pending ? "待审" : "未通过"}</em></span>`;
  }).join("");
  const citedClaims = (items = []) => items.map((item) => {
    const citations = (item.citation_ids || []).map(citationMarkerMarkup).join("");
    return `<li><p>${escapeHtml(item.text || "")}</p><span>${citations}</span></li>`;
  }).join("");
  const mechanismSteps = (candidate.mechanism_steps || []).map((step, index) => `<li><span>${String(index + 1).padStart(2, "0")}</span><div><strong>${escapeHtml(step.action || "方法步骤")}</strong><p><b>输入</b>${escapeHtml(step.input || "—")}</p><p><b>输出</b>${escapeHtml(step.output || "—")}</p></div></li>`).join("");
  const implementationByStep = new Map((implementability.enriched_steps || []).map((item) => [String(item.step_id || ""), item]));
  const implementationSteps = (candidate.mechanism_steps || []).map((step) => {
    const spec = implementationByStep.get(String(step.id || "")) || {};
    const dependencies = (spec.dependencies || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
    return `<article><header><b>${escapeHtml(step.id || "STEP")}</b><strong>${escapeHtml(spec.implementation || step.action || "尚未形成实现规格")}</strong></header>${dependencies ? `<div class="idea-dependencies">${dependencies}</div>` : ""}<p><em>验收</em>${escapeHtml(spec.acceptance_check || "待补充")}</p></article>`;
  }).join("");
  const openHoles = (implementability.underspecified_points || []).filter((item) => item.severity === "open");
  const holesMarkup = openHoles.map((item) => `<li><b>${escapeHtml(item.step_id || "未定位")}</b><span>${escapeHtml(item.hole || "未说明")}</span>${item.fill ? `<small>${escapeHtml(item.fill)}</small>` : ""}</li>`).join("");
  const dryRun = coherence.dry_run || {};
  const trace = (dryRun.step_trace || []).map((item, index) => `<li><b>${String(index + 1).padStart(2, "0")}</b><span>${escapeHtml(typeof item === "string" ? item : item.result || item.output || item.action || JSON.stringify(item))}</span></li>`).join("");
  const falsification = candidate.falsification || {};
  const falsificationFields = [
    ["关键实验", falsification.experiment],
    ["结果指标", falsification.outcome_metric],
    ["预期方向", falsification.expected_direction],
    ["承重变量", falsification.load_bearing_variable],
    ["负对照", falsification.negative_control],
    ["终止条件", falsification.failure_condition],
  ].map(([label, value]) => `<div><span>${label}</span><p>${escapeHtml(value || "未定义")}</p></div>`).join("");
  const evidence = [
    ...(bottleneck.evidence_claims || []),
    ...(candidate.evidence_basis || []),
  ];
  const limitations = (payload.limitations || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const ideaStatus = payload.status === "ready_for_novelty_check" ? "is-ready" : "is-revision";
  return `<article class="research-idea-card ${ideaStatus}"><header class="idea-hero"><div><span>ONE CANDIDATE · EVIDENCE FIRST</span><h3>${escapeHtml(candidate.title || payload.title || "研究候选")}</h3><p>${escapeHtml(candidate.hook || payload.reader_answer?.text || "")}</p></div><aside><small>当前状态</small><b>${payload.status === "ready_for_novelty_check" ? "待查新" : "需修订"}</b><em>不宣称已创新</em></aside></header><div class="idea-gate-strip" aria-label="研究构思质量门">${gateStrip}</div><section class="idea-thesis"><span>核心机制</span><p>${escapeHtml(candidate.core_mechanism || "尚未形成可审查的核心机制。")}</p></section><div class="idea-two-column"><section class="idea-panel idea-bottleneck"><header><span>01</span><div><small>LOAD-BEARING BOTTLENECK</small><h4>承重瓶颈</h4></div></header><p class="idea-lead">${escapeHtml(bottleneck.bottleneck_statement || bottleneck.reason || "证据不足，尚不能诊断瓶颈。")}</p>${bottleneck.why_load_bearing ? `<p>${escapeHtml(bottleneck.why_load_bearing)}</p>` : ""}<ul class="idea-evidence-claims">${citedClaims(bottleneck.evidence_claims || [])}</ul></section><section class="idea-panel idea-mechanism"><header><span>02</span><div><small>MECHANISM PATH</small><h4>机制路径</h4></div></header><ol>${mechanismSteps || "<li>尚无可执行步骤。</li>"}</ol></section></div><section class="idea-panel idea-evidence"><header><span>03</span><div><small>FULL-TEXT BASIS</small><h4>全文证据依据</h4></div></header><ul class="idea-evidence-claims">${citedClaims(evidence) || "<li><p>当前没有形成可回跳的全文证据链。</p></li>"}</ul></section><section class="idea-panel idea-falsification"><header><span>04</span><div><small>KILL THE IDEA EARLY</small><h4>可证伪设计</h4></div></header><div class="idea-falsification-grid">${falsificationFields}</div></section><div class="idea-two-column idea-audits"><section class="idea-panel"><header><span>05</span><div><small>MODEL-SIMULATED · NOT EXECUTED</small><h4>连贯性演算</h4></div></header><div class="idea-simulation-label">${uiIcon("brain")} 模型结构化模拟，不是真实代码执行</div><p><b>例子：</b>${escapeHtml(dryRun.example || "未提供")}</p><ol class="idea-trace">${trace || "<li><span>没有有效演算轨迹。</span></li>"}</ol>${dryRun.result ? `<p><b>演算结果：</b>${escapeHtml(dryRun.result)}</p>` : ""}</section><section class="idea-panel"><header><span>06</span><div><small>BUILD SPECIFICATION</small><h4>可实现性规格</h4></div></header><div class="idea-implementation">${implementationSteps || "<p>尚未形成实现规格。</p>"}</div>${holesMarkup ? `<div class="idea-open-holes"><strong>仍需补齐</strong><ul>${holesMarkup}</ul></div>` : ""}</section></div><section class="idea-next-gate"><div><span>${uiIcon("shield-check")}</span><div><small>REQUIRED NEXT GATE</small><h4>最后再做独立证据查新</h4><p>构思通过内部质量门不等于新颖。下一步会用同一问题与核心机制检索潜在重合工作。</p></div></div><button type="button" data-action="prepare-idea-novelty" data-novelty-problem="${escapeHtml(nextGate.problem || payload.direction || "")}" data-novelty-claim="${escapeHtml(nextGate.novelty || candidate.core_mechanism || "")}">带入证据查新 ${uiIcon("arrow-right")}</button></section>${limitations ? `<footer class="idea-limitations"><strong>结论边界</strong><ul>${limitations}</ul></footer>` : ""}</article>`;
}

function noveltyAssessmentMarkup(payload) {
  const verdict = payload.verdict || {};
  const adequacy = payload.evidence_adequacy || {};
  const coverage = payload.coverage || {};
  const axisLabels = {
    problem_framing: "问题设定",
    core_mechanism: "核心机制",
    key_insight: "关键洞见",
    application_domain: "应用领域",
  };
  const statusLabels = { match: "重合", partial: "部分重合", differ: "差异", unknown: "证据未知" };
  const priorWorks = (payload.prior_works || []).map((work, index) => {
    const axes = Object.entries(axisLabels).map(([key, label]) => {
      const status = work.axes?.[key] || "unknown";
      return `<span class="novelty-axis ${escapeHtml(status)}"><b>${escapeHtml(label)}</b><em>${escapeHtml(statusLabels[status] || status)}</em></span>`;
    }).join("");
    const citations = (work.citation_ids || []).map(citationMarkerMarkup).join("");
    return `<article class="novelty-prior-work"><header><span>${String(index + 1).padStart(2, "0")}</span><div><h4>${escapeHtml(work.paper || "未命名文献")}</h4><small>${escapeHtml(`${Number(work.matching_axis_count || 0)} / 4 轴存在重合风险`)}</small></div>${citations}</header><div class="novelty-axis-row">${axes}</div>${work.summary ? `<p>${escapeHtml(work.summary)}</p>` : ""}</article>`;
  }).join("");
  const limitations = (payload.limitations || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const providerText = (coverage.providers_succeeded || []).join(" · ") || "未记录";
  const level = verdict.level == null ? "—" : String(verdict.level);
  const delta = payload.delta_statement
    ? `<section class="novelty-delta"><span>可辩护差异</span><p>${escapeHtml(payload.delta_statement)}</p></section>`
    : "";
  const unresolved = verdict.code === "unresolved";
  return `<article class="novelty-report ${unresolved ? "is-unresolved" : ""}"><header class="novelty-verdict"><div><span>PRIOR-ART OVERLAP · FULL-TEXT GROUNDED</span><h3>${escapeHtml(verdict.label || "查新审查")}</h3><p>${escapeHtml(payload.reader_answer?.text || "")}</p></div><div class="novelty-level"><b>${escapeHtml(level)}</b><span>${verdict.level == null ? "未定级" : "风险级别"}</span></div></header><div class="novelty-audit-strip"><span><b>${escapeHtml(String(coverage.query_count || 0))}</b> 检索式</span><span><b>${escapeHtml(String(coverage.deduplicated_count || 0))}</b> 候选工作</span><span><b>${escapeHtml(String(adequacy.document_count || 0))}</b> 全文文献</span><span><b>${escapeHtml(String(adequacy.citation_count || 0))}</b> 证据片段</span></div><p class="novelty-source-line">检索来源：${escapeHtml(providerText)}</p>${delta}<section class="novelty-prior-list"><header><span>逐论文四轴审查</span><small>差异结论无法由引文证明时必须标记“证据未知”</small></header>${priorWorks || '<div class="novelty-empty">当前没有形成可引用的逐论文重合判断。</div>'}</section><section class="novelty-caveat"><strong>${uiIcon("shield-check")} 结论边界</strong><ul>${limitations || "<li>未检出强重合不等于证明新颖。</li>"}</ul></section></article>`;
}

function localPathLeaf(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || String(path || "");
}

function localPathParent(path) {
  const value = String(path || "").trim().replace(/[\\/]+$/, "");
  const separator = Math.max(value.lastIndexOf("\\"), value.lastIndexOf("/"));
  return separator > 2 ? value.slice(0, separator) : "";
}

function localFileLinkMarkup(path, label = "", { folder = false, compact = false, inline = false } = {}) {
  const value = String(path || "").trim();
  if (!value) return "";
  const name = label || localPathLeaf(value);
  const kind = localResourceKind(value, { folder });
  const classes = ["local-artifact-link", compact ? "is-compact" : "", inline ? "is-inline" : ""].filter(Boolean).join(" ");
  return `<span class="${classes}" title="${escapeHtml(value)}"><button type="button" class="local-artifact-open" data-action="open-local-path" data-local-path="${escapeHtml(value)}" aria-label="${kind === "folder" ? "打开文件夹" : "打开文件"} ${escapeHtml(name)}"><span class="local-artifact-icon is-${escapeHtml(kind)}">${uiIcon(localResourceIcon(kind))}</span><span>${escapeHtml(name)}</span></button>${kind === "folder" || inline ? "" : `<button type="button" class="local-artifact-reveal" data-action="reveal-local-path" data-local-path="${escapeHtml(value)}" aria-label="在文件夹中显示 ${escapeHtml(name)}" title="在文件夹中显示">${uiIcon("folder-open")}</button>`}</span>`;
}

async function openLocalArtifact(path, { reveal = false } = {}) {
  const method = reveal ? "reveal_local_path" : "open_local_path";
  const api = window.pywebview?.api;
  if (!api || typeof api[method] !== "function") {
    throw new Error("请在 ScanSci 桌面应用中打开本地文件");
  }
  const result = await api[method](String(path || ""));
  if (!result?.ok) throw new Error(result?.message || "本地文件无法打开");
  return result;
}

function downloadedPaperArtifactMarkup(artifact) {
  const payload = artifact.payload || {};
  const papers = new Map((payload.papers || []).map((paper) => [String(paper.identifier || paper.doi || paper.arxiv_id || "").toLowerCase(), paper]));
  const items = Array.isArray(payload.items) && payload.items.length
    ? payload.items
    : [{ identifier: payload.identifier || artifact.title, status: payload.ok === false ? "failed" : "completed", files: payload.files || [] }];
  const completed = Number(payload.completed ?? items.filter((item) => item.status === "completed").length);
  const failed = Number(payload.failed ?? items.filter((item) => item.status === "failed").length);
  const pending = Math.max(0, items.length - completed - failed);
  const rows = items.map((item, index) => {
    const paper = papers.get(String(item.identifier || "").toLowerCase()) || {};
    const title = paper.title || item.identifier || `论文 ${index + 1}`;
    const status = item.status === "completed" ? "已保存" : item.status === "failed" ? "未获取" : item.status || "等待中";
    const files = Array.isArray(item.files) ? item.files.map((file) => localFileLinkMarkup(file, "", { compact: true })).join("") : "";
    const meta = [item.identifier, paper.year, paper.cited_by_count ? `${paper.cited_by_count} 次引用` : ""].filter(Boolean).join(" · ");
    return `<div class="downloaded-paper-row ${escapeHtml(item.status || "pending")}"><span>${item.status === "completed" ? "✓" : item.status === "failed" ? "!" : index + 1}</span><div><strong>${escapeHtml(title)}</strong>${meta ? `<small>${escapeHtml(meta)}</small>` : ""}${files ? `<div class="downloaded-paper-files">${files}</div>` : ""}${item.error ? `<em>${escapeHtml(item.error)}</em>` : ""}</div><b>${escapeHtml(status)}</b></div>`;
  }).join("");
  return `<article class="downloaded-paper-artifact"><header><div><span>FULL TEXT</span><h3>${escapeHtml(payload.message || artifact.summary || "文献下载已完成")}</h3></div><div class="downloaded-paper-metrics"><span><b>${completed}</b> 已保存</span><span><b>${failed}</b> 未获取</span>${pending ? `<span><b>${pending}</b> 待处理</span>` : ""}</div></header>${payload.output_dir ? `<div class="artifact-folder-link">${localFileLinkMarkup(payload.output_dir, localPathLeaf(payload.output_dir), { folder: true, inline: true })}</div>` : ""}<div class="downloaded-paper-list">${rows}</div></article>`;
}

function partialDownloadArtifactMarkup(run) {
  if (!String(run.workflow_type || "").startsWith("paper_")) return "";
  const stage = (run.stages || []).find((item) => item.key === "execute") || (run.stages || []).find((item) => item.kind === "tool");
  const output = stage?.output || {};
  const items = Array.isArray(output.items) ? output.items : [];
  if (!items.length) return "";
  const payload = {
    ...output,
    items,
    papers: Array.isArray(output.papers) ? output.papers : [],
    output_dir: output.output_dir || run.input?.output_dir || "",
    message: run.status === "paused" ? "任务中断前已保存的下载结果" : "下载进行中的结果",
  };
  const artifact = { title: run.title, summary: payload.message, payload };
  const note = run.status === "paused"
    ? `<p class="run-partial-result-note">这些是应用重启前已经落盘的结果；点击“继续”会从未完成阶段接着下载。</p>`
    : `<p class="run-partial-result-note">结果会边下载边保存，任务完成后将转换为最终交付记录。</p>`;
  return `${downloadedPaperArtifactMarkup(artifact)}${note}`;
}

function academicSearchArtifactMarkup(payload) {
  const plan = payload.search_plan || {};
  const gate = payload.quality_gate || {};
  const items = Array.isArray(payload.items) ? payload.items : [];
  const accepted = Number(gate.accepted_count ?? payload.count ?? items.length);
  const rejected = Number(gate.rejected_count || 0);
  const insufficient = ["insufficient", "no_candidates"].includes(String(gate.status || ""));
  const variants = Array.isArray(payload.query_variants) && payload.query_variants.length
    ? payload.query_variants
    : (Array.isArray(plan.query_variants) ? plan.query_variants : []);
  const providers = Array.isArray(payload.providers_requested) && payload.providers_requested.length
    ? payload.providers_requested
    : (Array.isArray(plan.providers) ? plan.providers : []);
  const succeededProviders = Array.isArray(payload.providers_succeeded) ? payload.providers_succeeded : [];
  const providerCounts = payload.provider_counts && typeof payload.provider_counts === "object" ? payload.provider_counts : {};
  const providerErrors = payload.provider_errors && typeof payload.provider_errors === "object" ? payload.provider_errors : {};
  const queryChips = variants.slice(0, 3).map((item) => `<code>${escapeHtml(item)}</code>`).join("");
  const providerText = providers.map((item) => academicProviderLabels[String(item)] || String(item).replace(/-/g, " ")).join(" · ") || "暂无可用来源";
  const sourceCoverage = `${succeededProviders.length} / ${providers.length || succeededProviders.length} 个来源可用`;
  const sourceRows = providers.map((provider) => {
    const name = String(provider);
    const label = academicProviderLabels[name] || name;
    const error = String(providerErrors[name] || "").trim();
    const count = Number(providerCounts[name] || 0);
    return `<li class="${error ? "is-failed" : succeededProviders.includes(name) ? "is-ready" : "is-empty"}"><span>${escapeHtml(label)}</span><small>${error ? "暂不可用" : `${count} 条记录`}</small>${error ? `<em title="${escapeHtml(error)}">${escapeHtml(error)}</em>` : ""}</li>`;
  }).join("");
  const qualityLine = insufficient
    ? `<div class="academic-search-gate is-warning"><strong>没有交付不相关的文献</strong><span>${escapeHtml(gate.reason || "请检查主题措辞，或补充英文同义词后重试。")}</span></div>`
    : `<div class="academic-search-gate"><strong>主题相关性已核验</strong><span>保留 ${escapeHtml(String(accepted))} 条${rejected ? `，筛除 ${escapeHtml(String(rejected))} 条泛匹配候选` : ""}</span></div>`;
  const rows = items.length ? items.map((paper, index) => {
    const authors = Array.isArray(paper.authors) ? paper.authors.slice(0, 3).join("、") : "";
    const details = [authors, paper.year, paper.venue].filter(Boolean).join(" · ");
    const source = Array.isArray(paper.sources) ? paper.sources.join(" · ") : paper.source || "";
    const destination = String(paper.oa_url || paper.url || (paper.doi ? `https://doi.org/${paper.doi}` : "")).trim();
    const title = escapeHtml(paper.title || `候选文献 ${index + 1}`);
    const action = destination
      ? `<button type="button" class="academic-paper-open" data-action="open-external" data-url="${escapeHtml(destination)}">查看来源</button>`
      : "";
    return `<li><span>${index + 1}</span><div><strong title="${title}">${title}</strong>${details ? `<small>${escapeHtml(details)}</small>` : ""}${paper.doi ? `<code>DOI ${escapeHtml(paper.doi)}</code>` : ""}</div><aside><small>${escapeHtml(source)}</small>${action}</aside></li>`;
  }).join("") : "";
  const diagnostics = `<details class="academic-search-details"><summary>检索详情</summary><div><p><b>主题</b>${escapeHtml(plan.normalized_topic || plan.topic || payload.query || "")}</p><p><b>检索式</b>${queryChips || "<span>未记录</span>"}</p><p><b>来源</b>${escapeHtml(providerText)}</p><p><b>候选</b>${escapeHtml(String(payload.candidate_count || 0))} 条原始记录，去重后 ${escapeHtml(String(payload.deduplicated_count || 0))} 条</p><section class="academic-source-coverage"><strong>来源覆盖</strong><span>${escapeHtml(sourceCoverage)}</span><ul>${sourceRows || "<li><span>暂无来源状态</span></li>"}</ul></section></div></details>`;
  const discoveryNotice = `<p class="academic-discovery-notice">这是公开元数据检索的候选集，未自动写入知识库；需要引用时，请先取得合法全文并完成证据索引。</p>`;
  return `<article class="academic-search-artifact ${insufficient ? "is-insufficient" : ""}"><header><div><span>ACADEMIC DISCOVERY</span><h3>${escapeHtml(plan.normalized_topic || plan.topic || payload.query || "学术检索")}</h3></div><b>${insufficient ? "需调整检索式" : `${accepted} 条高相关`}</b></header>${qualityLine}${rows ? `<ol class="academic-paper-list">${rows}</ol>` : `<div class="academic-search-empty"><strong>没有可交付的高相关候选</strong><p>已保留本次检索计划和来源诊断；请把主题写得更具体，或补充英文术语后重试。</p></div>`}${discoveryNotice}${diagnostics}</article>`;
}

function genericArtifactMarkup(artifact) {
  const payload = artifact.payload || {};
  const rows = payload.items || payload.results || payload.slides || payload.files || [];
  const rowMarkup = Array.isArray(rows) && rows.length ? `<div class="artifact-items">${rows.slice(0, 12).map((row, index) => {
    const item = typeof row === "string" ? { title: row } : row;
    const title = item.title || item.name || item.identifier || item.doi || item.path || `结果 ${index + 1}`;
    const meta = item.cas_partition || item.jcr_quartile || item.purpose || item.status || item.source || "";
    return `<div><span>${index + 1}</span><p><strong>${escapeHtml(title)}</strong>${meta ? `<small>${escapeHtml(meta)}</small>` : ""}</p></div>`;
  }).join("")}</div>` : "";
  const filePath = artifact.file_path ? `<div class="artifact-file-link">${localFileLinkMarkup(artifact.file_path, "", { inline: true })}</div>` : "";
  const external = payload.external_url ? `<button type="button" class="secondary-button" data-action="open-external" data-url="${escapeHtml(payload.external_url)}">在网页中继续 ↗</button>` : "";
  return `<article class="artifact-card"><span class="artifact-type">${escapeHtml(artifact.artifact_type)}</span><h3>${escapeHtml(artifact.title)}</h3><p>${escapeHtml(artifact.summary || payload.message || "研究产物已保存")}</p>${filePath}${rowMarkup}${external}</article>`;
}

function bindRunCitations(result) {
  bindCitationInteractions(result);
}

async function openTask(id, { record = true } = {}) {
  try {
    const run = await request(`/api/runs/${encodeURIComponent(id)}`);
    let displayRun = run;
    // An application restart is an infrastructure interruption, not a user
    // decision to pause. Reconnect the remembered task automatically so the
    // worker can finish and deliver its artifact without a silent gap.
    if (run.status === "paused" && run.error?.code === "app_restarted") {
      try {
        displayRun = await request(`/api/runs/${encodeURIComponent(id)}/resume`, { method: "POST", body: "{}" });
      } catch (error) {
        console.warn("Automatic task recovery failed", error);
      }
    }
    upsertRun(displayRun);
    state.activeTaskId = displayRun.run_id;
    window.localStorage.setItem("scansci.active.task", displayRun.run_id);
    state.sessionId = `research-run-${displayRun.run_id}`;
    window.localStorage.setItem("scansci.active.session", state.sessionId);
    void restoreSessionStats(estimateRunSessionStats(displayRun));
    if (displayRun.workflow_type === "pdf_to_ppt") {
      const composer = byId("chatQuestionInput");
      if (composer) composer.placeholder = "通用模式可继续讨论；幻灯片模式可选择模板后重新制作";
    }
    byId("conversationTitle").textContent = ["literature_review", "deep_research"].includes(run.workflow_type) ? (run.workflow_type === "deep_research" ? "深度研究" : "证据综述") : compact(runDisplayTitle(run), 80);
    // A direct-chat render can leave the previous task's render key behind.
    // Invalidate it whenever a history item is opened so the fetched run,
    // including its durable message history, replaces the visible thread.
    state.lastRunRenderKey = "";
    setView("conversation", { record });
    try {
      renderRun(displayRun);
    } catch (error) {
      // Keep a failed renderer from leaving the previous direct-chat thread
      // on screen.  The diagnostic is visible in the task surface and also
      // helps identify malformed historical payloads during recovery.
      byId("answerArea").innerHTML = `<div class="error-state">历史任务显示失败：${escapeHtml(error.message || error)}</div>`;
      console.error("Failed to render historical task", error);
    }
    if (!["completed", "failed", "cancelled", "paused"].includes(displayRun.status)) {
      watchRun(displayRun.run_id, (next) => {
        if (state.activeView === "conversation" && state.activeTaskId === next.run_id) renderRun(next);
      });
    }
  } catch (error) {
    toast(error.message, true);
  }
}

const modeDefinitions = {
  library: { overline: "本地研究空间", title: "知识库" },
  tools: { overline: "ScanSci Suite", title: "功能" },
  review: { overline: "Evidence Studio", title: "文献综述" },
  atlas: { overline: "Paper Atlas", title: "研究图谱" },
  ppt: { overline: "EasySlides", title: "PPT Studio" },
  download: { overline: "scansci-pdf · open access", title: "论文获取" },
  journal: { overline: "Journal Scout", title: "期刊查询" },
  verify: { overline: "Citation Lab", title: "引文核查" },
};

function renderMode() {
  const definition = modeDefinitions[state.activeMode] || modeDefinitions.tools;
  byId("modeOverline").textContent = definition.overline;
  byId("modeTitle").textContent = definition.title;
  document.querySelectorAll("[data-mode]").forEach((button) => button.classList.toggle("is-active", button.dataset.mode === state.activeMode));
  const target = byId("modeContent");
  target.classList.toggle("is-library-mode", state.activeMode === "library");
  document.querySelector(".mode-view")?.classList.toggle("is-library-mode", state.activeMode === "library");
  if (state.activeMode === "library") {
    target.innerHTML = renderImaLibraryMode();
    syncKnowledgeLibraryKindLabel();
    syncKnowledgeTreeControl();
  }
  else if (state.activeMode === "review") target.innerHTML = renderReviewMode();
  else if (state.activeMode === "journal") target.innerHTML = renderJournalMode();
  else if (state.activeMode === "verify") target.innerHTML = renderVerifyMode();
  else if (state.activeMode === "atlas") target.innerHTML = renderAtlasMode();
  else if (state.activeMode === "download") target.innerHTML = renderDownloadMode();
  else if (state.activeMode === "ppt") target.innerHTML = renderPptMode();
  else target.innerHTML = renderToolsMode();
}

function modeIntro(text, meta = "") {
  return `<div class="mode-intro"><p>${escapeHtml(text)}</p>${meta ? `<span>${escapeHtml(meta)}</span>` : ""}</div>`;
}

function syncKnowledgeLibraryKindLabel() {
  if (state.activeMode !== "library") return;
  const label = document.querySelector(".ima-library-heading > div > span");
  if (label && knowledgeSourceKind(state.notebook) === "notion") label.textContent = "Notion";
}

function syncKnowledgeTreeControl() {
  if (state.activeMode !== "library") return;
  const toolbar = document.querySelector(".ima-library-toolbar");
  if (!toolbar) return;
  let button = toolbar.querySelector('[data-action="toggle-knowledge-folders"]');
  if (!button) {
    toolbar.insertAdjacentHTML(
      "beforeend",
      '<button type="button" class="ima-tree-toggle" data-action="toggle-knowledge-folders"></button>',
    );
    button = toolbar.querySelector('[data-action="toggle-knowledge-folders"]');
  }
  const expanded = state.knowledgeTreeExpanded !== false;
  button.innerHTML = `${uiIcon("chevron-down")}${expanded ? "全部收起" : "全部展开"}`;
  button.setAttribute("aria-label", expanded ? "全部收起文件夹" : "全部展开文件夹");
  button.title = expanded ? "收起所有文件夹" : "展开所有文件夹";
}

function libraryKindCopy(kind) {
  if (kind === "zotero") return { title: "Zotero", detail: "本机文献数据库", icon: "library" };
  if (kind === "obsidian") return { title: "Obsidian", detail: "Vault 或笔记文件夹", icon: "book" };
  if (kind === "notion") return { title: "Notion", detail: "页面与数据库同步", icon: "book" };
  if (kind === "empty") return { title: "自建知识库", detail: "逐步添加本地文件", icon: "file-plus" };
  if (kind === "files") return { title: "本地文件", detail: "多个独立文献文件", icon: "file-plus" };
  return { title: "本地文件夹", detail: "绑定原位置并建立索引", icon: "folder-open" };
}

function pathLeaf(path) {
  const raw = String(path || "").trim();
  if (!raw || raw === ".") return "当前资料目录";
  const parts = raw.split(/[\\/]+/).filter(Boolean);
  return parts.at(-1) || "未命名知识库";
}

function libraryBookMarkup(source, index, { external = false } = {}) {
  const details = source.doi || (source.publication_year ? `${source.publication_year} · 文献` : external ? "Zotero PDF · 等待解析" : "已建立证据索引");
  const tag = external ? "span" : "button";
  const action = external ? "" : ` type="button" data-action="open-source-reader" data-doc-id="${escapeHtml(source.doc_id)}"`;
  return `<${tag} class="knowledge-book book-tone-${index % 6}${external ? " is-external" : ""}"${action}><span class="knowledge-book-head"><small>${external ? "ZOTERO" : `文献 ${String(index + 1).padStart(2, "0")}`}</small>${uiIcon(external ? "book" : "file-plus")}</span><strong>${escapeHtml(compact(source.title || source.doc_id || "未命名文献", 68))}</strong><em>${escapeHtml(compact(String(details), 52))}</em></${tag}>`;
}

function renderLibraryMode() {
  const notebooks = state.workspace?.notebooks || [];
  const active = state.notebook;
  const zoteroLibraries = notebooks.filter((item) => String(item.metadata?.library_kind || "") === "zotero");
  const obsidianLibraries = notebooks.filter((item) => String(item.metadata?.library_kind || "") === "obsidian");
  const notionLibraries = notebooks.filter((item) => String(item.metadata?.library_kind || "") === "notion");
  const localLibraries = notebooks.filter((item) => !["zotero", "obsidian", "notion"].includes(String(item.metadata?.library_kind || "folder")));
  const totalSources = notebooks.reduce((sum, item) => sum + Number(item.counts?.sources || 0), 0);
  const sourceRows = notebooks.map((notebook) => {
    const kindKey = String(notebook.metadata?.library_kind || "folder");
    const kind = libraryKindCopy(kindKey);
    const selected = notebook.notebook_id === active?.notebook_id;
    const count = Number(notebook.counts?.sources || 0);
    const zotero = notebook.metadata?.zotero || {};
    const itemCount = kindKey === "zotero" ? Number(zotero.item_count || zotero.pdf_count || 0) : count;
    const path = kindKey === "zotero"
      ? "通过 Zotero 本机接口连接"
      : kindKey === "empty"
        ? "等待添加本地文件"
        : String(notebook.root_path || "等待添加文件");
    const addAction = kindKey === "zotero"
      ? `<button type="button" class="knowledge-source-quiet" data-action="choose-zotero-library" data-notebook-id="${escapeHtml(notebook.notebook_id)}">刷新</button>`
      : `<button type="button" class="knowledge-source-quiet" data-action="choose-library-files" data-notebook-id="${escapeHtml(notebook.notebook_id)}">添加文件</button>`;
    const dropAttributes = kindKey === "zotero" ? "" : ` data-library-dropzone data-notebook-id="${escapeHtml(notebook.notebook_id)}"`;
    return `<article class="knowledge-source-row ${selected ? "is-selected" : ""}"${dropAttributes}><span class="knowledge-source-mark ${escapeHtml(kindKey)}">${uiIcon(kind.icon)}</span><div class="knowledge-source-copy"><span>${escapeHtml(kind.title)}${selected ? " · 本轮检索范围" : ""}</span><h3>${escapeHtml(notebook.title || pathLeaf(notebook.root_path))}</h3><p title="${escapeHtml(path)}">${escapeHtml(compact(path, 72))}</p></div><div class="knowledge-source-count"><strong>${itemCount}</strong><span>${kindKey === "zotero" ? "条文献" : "篇已索引"}</span></div><div class="knowledge-source-actions">${addAction}<button type="button" class="knowledge-source-select" data-action="select-notebook" data-notebook-id="${escapeHtml(notebook.notebook_id)}">${selected ? `${uiIcon("check")} 已选择` : "用于对话"}</button></div></article>`;
  }).join("");
  return `<section class="knowledge-library knowledge-source-hub"><header class="knowledge-hub-hero"><div><span>LOCAL DATA SOURCES</span><h2>连接资料，而不是搬运资料</h2><p>Zotero、Obsidian、Notion 和本地文件夹各自作为一个数据源；在对话中只选择本轮要检索的范围。</p></div><aside>${uiIcon("shield-check")}<div><strong>原文件留在原处</strong><span>ScanSci 只保存可重建索引和引用定位，不把几千篇 PDF 画成几千本书。</span></div></aside></header><section class="knowledge-hub-summary"><div><strong>${notebooks.length}</strong><span>已连接数据源</span></div><div><strong>${totalSources}</strong><span>篇可检索来源</span></div><div><strong>${active ? escapeHtml(compact(knowledgeScopeTitle(active), 22)) : "未选择"}</strong><span>本轮检索范围</span></div></section><section class="knowledge-connector-grid" aria-label="连接数据源"><article class="knowledge-connector zotero"><span class="knowledge-connector-icon">${uiIcon("library")}</span><div><header><h3>Zotero</h3><i>${zoteroLibraries.length ? `${zoteroLibraries.length} 个已连接` : "未连接"}</i></header><p>连接本机数据库后，按全库或 Collection 选择检索范围。</p><button type="button" data-action="choose-zotero-library">${zoteroLibraries.length ? "再连接一个资料库" : "连接 Zotero"}${uiIcon("chevron-right")}</button></div></article><article class="knowledge-connector obsidian"><span class="knowledge-connector-icon">${uiIcon("book")}</span><div><header><h3>Obsidian</h3><i>${obsidianLibraries.length ? `${obsidianLibraries.length} 个已连接` : "未连接"}</i></header><p>可以绑定整个 Vault，也可以只绑定其中一个研究文件夹。</p><button type="button" data-action="choose-obsidian-vault">选择 Vault 或文件夹${uiIcon("chevron-right")}</button></div></article><article class="knowledge-connector notion"><span class="knowledge-connector-icon"><img src="/notion-logo.png" alt="" /></span><div><header><h3>Notion</h3><i>${notionLibraries.length ? `${notionLibraries.length} 个已连接` : "未连接"}</i></header><p>连接一个 Notion 根页面，自动同步它下面已授权的子页面和数据库。</p><button type="button" data-action="connect-notion">${notionLibraries.length ? "再连接一个 Notion 页面" : "连接 Notion"}${uiIcon("chevron-right")}</button></div></article><article class="knowledge-connector folder"><span class="knowledge-connector-icon">${uiIcon("folder-open")}</span><div><header><h3>本地文件夹</h3><i>${localLibraries.length ? `${localLibraries.length} 个已连接` : "未连接"}</i></header><p>C 盘、D 盘中的目录可以逐个绑定，互不替换。</p><button type="button" data-action="choose-library-folder">绑定文件夹${uiIcon("chevron-right")}</button></div></article><article class="knowledge-connector empty"><span class="knowledge-connector-icon">${uiIcon("plus")}</span><div><header><h3>空知识库</h3><i>按需创建</i></header><p>先创建一个检索容器，再逐步添加散落的文献文件。</p><button type="button" data-action="create-empty-library">创建知识库${uiIcon("chevron-right")}</button></div></article></section><section class="knowledge-source-list"><header><div><span>CONNECTED SOURCES</span><h2>已连接的数据源</h2></div><button type="button" data-action="open-knowledge-scope">选择本轮范围</button></header><div>${sourceRows || `<button type="button" class="knowledge-source-empty" data-action="choose-library-folder">${uiIcon("folder-open")}<span><strong>还没有数据源</strong><small>从 Zotero、Obsidian、Notion 或任意本地文件夹开始</small></span>${uiIcon("chevron-right")}</button>`}</div></section></section>`;
}

function knowledgeSourceKind(notebook) {
  const kind = String(notebook?.metadata?.library_kind || "folder");
  if (kind === "zotero" || notebook?.metadata?.zotero) return "zotero";
  if (kind === "obsidian" || notebook?.metadata?.obsidian) return "obsidian";
  if (kind === "notion" || notebook?.metadata?.notion) return "notion";
  return "personal";
}

function knowledgeItemUsesPdfIcon(item, notebook) {
  const candidates = [item?.pdf_path, item?.path, item?.source_url, item?.title].filter(Boolean);
  const attachments = Array.isArray(item?.attachments) ? item.attachments : [];
  const explicitPdf = String(item?.type || "").toLowerCase() === "pdf"
    || candidates.some((value) => sourceSuffix(value) === ".pdf")
    || attachments.some((attachment) => {
      const contentType = String(attachment?.content_type || attachment?.contentType || "").toLowerCase();
      return contentType === "application/pdf" || sourceSuffix(attachment?.path || attachment?.name || "") === ".pdf";
    });
  // Zotero rows represent literature documents in this view. Some local
  // Zotero snapshots expose the PDF count but omit child-attachment paths
  // from their compact item sample, so the document icon remains stable.
  return explicitPdf || knowledgeSourceKind(notebook) === "zotero";
}

function knowledgeSourceItems(notebook) {
  const kind = knowledgeSourceKind(notebook);
  const indexed = (notebook?.sources || []).map((source) => ({
    ...source,
    id: source.source_id || source.doc_id || source.title,
    title: source.title || source.doc_id || "未命名文件",
    // A Notion page has a public source URL, but its managed Markdown path is
    // the thing that preserves the synced parent-chain.  Keep that path for
    // tree rendering while the preview still receives source_url separately.
    path: kind === "notion" ? source.html_path || source.source_url || "" : source.source_url || source.html_path || "",
    type: sourceTypeLabel(kind === "notion" ? source.html_path || source.title || "" : source.source_url || source.title || ""),
  }));
  if (indexed.length || kind !== "zotero") return indexed;
  const items = notebook?.metadata?.zotero?.items || [];
  return items.map((item, index) => ({
    ...item,
    id: item.key || `zotero-${index}`,
    title: item.title || "未命名文献",
    path: item.pdf_path || item.url || item.doi || "",
    type: item.pdf_path ? "PDF" : "Zotero",
  }));
}

function knowledgeItemSearchText(item, notebook) {
  return [
    knowledgeFolderName(item, notebook),
    item.title,
    item.type,
    item.path,
    item.publication,
    item.creators,
    item.doi,
    item.date,
  ].filter(Boolean).join(" ").toLowerCase();
}

function knowledgeFolderName(item, notebook) {
  if (knowledgeSourceKind(notebook) === "zotero") {
    const collectionNames = new Map(
      (notebook?.metadata?.zotero?.collections || []).map((collection) => [
        String(collection.key),
        String(collection.name || collection.key),
      ]),
    );
    const collectionName = (item.collections || [])
      .map((key) => collectionNames.get(String(key)))
      .find(Boolean);
    return collectionName || "未分类";
  }
  const raw = String(item.path || item.source_url || "");
  const parts = raw.split(/[\\/]+/).filter(Boolean);
  if (parts.length > 1) return parts.at(-2);
  return pathLeaf(notebook?.root_path) || "全部文件";
}

function renderKnowledgeFileRow(item, notebook, items) {
  const active = String(item.id) === String(state.knowledgePreviewSourceId || items[0]?.id);
  const usesPdfIcon = knowledgeItemUsesPdfIcon(item, notebook);
  const searchText = knowledgeItemSearchText(item, notebook);
  const title = String(item.title || pathLeaf(item.path) || "未命名文件");
  return `<button type="button" class="ima-file-row ${active ? "is-active" : ""}" data-action="preview-knowledge-source" data-source-id="${escapeHtml(String(item.id))}" data-search-text="${escapeHtml(searchText)}" title="${escapeHtml(title)}" aria-label="预览：${escapeHtml(title)}"><span class="ima-file-icon ${usesPdfIcon ? "is-pdf" : ""}"><img src="${usesPdfIcon ? "/pdf-document.svg" : knowledgeLogoUrl(knowledgeSourceKind(notebook))}" alt="" /></span><span class="ima-file-copy"><strong>${escapeHtml(compact(title, 88))}</strong><small>${escapeHtml(item.type || sourceTypeLabel(item.path || item.title))}${item.publication_year ? ` · ${escapeHtml(String(item.publication_year))}` : ""}</small></span></button>`;
}

function notionTreeLabel(segment) {
  return String(segment || "Notion 页面")
    .replace(/\.(?:md|markdown)$/i, "")
    .replace(/--[a-f0-9]{10}$/i, "")
    .trim() || "Notion 页面";
}

function notionRelativeSegments(item, notebook) {
  const raw = String(item.html_path || item.path || "").replace(/\\/g, "/");
  const root = String(notebook?.root_path || "").replace(/\\/g, "/").replace(/\/+$/, "");
  const local = root && raw.toLowerCase().startsWith(`${root.toLowerCase()}/`)
    ? raw.slice(root.length + 1)
    : raw;
  const parts = local.split("/").filter(Boolean).filter((part) => part !== "manifest.json");
  return parts.length ? parts : [`${notionTreeLabel(item.title)}--${String(item.id || "page").slice(-10)}.md`];
}

function buildNotionTree(notebook, items) {
  const root = { label: "", item: null, children: new Map() };
  items.forEach((item) => {
    let node = root;
    notionRelativeSegments(item, notebook).forEach((part) => {
      const key = notionTreeLabel(part);
      if (!node.children.has(key)) node.children.set(key, { label: key, item: null, children: new Map() });
      node = node.children.get(key);
    });
    node.item = item;
  });
  return root;
}

function notionTreeCount(node) {
  return (node.item ? 1 : 0) + [...node.children.values()].reduce((total, child) => total + notionTreeCount(child), 0);
}

function renderNotionTreeNode(node, notebook, items, depth = 0) {
  const children = [...node.children.values()].sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
  if (!children.length) return node.item ? renderKnowledgeFileRow(node.item, notebook, items) : "";
  const count = notionTreeCount(node);
  const pageTrigger = node.item
    ? `<button type="button" class="ima-notion-page-trigger" data-action="preview-knowledge-source" data-source-id="${escapeHtml(String(node.item.id))}" title="打开 ${escapeHtml(node.label)}">${escapeHtml(node.label)}</button>`
    : `<strong>${escapeHtml(node.label)}</strong>`;
  return `<details class="ima-folder ima-notion-folder" data-notion-depth="${depth}"${state.knowledgeTreeExpanded !== false ? " open" : ""}><summary>${uiIcon("chevron-right")}<span>${uiIcon("folder-open")}</span>${pageTrigger}<small>${count}</small></summary><div>${children.map((child) => renderNotionTreeNode(child, notebook, items, depth + 1)).join("")}</div></details>`;
}

function renderNotionTree(notebook, items) {
  const tree = buildNotionTree(notebook, items);
  return [...tree.children.values()]
    .sort((left, right) => left.label.localeCompare(right.label, "zh-CN"))
    .map((node) => renderNotionTreeNode(node, notebook, items))
    .join("");
}

function renderKnowledgeTree(notebook, items) {
  if (!items.length) {
    if (knowledgeSourceKind(notebook) === "zotero") {
      const connected = Boolean(notebook?.metadata?.zotero?.connected);
      return `<div class="ima-library-empty"><strong>${connected ? "未找到可检索的 PDF 正文" : "尚未连接本机 Zotero"}</strong><span>${connected ? "请确认文献已附加可读取的 PDF，再重新读取。" : "连接后会自动读取文献与可访问的 PDF。"}</span><button type="button" data-action="choose-zotero-library" data-notebook-id="${escapeHtml(notebook?.notebook_id || "")}">${uiIcon(connected ? "refresh-cw" : "link")} ${connected ? "重新读取 Zotero" : "连接本机 Zotero"}</button></div>`;
    }
    const binding = notebook?.metadata?.local_binding || {};
    if (binding.state === "bound") {
      const status = state.knowledgeIndexStatuses[String(notebook?.notebook_id || "")] || {};
      const failed = String(binding.index_state || "") === "failed" || status.state === "failed";
      const progress = Math.max(0, Math.min(100, Math.round(Number(status.progress || 0) * 100)));
      const detail = failed
        ? String(status.error || binding.error || "索引未完成，原文件仍保持原位。")
        : `${progress ? `${progress}% · ` : ""}文件夹已绑定，正在后台建立可检索索引。`;
      const action = failed
        ? `<button type="button" data-action="retry-bound-library-import" data-notebook-id="${escapeHtml(notebook?.notebook_id || "")}">${uiIcon("refresh-cw")} 重试索引</button>`
        : "";
      return `<div class="ima-library-empty is-binding"><strong>${failed ? "文件夹已绑定，但索引未完成" : "文件夹已绑定"}</strong><span>${escapeHtml(detail)}</span>${action}</div>`;
    }
    return `<div class="ima-library-empty">此知识库尚未链接文件或文件夹</div>`;
  }
  if (knowledgeSourceKind(notebook) === "notion") return renderNotionTree(notebook, items);
  const groups = new Map();
  items.forEach((item) => {
    const folder = knowledgeFolderName(item, notebook);
    if (!groups.has(folder)) groups.set(folder, []);
    groups.get(folder).push(item);
  });
  return [...groups.entries()].map(([folder, entries]) => `<details class="ima-folder"${state.knowledgeTreeExpanded !== false ? " open" : ""}><summary>${uiIcon("chevron-right")}<span>${uiIcon("folder-open")}</span><strong>${escapeHtml(folder)}</strong><small>${entries.length}</small></summary><div>${entries.map((item) => renderKnowledgeFileRow(item, notebook, items)).join("")}</div></details>`).join("");
}

// External sources are fixed integration slots. Only personal libraries can be added.
function renderKnowledgeSourceGroup(title, kind, notebooks) {
  const connectionAction = kind === "zotero"
    ? "choose-zotero-library"
    : kind === "obsidian"
      ? "choose-obsidian-vault"
      : kind === "notion"
        ? "connect-notion"
        : "create-empty-library";
  const isPersonal = kind === "personal";
  const headerAction = isPersonal
    ? `<button type="button" data-action="create-empty-library" aria-label="新建个人知识库" title="新建个人知识库">${uiIcon("plus")}</button>`
    : "";
  const entries = notebooks.map((notebook) => `<button type="button" class="ima-source-entry ${notebook.notebook_id === state.notebook?.notebook_id ? "is-active" : ""}" data-action="activate-library" data-notebook-id="${escapeHtml(notebook.notebook_id)}"><img src="${knowledgeLogoUrl(kind)}" alt="" /><span>${escapeHtml(notebook.title || pathLeaf(notebook.root_path))}</span></button>`).join("");
  const emptyConnection = !isPersonal && !notebooks.length
    ? `<button type="button" class="ima-source-entry is-empty" data-action="${connectionAction}" aria-label="连接 ${escapeHtml(title)}"><img src="${knowledgeLogoUrl(kind)}" alt="" /><span>连接 ${escapeHtml(title)}</span></button>`
    : "";
  return `<section class="ima-source-group"><header><span>${escapeHtml(title)}</span>${headerAction}</header>${entries || emptyConnection}</section>`;
}

function knowledgeIndexStatusMarkup(notebook) {
  const notebookId = String(notebook?.notebook_id || "");
  const status = state.knowledgeIndexStatuses[notebookId] || {};
  const sourceCount = Number(notebook?.counts?.sources || knowledgeSourceItems(notebook).length || 0);
  const binding = notebook?.metadata?.local_binding || {};
  const bindingState = String(binding.index_state || "");
  const fallbackState = bindingState === "failed"
    ? "failed"
    : bindingState === "queued"
      ? "importing"
      : bindingState === "ready" && sourceCount
        ? "ready"
        : sourceCount
          ? "pending"
          : "empty";
  const statusState = String(status.state || fallbackState);
  const progress = Math.max(0, Math.min(100, Math.round(Number(status.progress || 0) * 100)));
  const labels = {
    ready: "检索已就绪",
    // Source text can be searched as soon as document evidence has been
    // materialized.  The later vector/reranker pass improves ranking, but it
    // must not make a populated Zotero shelf look empty or unusable.
    indexing: sourceCount ? `全文可检索 · 优化${progress ? ` ${progress}%` : ""}` : `正在建立索引${progress ? ` ${progress}%` : ""}`,
    importing: `正在建立索引${progress ? ` ${progress}%` : ""}`,
    installing: `正在安装检索组件${progress ? ` ${progress}%` : ""}`,
    degraded: "部分可用",
    failed: "同步失败",
    pending: "等待同步",
    empty: "尚无内容",
  };
  const retryable = ["failed", "degraded", "pending"].includes(statusState);
  const title = status.error
    ? `检索索引：${labels[statusState] || "等待同步"}。${String(status.error)}`
    : `检索索引：${labels[statusState] || "等待同步"}`;
  return `<button type="button" class="ima-index-status is-${escapeHtml(statusState)}" data-knowledge-index-status data-action="${retryable ? "retry-evidence-index" : "refresh-evidence-index"}" data-notebook-id="${escapeHtml(notebookId)}" title="${escapeHtml(title)}" ${statusState === "empty" ? "disabled" : ""}><svg viewBox="0 0 12 12" aria-hidden="true"><circle class="track" cx="6" cy="6" r="4.5"></circle><circle class="value" cx="6" cy="6" r="4.5" pathLength="100" stroke-dasharray="${progress} 100"></circle></svg><span>${escapeHtml(labels[statusState] || "等待同步")}</span></button>`;
}

function syncKnowledgeIndexBadge(notebookId) {
  if (state.activeMode !== "library" || state.notebook?.notebook_id !== notebookId) return;
  const current = document.querySelector("[data-knowledge-index-status]");
  if (!current) return;
  const template = document.createElement("template");
  template.innerHTML = knowledgeIndexStatusMarkup(state.notebook).trim();
  current.replaceWith(template.content.firstElementChild);
}

function focusKnowledgeFileSearch() {
  if (!state.knowledgeSearchOpen) {
    state.knowledgeSearchOpen = true;
    renderMode();
  }
  window.setTimeout(() => {
    const search = document.querySelector("[data-knowledge-file-search]");
    if (!search) return;
    search.focus({ preventScroll: true });
    if (search.value) search.select();
  }, 0);
}

function closeKnowledgeFileSearch() {
  if (!state.knowledgeSearchOpen) return;
  state.knowledgeSearchOpen = false;
  renderMode();
}

function renderImaLibraryMode() {
  const notebooks = state.workspace?.notebooks || [];
  const active = state.notebook || notebooks[0] || null;
  const kind = knowledgeSourceKind(active);
  const items = knowledgeSourceItems(active);
  const query = String(state.knowledgeQuery || "").trim().toLowerCase();
  const matchingItems = query
    ? items.filter((item) => knowledgeItemSearchText(item, active).includes(query))
    : items;
  const visibleLimit = Math.max(200, Number(state.knowledgeVisibleLimit) || 200);
  const visibleItems = matchingItems.slice(0, visibleLimit);
  const remainingItems = Math.max(0, matchingItems.length - visibleItems.length);
  const totalItemCount = kind === "zotero"
    ? Number(active?.metadata?.zotero?.item_count || items.length)
    : items.length;
  const indexedSourceCount = Number(active?.counts?.sources || items.length || 0);
  // Zotero keeps bibliography records and locally readable full text
  // separately.  Show both, so users never mistake a metadata total for the
  // number of documents available to evidence search.
  const contentCountLabel = kind === "zotero"
    ? `全文 ${indexedSourceCount} / 文献 ${totalItemCount}`
    : `${totalItemCount}`;
  const previewId = state.knowledgePreviewSourceId || items[0]?.id || "";
  const preview = items.find((item) => String(item.id) === String(previewId)) || items[0] || null;
  const personal = notebooks.filter((notebook) => knowledgeSourceKind(notebook) === "personal");
  const zotero = notebooks.filter((notebook) => knowledgeSourceKind(notebook) === "zotero");
  const obsidian = notebooks.filter((notebook) => knowledgeSourceKind(notebook) === "obsidian");
  const activeTitle = active?.title || "个人知识库";
  const activeReady = notebookHasSearchableContent(active);
  const linked = activeReady && (state.knowledgeScopeIds || []).includes(active.notebook_id);
  const zoteroConnected = Boolean(active?.metadata?.zotero?.connected);
  const zoteroActionLabel = zoteroConnected ? "重新读取 Zotero" : "连接本机 Zotero";
  const libraryScopeControl = activeReady
    ? `<button type="button" class="ima-scope-toggle ${linked ? "is-active" : ""}" data-action="toggle-active-library-scope">${linked ? `@${escapeHtml(activeTitle)}` : "用于对话"}</button>`
    : kind === "zotero"
      ? `<button type="button" class="ima-scope-toggle" data-action="choose-zotero-library" data-notebook-id="${escapeHtml(active?.notebook_id || "")}">${escapeHtml(zoteroActionLabel)}</button>`
      : `<span class="ima-scope-toggle is-disabled">导入后可用于对话</span>`;
  const libraryToolbarActions = kind === "zotero"
    ? `<button type="button" data-action="choose-zotero-library" data-notebook-id="${escapeHtml(active?.notebook_id || "")}">${uiIcon(zoteroConnected ? "refresh-cw" : "link")} ${escapeHtml(zoteroActionLabel)}</button>`
    : `<button type="button" data-action="choose-library-files" data-notebook-id="${escapeHtml(active?.notebook_id || "")}">${uiIcon("link")}链接文件</button><button type="button" data-action="choose-library-folder" data-notebook-id="${escapeHtml(active?.notebook_id || "")}">${uiIcon("folder-open")}链接文件夹</button>`;
  const previewPanel = !activeReady
    ? `<div class="ima-preview-empty">${uiIcon("circle-alert")}<span>导入资料后可基于证据问答</span></div>`
    : preview
    ? `<article class="ima-preview-card"><span>${escapeHtml(preview.type || sourceTypeLabel(preview.path || preview.title))}</span><h3>${escapeHtml(preview.title)}</h3><p>${escapeHtml(preview.creators || preview.doi || preview.path || "本地链接文件")}</p>${preview.publication ? `<small>${escapeHtml(preview.publication)}</small>` : ""}</article>`
    : `<div class="ima-preview-empty">${uiIcon("message-circle")}<span>基于知识库问答</span></div>`;
  const suggestions = activeReady ? [
    `总结「${activeTitle}」中的核心主题`,
    `比较「${activeTitle}」中不同文献的观点`,
    `找出「${activeTitle}」尚未解决的问题`,
  ] : [];
  const resultLabel = query
    ? `${matchingItems.length} 个结果${remainingItems ? ` · 已显示 ${visibleItems.length}` : ""}`
    : remainingItems
      ? `已显示 ${visibleItems.length}`
      : "";
  const loadMore = remainingItems
    ? `<button type="button" class="ima-library-load-more" data-action="load-more-knowledge-items">加载更多（剩余 ${remainingItems}）</button>`
    : "";
  const searchOpen = Boolean(state.knowledgeSearchOpen);
  const topSearch = searchOpen
    ? `<label class="ima-library-appbar-search-field"><span>${uiIcon("search")}</span><input type="search" data-knowledge-file-search value="${escapeHtml(state.knowledgeQuery || "")}" placeholder="输入文件名、作者或路径" aria-label="搜索当前知识库" /><button type="button" data-action="close-knowledge-file-search" aria-label="收起搜索" title="收起搜索">${uiIcon("x")}</button></label>`
    : "";
  return `<section class="ima-library-layout ${state.knowledgePreviewCollapsed ? "is-preview-collapsed" : ""} ${searchOpen ? "is-search-open" : ""}">
    <header class="ima-library-appbar">
      <div class="ima-library-appbar-context">${uiIcon("folder-open")}<strong>${escapeHtml(activeTitle)}</strong></div>
      <div class="ima-library-appbar-actions">
        ${topSearch}<button type="button" class="ima-library-appbar-search" data-action="focus-knowledge-file-search" aria-label="搜索当前知识库" aria-expanded="${searchOpen}" title="搜索当前知识库（Ctrl+F）">${uiIcon("search")}</button>
        <button type="button" class="ima-preview-toggle" data-action="toggle-knowledge-preview" aria-label="${state.knowledgePreviewCollapsed ? "展开详情栏" : "折叠详情栏"}" title="${state.knowledgePreviewCollapsed ? "展开详情栏" : "折叠详情栏"}">${uiIcon(state.knowledgePreviewCollapsed ? "panel-left" : "panel-right")}</button>
      </div>
    </header>
    <aside class="ima-library-sources">${renderKnowledgeSourceGroup("个人知识库", "personal", personal)}${renderKnowledgeSourceGroup("Zotero", "zotero", zotero)}${renderKnowledgeSourceGroup("Obsidian", "obsidian", obsidian)}${renderKnowledgeSourceGroup("Notion", "notion", notebooks.filter((notebook) => knowledgeSourceKind(notebook) === "notion"))}</aside>
    <main class="ima-library-main"><header class="ima-library-title"><img src="${knowledgeLogoUrl(kind)}" alt="" /><div class="ima-library-heading"><h2>${escapeHtml(activeTitle)}</h2><div><span>${kind === "personal" ? "个人知识库" : kind === "zotero" ? "Zotero" : kind === "obsidian" ? "Obsidian" : "Notion"}</span>${knowledgeIndexStatusMarkup(active)}</div></div><div class="ima-library-title-actions">${libraryScopeControl}${kind === "personal" && active ? `<button type="button" class="ima-library-delete" data-action="delete-personal-library" data-notebook-id="${escapeHtml(active.notebook_id)}" title="移除个人知识库" aria-label="移除个人知识库 ${escapeHtml(activeTitle)}">${uiIcon("trash")}移除</button>` : ""}</div></header><div class="ima-library-toolbar"><label><span data-ui-icon="search"></span><input type="search" data-knowledge-file-search value="${escapeHtml(state.knowledgeQuery || "")}" placeholder="搜索当前知识库" /></label>${libraryToolbarActions}</div><section class="ima-library-tree"><header><strong>内容 (${contentCountLabel})</strong><span data-knowledge-search-count>${escapeHtml(resultLabel)}</span></header>${renderKnowledgeTree(active, visibleItems)}${loadMore}</section></main>
    <aside class="ima-library-preview"><div class="ima-library-preview-content">${previewPanel}<section class="ima-library-suggestions"><span>你可以这样开始</span>${suggestions.map((prompt) => `<button type="button" data-action="use-knowledge-suggestion" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}${uiIcon("chevron-right")}</button>`).join("")}</section></div></aside>
  </section>`;
}

function renderToolsMode() {
  // Paper retrieval is a primary sidebar destination, not a duplicate tool card.
  const tools = (state.capabilities?.tools || []).filter((tool) => tool.id !== "paper-download");
  const modeByTool = { "paper-download": "download", "journal-scout": "journal", "citation-lab": "verify", "paper-atlas": "atlas", "ppt-studio": "ppt", "evidence-trace": "review" };
  const cards = tools.map((tool) => `<button type="button" class="tool-card" data-action="open-mode" data-mode="${escapeHtml(modeByTool[tool.id] || "tools")}"><span class="tool-status ${escapeHtml(tool.status)}"></span><strong>${escapeHtml(tool.name)}</strong><p>${escapeHtml(tool.description)}</p><small>${tool.status === "ready" ? "可用" : tool.status === "external" ? "网页接力" : tool.status === "needs-data" ? "需要资料" : "未检测到"}</small></button>`).join("");
  const usable = tools.filter((tool) => ["ready", "external"].includes(tool.status)).length;
  return `${modeIntro("同一项目、同一份证据，按任务调用不同工具。", `${usable}/${tools.length} 可用`)}<section class="tool-grid">${cards}</section>`;
}

function renderReviewMode() {
  const sources = state.notebook?.sources || [];
  const sourceCount = sources.length;
  const sourceChoices = sources.map((source, index) => `<label class="review-source-choice"><input type="checkbox" data-review-source value="${escapeHtml(source.doc_id)}" checked /><span><b>${String(index + 1).padStart(2, "0")}</b><strong>${escapeHtml(compact(source.title || source.doc_id || "未命名来源", 84))}</strong><small>${escapeHtml([source.publication_year, source.doi].filter(Boolean).join(" · ") || "本地可检索来源")}</small></span></label>`).join("");
  const sourcePanel = sources.length
    ? `<details class="review-source-scope" open><summary><span>写作来源</span><strong><i data-review-selected-count>${sourceCount}</i> / ${sourceCount} 篇已选</strong></summary><div class="review-source-tools"><p>回答和正文只使用勾选来源；引用可回跳到原文证据。</p><div><button type="button" data-action="select-all-review-sources">全选</button><button type="button" data-action="clear-review-sources">清空</button></div></div><div class="review-source-list">${sourceChoices}</div></details>`
    : `<div class="review-source-empty"><strong>当前没有可用来源</strong><p>请先在知识库中导入论文，再开始证据约束写作。</p><button type="button" data-action="open-mode" data-mode="library">前往知识库</button></div>`;
  return `${modeIntro("先构建问题与证据矩阵，再写段落；每个结论保留原文跳转。", `${sourceCount} 篇来源`)}
    <section class="workflow-strip"><div><b>1</b><span>定义问题</span></div><div><b>2</b><span>检索证据</span></div><div><b>3</b><span>比较研究</span></div><div><b>4</b><span>写作与核验</span></div></section>
    <form class="mode-form review-form" id="reviewAskForm"><label class="review-question-field"><span>综述问题</span><textarea id="reviewQuestionInput" rows="4" placeholder="例如：AI 在生态监测中的主要应用、证据强度与研究空白是什么？"></textarea></label>${sourcePanel}<fieldset class="review-writing-brief"><legend>写作简报</legend><label><span>读者</span><select id="reviewAudience"><option value="researcher">科研人员</option><option value="student">研究生</option><option value="general">跨学科读者</option></select></label><label><span>语气</span><select id="reviewTone"><option value="academic">严谨学术</option><option value="concise">简洁直接</option><option value="teaching">解释清楚</option></select></label><label><span>篇幅</span><select id="reviewLength"><option value="standard">标准</option><option value="short">简短</option><option value="long">深入</option></select></label><label class="review-focus-field"><span>特别关注（可选）</span><input id="reviewFocus" maxlength="300" placeholder="例如：优先比较方法差异与证据局限" /></label></fieldset><footer class="review-form-footer"><p>${uiIcon("check")} 仅依据已选来源 · 事实句必须带可回跳引用</p><button type="submit" class="primary-button" ${sources.length ? "" : "disabled"}>检索证据并写作</button></footer></form>`;
}

function renderJournalMode() {
  return `${modeIntro("查询期刊名、ISSN、中科院分区、JCR 与预警信息。", "Journal Scout")}
    <form class="mode-form inline-mode-form" id="journalSearchForm"><label><span>期刊</span><input id="journalQuery" required placeholder="Nature Communications 或 ISSN" /></label><button type="submit" class="primary-button">查询</button></form><div class="mode-results" id="modeResults"></div>`;
}

function renderVerifyMode() {
  return `${modeIntro("粘贴参考文献，核对 Crossref/OpenAlex 元数据；也可连同正文检查断言支持度。", "Citation Lab")}
    <form class="mode-form" id="referenceAnalyzeForm"><label><span>正文与参考文献</span><textarea id="referenceText" rows="10" required placeholder="粘贴正文 + References，或只粘贴参考文献列表"></textarea></label><div class="form-row"><label class="compact-field"><span>模式</span><select id="referenceMode"><option value="references">仅核查参考文献</option><option value="full">正文与断言一起核查</option></select></label><button type="submit" class="primary-button">开始核查</button></div></form><div class="mode-results" id="modeResults"></div>`;
}

function renderAtlasMode() {
  return `${modeIntro("从题目、关键词或 DOI 找到种子论文，再进入引用与相似论文网络。", "Paper Atlas")}
    <form class="mode-form inline-mode-form" id="atlasSearchForm"><label><span>种子论文</span><input id="atlasQuery" required placeholder="论文题目、关键词或 DOI" /></label><button type="submit" class="primary-button">构建入口</button></form><div class="mode-results" id="modeResults"></div>`;
}

function renderDownloadMode() {
  const directory = state.capabilities?.download_directory || "downloads";
  const strategies = [
    ["oa_first", "开放获取优先"],
    ["gray_oa", "灰色文献与开放存档"],
    ["legal_only", "仅开放与出版商直链"],
  ];
  const selected = strategies.find(([id]) => id === state.downloadStrategy) || strategies[0];
  const menu = strategies.map(([id, label]) => `<button type="button" class="${id === state.downloadStrategy ? "is-selected" : ""}" data-action="select-download-strategy" data-download-strategy="${id}"><span>${escapeHtml(label)}</span>${id === state.downloadStrategy ? uiIcon("check") : ""}</button>`).join("");
  const batchCount = state.pendingBatchIdentifiers.length;
  const transportOptions = [["snowflake", "Snowflake（CDN 域前置，最抗封锁）"], ["obfs4", "obfs4 网桥"], ["none", "直连（不推荐）"]];
  const transportMenu = transportOptions.map(([id, label]) => `<button type="button" class="${id === state.torTransport ? "is-selected" : ""}" data-action="select-tor-transport" data-tor-transport="${id}"><span>${escapeHtml(label)}</span>${id === state.torTransport ? uiIcon("check") : ""}</button>`).join("");
  const torControls = `<label class="paper-batch-tor"><input type="checkbox" id="useTorToggle" data-action="toggle-use-tor" ${state.useTor ? "checked" : ""} /><span>Tor 轮换（匿名，较慢）</span></label>${state.useTor ? `<div class="paper-batch-tor paper-batch-tor-sub"><span>传输方式</span><button type="button" class="paper-strategy-trigger paper-tor-transport" data-action="toggle-tor-transport" aria-haspopup="listbox" aria-expanded="${state.torTransportOpen}">${escapeHtml(transportOptions.find(([id]) => id === state.torTransport)?.[1] || "Snowflake")}${uiIcon("chevron-down")}</button>${state.torTransportOpen ? `<div class="paper-strategy-menu paper-tor-transport-menu" role="listbox">${transportMenu}</div>` : ""}</div><label class="paper-batch-tor-every"><span>每</span><input type="number" id="torRotateEvery" min="1" max="20" value="${state.torRotateEvery}" data-action="set-tor-rotate" /><span>篇换 IP</span></label>` : ""}`;
  const batchPreview = batchCount
    ? `<div class="paper-batch-preview"><div class="paper-batch-preview-head"><span>已识别 ${batchCount} 个标识符</span><button type="button" class="paper-batch-clear" data-action="clear-batch-identifiers">清空</button></div><ul class="paper-batch-list">${state.pendingBatchIdentifiers.map((id) => `<li>${escapeHtml(id)}</li>`).join("")}</ul>${torControls}<button type="button" class="primary-button paper-batch-submit" data-action="start-batch-download">批量获取 (${batchCount})</button></div>`
    : "";
  return `<section class="paper-fetch-stage"><div class="paper-fetch-card"><span class="paper-fetch-eyebrow">SCANSCI · FULL TEXT</span><h1>获取论文全文</h1><p>输入 DOI 或 arXiv ID，优先从开放获取与灰色文献存档中查找可直接保存的 PDF。</p><form id="paperDownloadForm" class="paper-fetch-composer"><input id="paperIdentifier" required placeholder="输入 DOI 或 arXiv ID，例如 10.1038/..." autofocus /><button type="submit">获取</button></form><div class="paper-batch-dropzone"><label for="paperBatchFile"><span>批量获取：上传 .txt / .bib / .csv 文件，按行或字段解析 DOI 与 arXiv ID</span></label><input type="file" id="paperBatchFile" accept=".txt,.bib,.csv,text/plain" data-action="pick-batch-file" /></div>${batchPreview}<div class="paper-fetch-options"><div class="paper-strategy"><span>来源策略</span><button type="button" class="paper-strategy-trigger" data-action="toggle-download-strategy" aria-haspopup="listbox" aria-expanded="${state.downloadStrategyOpen}">${escapeHtml(selected[1])}${uiIcon("chevron-down")}</button>${state.downloadStrategyOpen ? `<div class="paper-strategy-menu" role="listbox">${menu}</div>` : ""}</div><span>保存至 ${escapeHtml(directory)}</span></div><p class="paper-fetch-footnote">无需资料库、无需模型 API。灰色文献包括机构仓储、预印本和公开报告；不会绕过付费墙。</p></div><div class="mode-results paper-fetch-results" id="modeResults"></div></section>`;
}

function renderPptMode() {
  const directory = state.capabilities?.presentation_directory || "presentations";
  const template = selectedSlideTemplate();
  return `${modeIntro("先生成有来源绑定的叙事大纲，再创建 EasySlides 项目；最终导出可编辑 PPTX。", directory)}
    <section class="ppt-layout"><form class="mode-form" id="pptOutlineForm"><label><span>汇报主题</span><input id="pptTopic" placeholder="默认使用当前项目名称" /></label><label><span>模板</span><button type="button" class="secondary-button" data-action="open-slide-templates">${escapeHtml(template?.name || "选择 EasySlides 模板")}</button></label><div class="form-row"><button type="submit" class="primary-button">生成大纲</button><button type="button" class="secondary-button" data-action="create-ppt-project">创建 EasySlides 项目</button></div></form><div class="ppt-preview" id="modeResults"><div class="ppt-placeholder"><span>16:9</span><p>大纲会显示在这里</p></div></div></section>`;
}

function renderJournalResults(payload) {
  const rows = payload.items || [];
  byId("modeResults").innerHTML = rows.length ? rows.map((row) => `<a class="result-card" href="${escapeHtml(row.detail_url)}" target="_blank" rel="noopener"><div><strong>${escapeHtml(row.title)}</strong><p>${escapeHtml([row.issn, row.eissn].filter(Boolean).join(" / "))}</p></div><div class="result-tags"><span>${escapeHtml(row.cas_partition || "未标注分区")}</span><span>${escapeHtml(row.jcr_quartile || "JCR -")}</span><span>IF ${escapeHtml(row.impact_factor ?? "-")}</span>${row.warning ? '<i>预警</i>' : ""}</div></a>`).join("") : '<div class="mode-empty">没有找到匹配期刊。</div>';
}

function renderReferenceResults(payload) {
  const values = Object.values(payload.reference_results || {});
  const healthy = values.filter((item) => item.status === "green").length;
  const risk = values.filter((item) => item.status === "red").length;
  byId("modeResults").innerHTML = `<div class="result-summary"><div><b>${values.length}</b><span>参考文献</span></div><div><b>${healthy}</b><span>元数据健康</span></div><div><b>${risk}</b><span>高风险</span></div></div>${values.slice(0, 30).map((item) => `<article class="verification-row ${escapeHtml(item.status || "white")}"><div><strong>${escapeHtml(item.official?.title || item.ref_id)}</strong><p>${escapeHtml(item.reason || item.label || "")}</p></div><span>${escapeHtml(item.label || item.status || "待核验")}</span></article>`).join("")}`;
}

function renderAtlasResults(payload) {
  const rows = payload.items || [];
  if (!rows.length && payload.external_url) {
    byId("modeResults").innerHTML = `<a class="external-fallback" href="${escapeHtml(payload.external_url)}" target="_blank" rel="noopener"><span>↗</span><div><strong>在 Paper Atlas 网页继续</strong><p>${escapeHtml(payload.message || "图谱服务当前需要在网页中打开。")}</p></div></a>`;
    return;
  }
  byId("modeResults").innerHTML = rows.length ? rows.map((row) => `<a class="result-card" href="${escapeHtml(payload.external_url || "https://paperatlas.scansci.com/")}" target="_blank" rel="noopener"><div><strong>${escapeHtml(row.title || row.paper_id)}</strong><p>${escapeHtml((row.authors || []).slice(0, 3).join(", "))} · ${escapeHtml(row.year || "")}</p></div><div class="result-tags"><span>${escapeHtml(row.citation_count || 0)} 引用</span><span>打开图谱 ↗</span></div></a>`).join("") : '<div class="mode-empty">没有找到匹配论文。</div>';
}

function renderPptOutline(payload) {
  const slides = payload.slides || payload.outline?.slides || [];
  const project = payload.project_path ? `<p class="project-path">项目已创建：<code>${escapeHtml(payload.project_path)}</code></p>` : "";
  const template = payload.template || payload.outline?.template;
  const templateCard = template ? `<div class="slide-project-artifact"><img class="slide-project-cover" src="${escapeHtml(template.preview_url)}" alt="" /><div class="slide-project-copy"><span>EasySlides template</span><h3>${escapeHtml(template.name)}</h3><p>${escapeHtml(template.description || template.tone || template.summary || "")}</p>${payload.project_path ? `<code>${escapeHtml(payload.project_path)}</code>` : ""}</div></div>` : "";
  byId("modeResults").innerHTML = `${project}${templateCard}<div class="slide-list">${slides.map((slide) => `<article><b>${escapeHtml(slide.index)}</b><div><strong>${escapeHtml(slide.title)}</strong><p>${escapeHtml(slide.purpose)}</p></div><span>${(slide.source_ids || []).length} 来源</span></article>`).join("")}</div>`;
}

const ONBOARDING_RETRIEVAL_MODELS = ["Qwen/Qwen3-Embedding-0.6B", "Qwen/Qwen3-Reranker-0.6B"];
const ONBOARDING_CHAT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct";

function onboardingPreferences() {
  return {
    welcome_dismissed: Boolean(state.settings?.onboarding?.welcome_dismissed),
    resource_setup_completed: Boolean(state.settings?.onboarding?.resource_setup_completed),
    data_setup_completed: Boolean(state.settings?.onboarding?.data_setup_completed),
  };
}

function resourceInstallSnapshot(resource) {
  const installed = state.localModelMarket?.installed || [];
  const jobs = state.localModelInstall?.jobs || [];
  const runtimeReady = Boolean(state.localRuntime?.installed);
  const definition = resource === "chat"
    ? {
      id: "chat",
      jobId: `model:${ONBOARDING_CHAT_MODEL}`,
      models: [ONBOARDING_CHAT_MODEL],
      eyebrow: "可选 · 本地对话",
      title: "小型本地对话模型",
      description: "在网络不稳定或想离线工作时，提供一个可在本机运行的基础对话模型。",
      detail: "Qwen2.5 1.5B Instruct",
      icon: "brain",
    }
    : {
      id: "retrieval",
      jobId: "retrieval-core",
      models: ONBOARDING_RETRIEVAL_MODELS,
      eyebrow: "推荐 · 知识库能力",
      title: "研究检索组件",
      description: "用于语义检索、知识库问答和证据重排；没有它仍可使用基础关键词检索。",
      detail: "Qwen3 Embedding + Reranker",
      icon: "sparkles",
    };
  const ready = definition.models.every((modelId) => installed.some((item) => item.id === modelId && item.ready));
  const job = jobs.find((item) => item.job_id === definition.jobId) || null;
  const runtimeJob = state.localRuntime?.install_job || null;
  const runtimeJobState = String(runtimeJob?.state || "idle");
  const runtimeActive = ["queued", "installing"].includes(runtimeJobState);
  const runtimeFailed = ["failed", "cancelled", "interrupted"].includes(runtimeJobState);
  const jobState = String(job?.state || "idle");
  const active = ["queued", "downloading"].includes(jobState);
  const failed = ["failed", "cancelled", "interrupted"].includes(jobState);
  const displayJob = !runtimeReady && (runtimeActive || runtimeFailed) ? runtimeJob : job;
  const progress = ready || jobState === "ready"
    ? 100
    : Math.max(0, Math.min(100, Math.round(Number(displayJob?.progress || 0) * 100)));
  return {
    ...definition,
    job: displayJob,
    runtimeReady,
    state: !runtimeReady
      ? runtimeActive ? "runtime_installing" : runtimeFailed ? "runtime_failed" : "runtime_required"
      : ready || jobState === "ready" ? "ready" : active ? jobState : failed ? "failed" : "idle",
    progress,
  };
}

function resourceInstallStatusCopy(resource) {
  if (resource.state === "runtime_required") return {
    label: "需要运行时",
    hint: state.localRuntime?.install_available
      ? "先安装 ScanSci 提供的本地运行能力，再下载模型。"
      : "当前发行渠道未提供本地运行能力；不会下载无法执行的模型。",
  };
  if (resource.state === "runtime_installing") return {
    label: `安装运行组件 ${resource.progress}%`,
    hint: resource.job?.message || "正在下载并校验本地运行组件。",
  };
  if (resource.state === "runtime_failed") return {
    label: resource.job?.state === "interrupted" ? "安装已中断" : "安装未完成",
    hint: resource.job?.error || resource.job?.message || "可以重试；已下载内容会自动复用。",
  };
  if (resource.state === "ready") return { label: "已就绪", hint: "已保存在本机，可随时使用。" };
  if (resource.state === "queued") return { label: "准备下载", hint: "正在连接可用下载源。" };
  if (resource.state === "downloading") return { label: `下载中 ${resource.progress}%`, hint: resource.job?.current_model || resource.detail };
  if (resource.state === "failed") return { label: resource.job?.state === "interrupted" ? "下载已中断" : "下载未完成", hint: resource.job?.error || resource.job?.message || "可重试；已下载内容会继续复用。" };
  return { label: "尚未下载", hint: resource.detail };
}

function resourceSetupCard(resource) {
  const copy = resourceInstallStatusCopy(resource);
  const active = ["queued", "downloading", "runtime_installing"].includes(resource.state);
  const actionLabel = resource.state === "ready"
    ? "已就绪"
    : resource.state === "runtime_required"
      ? state.localRuntime?.install_available ? "安装本地运行能力" : "查看本地运行设置"
    : ["failed", "runtime_failed"].includes(resource.state)
      ? "重试下载"
      : active
        ? "正在下载"
        : "立即下载";
  const progress = active
    ? `<div class="resource-download-detail"><small>${escapeHtml(downloadJobTelemetry(resource.job) || "正在建立下载连接")}</small><div class="resource-setup-progress" role="progressbar" aria-label="${escapeHtml(resource.title)} 下载进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${resource.progress}"><span class="${progressWidthClass(resource.progress)}"></span></div></div>`
    : "";
  const action = ["runtime_required", "runtime_failed"].includes(resource.state)
    ? `<button type="button" data-action="${state.localRuntime?.install_available ? "install-local-runtime" : "open-local-runtime-setup"}">${uiIcon(state.localRuntime?.install_available ? (resource.state === "runtime_failed" ? "refresh" : "download") : "settings")}${escapeHtml(actionLabel)}</button>`
    : resource.state === "runtime_installing"
      ? `<span class="resource-install-running">${uiIcon("loader-circle")}</span>`
    : resource.state === "ready"
      ? `<span>${uiIcon("check")}</span>`
      : `<button type="button" data-action="start-onboarding-resource" data-resource-id="${escapeHtml(resource.id)}" ${active ? "disabled" : ""}>${uiIcon(resource.state === "failed" ? "refresh" : "download")}${escapeHtml(actionLabel)}</button>`;
  return `<article class="resource-setup-card is-${escapeHtml(resource.state)}"><div class="resource-setup-mark">${uiIcon(resource.icon)}</div><div class="resource-setup-copy"><span>${escapeHtml(resource.eyebrow)}</span><h3>${escapeHtml(resource.title)}</h3><p>${escapeHtml(resource.description)}</p><small>${escapeHtml(copy.hint)}</small>${progress}</div><div class="resource-setup-action"><b>${escapeHtml(copy.label)}</b>${action}</div></article>`;
}

function resourceSetupCardsMarkup() {
  return [resourceInstallSnapshot("retrieval"), resourceInstallSnapshot("chat")].map(resourceSetupCard).join("");
}

function resourceSettingsRow(resource) {
  const copy = resourceInstallStatusCopy(resource);
  const active = ["queued", "downloading", "runtime_installing"].includes(resource.state);
  const actionLabel = resource.state === "failed" ? "重试" : "下载";
  const progress = active
    ? `<div class="resource-download-detail"><small>${escapeHtml(downloadJobTelemetry(resource.job) || "正在建立下载连接")}</small><div class="resource-settings-row-progress" role="progressbar" aria-label="${escapeHtml(resource.title)} 下载进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${resource.progress}"><span class="${progressWidthClass(resource.progress)}"></span></div></div>`
    : "";
  const action = resource.state === "ready"
    ? `<span class="resource-settings-row-ready">${uiIcon("check")} 已就绪</span>`
    : ["runtime_required", "runtime_failed"].includes(resource.state)
      ? `<button type="button" class="resource-settings-row-action" data-action="${state.localRuntime?.install_available ? "install-local-runtime" : "open-local-runtime-setup"}">${state.localRuntime?.install_available ? (resource.state === "runtime_failed" ? "重试安装" : "安装本地运行能力") : "查看本地运行设置"}</button>`
    : active
      ? `<span class="resource-settings-row-state">${escapeHtml(copy.label)}</span>`
      : `<button type="button" class="resource-settings-row-action" data-action="start-onboarding-resource" data-resource-id="${escapeHtml(resource.id)}">${uiIcon(resource.state === "failed" ? "refresh" : "download")}${actionLabel}</button>`;
  return `<article class="resource-settings-row is-${escapeHtml(resource.state)}"><span class="resource-settings-row-icon">${uiIcon(resource.icon)}</span><div class="resource-settings-row-copy"><strong>${escapeHtml(resource.title)}</strong><small>${escapeHtml(resource.state === "ready" ? resource.detail : copy.hint)}</small>${progress}</div><div class="resource-settings-row-end">${action}</div></article>`;
}

function connectedDataSourceCount() {
  return (state.workspace?.notebooks || []).filter((notebook) => {
    const kind = String(notebook?.metadata?.library_kind || "");
    return kind && kind !== "empty";
  }).length;
}

function onboardingSourceIcon(kind) {
  if (kind === "zotero") return '<img src="/zotero-logo.svg" alt="" />';
  if (kind === "obsidian") return '<img src="/obsidian-logo.svg" alt="" />';
  if (kind === "notion") return '<img src="/notion-logo.png" alt="" />';
  return uiIcon("folder-open");
}

function onboardingSourceCard({ kind, action, title, description, actionLabel }) {
  const notebooks = state.workspace?.notebooks || [];
  const count = notebooks.filter((notebook) => {
    const libraryKind = String(notebook?.metadata?.library_kind || "");
    if (kind === "folder") {
      return libraryKind && !["empty", "zotero", "obsidian", "notion"].includes(libraryKind);
    }
    return libraryKind === kind;
  }).length;
  const job = state.libraryImportJob;
  const importing = ["queued", "running"].includes(job?.state) && ["folder", "obsidian", "zotero"].includes(kind);
  const status = count ? `已连接 ${count} 个` : importing ? "正在接入" : "未连接";
  return `<article class="data-source-card ${count ? "is-connected" : ""} ${importing ? "is-importing" : ""}"><span class="data-source-card-icon ${escapeHtml(kind)}">${onboardingSourceIcon(kind)}</span><div><header><strong>${escapeHtml(title)}</strong><i>${escapeHtml(status)}</i></header><p>${escapeHtml(description)}</p><button type="button" data-action="${escapeHtml(action)}" ${importing ? "disabled" : ""}>${uiIcon(count ? "plus" : "arrow-up-right")}${escapeHtml(actionLabel)}</button></div></article>`;
}

function renderDataOnboarding() {
  const sources = connectedDataSourceCount();
  return `<div class="resource-onboarding-backdrop"><section class="resource-onboarding-card" role="dialog" aria-modal="true" aria-labelledby="resourceOnboardingTitle"><aside class="resource-onboarding-aside"><span class="resource-onboarding-brand">ScanSci · FIRST RUN</span><div class="resource-onboarding-glyph">${uiIcon("library")}</div><h1 id="resourceOnboardingTitle">把资料留在原处，<br />让证据变得可用。</h1><p>选择你愿意连接的资料源。ScanSci 只读取内容、建立本地索引与引用定位，不会移动或上传原文件。</p><div class="resource-onboarding-note"><span>${uiIcon("map-pin")}</span><p>每条回答都可回到文档、章节和原文证据片段。扫描件无法读取时会明确提示你启用 OCR。</p></div></aside><main class="resource-onboarding-main data-onboarding-main"><header><div><span>资料接入</span><h2>从一个资料源开始就够了</h2><p>连接后会自动完成：文档 → 章节 → 原文证据片段。其他资料源可随后在知识库中添加。</p></div><span class="resource-onboarding-step">02 / 02</span></header><div class="data-source-grid">${onboardingSourceCard({ kind: "folder", action: "onboarding-connect-folder", title: "本地文件夹", description: "递归读取论文、报告、Markdown 和常见办公文档。", actionLabel: "选择文件夹" })}${onboardingSourceCard({ kind: "zotero", action: "onboarding-connect-zotero", title: "Zotero", description: "连接本机文献库与其已管理的论文附件。", actionLabel: "连接 Zotero" })}${onboardingSourceCard({ kind: "obsidian", action: "onboarding-connect-obsidian", title: "Obsidian", description: "保留 Vault 的笔记层级，并为每个段落建立定位。", actionLabel: "选择 Vault" })}${onboardingSourceCard({ kind: "notion", action: "onboarding-connect-notion", title: "Notion", description: "使用你的 Integration 同步已授权的页面和数据库。", actionLabel: "连接 Notion" })}</div>${guidedImportJobMarkup()}<footer><p>${sources ? `<strong>已连接 ${sources} 个资料源。</strong> 你可完成配置；资料仍会在后台建立语义索引。` : "不接入资料也可先体验 ScanSci；随时可在 设置 · 资源配置 或 知识库 中继续。"}</p><div><button type="button" class="resource-skip-button" data-action="back-resource-onboarding">上一步</button><button type="button" class="resource-skip-button" data-action="skip-resource-onboarding">暂时跳过</button>${sources ? `<button type="button" class="resource-finish-button" data-action="finish-data-onboarding">完成并开始 ${uiIcon("arrow-up-right")}</button>` : ""}</div></footer></main></section></div>`;
}

function renderResourceOnboarding() {
  const host = byId("resourceOnboarding");
  if (!host) return;
  if (!state.onboardingOpen || !state.settings) {
    host.hidden = true;
    host.innerHTML = "";
    return;
  }
  if (state.onboardingStep === "sources") {
    host.hidden = false;
    host.innerHTML = renderDataOnboarding();
    hydrateIcons(host);
    return;
  }
  host.hidden = false;
  host.innerHTML = `<div class="resource-onboarding-backdrop"><section class="resource-onboarding-card" role="dialog" aria-modal="true" aria-labelledby="resourceOnboardingTitle"><aside class="resource-onboarding-aside"><span class="resource-onboarding-brand">ScanSci · FIRST RUN</span><div class="resource-onboarding-glyph">${uiIcon("sparkles")}</div><h1 id="resourceOnboardingTitle">先把研究桌面<br />准备好。</h1><p>ScanSci 已包含基础能力；需要下载的模型由你决定，并始终保存在这台电脑上。</p><div class="resource-onboarding-note"><span>${uiIcon("shield-check")}</span><p>下载可断点续传。跳过不会影响基础使用，之后可在设置里继续。</p></div></aside><main class="resource-onboarding-main"><header><div><span>资源配置</span><h2>按需添加，不打扰开始研究</h2><p>建议先下载检索组件；下一步可以连接你的资料。</p></div><span class="resource-onboarding-step">01 / 02</span></header><div class="resource-setup-cards">${resourceSetupCardsMarkup()}</div><footer><p>本地检索组件是可选项。资料接入后，ScanSci 才能把回答精确定位回你的原文证据。</p><div><button type="button" class="resource-skip-button" data-action="skip-resource-onboarding">暂时跳过</button><button type="button" class="resource-finish-button" data-action="advance-resource-onboarding">下一步：接入资料 ${uiIcon("arrow-right")}</button></div></footer></main></section></div>`;
  hydrateIcons(host);
}

function renderResourceSetupSettings() {
  const sourceCount = connectedDataSourceCount();
  const dataStatus = sourceCount ? `已连接 ${sourceCount} 个资料源` : "尚未接入资料";
  const resourceRows = [resourceInstallSnapshot("retrieval"), resourceInstallSnapshot("chat")].map(resourceSettingsRow).join("");
  const taskEntries = downloadTaskEntries({ includeReady: true }).slice(0, 6);
  const downloadTasks = taskEntries.length
    ? `<section class="download-task-section"><header><div><h2>下载任务</h2><p>关闭应用后仍保留状态；再次开始会复用已下载内容。</p></div>${state.downloadStatusError ? `<span class="download-task-connection-error">${uiIcon("wifi-off")}进度连接正在重试</span>` : ""}</header><div class="download-task-list">${taskEntries.map(downloadTaskRow).join("")}</div></section>`
    : "";
  return `<section class="resource-settings-page resource-settings-page--compact"><header class="resource-settings-heading"><div><h1>资源配置</h1><p>只显示需要你处理的资源；资料和模型始终保留在这台电脑上。</p></div><button type="button" class="quiet-text-button" data-action="reopen-resource-onboarding">首次配置</button></header>${downloadTasks}<section class="resource-settings-list" aria-label="资源配置列表">${resourceRows}<article class="resource-settings-row resource-settings-data-row"><span class="resource-settings-row-icon">${uiIcon(sourceCount ? "check" : "library")}</span><div class="resource-settings-row-copy"><strong>资料接入</strong><small>${escapeHtml(dataStatus)}${sourceCount ? " · 已建立本地索引" : " · 连接后自动建立文档、章节与证据片段"}</small></div><div class="resource-settings-row-end"><button type="button" class="resource-settings-row-action is-quiet" data-action="open-data-onboarding">${sourceCount ? "管理" : "接入资料"}${uiIcon("arrow-right")}</button></div></article></section><p class="resource-settings-footnote">未下载检索模型时，ScanSci 仍会使用基础关键词检索。</p></section>`;
}

async function persistOnboardingPreferences(patch, message, { close = false } = {}) {
  if (!state.settings || state.onboardingPersisting) return;
  state.onboardingPersisting = true;
  state.settings.onboarding = { ...onboardingPreferences(), ...patch };
  if (close) state.onboardingOpen = false;
  renderResourceOnboarding();
  try {
    await persistSettings(message);
  } finally {
    state.onboardingPersisting = false;
    renderResourceOnboarding();
  }
}

async function startOnboardingResource(resourceId) {
  const resource = resourceInstallSnapshot(resourceId === "chat" ? "chat" : "retrieval");
  if (["ready", "queued", "downloading"].includes(resource.state)) return;
  if (["runtime_required", "runtime_installing", "runtime_failed"].includes(resource.state)) {
    state.activeView = "settings";
    state.activeSettings = "local-models";
    renderWorkspace();
    document.querySelector(".local-runtime-disclosure")?.setAttribute("open", "");
    toast(
      resource.state === "runtime_installing"
        ? "本地运行组件仍在安装；右上角可持续查看进度。"
        :
      state.localRuntime?.install_available
        ? "请先安装 ScanSci 本地运行能力；模型尚未开始下载。"
        : "当前渠道没有提供本地运行能力；ScanSci 不会下载无法执行的模型。",
      resource.state !== "runtime_installing",
    );
    return;
  }
  const endpoint = resource.id === "retrieval" ? "/api/resources/retrieval/download" : "/api/local-models/download";
  const payload = resource.id === "retrieval" ? {} : { id: ONBOARDING_CHAT_MODEL };
  const job = await request(endpoint, { method: "POST", body: JSON.stringify(payload) });
  mergeLocalModelInstall(job);
  scheduleLocalModelInstallPoll();
  renderResourceOnboarding();
  if (state.activeView === "settings" && state.activeSettings === "resources") renderSettings();
  renderDownloadActivity();
  toast(`${resource.title} 已开始下载；右上角可持续查看进度。`);
}

function renderSettings() {
  if (state.activeSettings === "routing") state.activeSettings = "general";
  applyAppearancePreferences();
  document.querySelectorAll(".settings-nav").forEach((button) => button.classList.toggle("is-active", button.dataset.settingsPanel === state.activeSettings));
  const target = byId("settingsContent");
  if (!state.settings) {
    target.innerHTML = '<div class="error-state">设置尚未载入。</div>';
    return;
  }
  if (state.activeSettings === "resources") target.innerHTML = renderResourceSetupSettings();
  else if (state.activeSettings === "models") target.innerHTML = renderModelsSettings();
  else if (state.activeSettings === "local-models") target.innerHTML = renderLocalModelsSettings();
  else if (state.activeSettings === "document-processing") target.innerHTML = renderDocumentProcessingSettings();
  else if (state.activeSettings === "skills") target.innerHTML = renderRecordsSettings("skills");
  else if (state.activeSettings === "mcp") target.innerHTML = renderMcpMarketplaceSettings();
  else if (state.activeSettings === "plugins") target.innerHTML = renderRecordsSettings("plugins");
  else if (state.activeSettings === "about") target.innerHTML = renderAboutSettings();
  else target.innerHTML = renderGeneralSettings();
  hydrateIcons(target);
  renderDownloadActivity();
}

function renderExtensions() {
  const target = byId("extensionsContent");
  if (!target) return;
  const skills = state.extensions.skills || state.settings?.skills || [];
  const plugins = (state.settings?.plugins || []).filter((item) => !item.uninstalled);
  const tab = state.activeExtensions;
  const panels = {
    plugins: renderExtensionPlugins(plugins),
    skills: renderExtensionSkills(skills),
    market: renderExtensionMarket(),
  };
  const tabs = [
    ["plugins", "插件", plugins.length],
    ["skills", "技能", skills.length],
    ["market", "市场", "skills.sh"],
  ].map(([id, label, count]) => `<button type="button" class="extension-tab ${tab === id ? "is-active" : ""}" data-extension-tab="${id}" aria-current="${tab === id ? "page" : "false"}"><span>${label}</span><small>${escapeHtml(count)}</small></button>`).join("");
  target.innerHTML = `<div class="extensions-shell">
    <nav class="extension-tabs" aria-label="插件和技能页面">${tabs}</nav>
    <section class="extension-panel">${panels[tab]}</section>
  </div>${renderExtensionDetail()}`;
}

function renderExtensionDetail() {
  const detail = state.extensionDetail;
  if (!detail) return "";
  const records = detail.kind === "skills" ? (state.extensions.skills || []) : (state.settings.plugins || []);
  const item = records.find((row) => row.id === detail.id);
  if (!item) return "";
  const source = detail.kind === "skills" ? (item.path || item.source || "内置") : (item.source || "未指定来源");
  const title = detail.kind === "skills" ? "Skill" : "插件";
  const operations = Array.isArray(item.skills) && item.skills.length ? `<section class="extension-detail-operations"><span>包含能力</span>${item.skills.map((skill) => `<p>${escapeHtml(skill)}</p>`).join("")}</section>` : "";
  const remove = item.builtin ? "" : `<button type="button" class="extension-remove" data-action="uninstall-extension" data-extension-kind="${detail.kind}" data-extension-id="${escapeHtml(item.id)}">卸载</button>`;
  return `<div class="extension-detail-backdrop" data-action="close-extension-detail"><section class="extension-detail-card" data-action="extension-detail-content" role="dialog" aria-modal="true" aria-label="${escapeHtml(item.name)} 详情"><header>${extensionRecordMark(detail.kind, item)}<div><span>${title}</span><h2>${escapeHtml(item.name)}</h2></div><button type="button" data-action="close-extension-detail" aria-label="关闭">${uiIcon("x")}</button></header><p>${escapeHtml(item.description || "尚未添加说明")}</p>${operations}<dl><div><dt>标识</dt><dd><code>${escapeHtml(item.id)}</code></dd></div><div><dt>来源</dt><dd><code>${escapeHtml(source)}</code></dd></div><div><dt>状态</dt><dd>${item.enabled ? "已启用" : "已停用"}</dd></div></dl><footer>${remove}<label class="extension-switch"><input type="checkbox" data-action="toggle-record" data-record-kind="${detail.kind}" data-record-id="${escapeHtml(item.id)}" ${item.enabled ? "checked" : ""} /><span>${item.enabled ? "启用" : "已停用"}</span></label></footer></section></div>`;
}

const BUILTIN_PLUGIN_LOGOS = Object.freeze({
  zotero: "/zotero-logo.svg",
  documents: "/codex-plugin-documents.png",
  pdf: "/codex-plugin-pdf.png",
  spreadsheets: "/codex-plugin-spreadsheets.png",
  presentations: "/codex-plugin-presentations.png",
  latex: "/codex-plugin-latex.png",
});

function extensionRecordMark(kind, item) {
  if (kind === "skills") {
    return `<div class="extension-record-mark skill-mark">${uiIcon("wand")}</div>`;
  }
  const logo = BUILTIN_PLUGIN_LOGOS[String(item?.id || "")];
  if (logo) {
    return `<div class="extension-record-mark plugin-mark has-logo plugin-${escapeHtml(item.id)}"><img src="${logo}" alt="" /></div>`;
  }
  return `<div class="extension-record-mark plugin-mark">${uiIcon("puzzle")}</div>`;
}

function renderExtensionPlugins(plugins) {
  const rows = plugins.length ? plugins.map((plugin) => {
    const runtime = plugin.runtime || {};
    const runtimeText = runtime.ready === false ? (runtime.detail || "运行环境未就绪") : (runtime.detail || "可用");
    return `<article class="extension-record plugin-record"><button type="button" class="extension-record-main" data-action="open-extension-detail" data-extension-kind="plugins" data-extension-id="${escapeHtml(plugin.id)}">${extensionRecordMark("plugins", plugin)}<div class="extension-record-copy"><div class="extension-record-title"><h3>${escapeHtml(plugin.name)}</h3><span>${plugin.builtin ? "内置" : "插件"}</span></div><p>${escapeHtml(plugin.description || "尚未添加说明")}</p></div></button><div class="extension-record-actions"><span class="extension-status ${runtime.ready === false ? "is-missing" : "is-ready"}">${escapeHtml(runtimeText)}</span><label class="extension-switch"><input type="checkbox" data-action="toggle-record" data-record-kind="plugins" data-record-id="${escapeHtml(plugin.id)}" ${plugin.enabled ? "checked" : ""} /><span>${plugin.enabled ? "启用" : "已停用"}</span></label></div></article>`;
  }).join("") : `<div class="extension-empty"><span>${uiIcon("puzzle")}</span><strong>还没有插件来源</strong><p>登记受信任的本地路径或远程来源后，可在这里统一启停和维护。</p></div>`;
  return `<div class="extension-panel-summary"><p>内置办公与 LaTeX 插件由 Pi 直接调用；MCP 服务器在左侧独立管理。</p><span class="panel-count">${plugins.length} 项</span></div>
    <section class="extension-record-list">${rows}</section>
    <form class="extension-form plugin-form" id="extensionPluginForm"><div class="extension-form-copy"><strong>登记插件来源</strong><span>仅保存元数据，不会自动启动或执行插件。</span></div><label><span>名称</span><input name="plugin-name" required maxlength="100" placeholder="例如：文献管理连接器" /></label><label><span>来源</span><input name="plugin-source" required maxlength="500" placeholder="本地路径或受信任的插件地址" /></label><label class="extension-form-wide"><span>说明（可选）</span><input name="plugin-description" maxlength="400" placeholder="它会为研究流程提供什么能力？" /></label><button type="submit" class="extension-primary">登记插件</button></form>`;
}

function renderExtensionSkills(skills) {
  const rows = skills.length ? skills.map((skill) => {
    const sourceLabel = skill.builtin ? "内置能力" : ({ local: "本地导入", git: "Git 仓库", archive: "压缩包", marketplace: "skills.sh 市场" }[skill.source_type] || "手动登记");
    const status = skill.available ? "可用" : "缺少文件";
    return `<article class="extension-record skill-record"><button type="button" class="extension-record-main" data-action="open-extension-detail" data-extension-kind="skills" data-extension-id="${escapeHtml(skill.id)}">${extensionRecordMark("skills", skill)}<div class="extension-record-copy"><div class="extension-record-title"><h3>${escapeHtml(skill.name || skill.id)}</h3><span>${escapeHtml(sourceLabel)}</span></div><p>${escapeHtml(skill.description || "尚未添加说明")}</p></div></button><div class="extension-record-actions"><span class="extension-status ${skill.available ? "is-ready" : "is-missing"}">${status}</span><label class="extension-switch"><input type="checkbox" data-action="toggle-record" data-record-kind="skills" data-record-id="${escapeHtml(skill.id)}" ${skill.enabled ? "checked" : ""} /><span>${skill.enabled ? "启用" : "已停用"}</span></label></div></article>`;
  }).join("") : `<div class="extension-empty"><span>${uiIcon("wand")}</span><strong>还没有可用技能</strong><p>从本地文件夹、Git 仓库、压缩包或市场中安装一个 Skill。</p></div>`;
  return `<section class="extension-record-list skill-list">${rows}</section>`;
}

function renderExtensionMarket() {
  const query = state.marketplaceQuery.trim().toLowerCase();
  const allItems = state.extensions.marketplace || [];
  const items = allItems.filter((item) => !query || [item.name, item.slug, item.source].join(" ").toLowerCase().includes(query));
  const sources = [...new Set(allItems.map((item) => item.source).filter(Boolean))].slice(0, 8);
  const sourceChips = sources.map((source) => `<span>${escapeHtml(source)}</span>`).join("");
  const empty = state.extensions.marketplaceLoaded ? `<div class="extension-empty market-empty"><span>${uiIcon("search")}</span><strong>没有匹配的市场技能</strong><p>换一个关键词，或点击刷新市场以同步公开目录。</p></div>` : `<div class="extension-empty market-empty"><span>${uiIcon("refresh")}</span><strong>正在连接技能市场</strong><p>首次加载会同步公开目录；之后可手动刷新。</p></div>`;
  const cards = items.length ? items.map((item) => `<article class="market-card"><div class="market-card-top"><span class="market-orb">${uiIcon("wand")}</span><a href="${escapeHtml(safeExternalUrl(item.url))}" target="_blank" rel="noopener" aria-label="在浏览器打开 ${escapeHtml(item.name || item.slug)}">${uiIcon("arrow-up-right")}</a></div><h3>${escapeHtml(item.name || item.slug)}</h3><p>${escapeHtml(item.source || "公开来源")}</p><div class="market-card-meta"><span>${item.installs ? `${Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(item.installs)} 安装` : "待同步安装数"}</span><span>${escapeHtml(item.sourceType || "Skill")}</span></div><button type="button" class="market-install" data-action="install-market-skill" data-market-skill-id="${escapeHtml(item.id)}">安装到技能库 <b>${uiIcon("plus")}</b></button></article>`).join("") : empty;
  return `<div class="market-status-row"><span class="market-connection ${state.extensions.marketplaceOffline ? "is-offline" : ""}">${state.extensions.marketplaceOffline ? "离线示例" : "已连接 skills.sh"}</span></div>
    <section class="market-toolbar"><label class="market-search">${uiIcon("search")}<input id="extensionsMarketSearch" type="search" value="${escapeHtml(state.marketplaceQuery)}" placeholder="搜索技能名称、描述或来源" autocomplete="off" /></label><div class="market-source-chips"><b>来源</b><span class="is-selected">全部</span>${sourceChips}</div></section>
    <section class="market-grid">${cards}</section>`;
}

function safeExternalUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return ["https:", "http:"].includes(url.protocol) ? url.href : "https://skills.sh";
  } catch {
    return "https://skills.sh";
  }
}

async function refreshExtensions({ marketOnly = false, quiet = false, includeMarket = marketOnly || state.activeExtensions === "market" } = {}) {
  const requests = [];
  if (includeMarket) requests.push(request("/api/skills/market"));
  if (!marketOnly) requests.push(request("/api/skills"));
  const responses = await Promise.all(requests);
  const market = includeMarket ? responses.shift() : null;
  if (market) {
    state.extensions.marketplace = market.items || [];
    state.extensions.marketplaceOffline = Boolean(market.offline);
    state.extensions.marketplaceLoaded = true;
  }
  if (!marketOnly) {
    const installed = responses[0];
    state.extensions.skills = installed.skills || [];
    state.extensions.libraryPath = installed.library_path || "";
  }
  if (state.activeView === "extensions") renderExtensions();
  if (!quiet && market) toast(market.offline ? "市场暂不可用，正在显示可安装示例" : "市场已刷新");
}

async function installSkill(sourceType, source) {
  const result = await request("/api/skills/install", { method: "POST", body: JSON.stringify({ source_type: sourceType, source }) });
  state.settings = result.settings || state.settings;
  state.extensions.skills = result.skills || [];
  renderModelSelectors();
  renderExtensions();
  const count = (result.installed || []).length;
  toast(count ? `已安装 ${count} 个 Skill` : "Skill 已安装");
}

async function installMarketSkill(skillId) {
  await installSkill("marketplace", skillId);
}

function settingsHeading(title, description) {
  return `<header class="settings-heading"><div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div><span class="save-indicator">${escapeHtml(copy("localSaved"))}</span></header>`;
}

function renderGeneralSettings() {
  const counts = state.notebook?.counts || {};
  const { provider, model } = activeModel();
  const readyTools = (state.capabilities?.tools || []).filter((tool) => ["ready", "external"].includes(tool.status)).length;
  const appearance = appearancePreferences();
  const languageChoices = [
    ["zh-CN", "中文", "简体中文"],
    ["en", "English", "English"],
  ].map(([value, title, note]) => `<label class="appearance-choice"><input type="radio" name="appearance-locale" value="${value}" ${appearance.locale === value ? "checked" : ""} /><span class="appearance-choice-copy"><b>${title}</b><small>${note}</small></span><i aria-hidden="true"></i></label>`).join("");
  const themeChoices = [
    ["system", "layout"],
    ["light", "sun"],
    ["dark", "moon"],
  ].map(([value, icon]) => `<label class="appearance-choice appearance-theme-choice"><input type="radio" name="appearance-theme" value="${value}" ${appearance.theme === value ? "checked" : ""} /><span class="appearance-option-icon">${uiIcon(icon)}</span><span class="appearance-choice-copy"><b>${escapeHtml(copy(value))}</b><small>${escapeHtml(copy(`${value}Detail`))}</small></span><i aria-hidden="true"></i></label>`).join("");
  const accentChoices = ["jade", "ocean", "plum", "amber"].map((value) => `<label class="accent-choice" data-accent-choice="${value}"><input type="radio" name="appearance-accent" value="${value}" ${appearance.accent === value ? "checked" : ""} /><span class="accent-swatch" aria-hidden="true"></span><span>${escapeHtml(copy(value))}</span></label>`).join("");
  const modelLabel = provider ? `${provider.name} · ${model?.name || ""}` : (appearance.locale === "en" ? "Not selected" : "未选择");
  return `${settingsHeading(copy("settingsTitle"), copy("settingsDescription"))}
    <form id="generalPreferencesForm" class="general-preferences-form">
      <section class="settings-card appearance-card">
        <header class="appearance-card-heading"><span class="appearance-card-mark">${uiIcon("sliders")}</span><div><h2>${escapeHtml(copy("appearanceTitle"))}</h2><p>${escapeHtml(copy("appearanceDescription"))}</p></div></header>
        <div class="appearance-rule"></div>
        <section class="appearance-setting-group"><div class="appearance-setting-copy"><h3>${escapeHtml(copy("interfaceLanguage"))}</h3><p>${escapeHtml(copy("interfaceLanguageHint"))}</p></div><div class="appearance-choice-grid">${languageChoices}</div></section>
        <section class="appearance-setting-group"><div class="appearance-setting-copy"><h3>${escapeHtml(copy("appearanceTheme"))}</h3><p>${escapeHtml(copy("appearanceThemeHint"))}</p></div><div class="appearance-choice-grid appearance-theme-grid">${themeChoices}</div></section>
        <section class="appearance-setting-group"><div class="appearance-setting-copy"><h3>${escapeHtml(copy("accentColor"))}</h3><p>${escapeHtml(copy("accentColorHint"))}</p></div><div class="accent-choice-grid">${accentChoices}</div></section>
        <footer class="settings-footer-actions"><button type="submit" class="save-button">${escapeHtml(copy("saveAppearance"))}</button></footer>
      </section>
    </form>
    <section class="settings-card"><h2>${escapeHtml(copy("currentWorkspace"))}</h2><p>${escapeHtml(state.notebook?.title || copy("noWorkspace"))}</p><div class="setting-metrics"><div class="setting-metric"><b>${escapeHtml(counts.sources || 0)}</b><span>${escapeHtml(copy("sources"))}</span></div><div class="setting-metric"><b>${escapeHtml(counts.citations || 0)}</b><span>${escapeHtml(copy("citations"))}</span></div><div class="setting-metric"><b>${escapeHtml(counts.layers || 0)}</b><span>${escapeHtml(copy("layers"))}</span></div></div><p class="local-note">${escapeHtml(copy("currentModel"))}：${escapeHtml(modelLabel)}。${escapeHtml(copy("modelKeyNote"))}</p></section>
    <section class="settings-card"><h2>${escapeHtml(copy("runtimeStatus"))}</h2><p>${readyTools} ${escapeHtml(copy("readyTools"))}</p></section>`;
}

function updateStatusCopy(update = state.update || {}) {
  const status = ["checking", "installing", "restarting"].includes(update.state) ? update.state : (update.available ? "available" : update.state || "idle");
  if (status === "checking") return "正在获取最新版本信息…";
  if (status === "installing") return "正在下载并校验更新包…";
  if (status === "restarting") return "更新已准备好，正在重启 ScanSci…";
  if (update.available) return `发现新版本 v${update.latest_version || "—"}，已在右上角提示。`;
  if (status === "error") return "暂时无法连接更新服务，可稍后再试。";
  if (update.checked_at) return "当前已是最新版本。";
  return "尚未检查更新。";
}

function renderAboutSettings() {
  const update = state.update || {};
  const isBusy = ["checking", "installing", "restarting"].includes(update.state);
  const hasUpdate = Boolean(update.available);
  const version = update.current_version || "0.2.0";
  const latestVersion = update.latest_version || version;
  const checkAction = hasUpdate && update.can_install ? "install-app-update" : "check-app-update";
  const checkLabel = isBusy ? (update.state === "installing" ? "正在更新" : "检查中") : (hasUpdate && update.can_install ? "立即更新" : "检查更新");
  const notes = (update.release_notes || []).flatMap((section) => section.items || []).slice(0, 2);
  const releaseSummary = hasUpdate
    ? (notes.length ? notes.join(" · ") : "新版本的更新说明已准备就绪。")
    : "发现新版本后，可在这里查看发布说明。";
  const checkedAt = formatUpdateTime(update.checked_at).replace(/^检查于/, "") || "尚未检查";
  return `<main class="about-settings">
    <section class="about-card about-product-card">
      <header class="about-card-heading"><h1>关于 ScanSci</h1><span>DESKTOP</span></header>
      <div class="about-product">
        <img class="about-product-mark" src="/scansci-mark.png" alt="ScanSci" />
        <div class="about-product-copy"><h2>ScanSci</h2><p>由 Pi Agent 驱动的可追溯 AI 研究工作台</p><span class="about-version">v${escapeHtml(version)}</span></div>
        <button type="button" class="about-check-button" data-action="${checkAction}" ${isBusy ? "disabled" : ""}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M15.8 7.2A6.3 6.3 0 1 0 16 12"></path><path d="M16 3.8v3.8h-3.8"></path></svg>${checkLabel}</button>
      </div>
      <div class="about-update-rows">
        <div class="about-row"><div><strong>自动检查更新</strong><p>启动 ScanSci 时在后台检查稳定版更新</p></div><label class="about-switch"><input type="checkbox" data-update-auto-check ${state.autoCheckUpdates ? "checked" : ""} /><span aria-hidden="true"></span></label></div>
        <div class="about-row"><div><strong>版本状态</strong><p>${escapeHtml(updateStatusCopy(update))}</p></div><span class="about-row-value ${hasUpdate ? "is-update" : ""}">${hasUpdate ? `v${escapeHtml(latestVersion)}` : `v${escapeHtml(version)}`}</span></div>
      </div>
    </section>
    <section class="about-card about-details-card" aria-label="版本详情">
      <div class="about-row"><div><strong>更新通道</strong><p>仅接收经过验证的稳定版本</p></div><span class="about-row-value">稳定版</span></div>
      <div class="about-row"><div><strong>上次检查</strong><p>${escapeHtml(releaseSummary)}</p></div><span class="about-row-value">${escapeHtml(checkedAt)}</span></div>
    </section>
  </main>`;
}

function selectedProvider() {
  const providers = state.settings?.providers || [];
  const selected = providers.find((provider) => provider.id === state.selectedProviderId);
  if (selected?.kind !== "local") return selected || providers.find((provider) => provider.kind !== "local") || providers[0];
  return providers.find((provider) => provider.kind !== "local") || selected || providers[0];
}

function renderModelsSettings() {
  const provider = selectedProvider();
  if (!provider) return `${settingsHeading("模型服务", "添加并选择用于研究对话的模型提供商。")}<div class="empty-records">还没有可用提供商。</div>`;
  state.selectedProviderId = provider.id;
  const allProviders = state.settings.providers || [];
  const query = state.providerQuery.trim().toLocaleLowerCase();
  const matchesQuery = (item) => !query || `${item.name} ${item.category || ""} ${item.summary || ""}`.toLocaleLowerCase().includes(query);
  const catalogProviders = allProviders.filter((item) => item.kind !== "local" && matchesQuery(item));
  const localProviders = allProviders.filter((item) => item.kind === "local");
  const providerRow = (item, sortable = item.kind !== "local") => `<article class="cherry-provider-item ${item.id === provider.id ? "is-active" : ""} ${item.enabled ? "is-enabled" : "is-disabled"}" ${sortable ? `draggable="true" data-provider-drag-id="${escapeHtml(item.id)}"` : ""}><span class="cherry-provider-drag" aria-hidden="true" title="拖拽排序">${uiIcon("grip-vertical")}</span><button type="button" class="cherry-provider-button" data-action="select-provider" data-provider-id="${escapeHtml(item.id)}" aria-current="${item.id === provider.id ? "page" : "false"}">${providerLogo(item)}<span>${escapeHtml(item.name)}</span></button><button type="button" class="cherry-provider-status" data-action="toggle-provider-enabled" data-provider-id="${escapeHtml(item.id)}" aria-pressed="${item.enabled ? "true" : "false"}" title="${item.enabled ? "停用服务商" : "启用服务商"}">${item.enabled ? "ON" : "OFF"}</button></article>`;
  const providerItems = catalogProviders.map((item) => providerRow(item, !query)).join("");
  const localRuntimeNotice = localProviders.length ? `<section class="cherry-local-runtime-notice"><span>${uiIcon("folder-open")}</span><div><strong>本机运行能力</strong><p>离线检索和已发现的 Hugging Face 模型不属于 API 服务商，统一在“本地模型”中管理。</p><button type="button" data-action="open-local-models">打开本地模型 ${uiIcon("arrow-up-right")}</button></div></section>` : "";
  const groupedModels = new Map();
  const modelQuery = state.modelQuery.trim().toLocaleLowerCase();
  provider.models.forEach((model, index) => {
    if (modelQuery && !`${model.name || ""} ${model.id || ""} ${model.group || ""}`.toLocaleLowerCase().includes(modelQuery)) return;
    const group = String(model.group || "默认模型");
    if (!groupedModels.has(group)) groupedModels.set(group, []);
    groupedModels.get(group).push({ model, index });
  });
  const modelRows = [...groupedModels.entries()].map(([group, models]) => `<section class="cherry-model-group"><header><strong>${escapeHtml(group)}</strong></header>${models.map(({ model, index }) => `<article class="cherry-model-row"><span class="cherry-model-mark">${escapeHtml((group || "M").slice(0, 1).toUpperCase())}</span><div class="cherry-model-copy"><button type="button" data-action="edit-model" data-model-index="${index}">${escapeHtml(model.name || model.id)}</button><small>${escapeHtml(model.id)}${model.context_window ? ` · ${escapeHtml(model.context_window)}` : ""}</small></div>${modelCapabilityChips(model, index)}<details class="cherry-model-more"><summary aria-label="编辑模型能力">${uiIcon("settings")}</summary>${modelCapabilityChips(model, index, { showAll: true })}</details><button class="cherry-row-remove" type="button" data-action="remove-model" data-model-index="${index}" aria-label="移除模型">${uiIcon("minus")}</button></article>`).join("")}</section>`).join("");
  const kindOptions = ["local", "openai-compatible", "anthropic-compatible"].map((kind) => `<option value="${kind}" ${provider.kind === kind ? "selected" : ""}>${kind === "local" ? "本地" : kind}</option>`).join("");
  const customNameField = isBuiltInProvider(provider) ? `<input type="hidden" name="provider-name" value="${escapeHtml(provider.name)}" />` : `<label class="cherry-field"><span>服务商名称</span><input name="provider-name" value="${escapeHtml(provider.name)}" required maxlength="80" /></label>`;
  const kindField = isBuiltInProvider(provider) ? `<input type="hidden" name="provider-kind" value="${escapeHtml(provider.kind)}" />` : `<label class="cherry-field cherry-kind-field"><span>接口类型</span><select name="provider-kind">${kindOptions}</select></label>`;
  const isManaged = provider.auth_mode === "managed";
  const keyField = isManaged ? `<p class="cherry-field-hint">此模型由 ScanSci 托管提供，使用时无需配置 API 密钥。</p>` : provider.kind !== "local" ? `<div class="cherry-key-row"><label class="cherry-field cherry-secret-field"><span>API 密钥${provider.api_key_configured ? '<em>已保存</em>' : ""}</span><span class="cherry-secret-control"><input name="provider-api-key" type="password" autocomplete="new-password" autocapitalize="off" spellcheck="false" placeholder="${provider.api_key_configured ? "••••••••••••••••" : "输入后仅保存在系统凭据管理器"}" /><button type="button" class="cherry-secret-toggle" data-action="toggle-provider-key" aria-label="${provider.api_key_configured ? "显示已保存的 API 密钥" : "显示 API 密钥"}" aria-pressed="false" title="${provider.api_key_configured ? "显示已保存的密钥" : "显示密钥"}">${uiIcon("eye")}</button></span></label><button type="button" class="cherry-detect-button" data-action="test-provider" ${!provider.api_key_configured ? "disabled" : ""}>检 测</button></div><p class="cherry-field-hint">${provider.api_key_configured ? "密钥默认隐藏；仅在点击眼睛时从本机凭据管理器读取。" : "多个密钥可用英文逗号分隔。"}</p>` : `<p class="cherry-field-hint">内置证据引擎不需要 API 密钥。</p>`;
  const restoreDefaultButton = isBuiltInProvider(provider) ? '<button type="button" class="cherry-restore-default" data-action="restore-provider-default">恢复默认</button>' : "";
  const providerHeaderActions = `${restoreDefaultButton}${provider.api_key_configured && !isManaged ? '<button type="button" class="cherry-text-button" data-action="remove-provider-key">移除密钥</button>' : ""}<button type="submit" class="cherry-save-button">保存</button>`;
  return `<section class="cherry-model-services"><aside class="cherry-provider-catalog"><label class="cherry-provider-search"><svg class="cherry-search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.75" cy="10.75" r="6.75"></circle><path d="m16 16 5 5"></path></svg><input id="modelServiceSearch" type="search" value="${escapeHtml(state.providerQuery)}" placeholder="搜索模型平台..." autocomplete="off" /></label><div class="cherry-provider-scroll">${providerItems || '<div class="cherry-provider-empty">没有匹配的模型平台</div>'}${localRuntimeNotice}</div><button class="cherry-add-provider" type="button" data-action="add-provider">＋&nbsp; 添加</button></aside><main class="cherry-provider-panel"><form id="modelProviderForm"><header class="cherry-provider-header"><div><div class="cherry-provider-name">${providerLogo(provider)}<h1>${escapeHtml(provider.name)}</h1><button type="button" class="cherry-mini-gear" aria-label="服务商设置">⚙</button></div>${kindField}</div><div class="cherry-provider-header-actions">${providerHeaderActions}<span class="cherry-provider-header-divider" aria-hidden="true"></span><label class="cherry-toggle"><input name="provider-enabled" type="checkbox" ${provider.enabled ? "checked" : ""} /><span></span></label></div></header><section class="cherry-connection-section">${customNameField}${keyField}<label class="cherry-field"><span>API 地址 <i>⌁</i></span><input name="provider-base-url" value="${escapeHtml(provider.base_url || "")}" placeholder="https://api.example.com/v1" maxlength="500" ${isManaged ? "readonly" : ""} /></label><p class="cherry-endpoint-preview">预览：${escapeHtml(provider.base_url ? `${provider.base_url.replace(/\/$/, "")}/chat/completions` : "请填写服务商 API 地址")}</p></section><section class="cherry-model-section"><header><div class="cherry-model-section-title"><h2>模型</h2><b>${provider.models.length}</b></div><label class="cherry-model-search"><span>⌕</span><input id="modelListSearch" type="search" value="${escapeHtml(state.modelQuery)}" placeholder="搜索模型..." aria-label="搜索模型" autocomplete="off" /></label><div class="cherry-model-actions"><button type="button" class="cherry-fetch-button" data-action="fetch-provider-models" ${provider.kind === "local" || !provider.model_listing ? "disabled" : ""}>↻&nbsp; 获取模型列表</button><button type="button" class="cherry-plus-button" data-action="add-model" aria-label="添加模型">＋</button></div></header><div class="cherry-model-list">${modelRows || `<div class="cherry-provider-empty">${modelQuery ? "没有匹配的模型" : "尚未添加模型"}</div>`}</div></section><footer class="cherry-provider-footer"><button type="button" class="cherry-remove-provider" data-action="remove-provider" ${isBuiltInProvider(provider) ? "disabled" : ""}>移除服务商</button></footer>${modelEditorMarkup(provider)}</form></main></section>`;
}

function renderLocalModelsSettings() {
  const presets = (state.presets?.local_models || []).map((item) => `<button type="button" class="quiet-add-chip" data-action="add-local-preset" data-preset-id="${escapeHtml(item.id)}">＋ ${escapeHtml(item.name)}</button>`).join("");
  const installedItems = state.localModelMarket?.installed || [];
  const runtime = state.localRuntime || { installed: false, install_available: false, mode: "missing" };
  const runtimeReady = Boolean(runtime.installed);
  const runtimeJob = runtime.install_job || {};
  const runtimeInstalling = ["queued", "installing"].includes(runtimeJob.state);
  const runtimeNeedsRetry = ["failed", "cancelled", "interrupted"].includes(runtimeJob.state);
  const runtimeProgress = Math.max(0, Math.min(100, Math.round(Number(runtimeJob.progress || 0) * 100)));
  const runtimeAction = runtimeReady
    ? `<span class="local-model-primary-ready">${uiIcon("check")} 运行时已就绪</span>`
    : runtimeInstalling
      ? `<span class="local-model-primary-state">${escapeHtml(runtimeJob.message || "正在安装")} ${runtimeProgress}%<small>${escapeHtml(downloadJobTelemetry(runtimeJob))}</small></span>`
    : runtimeNeedsRetry && runtime.install_available
      ? `<button type="button" class="local-model-primary-action" data-action="install-local-runtime">${uiIcon("refresh")}继续安装</button>`
    : runtime.install_available
      ? `<button type="button" class="local-model-primary-action" data-action="install-local-runtime">${uiIcon("download")}安装本地运行能力</button>`
      : `<button type="button" class="local-model-primary-action" data-action="open-local-runtime-setup">${uiIcon("settings")}查看本地运行设置</button>`;
  const runtimeDescription = runtimeReady
    ? "可使用已安装的本地模型；模型下载完成后会自动校验。"
    : runtimeInstalling
      ? "由 ScanSci 提供，正在下载、校验并自检；进度会持续保留。"
    : runtimeNeedsRetry
      ? runtimeJob.error || runtimeJob.message || "安装未完成；继续安装会复用已下载内容。"
    : runtime.install_available
      ? "由 ScanSci 提供并按需安装；核心程序保持轻量，安装完成后可下载本地模型。"
      : "当前发行渠道未提供本地运行能力；可连接 Ollama、LM Studio 使用已有模型，但不会下载无法执行的 Hugging Face 权重。";
  const capabilityLabel = (kind) => ({ chat: "对话", embedding: "嵌入", reranking: "重排", vision: "视觉", audio: "语音" }[kind] || "通用");
  const installed = installedItems.map((item) => {
    const size = `${(Number(item.size_bytes || 0) / 1024 / 1024 / 1024).toFixed(1)} GB`;
    const kind = item.kind || (/(embedding|embed|bge|gte|e5-)/i.test(item.id || "") ? "embedding" : /(rerank)/i.test(item.id || "") ? "reranking" : "chat");
    return `<article class="quiet-model-row"><span class="quiet-model-mark">${kind === "chat" ? "◎" : "◇"}</span><div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.architecture || item.model_type || "Hugging Face")} · 自动发现</p><div class="local-capability-tags"><span>${capabilityLabel(kind)}</span>${item.format ? `<span>${escapeHtml(item.format)}</span>` : ""}</div></div><span class="quiet-row-note">${item.ready ? "已就绪" : "下载未完成"}</span><span class="quiet-row-size">${size}</span></article>`;
  }).join("") || '<div class="quiet-empty">未发现本地 Hugging Face 快照。</div>';
  const catalog = (state.localModelMarket?.catalog || []).map((item) => `<article class="quiet-model-row"><span class="quiet-model-mark is-muted">↓</span><div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.description || "Hugging Face")}${item.size_hint ? ` · ${escapeHtml(item.size_hint)}` : ""}</p><div class="local-capability-tags"><span>${capabilityLabel(item.kind)}</span>${item.downloads ? `<span>${Intl.NumberFormat("zh-CN", { notation: "compact" }).format(item.downloads)} 下载</span>` : ""}</div></div>${item.installed ? `<span class="quiet-row-note">${item.ready ? "已安装" : "未完成"}</span>` : runtimeReady ? `<button type="button" class="quiet-text-button" data-action="download-local-model" data-model-repo="${escapeHtml(item.id)}">下载</button>` : `<button type="button" class="quiet-text-button" data-action="open-local-runtime-setup">查看运行时</button>`}</article>`).join("") || '<div class="quiet-empty">市场目录暂不可用。</div>';
  const runtimeRows = (state.settings.local_models || []).map((item, index) => ({ item, index })).filter(({ item }) => item.runtime !== "builtin").map(({ item, index }) => `<details class="quiet-runtime-row"><summary><span class="quiet-model-mark">◌</span><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.runtime)} · ${item.enabled ? "可用" : "已停用"}</small></span><span class="quiet-row-note">配置</span></summary><div class="quiet-runtime-fields"><label><span>名称</span><input data-local-name="${index}" value="${escapeHtml(item.name)}" /></label><label><span>运行时</span><input data-local-runtime="${index}" value="${escapeHtml(item.runtime)}" /></label><label><span>地址</span><input data-local-url="${index}" value="${escapeHtml(item.base_url || "")}" placeholder="http://127.0.0.1:11434/v1" /></label><label><span>模型 ID</span><input data-local-model="${index}" value="${escapeHtml(item.model_id || "")}" placeholder="例如 qwen3:8b" /></label><label class="quiet-switch"><input type="checkbox" data-local-enabled="${index}" ${item.enabled ? "checked" : ""} /><span>启用</span></label><div><button type="button" class="quiet-text-button" data-action="test-local-model" data-local-id="${escapeHtml(item.id)}">测试连接</button><button type="button" class="quiet-danger-button" data-action="remove-local-model" data-local-index="${index}">移除</button></div></div></details>`).join("") || '<div class="quiet-empty">尚未添加外部本地运行时。</div>';
  const retrievalIds = new Set(["Qwen/Qwen3-Embedding-0.6B", "Qwen/Qwen3-Reranker-0.6B"]);
  const retrievalReady = [...retrievalIds].every((id) => installedItems.some((item) => item.id === id && item.ready));
  const retrievalJob = (state.localModelInstall?.jobs || []).find((item) => item.job_id === "retrieval-core") || null;
  const retrievalState = !runtimeReady ? "runtime_required" : retrievalReady ? "ready" : String(retrievalJob?.state || "idle");
  const retrievalProgress = retrievalReady ? 100 : Math.max(0, Math.min(100, Math.round(Number(retrievalJob?.progress || 0) * 100)));
  const retrievalActive = ["queued", "downloading"].includes(retrievalState);
  const retrievalNeedsRetry = ["failed", "cancelled", "interrupted"].includes(retrievalState);
  const retrievalTitle = retrievalReady
    ? "Qwen3 Embedding 0.6B + Qwen3 Reranker 0.6B"
    : "基础关键词检索";
  const retrievalDescription = !runtimeReady
    ? runtimeDescription
    : retrievalReady
    ? "用于资料库语义检索与证据重排"
    : "尚未安装 Qwen 检索模型；不会假称语义检索";
  const retrievalStateLabel = retrievalState === "runtime_required" ? "需要运行时" : retrievalReady ? "已就绪" : retrievalActive ? `下载中 ${retrievalProgress}%` : retrievalNeedsRetry ? (retrievalState === "interrupted" ? "下载已中断" : "下载失败") : "未下载";
  const retrievalAction = retrievalState === "runtime_required"
    ? runtimeAction
    : retrievalReady
    ? `<span class="local-model-primary-ready">${uiIcon("check")} 已就绪</span>`
    : retrievalActive
      ? `<span class="local-model-primary-state">${escapeHtml(retrievalStateLabel)}</span>`
      : `<button type="button" class="local-model-primary-action" data-action="install-retrieval-models">${uiIcon(retrievalState === "failed" ? "refresh" : "download")}${retrievalState === "failed" ? "重试" : "下载"}</button>`;
  const retrievalProgressMarkup = retrievalActive
    ? `<div class="resource-download-detail"><small>${escapeHtml(downloadJobTelemetry(retrievalJob) || "正在建立下载连接")}</small><div class="local-model-primary-progress" role="progressbar" aria-label="研究检索组件下载进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${retrievalProgress}"><span class="${progressWidthClass(retrievalProgress)}"></span></div></div>`
    : "";
  return `<section class="quiet-settings-page local-models-page local-models-page--compact"><header class="quiet-page-heading"><div><h1>本地模型</h1><p>模型与资料均保留在这台电脑上。</p></div><button type="button" class="quiet-text-button" data-action="refresh-local-model-market">刷新</button></header>
    <section class="local-model-primary"><span class="local-model-primary-icon">${uiIcon("library")}</span><div class="local-model-primary-copy"><span>知识库检索 · ${escapeHtml(retrievalStateLabel)}</span><strong>${escapeHtml(retrievalTitle)}</strong><p>${escapeHtml(retrievalDescription)}</p>${retrievalProgressMarkup}</div><div class="local-model-primary-end">${retrievalAction}</div></section>
    <p class="local-model-fallback">离线或小型资料库时，会自动使用基础关键词检索。</p>
    <details class="local-model-disclosure"><summary><span>已发现的模型</span><em>${installedItems.length}</em></summary><div class="quiet-model-list">${installed}</div></details>
    <details class="local-model-disclosure local-runtime-disclosure"><summary><span>本地运行时</span><em>${runtimeReady ? "已就绪" : "需要配置"}</em></summary><div class="local-model-disclosure-body"><p>${escapeHtml(runtimeDescription)}</p><div class="quiet-add-chips">${presets}</div><form id="localModelsForm" class="quiet-runtime-list">${runtimeRows}<footer><button type="submit" class="quiet-primary-button">保存更改</button></footer></form></div></details>
    <details class="local-model-disclosure"><summary><span>模型市场</span><em>按需下载</em></summary><div class="local-model-disclosure-body"><form id="localModelMarketSearch" class="local-model-market-search"><input name="query" type="search" value="${escapeHtml(state.localModelMarket?.query || "")}" placeholder="搜索模型，例如 embedding、reranker、Qwen" /><button type="submit" class="quiet-text-button">搜索</button></form><div class="quiet-model-list">${catalog}</div></div></details></section>`;
}

function renderDocumentProcessingSettings() {
  const processing = state.settings.document_processing || {};
  const ocr = processing.ocr || { provider: "system", base_url: "", languages: ["zh", "en"], enabled: true };
  const mineru = processing.mineru || { provider: "mineru", base_url: "https://mineru.net", enabled: false };
  const ocrLanguages = new Set(ocr.languages || []);
  const paddleSelected = ocr.provider === "paddle";
  const ocrConnection = ocr.provider === "custom" ? `<div class="document-service-fields"><label class="setting-field"><span>API 地址</span><input name="ocr-base-url" value="${escapeHtml(ocr.base_url || "")}" placeholder="https://ocr.example.com/v1" maxlength="500" /></label><label class="setting-field"><span>API 密钥</span><input name="ocr-api-key" type="password" autocomplete="new-password" placeholder="${ocr.api_key_configured ? "已保存在系统凭据管理器；输入新值以替换" : "可选，保存后仅存于系统凭据管理器"}" /></label></div>` : ocr.provider === "system" ? `<p class="document-service-note">使用系统 OCR 识别扫描页与图片中的中英文文字，无需填写 API 密钥。</p>` : "";
  const paddleGuide = ocr.provider !== "custom" ? `<aside class="paddle-ocr-guide ${paddleSelected ? "is-configuring" : ""}"><span class="paddle-ocr-guide-icon">P</span><div class="paddle-ocr-guide-main"><header><strong>PaddleOCR</strong><em>飞桨 AI Studio · 可选</em></header><p>${paddleSelected ? "粘贴个人 Access Token 即可；令牌仅保存在这台电脑的系统凭据管理器中。" : "需要更强的扫描件识别时，可使用个人 AI Studio Access Token。"}</p>${paddleSelected ? `<label class="setting-field paddle-ocr-token-field"><span>Access Token</span><input name="ocr-api-key" type="password" autocomplete="new-password" placeholder="${ocr.api_key_configured ? "已保存在系统凭据管理器；输入新值以替换" : "粘贴 AI Studio Access Token"}" ${ocr.api_key_configured ? "" : "required"} /></label>` : ""}</div><div class="paddle-ocr-guide-actions"><a href="https://aistudio.baidu.com/account/accessToken" target="_blank" rel="noreferrer">获取 Token ${uiIcon("arrow-up-right")}</a>${paddleSelected ? "" : `<button type="button" data-action="configure-paddle-ocr">开始配置</button>`}</div></aside>` : "";
  const mineruName = mineru.provider === "mineru" ? "MinerU" : "自定义文档解析服务";
  return `${settingsHeading("文档处理", "配置扫描页识别与学术 PDF 解析服务。密钥不会写入工作区文件。")}
    <form id="documentProcessingForm" class="document-processing-form">
      <section class="document-service-card"><div class="document-service-heading"><div><span class="document-service-icon">O</span><div><h2>OCR 服务</h2><p>从扫描 PDF、图像和无法直接复制的页面提取文字。</p></div></div><label class="switch-label"><input name="ocr-enabled" type="checkbox" ${ocr.enabled ? "checked" : ""} />启用</label></div><div class="document-service-rule"></div><label class="document-select-row"><span>OCR 服务提供商</span><select name="ocr-provider"><option value="system" ${ocr.provider === "system" ? "selected" : ""}>系统 OCR</option><option value="paddle" ${paddleSelected ? "selected" : ""}>PaddleOCR（AI Studio）</option><option value="custom" ${ocr.provider === "custom" ? "selected" : ""}>自定义 OCR API</option></select></label>${paddleGuide}<div class="document-language-row"><span>识别语言</span><div class="language-chips"><label><input name="ocr-language" type="checkbox" value="zh" ${ocrLanguages.has("zh") ? "checked" : ""} />中文</label><label><input name="ocr-language" type="checkbox" value="en" ${ocrLanguages.has("en") ? "checked" : ""} />English</label></div></div>${ocrConnection}</section>
      <section class="document-service-card"><div class="document-service-heading"><div><span class="document-service-icon">M</span><div><h2>文档解析</h2><p>按版面保留论文的段落、表格、公式与图片结构。</p></div></div><label class="switch-label"><input name="mineru-enabled" type="checkbox" ${mineru.enabled ? "checked" : ""} />启用</label></div><div class="document-service-rule"></div><label class="document-select-row"><span>文档处理服务商</span><select name="mineru-provider"><option value="mineru" ${mineru.provider === "mineru" ? "selected" : ""}>MinerU</option><option value="custom" ${mineru.provider === "custom" ? "selected" : ""}>自定义解析 API</option></select></label><div class="document-service-fields"><label class="setting-field"><span>${escapeHtml(mineruName)} API 密钥</span><input name="mineru-api-key" type="password" autocomplete="new-password" placeholder="${mineru.api_key_configured ? "已保存在系统凭据管理器；输入新值以替换" : "输入后仅保存至系统凭据管理器"}" /></label><label class="setting-field"><span>API 地址</span><input name="mineru-base-url" value="${escapeHtml(mineru.base_url || "")}" placeholder="https://mineru.net" maxlength="500" /></label></div><p class="document-service-note">可填写多个 MinerU 密钥时请使用英文逗号分隔；密钥仅保存在当前电脑的系统凭据管理器中。</p></section>
      <div class="settings-footer-actions"><button type="submit" class="save-button">保存文档处理配置</button></div>
    </form>`;
}

function collectDocumentProcessingForm() {
  const form = byId("documentProcessingForm");
  if (!form) return state.settings.document_processing;
  state.settings.document_processing = {
    ocr: {
      provider: form.elements["ocr-provider"].value,
      base_url: form.elements["ocr-base-url"]?.value.trim() || "",
      languages: [...form.querySelectorAll('input[name="ocr-language"]:checked')].map((input) => input.value),
      enabled: form.elements["ocr-enabled"].checked,
    },
    mineru: {
      provider: form.elements["mineru-provider"].value,
      base_url: form.elements["mineru-base-url"].value.trim(),
      enabled: form.elements["mineru-enabled"].checked,
    },
  };
  return state.settings.document_processing;
}

function modelTargetOptions(selected = "", capability = "") {
  const options = ['<option value="">未指定</option>'];
  for (const provider of (state.settings.providers || []).filter(isProviderUsable)) {
    for (const model of provider.models || []) {
      if (capability && !(model.capabilities || []).includes(capability)) continue;
      const value = `provider:${provider.id}:${model.id}`;
      options.push(`<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>API · ${escapeHtml(provider.name)} · ${escapeHtml(model.name)}</option>`);
    }
  }
  for (const model of state.settings.local_models || []) {
    if (capability && model.runtime !== "builtin") continue;
    const value = `local:${model.id}`;
    options.push(`<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>本地 · ${escapeHtml(model.name)}</option>`);
  }
  return options.join("");
}

function renderRoutingSettings() {
  const definitions = [
    ["reasoning", "推理", "规划任务、比较证据与作出判断"],
    ["writing", "写作", "回答、综述与长文生成"],
    ["retrieval", "检索", "从本地资料库召回候选证据"],
    ["embedding", "嵌入", "构建语义索引"],
    ["reranking", "重排", "对候选片段重新排序"],
    ["vision", "视觉", "理解论文图表、图片和扫描页"],
    ["slides", "演示", "规划 PPT 结构与讲述节奏"],
  ];
  const roles = state.settings.model_roles || {};
  const rows = definitions.map(([id, name, description]) => `<label class="routing-row"><span><strong>${name}</strong><small>${description}</small></span><select data-model-role="${id}">${modelTargetOptions(roles[id] || "")}</select></label>`).join("");
  return `${settingsHeading("模型路由", "为不同科研任务指定模型。模型服务与本地模型可以各司其职。")}
    <section class="routing-callout"><span>R</span><div><strong>任务级切换仍然保留</strong><p>主页选择的是当前对话模型；这里定义 Agent 在后台检索、写作、视觉和演示任务中的默认分工。</p></div></section>
    <form id="modelRoleForm"><section class="routing-list">${rows}</section><div class="settings-footer-actions"><button type="submit" class="save-button">保存模型路由</button></div></form>`;
}

function renderRecordsSettings(kind) {
  const definitions = {
    skills: { title: "技能", description: "配置研究任务可用的本地技能。", singular: "技能", field: "path", label: "Skill 路径", placeholder: "例如 builtin:literature-search" },
    mcp: { title: "MCP 服务器", description: "登记 MCP 服务的启动命令；ScanSci 不会在保存时自动启动任何进程。", singular: "MCP 服务器", field: "command", label: "启动命令", placeholder: "例如 npx @modelcontextprotocol/server-filesystem" },
    plugins: { title: "插件管理", description: "登记本地或远程插件来源，按需启用。", singular: "插件", field: "source", label: "插件来源", placeholder: "本地路径或可信插件地址" },
  };
  const definition = definitions[kind];
  const records = kind === "mcp" ? state.settings.mcp_servers : state.settings[kind];
  const recordCards = records.length ? records.map((record) => {
    const auxiliary = kind === "skills" ? record.path : kind === "mcp" ? `${record.command}${record.args ? ` ${record.args}` : ""}` : record.source;
    return `<article class="settings-record"><div><h3>${escapeHtml(record.name)}</h3><p>${escapeHtml(record.description || "未添加说明")}</p>${auxiliary ? `<code>${escapeHtml(auxiliary)}</code>` : ""}</div><div class="record-actions"><label class="switch-label"><input type="checkbox" data-action="toggle-record" data-record-kind="${kind}" data-record-id="${escapeHtml(record.id)}" ${record.enabled ? "checked" : ""} />启用</label><button type="button" class="delete-button" data-action="remove-record" data-record-kind="${kind}" data-record-id="${escapeHtml(record.id)}" aria-label="删除">×</button></div></article>`;
  }).join("") : '<div class="empty-records">尚未配置。添加后会保存在当前电脑。</div>';
  const extra = kind === "mcp" ? '<label class="setting-field full-field"><span>参数（可选）</span><input name="record-args" placeholder="--stdio" maxlength="1000" /></label>' : "";
  return `${settingsHeading(definition.title, definition.description)}<section class="settings-records">${recordCards}</section><form class="record-form" data-record-form="${kind}"><label class="setting-field"><span>名称</span><input name="record-name" required maxlength="100" placeholder="${definition.singular}名称" /></label><label class="setting-field"><span>${definition.label}</span><input name="record-value" required maxlength="500" placeholder="${definition.placeholder}" /></label><label class="setting-field full-field"><span>说明（可选）</span><input name="record-description" maxlength="400" placeholder="简短说明它会做什么" /></label>${extra}<button type="submit" class="save-button">＋ 添加${definition.singular}</button></form>`;
}

function mcpCatalogItems() {
  const query = state.mcpMarketplaceQuery.trim().toLocaleLowerCase();
  const discipline = state.mcpMarketplaceDiscipline || "all";
  const rows = (state.mcpMarketplace.items || []).filter((item) => {
    const categories = Array.isArray(item.disciplines) ? item.disciplines : [];
    if (discipline !== "all" && !categories.includes(discipline)) return false;
    if (!query) return true;
    return [item.title, item.id, item.description, ...(item.tags || [])].join(" ").toLocaleLowerCase().includes(query);
  });
  if (state.mcpMarketplaceSort === "new") {
    rows.sort((left, right) => String(right.updated_at || "").localeCompare(String(left.updated_at || "")) || String(left.title).localeCompare(String(right.title)));
  } else if (state.mcpMarketplaceSort === "name") {
    rows.sort((left, right) => String(left.title || "").localeCompare(String(right.title || ""), "zh-Hans-CN"));
  } else {
    rows.sort((left, right) => Number(right.rank || 0) - Number(left.rank || 0) || String(left.title).localeCompare(String(right.title)));
  }
  return rows;
}

function mcpTransportLabel(item) {
  const value = item.transport || "stdio";
  return value === "streamable-http" ? "远程 HTTP" : value === "sse" ? "SSE" : "本地 stdio";
}

function mcpDisciplineLabel(identifier) {
  return (state.mcpMarketplace.disciplines || []).find((item) => item.id === identifier)?.label || "科研通用";
}

function renderMcpMarketplaceSettings() {
  const catalogue = state.mcpMarketplace;
  if (!catalogue.loaded && !catalogue.loading) {
    window.setTimeout(() => loadMcpMarketplace().catch((error) => toast(error.message, true)), 0);
  }
  const items = mcpCatalogItems();
  const installed = state.settings?.mcp_servers || [];
  const installedIds = new Set(installed.map((item) => item.catalog_id).filter(Boolean));
  const source = catalogue.source || { name: "Official MCP Registry", api_version: "v0.1" };
  const tabs = [
    ["public", "发现 MCP", `${catalogue.items?.length || 0}`],
    ["mine", "我的服务器", `${installed.length}`],
  ].map(([id, label, count]) => `<button type="button" class="mcp-market-tab ${state.mcpMarketplaceTab === id ? "is-active" : ""}" data-action="mcp-set-tab" data-mcp-tab="${id}" aria-current="${state.mcpMarketplaceTab === id ? "page" : "false"}">${escapeHtml(label)}<span>${escapeHtml(count)}</span></button>`).join("");
  const controls = `<div class="mcp-market-controls"><label class="mcp-market-search">${uiIcon("search")}<input id="mcpMarketplaceSearch" type="search" value="${escapeHtml(state.mcpMarketplaceQuery)}" placeholder="搜索 MCP、数据源或能力..." autocomplete="off" /></label><label class="mcp-market-select"><span>学科</span><select id="mcpMarketplaceDiscipline">${(catalogue.disciplines || [{ id: "all", label: "全部学科" }]).map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === state.mcpMarketplaceDiscipline ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}</select></label><div class="mcp-sort-control" aria-label="排序"><span>排序</span>${[["hot", "热门"], ["new", "最新"], ["name", "名称"]].map(([id, label]) => `<button type="button" data-action="mcp-set-sort" data-mcp-sort="${id}" class="${state.mcpMarketplaceSort === id ? "is-active" : ""}">${label}</button>`).join("")}</div></div>`;
  const content = state.mcpMarketplaceTab === "mine"
    ? renderMyMcpServers(installed)
    : renderMcpMarketplaceCards(items, installedIds, catalogue.loading);
  return `<section class="mcp-marketplace">
    <header class="mcp-market-hero"><div class="mcp-market-hero-copy"><p class="mcp-market-eyebrow">MCP MARKETPLACE</p><h1>MCP 广场</h1><p>为研究任务挑选可连接的工具、数据和服务。以官方 MCP Registry 为统一供给端，并用科研学科标签完成筛选。</p><div class="mcp-source-line">${uiIcon("server")}<span>${escapeHtml(source.name)} · ${escapeHtml(source.api_version || "v0.1")}</span><a href="${escapeHtml(source.url || "https://registry.modelcontextprotocol.io/")}" target="_blank" rel="noopener">查看来源 ${uiIcon("arrow-up-right")}</a></div></div><div class="mcp-market-orbit" aria-hidden="true"><i></i><b></b><em></em></div></header>
    <div class="mcp-market-toolbar"><nav class="mcp-market-tabs" aria-label="MCP 市场页面">${tabs}</nav><div class="mcp-market-toolbar-actions"><button type="button" class="mcp-create-button" data-action="open-mcp-manual">${uiIcon("plus")}创建 MCP</button><button type="button" class="mcp-sync-button" data-action="sync-mcp-marketplace" ${catalogue.loading ? "disabled" : ""}>${uiIcon("refresh")}${catalogue.loading ? "正在同步" : "同步官方目录"}</button></div></div>
    ${state.mcpMarketplaceTab === "public" ? controls : ""}
    ${content}
    <footer class="mcp-market-note">${uiIcon("info")}<span>“加入我的服务器”只保存连接配置，不会自动下载、启动或执行任何 MCP 进程。首次使用前请核对来源、权限和所需密钥。</span></footer>
    ${renderMcpCreateDialog()}
  </section>`;
}

function renderMcpMarketplaceView() {
  const target = byId("mcpMarketplaceContent");
  if (!target) return;
  target.innerHTML = renderMcpMarketplaceSettings();
}

function refreshMcpMarketplaceSurface() {
  if (state.activeView === "mcp") renderMcpMarketplaceView();
  else if (state.activeView === "settings" && state.activeSettings === "mcp") renderSettings();
}

function renderMcpMarketplaceCards(items, installedIds, loading) {
  if (loading && !items.length) return `<div class="mcp-market-loading">${uiIcon("refresh")}<span>正在读取本地科研目录…</span></div>`;
  if (!items.length) return `<div class="mcp-market-empty">${uiIcon("server")}<strong>没有匹配的 MCP</strong><p>更换学科或关键词，或同步官方目录以获得新的公开服务器。</p></div>`;
  return `<section class="mcp-market-grid">${items.map((item) => {
    const joined = installedIds.has(item.id);
    const disciplines = (item.disciplines || []).slice(0, 2).map((identifier) => `<span class="mcp-discipline-tag">${escapeHtml(mcpDisciplineLabel(identifier))}</span>`).join("");
    const tags = (item.tags || []).slice(0, 2).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("");
    return `<article class="mcp-market-card"><div class="mcp-card-top"><span class="mcp-card-icon">${uiIcon("server")}</span><span class="mcp-card-version">v${escapeHtml(item.version || "—")}</span></div><h2 title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</h2><p>${escapeHtml(item.description)}</p><div class="mcp-card-tags">${disciplines}${tags}</div><footer><span class="mcp-card-source">${uiIcon("check")}官方目录</span><span class="mcp-card-transport">${escapeHtml(mcpTransportLabel(item))}</span></footer><button type="button" class="mcp-install-button ${joined ? "is-added" : ""}" data-action="${joined ? "mcp-set-tab" : "install-mcp-marketplace"}" ${joined ? 'data-mcp-tab="mine"' : `data-mcp-id="${escapeHtml(item.id)}"`}>${joined ? `${uiIcon("check")}已加入` : `${uiIcon("plus")}加入我的服务器`}</button></article>`;
  }).join("")}</section>`;
}

function renderMyMcpServers(servers) {
  const records = servers.length ? servers.map((server) => {
    const connector = ({ zotero: "Zotero", obsidian: "Obsidian", general: "通用" })[server.connector_kind] || "通用";
    return `<article class="mcp-owned-record"><span class="mcp-owned-icon">${uiIcon("server")}</span><div><header><h2>${escapeHtml(server.name)}</h2><span>${escapeHtml(server.source || "自定义 MCP")} · ${connector}</span></header><p>${escapeHtml(server.description || "未添加说明")}</p><small>${escapeHtml(server.transport === "streamable-http" ? server.endpoint : [server.command, server.args].filter(Boolean).join(" ") || "等待填写连接信息")}</small><small>${server.allow_write ? "已授权写操作" : "只读工具；写操作未授权"}</small></div><div class="mcp-owned-actions"><button type="button" data-action="test-mcp-server" data-record-id="${escapeHtml(server.id)}">测试</button><label class="mcp-enabled-switch"><input type="checkbox" data-action="toggle-record" data-record-kind="mcp" data-record-id="${escapeHtml(server.id)}" ${server.enabled ? "checked" : ""} /><span>${server.enabled ? "启用" : "停用"}</span></label><button type="button" data-action="remove-record" data-record-kind="mcp" data-record-id="${escapeHtml(server.id)}" aria-label="移除 ${escapeHtml(server.name)}">${uiIcon("x")}</button></div></article>`;
  }).join("") : `<div class="mcp-market-empty is-mine">${uiIcon("server")}<strong>还没有已保存的 MCP</strong><p>从“发现 MCP”添加官方目录中的服务器，或登记自己的本地/远程连接。</p></div>`;
  return `<section class="mcp-owned-list">${records}</section><button type="button" class="mcp-manual-trigger" data-action="open-mcp-manual">${uiIcon("plus")}创建自定义 MCP</button>`;
}

function renderMcpCreateDialog() {
  if (!state.mcpManualOpen) return "";
  const mode = state.mcpCreateMode;
  const isStdio = mode === "stdio";
  const disciplines = state.mcpMarketplace.disciplines || [{ id: "all", label: "全部学科" }];
  const steps = `<ol class="mcp-create-steps" aria-label="创建步骤"><li class="is-current"><span>1</span>连接类型</li><li class="${mode ? "is-current" : ""}"><span>2</span>连接信息</li><li class="${mode ? "is-current" : ""}"><span>3</span>保存</li></ol>`;
  const choose = `<section class="mcp-create-choice"><div class="mcp-create-intro"><span class="mcp-create-mark">${uiIcon("plus")}</span><div><p>创建 MCP</p><h2>先选择连接类型</h2><span>选择后再填写必要信息；保存不会启动本地命令或访问远程服务。</span></div></div><div class="mcp-create-options"><button type="button" class="mcp-create-option" data-action="mcp-select-create-mode" data-mcp-create-mode="stdio"><span class="mcp-create-option-icon">${uiIcon("terminal")}</span><span><strong>本地 stdio</strong><small>连接本机命令行工具，例如 npx、uvx 或已安装的程序。</small></span><i>${uiIcon("arrow-right")}</i></button><button type="button" class="mcp-create-option" data-action="mcp-select-create-mode" data-mcp-create-mode="remote"><span class="mcp-create-option-icon is-remote">${uiIcon("globe")}</span><span><strong>远程服务</strong><small>连接团队部署或云端提供的 HTTP / SSE MCP 端点。</small></span><i>${uiIcon("arrow-right")}</i></button></div></section>`;
  const fields = isStdio
    ? `<div class="mcp-create-connection"><span class="mcp-create-connection-label">本地连接</span><label class="is-wide"><span>启动命令</span><input name="mcp-command" required maxlength="500" placeholder="例如：npx" autocomplete="off" /></label><label class="is-wide"><span>参数</span><input name="mcp-args" maxlength="1000" placeholder="例如：-y @scope/server" autocomplete="off" /></label><p>${uiIcon("shield-check")}命令仅作为连接配置保存，搜索科学不会在此时运行它。</p></div>`
    : `<div class="mcp-create-connection"><span class="mcp-create-connection-label">远程连接</span><label><span>传输协议</span><select name="mcp-transport"><option value="streamable-http">Streamable HTTP</option><option value="sse">Server-Sent Events</option></select></label><label class="is-wide"><span>服务端点</span><input name="mcp-endpoint" type="url" required maxlength="500" placeholder="https://example.org/mcp" autocomplete="url" /></label><p>${uiIcon("shield-check")}保存前只校验地址格式，不会向该端点发送请求。</p></div>`;
  const form = `<form id="mcpManualForm" class="mcp-create-form" data-mcp-create-mode="${escapeHtml(mode)}"><header><button type="button" class="mcp-create-back" data-action="mcp-create-back">${uiIcon("arrow-left")}返回类型</button><div><span>${isStdio ? "本地 stdio MCP" : "远程 MCP 服务"}</span><h2>填写连接信息</h2></div></header><div class="mcp-create-form-grid"><section class="mcp-create-basics"><label><span>名称</span><input name="mcp-name" required maxlength="100" placeholder="例如：Zotero MCP" autofocus /></label><label><span>关联连接器</span><select name="mcp-connector-kind"><option value="general">通用 MCP</option><option value="zotero">Zotero</option><option value="obsidian">Obsidian</option></select></label><label><span>适用学科</span><select name="mcp-discipline">${disciplines.filter((item) => item.id !== "all").map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("")}</select></label><label class="is-wide"><span>用途说明</span><textarea name="mcp-description" maxlength="400" rows="3" placeholder="它会为研究流程提供什么能力？"></textarea></label><label class="is-wide"><span>标签（可选）</span><input name="mcp-tags" maxlength="200" placeholder="例如：文献、笔记、只读检索（用逗号分隔）" /></label><label class="is-wide mcp-write-permission"><input name="mcp-allow-write" type="checkbox" /><span>允许模型看到新增、修改、删除等写操作（默认关闭）</span></label><label class="is-wide mcp-write-permission"><input name="mcp-deferred" type="checkbox" checked /><span>按需发现工具并延迟连接（推荐，减少上下文和启动等待）</span></label></section>${fields}</div><aside class="mcp-create-review"><span>${uiIcon("lock-keyhole")}执行边界</span><p>保存不会启动连接；启用后，Pi 仅在任务需要时连接并发现工具。默认过滤写操作。</p></aside><footer><button type="button" data-action="close-mcp-manual">取消</button><button type="submit" class="mcp-create-save">${uiIcon("check")}保存到我的服务器</button></footer></form>`;
  return `<div class="mcp-create-overlay" role="presentation"><section class="mcp-create-dialog" role="dialog" aria-modal="true" aria-labelledby="mcpCreateTitle"><header class="mcp-create-dialog-top"><div><span>自定义连接</span><h1 id="mcpCreateTitle">创建 MCP</h1></div><button type="button" data-action="close-mcp-manual" aria-label="关闭创建 MCP">${uiIcon("x")}</button></header>${steps}${mode ? form : choose}</section></div>`;
}

async function loadMcpMarketplace({ force = false } = {}) {
  if (state.mcpMarketplace.loading || (state.mcpMarketplace.loaded && !force)) return state.mcpMarketplace;
  state.mcpMarketplace.loading = true;
  refreshMcpMarketplaceSurface();
  try {
    const payload = await request("/api/mcp/marketplace");
    state.mcpMarketplace = { ...payload, loaded: true, loading: false };
    return state.mcpMarketplace;
  } finally {
    if (state.mcpMarketplace.loading) state.mcpMarketplace.loading = false;
    refreshMcpMarketplaceSurface();
  }
}

async function syncMcpMarketplace() {
  state.mcpMarketplace.loading = true;
  refreshMcpMarketplaceSurface();
  try {
    const payload = await request("/api/mcp/marketplace/sync", { method: "POST", body: "{}" });
    state.mcpMarketplace = { ...payload, loaded: true, loading: false };
    const count = payload.sync?.fetched || payload.cached_count || 0;
    toast(`已从官方目录同步 ${count} 个科研相关 MCP`);
  } catch (error) {
    state.mcpMarketplace.loading = false;
    throw error;
  }
  refreshMcpMarketplaceSurface();
}

async function installMcpMarketplaceServer(identifier) {
  const payload = await request("/api/mcp/marketplace/install", { method: "POST", body: JSON.stringify({ id: identifier }) });
  state.settings = payload.settings;
  renderModelSelectors();
  refreshMcpMarketplaceSurface();
  toast(payload.created ? "已加入我的服务器；尚未启动任何 MCP 进程" : "该 MCP 已在我的服务器中");
}

async function addManualMcpServer(form) {
  const mode = form.dataset.mcpCreateMode === "remote" ? "remote" : "stdio";
  const command = (form.elements["mcp-command"]?.value || "").trim();
  const endpoint = (form.elements["mcp-endpoint"]?.value || "").trim();
  const name = form.elements["mcp-name"].value.trim();
  if (!name) throw new Error("请为这个 MCP 填写名称。");
  if (mode === "stdio" && !command) throw new Error("请填写本地 MCP 的启动命令。");
  if (mode === "remote") {
    if (!endpoint) throw new Error("请填写远程 MCP 的服务端点。");
    try {
      const url = new URL(endpoint);
      if (!["http:", "https:"].includes(url.protocol)) throw new Error("unsupported protocol");
    } catch (_) {
      throw new Error("远程端点需要是以 http:// 或 https:// 开头的有效地址。");
    }
  }
  const tags = (form.elements["mcp-tags"]?.value || "").split(/[,，]/).map((tag) => tag.trim()).filter(Boolean).slice(0, 8);
  state.settings.mcp_servers.push({
    id: `mcp-${Date.now()}`,
    name,
    description: form.elements["mcp-description"].value.trim(),
    command,
    args: (form.elements["mcp-args"]?.value || "").trim(),
    endpoint,
    transport: mode === "stdio" ? "stdio" : form.elements["mcp-transport"].value,
    discipline: form.elements["mcp-discipline"].value || "general",
    connector_kind: form.elements["mcp-connector-kind"].value || "general",
    allow_write: Boolean(form.elements["mcp-allow-write"].checked),
    deferred: Boolean(form.elements["mcp-deferred"].checked),
    tags,
    source: "自定义 MCP",
    enabled: true,
  });
  state.mcpManualOpen = false;
  state.mcpCreateMode = "";
  state.mcpMarketplaceTab = "mine";
  await persistSettings("已保存 MCP 配置；将在相关任务中按需连接");
}

async function testMcpServer(serverId) {
  const result = await request("/api/mcp/test", {
    method: "POST",
    body: JSON.stringify({ server_id: serverId }),
  });
  if (!result.server_count) {
    const detail = result.diagnostics?.at(-1)?.error || "没有发现可用工具";
    throw new Error(detail);
  }
  toast(`MCP 已连接 · 发现 ${result.tool_count || 0} 个可用工具`);
}

function collectProviderForm() {
  const form = byId("modelProviderForm");
  const provider = selectedProvider();
  if (!form || !provider) return provider;
  provider.name = form.elements["provider-name"].value.trim() || provider.name;
  provider.kind = form.elements["provider-kind"].value;
  provider.base_url = form.elements["provider-base-url"].value.trim();
  provider.enabled = form.elements["provider-enabled"]?.checked ?? provider.enabled;
  provider.models = provider.models.map((model, index) => {
    const id = form.querySelector(`[data-model-id="${index}"]`)?.value.trim() || model.id;
    return {
      ...model,
      id,
      name: form.querySelector(`[data-model-name="${index}"]`)?.value.trim() || model.name || id,
      group: form.querySelector(`[data-model-group="${index}"]`)?.value.trim() || model.group || "默认模型",
      context_window: form.querySelector(`[data-model-context="${index}"]`)?.value.trim() || "",
    };
  });
  return provider;
}

function collectLocalModelsForm() {
  state.settings.local_models = (state.settings.local_models || []).map((model, index) => ({
    ...model,
    name: document.querySelector(`[data-local-name="${index}"]`)?.value.trim() || model.name,
    runtime: document.querySelector(`[data-local-runtime="${index}"]`)?.value.trim() || model.runtime,
    base_url: document.querySelector(`[data-local-url="${index}"]`)?.value.trim() || "",
    model_id: document.querySelector(`[data-local-model="${index}"]`)?.value.trim() || "",
    enabled: document.querySelector(`[data-local-enabled="${index}"]`)?.checked ?? model.enabled,
  }));
  return state.settings.local_models;
}

async function refreshLocalModelMarket() {
  const query = String(state.localModelMarket?.query || "").trim();
  state.localModelMarket.loading = true;
  const [installed, catalog, runtime] = await Promise.all([
    request("/api/local-models/installed"),
    request(`/api/local-models/market${query ? `?q=${encodeURIComponent(query)}` : ""}`),
    request("/api/local-runtime").catch(() => state.localRuntime),
  ]);
  state.localModelMarket = { installed: installed.models || [], catalog: catalog.items || [], source: catalog.source || "", query, loading: false };
  state.localRuntime = runtime || state.localRuntime;
  state.settings = await request("/api/settings");
  renderModelSelectors();
  if (state.activeView === "settings" && state.activeSettings === "local-models") renderSettings();
}

function collectModelRoleForm() {
  document.querySelectorAll("[data-model-role]").forEach((select) => {
    state.settings.model_roles[select.dataset.modelRole] = select.value;
  });
  return state.settings.model_roles;
}

function ensureActiveModel() {
  const { provider, model } = activeModel();
  if (!provider || !model) return;
  state.settings.active_model = { provider_id: provider.id, model_id: model.id };
}

async function persistSettings(message = "设置已保存") {
  ensureActiveModel();
  state.settings = await request("/api/settings", { method: "POST", body: JSON.stringify({ settings: state.settings }) });
  applyAppearancePreferences();
  state.selectedProviderId = selectedProvider()?.id || state.settings.providers[0]?.id || "";
  renderModelSelectors();
  if (state.activeView === "settings") renderSettings();
  if (state.activeView === "extensions") renderExtensions();
  if (state.activeView === "mcp") renderMcpMarketplaceView();
  toast(message);
}

function newRecord(kind, form) {
  const value = form.elements["record-value"].value.trim();
  const name = form.elements["record-name"].value.trim();
  const description = form.elements["record-description"].value.trim();
  const id = `${kind}-${Date.now()}`;
  if (kind === "skills") return { id, name, description, path: value, enabled: true };
  if (kind === "mcp") return { id, name, description, command: value, args: form.elements["record-args"].value.trim(), enabled: true };
  return { id, name, description, source: value, enabled: true };
}

async function handleSettingsAction(action, element) {
  if (action === "start-onboarding-resource") {
    await startOnboardingResource(element.dataset.resourceId || "retrieval");
    return;
  }
  if (action === "reopen-resource-onboarding") {
    state.onboardingStep = "resources";
    state.onboardingOpen = true;
    renderResourceOnboarding();
    return;
  }
  if (action === "open-data-onboarding") {
    state.onboardingStep = "sources";
    state.onboardingOpen = true;
    renderResourceOnboarding();
    return;
  }
  if (action === "advance-resource-onboarding" || action === "finish-resource-onboarding") {
    state.onboardingStep = "sources";
    renderResourceOnboarding();
    return;
  }
  if (action === "back-resource-onboarding") {
    state.onboardingStep = "resources";
    renderResourceOnboarding();
    return;
  }
  if (action === "skip-resource-onboarding") {
    await persistOnboardingPreferences({ welcome_dismissed: true }, "已暂时跳过首次配置；可随时在设置中继续", { close: true });
    return;
  }
  if (action === "finish-data-onboarding") {
    await persistOnboardingPreferences(
      {
        welcome_dismissed: true,
        resource_setup_completed: resourceInstallSnapshot("retrieval").state === "ready",
        data_setup_completed: connectedDataSourceCount() > 0,
      },
      "资料接入配置已完成",
      { close: true },
    );
    return;
  }
  if (action === "onboarding-connect-folder") {
    await chooseOnboardingLibraryFolder("folder");
    return;
  }
  if (action === "onboarding-connect-obsidian") {
    await chooseOnboardingLibraryFolder("obsidian");
    return;
  }
  if (action === "onboarding-connect-zotero") {
    await connectLocalZotero();
    return;
  }
  if (action === "onboarding-connect-notion") {
    await connectNotion();
    return;
  }
  if (action === "retry-guided-library-import") {
    const failed = state.libraryImportJob || {};
    await startGuidedLibraryImport(
      String(failed.path || ""),
      String(failed.library_kind || "folder"),
      String(failed.notebook_id || ""),
    );
    return;
  }
  if (action === "retry-bound-library-import") {
    const notebook = (state.workspace?.notebooks || []).find((item) => item.notebook_id === element.dataset.notebookId);
    const binding = notebook?.metadata?.local_binding || {};
    const path = String(binding.source_path || notebook?.root_path || "").trim();
    if (!path) throw new Error("找不到已绑定的文件夹路径，请重新选择文件夹。");
    await bindLibraryFolder(path, knowledgeSourceKind(notebook), notebook.notebook_id);
    return;
  }
  if (action === "open-local-models") {
    state.activeSettings = "local-models";
    renderSettings();
    return;
  }
  if (action === "configure-paddle-ocr") {
    const processing = collectDocumentProcessingForm();
    processing.ocr.provider = "paddle";
    processing.ocr.base_url = "";
    renderSettings();
    return;
  }
  if (action === "select-provider") {
    collectProviderForm();
    state.selectedProviderId = element.dataset.providerId;
    state.editingModelIndex = -1;
    state.modelQuery = "";
    renderSettings();
    return;
  }
  if (action === "toggle-provider-enabled") {
    collectProviderForm();
    const provider = state.settings.providers.find((item) => item.id === element.dataset.providerId);
    if (!provider) return;
    provider.enabled = !provider.enabled;
    const active = state.settings.active_model || {};
    if (!provider.enabled && active.provider_id === provider.id) {
      const fallback = state.settings.providers.find((item) => item.id !== provider.id && isProviderUsable(item) && item.models?.length);
      if (fallback) state.settings.active_model = { provider_id: fallback.id, model_id: fallback.models[0].id };
    }
    await persistSettings(`${provider.name} 已${provider.enabled ? "启用" : "停用"}`);
    return;
  }
  if (action === "restore-provider-default") {
    collectProviderForm();
    const provider = selectedProvider();
    const preset = (state.presets?.providers || []).find((item) => item.id === provider?.id);
    if (!provider || !preset) return;
    const confirmed = await requestConfirmation({
      eyebrow: "恢复默认配置",
      title: `恢复 ${provider.name} 的默认配置？`,
      message: "默认地址、模型与能力标签将被恢复，已保存的 API 密钥不会被删除。",
      confirmLabel: "恢复默认",
    });
    if (!confirmed) return;
    const index = state.settings.providers.findIndex((item) => item.id === provider.id);
    if (index < 0) return;
    state.settings.providers[index] = { ...structuredClone(preset), enabled: false, api_key_configured: Boolean(provider.api_key_configured) };
    state.editingModelIndex = -1;
    state.modelQuery = "";
    await persistSettings(`${provider.name} 已恢复默认配置`);
    return;
  }
  if (action === "add-provider") {
    collectProviderForm();
    const provider = { id: `provider-${Date.now()}`, name: "新服务商", logo: "custom", kind: "openai-compatible", base_url: "", category: "自定义提供商", summary: "自定义 OpenAI 或 Anthropic 兼容服务。", auth_mode: "key", model_listing: true, enabled: true, models: [{ id: "model", name: "新模型", group: "默认模型", context_window: "", capabilities: ["reasoning"] }] };
    state.settings.providers.push(provider);
    state.selectedProviderId = provider.id;
    state.editingModelIndex = 0;
    renderSettings();
    return;
  }
  if (action === "add-provider-preset") {
    collectProviderForm();
    const preset = (state.presets?.providers || []).find((item) => item.id === element.dataset.presetId);
    if (!preset) return;
    const existing = state.settings.providers.find((item) => item.id === preset.id);
    if (existing) {
      state.selectedProviderId = existing.id;
      renderSettings();
      toast(`${existing.name} 已在列表中`);
      return;
    }
    state.settings.providers.push(structuredClone(preset));
    state.selectedProviderId = preset.id;
    renderSettings();
    return;
  }
  if (action === "remove-provider") {
    if (state.settings.providers.length < 2) return;
    const provider = selectedProvider();
    state.settings.providers = state.settings.providers.filter((item) => item.id !== provider.id);
    state.selectedProviderId = state.settings.providers[0].id;
    ensureActiveModel();
    await persistSettings("提供商已移除");
    return;
  }
  if (action === "remove-provider-key") {
    const provider = selectedProvider();
    if (!provider || provider.kind === "local") return;
    provider.enabled = false;
    await persistSettings("已移除提供商密钥");
    state.settings = await request(`/api/settings/providers/${encodeURIComponent(provider.id)}/api-key`, { method: "POST", body: JSON.stringify({ api_key: "" }) });
    renderModelSelectors();
    renderSettings();
    return;
  }
  if (action === "toggle-provider-key") {
    const provider = selectedProvider();
    const input = byId("modelProviderForm")?.elements["provider-api-key"];
    if (!provider || !input) return;
    if (input.type === "text") {
      input.type = "password";
      element.innerHTML = uiIcon("eye");
      element.setAttribute("aria-label", "显示 API 密钥");
      element.setAttribute("title", "显示密钥");
      element.setAttribute("aria-pressed", "false");
      return;
    }
    if (!input.value && provider.api_key_configured) {
      element.disabled = true;
      element.classList.add("is-loading");
      try {
        const result = await request(`/api/settings/providers/${encodeURIComponent(provider.id)}/api-key/reveal`, {
          method: "POST",
          body: JSON.stringify({ reveal: true }),
        });
        input.value = String(result.api_key || "");
      } finally {
        element.disabled = false;
        element.classList.remove("is-loading");
      }
    }
    if (!input.value) {
      input.focus();
      return;
    }
    input.type = "text";
    element.innerHTML = uiIcon("eye-off");
    element.setAttribute("aria-label", "隐藏 API 密钥");
    element.setAttribute("title", "隐藏密钥");
    element.setAttribute("aria-pressed", "true");
    input.focus({ preventScroll: true });
    input.setSelectionRange(input.value.length, input.value.length);
    return;
  }
  if (action === "add-model") {
    const provider = collectProviderForm();
    provider.models.push({ id: `model-${provider.models.length + 1}`, name: "新模型", group: "默认模型", context_window: "", capabilities: ["reasoning"] });
    state.editingModelIndex = provider.models.length - 1;
    renderSettings();
    return;
  }
  if (action === "edit-model") {
    collectProviderForm();
    state.editingModelIndex = Number(element.dataset.modelIndex);
    renderSettings();
    return;
  }
  if (action === "close-model-editor" || action === "save-model-editor") {
    collectProviderForm();
    state.editingModelIndex = -1;
    renderSettings();
    return;
  }
  if (action === "toggle-model-capability") {
    const provider = collectProviderForm();
    const model = provider?.models?.[Number(element.dataset.modelIndex)];
    const capability = String(element.dataset.capability || "");
    if (!model || !modelCapabilityDefinitions.some(([id]) => id === capability)) return;
    const selected = new Set(Array.isArray(model.capabilities) ? model.capabilities : []);
    if (selected.has(capability)) selected.delete(capability);
    else selected.add(capability);
    model.capabilities = [...selected];
    renderSettings();
    return;
  }
  if (action === "fetch-provider-models") {
    const form = byId("modelProviderForm");
    const provider = collectProviderForm();
    if (!provider || provider.kind === "local") return;
    const apiKey = String(form?.elements["provider-api-key"]?.value || "").trim();
    if (apiKey) provider.enabled = true;
    await persistSettings(apiKey ? "连接信息已保存，正在读取模型列表…" : "连接信息已保存，正在读取模型列表…");
    if (apiKey) {
      state.settings = await request(`/api/settings/providers/${encodeURIComponent(provider.id)}/api-key`, { method: "POST", body: JSON.stringify({ api_key: apiKey }) });
    }
    const result = await request(`/api/settings/providers/${encodeURIComponent(provider.id)}/models`, { method: "POST", body: "{}" });
    const saved = state.settings.providers.find((item) => item.id === provider.id);
    if (!saved) return;
    const previous = new Map((saved.models || []).map((item) => [item.id, item]));
    const fetched = Array.isArray(result.models) ? result.models : [];
    if (fetched.length) {
      saved.models = fetched.map((item) => ({ ...previous.get(item.id), ...item }));
      await persistSettings(`已同步 ${fetched.length} 个模型`);
    } else {
      renderSettings();
      toast("服务商没有返回可用模型；可手动添加模型 ID");
    }
    return;
  }
  if (action === "remove-model") {
    const provider = collectProviderForm();
    if (provider.models.length < 2) return;
    provider.models.splice(Number(element.dataset.modelIndex), 1);
    state.editingModelIndex = -1;
    ensureActiveModel();
    renderSettings();
    return;
  }
  if (action === "test-provider") {
    const provider = collectProviderForm();
    await persistSettings("正在测试连接…");
    const result = await request(`/api/settings/providers/${encodeURIComponent(provider.id)}/test`, { method: "POST", body: "{}" });
    toast(`${result.provider || provider.name}：${result.message || "连接正常"}`);
    return;
  }
  if (action === "add-local-preset") {
    collectLocalModelsForm();
    const preset = (state.presets?.local_models || []).find((item) => item.id === element.dataset.presetId);
    if (!preset) return;
    const existing = state.settings.local_models.find((item) => item.id === preset.id);
    if (existing) {
      renderSettings();
      toast(`${existing.name} 已在列表中`);
      return;
    }
    state.settings.local_models.push(structuredClone(preset));
    renderSettings();
    return;
  }
  if (action === "remove-local-model") {
    collectLocalModelsForm();
    state.settings.local_models.splice(Number(element.dataset.localIndex), 1);
    renderSettings();
    return;
  }
  if (action === "test-local-model") {
    collectLocalModelsForm();
    await persistSettings("正在测试本地运行时…");
    const result = await request(`/api/settings/local-models/${encodeURIComponent(element.dataset.localId)}/test`, { method: "POST", body: "{}" });
    toast(`${result.runtime || "本地模型"}：${result.message || "连接正常"}`);
    return;
  }
  if (action === "refresh-local-model-market") {
    refreshLocalModelMarket().catch((error) => toast(error.message, true));
    return;
  }
  if (action === "open-local-runtime-setup") {
    state.activeSettings = "local-models";
    renderSettings();
    document.querySelector(".local-runtime-disclosure")?.setAttribute("open", "");
    return;
  }
  if (action === "install-local-runtime") {
    element.disabled = true;
    element.textContent = "正在准备…";
    request("/api/local-runtime/install", { method: "POST", body: "{}" })
      .then((job) => {
        state.localRuntime = { ...(state.localRuntime || {}), install_job: job };
        scheduleLocalRuntimeInstallPoll();
        if (state.activeView === "settings") renderSettings();
        renderDownloadActivity();
        toast("本地运行组件已开始下载；右上角可持续查看进度。");
      })
      .catch((error) => toast(error.message, true))
      .finally(() => { if (element.isConnected) element.disabled = false; });
    return;
  }
  if (action === "save-local-model-roles") {
    collectModelRoleForm();
    await persistSettings("资料库默认嵌入与重排模型已保存");
    return;
  }
  if (action === "download-local-model") {
    const repoId = element.dataset.modelRepo || "";
    if (!repoId) return;
    element.disabled = true;
    element.textContent = "准备下载…";
    request("/api/local-models/download", { method: "POST", body: JSON.stringify({ id: repoId }) })
      .then((job) => {
        mergeLocalModelInstall(job);
        scheduleLocalModelInstallPoll();
        if (state.activeView === "settings" && state.activeSettings === "local-models") renderSettings();
        renderDownloadActivity();
        toast(`${repoId} 已开始下载；右上角可持续查看进度。`);
      })
      .catch((error) => toast(error.message, true))
      .finally(() => { if (element.isConnected) element.disabled = false; });
    return;
  }
  if (action === "install-retrieval-models") {
    startOnboardingResource("retrieval").catch((error) => toast(error.message, true));
    return;
  }
  if (action === "remove-record") {
    const kind = element.dataset.recordKind;
    const key = kind === "mcp" ? "mcp_servers" : kind;
    state.settings[key] = state.settings[key].filter((record) => record.id !== element.dataset.recordId);
    await persistSettings("配置已移除");
  }
  if (action === "remove-plugin-record") {
    state.settings.plugins = state.settings.plugins.filter((plugin) => plugin.id !== element.dataset.pluginId);
    await persistSettings("插件记录已移除");
  }
}

function switchReviewDocumentTab(tabName) {
  const safeTab = tabName === "source" ? "source" : "preview";
  byId("reviewDocumentPanel")?.querySelectorAll("[data-review-tab]").forEach((button) => button.classList.toggle("is-active", button.dataset.reviewTab === safeTab));
  byId("reviewDocumentPanel")?.querySelectorAll("[data-review-view]").forEach((view) => view.classList.toggle("is-active", view.dataset.reviewView === safeTab));
}

function showReviewCitation(citationId) {
  const citation = state.reviewDocument?.citations?.find((item) => String(item.citation_id) === String(citationId));
  const drawer = byId("reviewEvidenceDrawer");
  if (!citation || !drawer) return;
  const sourceMeta = [citation.section, citation.doi, citation.evidence_id].filter(Boolean).join(" · ");
  const readerButton = safeReaderUrl(citation) ? `<button type="button" data-action="open-review-evidence-reader" data-citation-id="${escapeHtml(citation.citation_id)}">在应用中定位原文</button>` : "";
  const externalUrl = safeEvidenceSourceUrl(citation.original_url);
  const externalButton = externalUrl ? `<a class="review-evidence-link" href="${escapeHtml(externalUrl)}" target="_blank" rel="noopener noreferrer">打开公开来源 ${uiIcon("arrow-up-right")}</a>` : "";
  drawer.innerHTML = `<div class="review-evidence-head"><div><span>Evidence ${escapeHtml(citation.citation_id)}</span><strong>${escapeHtml(citation.paper)}</strong></div><button type="button" class="review-icon-button" data-action="close-review-evidence" aria-label="关闭证据">×</button></div><div class="review-evidence-body"><small>${escapeHtml(sourceMeta)}</small><blockquote>${escapeHtml(compact(citation.exact_quote || "当前引用没有保存原文摘录。", 900))}</blockquote>${readerButton}${externalButton}</div>`;
  hydrateIcons(drawer);
  drawer.classList.add("is-open");
}

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (!value) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("无法复制这条消息。");
}

async function copyConversationMessage(button) {
  await copyTextToClipboard(button?.dataset.copyText || "");
  button?.classList.add("is-copied");
  button?.setAttribute("aria-label", "已复制");
  toast("消息已复制");
  window.setTimeout(() => {
    button?.classList.remove("is-copied");
    button?.setAttribute("aria-label", "复制消息");
  }, 1200);
}

async function copyReviewDocument() {
  if (!state.reviewDocument?.markdown) return;
  await copyTextToClipboard(state.reviewDocument.markdown);
  toast("综述 Markdown 已复制");
}

function downloadReviewDocument() {
  if (!state.reviewDocument?.markdown) return;
  const blob = new Blob([state.reviewDocument.markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${state.reviewDocument.title.replace(/[\\/:*?"<>|]+/g, "-").slice(0, 64) || "ScanSci-综述"}.md`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function saveReviewAsNote() {
  if (!state.reviewDocument?.markdown) throw new Error("当前没有可保存的证据综述稿件。");
  const notebookId = state.notebook?.notebook_id;
  if (!notebookId) throw new Error("请先选择一个知识库。");
  const result = await request(`/api/notebooks/${encodeURIComponent(notebookId)}/notes`, {
    method: "POST",
    body: JSON.stringify({
      title: state.reviewDocument.title || "证据综述",
      body: state.reviewDocument.markdown,
      note_type: "literature_review",
    }),
  });
  if (result.notebook) state.notebook = result.notebook;
  state.workspace = await request("/api/workspace");
  state.notebook = (state.workspace.notebooks || []).find((item) => item.notebook_id === notebookId) || state.notebook;
  toast("综述已保存到当前知识库笔记");
}

document.addEventListener("click", (event) => {
  if (state.updateCardOpen && !event.target.closest("[data-app-update]")) toggleAppUpdateCard(false);
  if (!event.target.closest("[data-mode-picker]")) closeComposerModePickers();
  if (!event.target.closest("[data-composer-model]")) closeComposerModelPickers();
  if (!event.target.closest("[data-composer-thinking]")) closeComposerThinkingPickers();
  if (!event.target.closest("[data-context-usage]")) closeContextUsagePopovers();
  if (!event.target.closest("[data-web-search-picker]")) closeWebSearchPickers();
  if (!event.target.closest("[data-attachment-picker]")) closeAttachmentMenus();
  if (!event.target.closest("[data-profile-picker]")) closeProfileAvatarPicker();
  if (!event.target.closest(".task-row") && state.historyMenuRunId) {
    state.historyMenuRunId = "";
    renderTasks();
  }
  if (!event.target.closest(".skill-suggestions, #homeQuestionInput, #chatQuestionInput")) closeSkillSuggestions();
  const extensionTab = event.target.closest("[data-extension-tab]");
  if (extensionTab) {
    state.activeExtensions = extensionTab.dataset.extensionTab || "skills";
    if (state.activeView === "extensions") {
      renderExtensions();
      recordNavigation();
      if (state.activeExtensions === "market") refreshExtensions({ marketOnly: true, quiet: true }).catch((error) => toast(error.message, true));
    }
    return;
  }
  const settingsNav = event.target.closest("[data-settings-panel]");
  if (settingsNav && !settingsNav.dataset.action) {
    state.activeSettings = settingsNav.dataset.settingsPanel;
    if (state.activeView === "settings") {
      renderSettings();
      recordNavigation();
      if (state.activeSettings === "mcp") loadMcpMarketplace().catch((error) => toast(error.message, true));
    }
    return;
  }
  const element = event.target.closest("[data-action]");
  if (!element) return;
  const action = element.dataset.action;
  if (action === "confirm-dialog-content") return;
  if (action === "cancel-confirm-dialog") settleConfirmation(false);
  else if (action === "accept-confirm-dialog") settleConfirmation(true);
  else if (action === "jump-conversation-latest") followLatestConversationMessage({ smooth: true });
  else if (action === "minimize-window") controlDesktopWindow("minimize_window").catch((error) => toast(error.message, true));
  else if (action === "toggle-maximize-window") controlDesktopWindow("toggle_maximize_window").catch((error) => toast(error.message, true));
  else if (action === "close-window") controlDesktopWindow("close_window").catch((error) => toast(error.message, true));
  else if (action === "toggle-app-update") toggleAppUpdateCard();
  else if (action === "close-app-update") toggleAppUpdateCard(false);
  else if (action === "check-app-update") refreshAppUpdate().catch((error) => toast(error.message, true));
  else if (action === "install-app-update") installAppUpdate().catch((error) => toast(error.message, true));
  else if (action === "open-download-center") openSettings("resources");
  else if (action === "toggle-attachment-menu") {
    event.preventDefault();
    toggleAttachmentMenu(element);
  }
  else if (action === "choose-composer-image") {
    const key = element.dataset.composerKey === "home" ? "home" : "chat";
    byId(`${key}ImageFileInput`)?.click();
  }
  else if (action === "choose-composer-source") chooseComposerSources(element.dataset.composerKey === "home" ? "home" : "chat").catch((error) => toast(error.message, true));
  else if (action === "choose-presentation-sources") choosePresentationSources(element.dataset.composerKey === "home" ? "home" : "chat").catch((error) => toast(error.message, true));
  else if (action === "remove-composer-image") removeComposerImage(element.dataset.composerKey === "home" ? "home" : "chat", element.dataset.imageId || "");
  else if (action === "remove-composer-source") removeComposerSource(element.dataset.composerKey === "home" ? "home" : "chat", element.dataset.sourceId || "");
  else if (action === "use-file-suggestion") useFileSuggestion(element.dataset.composerKey === "home" ? "home" : "chat", element.dataset.fileName || "当前文件", element.dataset.suggestion || "总结");
  else if (action === "open-ingestion-source") {
    const url = element.dataset.sourceUrl || "";
    const name = element.dataset.sourceName || "附件";
    if (name.toLowerCase().endsWith(".pdf") && window.ScanSciPdfViewer) window.ScanSciPdfViewer.open(url, name);
    else window.open(url, "_blank", "noopener,noreferrer");
  }
  else if (action === "choose-library-folder") chooseLibraryFolder("folder", element.dataset.notebookId || "").catch((error) => toast(error.message, true));
  else if (action === "choose-obsidian-vault") chooseLibraryFolder("obsidian", element.dataset.notebookId || "").catch((error) => toast(error.message, true));
  else if (action === "choose-zotero-library") connectLocalZotero(element.dataset.notebookId || "").catch((error) => toast(error.message, true));
  else if (action === "connect-notion") connectNotion(element.dataset.notebookId || "").catch((error) => toast(error.message, true));
  else if (action === "choose-library-files") chooseLibraryFiles(element.dataset.notebookId || state.notebook?.notebook_id || "").catch((error) => toast(error.message, true));
  else if (action === "retry-evidence-index") {
    const notebookId = element.dataset.notebookId || state.notebook?.notebook_id || "";
    state.knowledgeIndexStatuses[notebookId] = {
      ...(state.knowledgeIndexStatuses[notebookId] || {}),
      state: "indexing",
      error: "",
    };
    syncKnowledgeIndexBadge(notebookId);
    ensureActiveKnowledgeIndex(notebookId).catch((error) => toast(error.message, true));
  }
  else if (action === "refresh-evidence-index") refreshKnowledgeIndexStatus(element.dataset.notebookId || "").catch(() => {});
  else if (action === "refresh-knowledge-scope-counts") refreshKnowledgeScopeCounts();
  else if (action === "create-empty-library") {
    closeKnowledgeScopeDialog();
    openLibraryPathDialog("empty");
  }
  else if (action === "delete-personal-library") deletePersonalLibrary(element.dataset.notebookId || "").catch((error) => toast(error.message, true));
  else if (action === "focus-knowledge-file-search") focusKnowledgeFileSearch();
  else if (action === "close-knowledge-file-search") closeKnowledgeFileSearch();
  else if (action === "open-knowledge-scope") openKnowledgeScopeDialog();
  else if (action === "close-knowledge-scope") closeKnowledgeScopeDialog();
  else if (action === "clear-knowledge-scope") {
    setKnowledgeScope(null, { close: false });
    toast("已移除本轮知识库范围");
  }
  else if (action === "remove-knowledge-scope") {
    removeKnowledgeScope(element.dataset.notebookId || "");
  }
  else if (action === "toggle-notebook-scope") {
    const notebook = (state.workspace?.notebooks || []).find((item) => item.notebook_id === element.dataset.notebookId);
    if (notebook) setKnowledgeScope(notebook, { close: false, toggle: true });
  }
  else if (action === "select-notebook") {
    const notebook = (state.workspace?.notebooks || []).find((item) => item.notebook_id === element.dataset.notebookId);
    if (notebook) {
      if (!notebookHasSearchableContent(notebook)) {
        const connectAction = unavailableKnowledgeAction(notebook);
        if (connectAction === "choose-zotero-library") connectLocalZotero(notebook.notebook_id).catch((error) => toast(error.message, true));
        else if (connectAction === "choose-obsidian-vault") chooseLibraryFolder("obsidian", notebook.notebook_id).catch((error) => toast(error.message, true));
        else if (connectAction === "connect-notion") connectNotion(notebook.notebook_id).catch((error) => toast(error.message, true));
        else chooseLibraryFiles(notebook.notebook_id).catch((error) => toast(error.message, true));
        return;
      }
      setKnowledgeScope(notebook, { close: false });
      toast(`已引用 ${notebook.title || pathLeaf(notebook.root_path)}`);
    }
  }
  else if (action === "select-zotero-collection") {
    const notebook = (state.workspace?.notebooks || []).find((item) => item.notebook_id === element.dataset.notebookId);
    if (notebook) {
      setZoteroCollectionScope(notebook, element.dataset.collectionKey || "", element.dataset.collectionName || "Collection");
      toast(`本轮将使用 Zotero / ${element.dataset.collectionName || "Collection"}`);
    }
  }
  else if (action === "activate-library") {
    const notebook = (state.workspace?.notebooks || []).find((item) => item.notebook_id === element.dataset.notebookId);
    if (notebook) {
      state.notebook = notebook;
      state.knowledgePreviewSourceId = "";
      state.knowledgeQuery = "";
      state.knowledgeVisibleLimit = 200;
      window.localStorage.setItem("scansci.knowledge.scope", notebook.notebook_id);
      renderMode();
      void ensureActiveKnowledgeIndex();
    }
  }
  else if (action === "load-more-knowledge-items") {
    state.knowledgeVisibleLimit = Math.max(200, Number(state.knowledgeVisibleLimit) || 200) + 200;
    renderMode();
  }
  else if (action === "toggle-knowledge-folders") {
    state.knowledgeTreeExpanded = state.knowledgeTreeExpanded === false;
    window.localStorage.setItem("scansci.knowledge.tree.expanded", String(state.knowledgeTreeExpanded));
    renderMode();
  }
  else if (action === "preview-knowledge-source") {
    event.preventDefault();
    state.knowledgePreviewSourceId = element.dataset.sourceId || "";
    renderMode();
  }
  else if (action === "toggle-active-library-scope") {
    if (state.notebook && notebookHasSearchableContent(state.notebook)) setKnowledgeScope(state.notebook, { close: false, toggle: true });
  }
  else if (action === "use-knowledge-suggestion") {
    if (state.notebook && !(state.knowledgeScopeIds || []).includes(state.notebook.notebook_id)) {
      setKnowledgeScope(state.notebook, { close: false });
    }
    setView("home");
    const input = byId("homeQuestionInput");
    if (input) {
      input.value = element.dataset.prompt || "";
      input.focus();
    }
  }
  else if (action === "export-pptxgenjs") exportActiveSlidePlan(element).catch((error) => toast(error.message, true));
  else if (action === "save-presentation") savePresentationToDevice(element.dataset.presentationPath, element.dataset.presentationName).then((result) => { if (!result?.cancelled) toast(`已保存 ${result.path || element.dataset.presentationName}`); }).catch((error) => toast(error.message, true));
  else if (action === "close-library-dialog") closeLibraryPathDialog();
  else if (action === "close-academic-search-plan") closeAcademicSearchPlanDialog();
  else if (action === "open-slide-templates") openSlideTemplateDialog();
  else if (action === "close-slide-templates") closeSlideTemplateDialog();
  else if (action === "preview-slide-template") {
    state.previewSlideTemplateId = element.dataset.templateId || state.previewSlideTemplateId;
    state.previewSlidePage = "";
    renderSlideTemplateBrowser();
  }
  else if (action === "preview-slide-page") {
    state.previewSlidePage = element.dataset.templatePage || "";
    renderSlideTemplateBrowser();
  }
  else if (action === "select-slide-template") selectPreviewedSlideTemplate();
  else if (action === "select-inline-slide-template") {
    event.preventDefault();
    selectSlideTemplate(element.dataset.templateId || "");
  }
  else if (action === "preview-inline-slide-template") {
    event.preventDefault();
    openInlineSlidePreview(element.dataset.templateId || "");
  }
  else if (action === "preview-inline-slide-page") {
    event.preventDefault();
    state.inlineSlidePreviewPage = element.dataset.templatePage || "";
    renderInlineSlidePreview();
  }
  else if (action === "close-inline-slide-preview") closeInlineSlidePreview();
  else if (action === "select-inline-preview-template") selectInlinePreviewedSlideTemplate();
  else if (action === "open-library") {
    closeAttachmentMenus();
    openMode("library");
  }
  else if (action === "toggle-composer-mode") {
    event.preventDefault();
    toggleComposerModePicker(element);
  }
  else if (action === "toggle-web-search") {
    event.preventDefault();
    toggleWebSearchPicker(element);
  }
  else if (action === "select-web-search") {
    event.preventDefault();
    setWebSearchMode(element.dataset.webSearchValue || "auto");
    closeWebSearchPickers();
    element.closest("[data-web-search-picker]")?.querySelector("[data-action='toggle-web-search']")?.focus();
  }
  else if (action === "select-composer-mode") {
    event.preventDefault();
    const requestedMode = element.dataset.modeValue || "general";
    const currentMode = byId("homeModeSelect")?.value || "general";
    // The home shortcuts are toggle buttons. Clicking the selected
    // shortcut again returns to the clean general/automatic state.
    const nextMode = requestedMode !== "general" && requestedMode === currentMode ? "general" : requestedMode;
    setComposerMode(nextMode);
    closeComposerModePickers();
    element.focus();
  }
  else if (action === "apply-mode-tool") {
    event.preventDefault();
    const mode = byId("homeModeSelect")?.value || "general";
    const tool = modeWorkbenchContent[mode]?.tools.find((item) => item.id === element.dataset.modeTool);
    if (!tool) return;
    if (mode === "knowledge" && tool.evidenceOutput) {
      setEvidenceOutputMode(tool.evidenceOutput);
      byId("homeQuestionInput")?.focus();
      return;
    }
    if (["research", "academic"].includes(mode) && tool.workflow) {
      const fallbackWorkflow = mode === "academic" ? "academic" : "";
      state.researchWorkflow = state.researchWorkflow === tool.workflow ? fallbackWorkflow : tool.workflow;
      renderHomeModeWorkbench(mode);
      renderKnowledgeScopeSurfaces();
    }
    if (tool.action === "upload") byId("homeSourceFileInput")?.click();
    else if (tool.action === "template") openSlideTemplateDialog();
    else homePromptFromWorkbench(tool.prompt);
  }
  else if (action === "apply-mode-example") {
    event.preventDefault();
    const mode = byId("homeModeSelect")?.value || "general";
    const example = currentModeWorkbenchContent(mode)?.examples.find((item) => item.id === element.dataset.modeExample);
    if (example) {
      if (["research", "academic"].includes(mode) && example.workflow) {
        state.researchWorkflow = example.workflow;
        renderHomeModeWorkbench(mode);
        renderKnowledgeScopeSurfaces();
      }
      homePromptFromWorkbench(example.prompt, `已填入“${example.title}”案例`);
    }
  }
  else if (action === "pick-home-batch-file") {
    event.preventDefault();
    byId("homePaperBatchFile")?.click();
  }
  else if (action === "clear-home-batch") {
    event.preventDefault();
    state.pendingBatchIdentifiers = [];
    state.pendingBatchFilename = "";
    renderHomeModeWorkbench("download");
  }
  else if (action === "start-home-batch-download") {
    event.preventDefault();
    if (!state.pendingBatchIdentifiers.length) return;
    const input = byId("homeQuestionInput");
    if (input) input.value = state.pendingBatchIdentifiers.join("\n");
    byId("homeAskForm")?.requestSubmit();
  }
  else if (action === "apply-download-guide") {
    event.preventDefault();
    const guide = modeWorkbenchContent.download.guides.find((item) => item.id === element.dataset.downloadGuide);
    if (guide?.prompt) {
      state.pendingBatchIdentifiers = [];
      state.pendingBatchFilename = "";
      renderHomeModeWorkbench("download");
      homePromptFromWorkbench(guide.prompt, `已填入“${guide.title}”`);
    }
  }
  else if (action === "prepare-idea-novelty") {
    event.preventDefault();
    state.researchWorkflow = "novelty";
    setComposerMode("research", { preserveResearchWorkflow: true });
    const input = byId("chatQuestionInput") || byId("homeQuestionInput");
    if (input) {
      input.value = `问题：${element.dataset.noveltyProblem || ""}\n\n新颖性：${element.dataset.noveltyClaim || ""}`;
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
    toast("已带入证据查新；确认问题与创新主张后即可运行。");
  }
  else if (action === "toggle-composer-model") {
    event.preventDefault();
    toggleComposerModelPicker(element);
  }
  else if (action === "toggle-context-usage") {
    event.preventDefault();
    toggleContextUsagePopover(element);
  }
  else if (action === "select-composer-model") {
    event.preventDefault();
    setActiveComposerModel(element.dataset.modelValue || "").catch((error) => toast(error.message, true));
  }
  else if (action === "toggle-composer-thinking") {
    event.preventDefault();
    toggleComposerThinkingPicker(element);
  }
  else if (action === "select-composer-thinking") {
    event.preventDefault();
    setComposerThinkingLevel(element.dataset.thinkingValue || "auto");
  }
  else if (action === "select-skill-suggestion") {
    event.preventDefault();
    selectSkillSuggestion(byId(element.dataset.inputId || ""), element.dataset.skillId || "");
  }
  else if (action === "review-document-tab") switchReviewDocumentTab(element.dataset.reviewTab || "preview");
  else if (action === "scroll-review-section") {
    switchReviewDocumentTab("preview");
    byId(element.dataset.sectionId || "review-abstract")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  else if (action === "open-review-citation") showReviewCitation(element.dataset.citationId || "");
  else if (action === "close-review-evidence") byId("reviewEvidenceDrawer")?.classList.remove("is-open");
  else if (action === "open-review-evidence-reader") {
    const citation = state.reviewDocument?.citations?.find((item) => String(item.citation_id) === String(element.dataset.citationId));
    if (citation) showEvidenceReader(citation, { returnPanel: "review" });
  }
  else if (action === "close-evidence-reader") closeEvidenceReader();
  else if (action === "show-evidence-blocks") {
    const frame = byId("evidenceReaderFrame");
    if (frame && state.activeEvidence?.reader_url) frame.src = evidenceReaderFrameUrl(state.activeEvidence.reader_url);
    element.parentElement?.querySelectorAll("button").forEach((button) => button.classList.toggle("is-active", button === element));
  }
  else if (action === "show-evidence-original") {
    const frame = byId("evidenceReaderFrame");
    if (frame && element.dataset.originalUrl) frame.src = element.dataset.originalUrl;
    element.parentElement?.querySelectorAll("button").forEach((button) => button.classList.toggle("is-active", button === element));
  }
  else if (action === "toggle-profile-avatar") {
    event.preventDefault();
    toggleProfileAvatarPicker(element);
  }
  else if (action === "select-profile-avatar") selectProfileAvatar(element.dataset.avatarValue || "male");
  else if (action === "open-source-reader") {
    const source = (state.notebook?.sources || []).find((item) => String(item.doc_id) === String(element.dataset.docId));
    if (source) openSourceReader(source);
  }
  else if (action === "copy-conversation-message") copyConversationMessage(element).catch((error) => toast(error.message, true));
  else if (action === "copy-review-document") copyReviewDocument().catch((error) => toast(error.message, true));
  else if (action === "save-review-note") saveReviewAsNote().catch((error) => toast(error.message, true));
  else if (action === "download-review-document") downloadReviewDocument();
  else if (action === "select-all-review-sources") setReviewSourceSelection(true);
  else if (action === "clear-review-sources") setReviewSourceSelection(false);
  else if (action === "refresh-review-document") {
    if (state.activeTaskId) openTask(state.activeTaskId, { record: false });
  }
  else if (action === "toggle-review-focus") {
    const focused = byId("conversationLayout")?.classList.toggle("is-review-focus");
    element.textContent = focused ? "↙" : "↗";
    element.setAttribute("aria-label", focused ? "退出专注阅读" : "专注阅读");
  }
  else if (action === "close-review-document") applyContextPanelPreset("evidence");
  else if (action === "open-review-document") applyContextPanelPreset("review");
  else if (action === "toggle-evidence-panel-expand") toggleEvidencePanelExpanded();
  else if (action === "toggle-context-panel") toggleContextPanel();
  else if (action === "toggle-sidebar") toggleSidebar();
  else if (action === "history-back") moveNavigation(-1);
  else if (action === "history-forward") moveNavigation(1);
  else if (action === "toggle-history-collapse") toggleHistoryCollapse();
  else if (action === "toggle-history-search") toggleHistorySearch();
  else if (action === "toggle-history-view") toggleHistoryView();
  else if (action === "toggle-task-menu") toggleTaskMenu(element.dataset.taskId || "");
  else if (action === "archive-task") archiveTask(element.dataset.taskId || "").catch((error) => toast(error.message, true));
  else if (action === "restore-task") restoreTask(element.dataset.taskId || "").catch((error) => toast(error.message, true));
  else if (action === "delete-task") deleteTask(element.dataset.taskId || "").catch((error) => toast(error.message, true));
  else if (action === "new-task") startTask();
  else if (action === "open-extensions") openExtensions();
  else if (action === "open-mcp-marketplace") openMcpMarketplace();
  else if (action === "test-mcp-server") testMcpServer(element.dataset.recordId || "").catch((error) => toast(error.message, true));
  else if (action === "refresh-marketplace") refreshExtensions({ marketOnly: true }).catch((error) => toast(error.message, true));
  else if (action === "install-market-skill") installMarketSkill(element.dataset.marketSkillId || "").catch((error) => toast(error.message, true));
  else if (action === "open-extension-detail") {
    state.extensionDetail = { kind: element.dataset.extensionKind, id: element.dataset.extensionId };
    renderExtensions();
  }
  else if (action === "close-extension-detail") {
    state.extensionDetail = null;
    renderExtensions();
  }
  else if (action === "extension-detail-content") {
    return;
  }
  else if (action === "uninstall-extension") {
    const key = element.dataset.extensionKind === "skills" ? "skills" : "plugins";
    const record = state.settings[key]?.find((row) => row.id === element.dataset.extensionId);
    if (record) {
      record.enabled = false;
      record.uninstalled = true;
      if (key === "skills") state.extensions.skills = (state.extensions.skills || []).filter((row) => row.id !== record.id);
      state.extensionDetail = null;
      persistSettings("已从当前工作区卸载").catch((error) => toast(error.message, true));
    }
  }
  else if (action === "toggle-download-strategy") {
    state.downloadStrategyOpen = !state.downloadStrategyOpen;
    renderMode();
  }
  else if (action === "select-download-strategy") {
    const strategy = element.dataset.downloadStrategy || "oa_first";
    if (["oa_first", "gray_oa", "legal_only"].includes(strategy)) {
      state.downloadStrategy = strategy;
      state.downloadStrategyOpen = false;
      window.localStorage.setItem("scansci.download.strategy", strategy);
      renderMode();
    }
  }
  else if (action === "clear-batch-identifiers") {
    state.pendingBatchIdentifiers = [];
    renderMode();
  }
  else if (action === "toggle-use-tor") {
    state.useTor = element.checked;
    renderMode();
  }
  else if (action === "toggle-tor-transport") {
    state.torTransportOpen = !state.torTransportOpen;
    renderMode();
  }
  else if (action === "select-tor-transport") {
    const transport = element.dataset.torTransport;
    if (["snowflake", "obfs4", "none"].includes(transport)) {
      state.torTransport = transport;
      state.torTransportOpen = false;
      renderMode();
    }
  }
  else if (action === "set-tor-rotate") {
    const value = Number(element.value);
    if (value >= 1 && value <= 20) {
      state.torRotateEvery = value;
    }
  }
  else if (action === "start-batch-download") {
    handlePaperBatchDownload().catch((error) => showModeError(error));
  }
  else if (action === "retry-batch-download") {
    const identifiers = String(element.dataset.identifiers || "")
      .split(/\r?\n|,/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!identifiers.length) return;
    handlePaperBatchDownload(identifiers).catch((error) => showModeError(error));
  }
  else if (action === "toggle-knowledge-preview") {
    state.knowledgePreviewCollapsed = !state.knowledgePreviewCollapsed;
    window.localStorage.setItem("scansci.knowledge.previewCollapsed", state.knowledgePreviewCollapsed ? "1" : "0");
    renderMode();
  }
  else if (action === "open-mode") openMode(element.dataset.mode || "tools");
  else if (action === "open-external") {
    const url = element.dataset.url || "";
    if (url.startsWith("/") || /^https?:\/\//i.test(url)) window.open(url, "_blank", "noopener");
  }
  else if (action === "open-local-path") {
    openLocalArtifact(element.dataset.localPath || "").catch((error) => toast(error.message, true));
  }
  else if (action === "reveal-local-path") {
    openLocalArtifact(element.dataset.localPath || "", { reveal: true }).catch((error) => toast(error.message, true));
  }
  else if (action === "create-ppt-project") createPptProject().catch((error) => toast(error.message, true));
  else if (action === "cancel-run") cancelRun(element.dataset.runId).catch((error) => toast(error.message, true));
  else if (action === "resume-run") resumeRun(element.dataset.runId).catch((error) => toast(error.message, true));
  else if (action === "respond-agent-interaction") respondAgentInteraction(element).catch((error) => toast(error.message, true));
  else if (action === "respond-run-interaction") respondRunInteraction(element).catch((error) => toast(error.message, true));
  else if (action === "recover-run") recoverRun(element).catch((error) => toast(error.message, true));
  else if (action === "advisor-action") advisorAction(element).catch((error) => toast(error.message, true));
  else if (action === "branch-run") branchRun(element).catch((error) => toast(error.message, true));
  else if (action === "compact-session") compactSession().catch((error) => toast(error.message, true));
  else if (action === "quick-search") {
    setView("conversation");
    window.setTimeout(() => byId("sourceFilter").focus(), 0);
  } else if (action === "open-settings") openSettings(element.dataset.settingsPanel || "general");
  else if (action === "sync-mcp-marketplace") syncMcpMarketplace().catch((error) => toast(error.message, true));
  else if (action === "install-mcp-marketplace") installMcpMarketplaceServer(element.dataset.mcpId || "").catch((error) => toast(error.message, true));
  else if (action === "mcp-set-tab") {
    state.mcpMarketplaceTab = element.dataset.mcpTab === "mine" ? "mine" : "public";
    state.mcpManualOpen = false;
    state.mcpCreateMode = "";
    refreshMcpMarketplaceSurface();
  } else if (action === "mcp-set-sort") {
    state.mcpMarketplaceSort = ["hot", "new", "name"].includes(element.dataset.mcpSort) ? element.dataset.mcpSort : "hot";
    refreshMcpMarketplaceSurface();
  } else if (action === "open-mcp-manual") {
    state.mcpManualOpen = true;
    state.mcpCreateMode = "";
    refreshMcpMarketplaceSurface();
  } else if (action === "mcp-select-create-mode") {
    state.mcpCreateMode = element.dataset.mcpCreateMode === "remote" ? "remote" : "stdio";
    refreshMcpMarketplaceSurface();
    window.setTimeout(() => byId("mcpManualForm")?.elements["mcp-name"]?.focus(), 0);
  } else if (action === "mcp-create-back") {
    state.mcpCreateMode = "";
    refreshMcpMarketplaceSurface();
  } else if (action === "close-mcp-manual") {
    state.mcpManualOpen = false;
    state.mcpCreateMode = "";
    refreshMcpMarketplaceSurface();
  }
  else if (action === "open-conversation") setView("conversation");
  else if (action === "open-task") {
    state.historyMenuRunId = "";
    openTask(element.dataset.taskId);
  }
  else handleSettingsAction(action, element).catch((error) => toast(error.message, true));
});

document.addEventListener("dblclick", (event) => {
  if (!event.target.closest("[data-titlebar-drag]")) return;
  controlDesktopWindow("toggle_maximize_window").catch((error) => toast(error.message, true));
});

document.addEventListener("change", (event) => {
  if (event.target.closest("#generalPreferencesForm")) {
    collectAppearanceForm();
    renderSettings();
    return;
  }
  if (event.target.matches("[data-review-source]")) {
    updateReviewSourceCount();
    return;
  }
  if (event.target.id === "mcpMarketplaceDiscipline") {
    state.mcpMarketplaceDiscipline = event.target.value || "all";
    refreshMcpMarketplaceSurface();
    return;
  }
  if (["homeModeSelect", "chatModeSelect"].includes(event.target.id)) {
    setComposerMode(event.target.value);
    return;
  }
  if (event.target.matches("[data-composer-image-file]")) {
    const key = event.target.dataset.composerImageFile === "home" ? "home" : "chat";
    const files = [...(event.target.files || [])];
    event.target.value = "";
    addComposerImages(key, files).catch((error) => toast(error.message, true));
    return;
  }
  if (event.target.matches("[data-composer-source-file]")) {
    const key = event.target.dataset.composerSourceFile === "home" ? "home" : "chat";
    const files = [...(event.target.files || [])];
    event.target.value = "";
    addComposerSources(key, files).catch((error) => toast(error.message, true));
    return;
  }
  if (event.target.closest("#documentProcessingForm") && ["ocr-provider", "mineru-provider"].includes(event.target.name)) {
    collectDocumentProcessingForm();
    renderSettings();
    return;
  }
  if (event.target.dataset.action === "toggle-record") {
    const kind = event.target.dataset.recordKind;
    const key = kind === "mcp" ? "mcp_servers" : kind;
    const record = state.settings[key].find((item) => item.id === event.target.dataset.recordId);
    if (record) {
      record.enabled = event.target.checked;
      persistSettings("启用状态已保存").catch((error) => toast(error.message, true));
    }
  }
});

function clearProviderDragFeedback() {
  document.querySelectorAll(".cherry-provider-item.is-dragging, .cherry-provider-item.is-drop-target").forEach((item) => {
    item.classList.remove("is-dragging", "is-drop-target");
  });
  state.draggedProviderId = "";
}

document.addEventListener("dragstart", (event) => {
  const row = event.target.closest?.("[data-provider-drag-id]");
  if (!row || state.activeSettings !== "models") return;
  collectProviderForm();
  state.draggedProviderId = row.dataset.providerDragId || "";
  if (!state.draggedProviderId) return;
  row.classList.add("is-dragging");
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", state.draggedProviderId);
  }
});

document.addEventListener("dragover", (event) => {
  const libraryDropzone = event.target.closest?.("[data-library-dropzone]");
  if (libraryDropzone && Array.from(event.dataTransfer?.types || []).includes("Files")) {
    event.preventDefault();
    libraryDropzone.classList.add("is-drag-over");
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    return;
  }
  const row = event.target.closest?.("[data-provider-drag-id]");
  if (!row || !state.draggedProviderId || row.dataset.providerDragId === state.draggedProviderId) return;
  event.preventDefault();
  document.querySelectorAll(".cherry-provider-item.is-drop-target").forEach((item) => item.classList.remove("is-drop-target"));
  row.classList.add("is-drop-target");
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
});

document.addEventListener("dragleave", (event) => {
  const libraryDropzone = event.target.closest?.("[data-library-dropzone]");
  if (libraryDropzone && !libraryDropzone.contains(event.relatedTarget)) libraryDropzone.classList.remove("is-drag-over");
  event.target.closest?.("[data-provider-drag-id]")?.classList.remove("is-drop-target");
});

document.addEventListener("dragend", clearProviderDragFeedback);

document.addEventListener("drop", (event) => {
  const libraryDropzone = event.target.closest?.("[data-library-dropzone]");
  if (libraryDropzone && event.dataTransfer?.files?.length) {
    event.preventDefault();
    libraryDropzone.classList.remove("is-drag-over");
    importLibraryDroppedFiles(event.dataTransfer.files, libraryDropzone.dataset.notebookId || "").catch((error) => toast(error.message, true));
    return;
  }
  const row = event.target.closest?.("[data-provider-drag-id]");
  const sourceId = state.draggedProviderId || event.dataTransfer?.getData("text/plain");
  const targetId = row?.dataset.providerDragId;
  if (!row || !sourceId || !targetId || sourceId === targetId) {
    clearProviderDragFeedback();
    return;
  }
  event.preventDefault();
  const providers = state.settings?.providers || [];
  const cloudProviders = providers.filter((item) => item.kind !== "local");
  const sourceIndex = cloudProviders.findIndex((item) => item.id === sourceId);
  const targetIndex = cloudProviders.findIndex((item) => item.id === targetId);
  if (sourceIndex < 0 || targetIndex < 0) {
    clearProviderDragFeedback();
    return;
  }
  const [moved] = cloudProviders.splice(sourceIndex, 1);
  cloudProviders.splice(targetIndex, 0, moved);
  state.settings.providers = [...cloudProviders, ...providers.filter((item) => item.kind === "local")];
  clearProviderDragFeedback();
  persistSettings("服务商排序已保存").catch((error) => toast(error.message, true));
});

document.addEventListener("keydown", (event) => {
  if (confirmDialogResolve) {
    if (event.key === "Escape") {
      event.preventDefault();
      settleConfirmation(false);
      return;
    }
    if (trapConfirmationFocus(event)) return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f" && state.activeView === "library") {
    event.preventDefault();
    focusKnowledgeFileSearch();
    return;
  }
  const composer = event.target.closest("#homeQuestionInput, #chatQuestionInput, #reviewQuestionInput");
  if (composer && document.querySelector(".skill-suggestions")) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      moveSkillSuggestion(event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      const active = document.querySelector(".skill-suggestion.is-active");
      if (active) {
        event.preventDefault();
        selectSkillSuggestion(composer, active.dataset.skillId || "");
        return;
      }
    }
  }
  if (composer && event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    composer.form?.requestSubmit();
    return;
  }
  if (event.key === "Escape") {
    if (state.activeView === "library" && state.knowledgeSearchOpen && event.target.matches?.("[data-knowledge-file-search]")) {
      event.preventDefault();
      closeKnowledgeFileSearch();
      return;
    }
    if (activeDirectChatController) {
      activeDirectChatController.abort();
      activeDirectChatController = null;
      request("/api/chat/cancel", {
        method: "POST",
        body: JSON.stringify({ run_id: state.activeStreamRunId || "" }),
      }).catch(() => {});
    }
    toggleAppUpdateCard(false);
    closeComposerModePickers();
    closeComposerModelPickers();
    closeAttachmentMenus();
    closeProfileAvatarPicker();
    closeSkillSuggestions();
  }
});

document.addEventListener("input", (event) => {
  if (event.target.matches("[data-knowledge-file-search]")) {
    state.knowledgeQuery = String(event.target.value || "");
    state.knowledgeVisibleLimit = 200;
    const cursor = state.knowledgeQuery.length;
    renderMode();
    window.setTimeout(() => {
      const search = document.querySelector("[data-knowledge-file-search]");
      search?.focus();
      search?.setSelectionRange(cursor, cursor);
    }, 0);
    return;
  }
  if (["homeQuestionInput", "chatQuestionInput"].includes(event.target.id)) {
    renderSkillSuggestions(event.target);
    return;
  }
  if (event.target.id === "historySearch") {
    state.historyQuery = event.target.value;
    renderTasks();
    return;
  }
  if (event.target.id === "extensionsMarketSearch") {
    state.marketplaceQuery = event.target.value;
    renderExtensions();
    window.setTimeout(() => byId("extensionsMarketSearch")?.focus(), 0);
  }
  if (event.target.id === "modelServiceSearch") {
    state.providerQuery = event.target.value;
    renderSettings();
    window.setTimeout(() => byId("modelServiceSearch")?.focus(), 0);
  }
  if (event.target.id === "modelListSearch") {
    state.modelQuery = event.target.value;
    renderSettings();
    window.setTimeout(() => byId("modelListSearch")?.focus(), 0);
  }
  if (event.target.id === "mcpMarketplaceSearch") {
    state.mcpMarketplaceQuery = event.target.value;
    refreshMcpMarketplaceSurface();
    window.setTimeout(() => byId("mcpMarketplaceSearch")?.focus(), 0);
  }
});

// Desktop webviews and IME paths do not always dispatch a bubbling `input`
// event for every keystroke.  Keep Skill mention suggestions in sync with
// keyboard input as well, while preserving the input handler above for paste
// and programmatic text-entry paths.
document.addEventListener("keyup", (event) => {
  if (
    ["homeQuestionInput", "chatQuestionInput"].includes(event.target.id)
    && !["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(event.key)
  ) {
    renderSkillSuggestions(event.target);
  }
});

document.addEventListener("paste", (event) => {
  const input = event.target.closest("#homeQuestionInput, #chatQuestionInput");
  if (!input) return;
  const files = [...(event.clipboardData?.items || [])]
    .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
    .map((item) => item.getAsFile())
    .filter(Boolean);
  if (!files.length) return;
  event.preventDefault();
  addComposerImages(composerKey(input.id), files).catch((error) => toast(error.message, true));
});

document.addEventListener("change", (event) => {
  const toggle = event.target.closest("[data-update-auto-check]");
  if (!toggle) return;
  state.autoCheckUpdates = Boolean(toggle.checked);
  window.localStorage.setItem("scansci.update.auto-check", String(state.autoCheckUpdates));
  toast(state.autoCheckUpdates ? "已开启自动检查更新" : "已关闭自动检查更新");
});

document.addEventListener("change", (event) => {
  const input = event.target.closest('#paperBatchFile[data-action="pick-batch-file"], #homePaperBatchFile[data-action="pick-home-batch-file"]');
  if (!input) return;
  const file = input.files && input.files[0];
  input.value = "";
  if (!file) return;
  parseBatchFile(file)
    .then((identifiers) => {
      state.pendingBatchIdentifiers = identifiers;
      state.pendingBatchFilename = identifiers.length ? file.name : "";
      if (input.id === "homePaperBatchFile") {
        const composer = byId("homeQuestionInput");
        if (composer) composer.value = "";
        renderHomeModeWorkbench("download");
      }
      else renderMode();
      toast(identifiers.length ? `已解析 ${identifiers.length} 个标识符` : "未在文件中识别到 DOI 或 arXiv ID", !identifiers.length);
    })
    .catch((error) => toast(`解析失败：${error.message}`, true));
});

document.addEventListener("submit", (event) => {
  if (event.target.id === "localModelMarketSearch") {
    event.preventDefault();
    state.localModelMarket.query = event.target.elements.query.value.trim();
    refreshLocalModelMarket().catch((error) => toast(error.message, true));
    return;
  }
  if (event.target.id === "mcpManualForm") {
    event.preventDefault();
    addManualMcpServer(event.target).catch((error) => toast(error.message, true));
  }
  else if (event.target.id === "academicSearchPlanForm") {
    event.preventDefault();
    startReviewedAcademicSearch().catch((error) => toast(`无法开始联网检索：${error.message}`, true));
  }
  else if (event.target.id === "libraryPathForm") {
    event.preventDefault();
    const value = byId("libraryPathInput").value.trim();
    if (!value) return;
    state.libraryImportGuided = false;
    const operation = state.libraryImportKind === "files"
      ? importLibraryFiles(value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))
      : state.libraryImportKind === "empty"
        ? createEmptyLibrary(value)
      : state.libraryImportKind === "zotero"
        ? registerZoteroLibrary(value)
        : bindLibraryFolder(value, state.libraryImportKind);
    operation.catch((error) => toast(error.message, true));
  }
  else if (event.target.id === "homeAskForm") askQuestion(event, "homeQuestionInput");
  else if (event.target.id === "chatAskForm") askQuestion(event, "chatQuestionInput");
  else if (event.target.id === "reviewAskForm") askQuestion(event, "reviewQuestionInput");
  else if (event.target.id === "journalSearchForm") handleJournalSearch(event).catch((error) => showModeError(error));
  else if (event.target.id === "referenceAnalyzeForm") handleReferenceAnalyze(event).catch((error) => showModeError(error));
  else if (event.target.id === "atlasSearchForm") handleAtlasSearch(event).catch((error) => showModeError(error));
  else if (event.target.id === "paperDownloadForm") handlePaperDownload(event).catch((error) => showModeError(error));
  else if (event.target.id === "pptOutlineForm") handlePptOutline(event).catch((error) => showModeError(error));
  else if (event.target.id === "modelProviderForm") {
    event.preventDefault();
    const provider = collectProviderForm();
    const key = String(event.target.elements["provider-api-key"]?.value || "").trim();
    if (key && provider) provider.enabled = true;
    (async () => {
      await persistSettings(key ? "提供商与密钥已保存" : "提供商已保存");
      if (!key || !provider) return;
      state.settings = await request(`/api/settings/providers/${encodeURIComponent(provider.id)}/api-key`, { method: "POST", body: JSON.stringify({ api_key: key }) });
      renderModelSelectors();
      renderSettings();
      toast("密钥已保存到系统凭据管理器");
    })().catch((error) => toast(error.message, true));
  } else if (event.target.id === "localModelsForm") {
    event.preventDefault();
    collectLocalModelsForm();
    persistSettings("本地模型已保存").catch((error) => toast(error.message, true));
  } else if (event.target.id === "generalPreferencesForm") {
    event.preventDefault();
    collectAppearanceForm();
    persistSettings(copy("appearanceSaved")).catch((error) => toast(error.message, true));
  } else if (event.target.id === "documentProcessingForm") {
    event.preventDefault();
    const ocrKey = String(event.target.elements["ocr-api-key"]?.value || "").trim();
    const mineruKey = String(event.target.elements["mineru-api-key"]?.value || "").trim();
    collectDocumentProcessingForm();
    (async () => {
      await persistSettings(ocrKey || mineruKey ? "文档处理配置与密钥已保存" : "文档处理配置已保存");
      if (ocrKey) state.settings = await request("/api/settings/document-processing/ocr/api-key", { method: "POST", body: JSON.stringify({ api_key: ocrKey }) });
      if (mineruKey) state.settings = await request("/api/settings/document-processing/mineru/api-key", { method: "POST", body: JSON.stringify({ api_key: mineruKey }) });
      renderSettings();
      if (ocrKey || mineruKey) toast("密钥已保存到系统凭据管理器");
    })().catch((error) => toast(error.message, true));
  } else if (event.target.id === "modelRoleForm") {
    event.preventDefault();
    collectModelRoleForm();
    persistSettings("模型路由已保存").catch((error) => toast(error.message, true));
  } else if (event.target.id === "skillInstallForm") {
    event.preventDefault();
    const sourceType = event.target.elements["source-type"].value;
    const source = event.target.elements.source.value.trim();
    installSkill(sourceType, source).catch((error) => toast(error.message, true));
  } else if (event.target.id === "extensionPluginForm") {
    event.preventDefault();
    const source = event.target.elements["plugin-source"].value.trim();
    const name = event.target.elements["plugin-name"].value.trim();
    if (!source || !name) return;
    state.settings.plugins.push({
      id: `plugin-${Date.now()}`,
      name,
      source,
      description: event.target.elements["plugin-description"].value.trim(),
      enabled: true,
    });
    persistSettings("插件来源已登记").catch((error) => toast(error.message, true));
  } else if (event.target.dataset.recordForm) {
    event.preventDefault();
    const kind = event.target.dataset.recordForm;
    const key = kind === "mcp" ? "mcp_servers" : kind;
    state.settings[key].push(newRecord(kind, event.target));
    persistSettings("配置已保存").catch((error) => toast(error.message, true));
  }
});

function setModeLoading(message) {
  const target = byId("modeResults");
  if (target) target.innerHTML = `<div class="mode-loading"><span></span>${escapeHtml(message)}</div>`;
}

function showModeError(error) {
  const target = byId("modeResults");
  if (target) target.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  toast(error.message, true);
}

async function handleJournalSearch(event) {
  event.preventDefault();
  await startModeRun("journal_search", { query: byId("journalQuery").value, limit: 10 }, "正在查询期刊分区…");
}

async function handleReferenceAnalyze(event) {
  event.preventDefault();
  await startModeRun("citation_analysis", { text: byId("referenceText").value, mode: byId("referenceMode").value }, "正在核对元数据与正文断言…");
}

async function handleAtlasSearch(event) {
  event.preventDefault();
  await startModeRun("paper_atlas", { query: byId("atlasQuery").value }, "正在寻找图谱入口…");
}

async function handlePaperDownload(event) {
  event.preventDefault();
  const strategy = state.downloadStrategy;
  const message = strategy === "oa_first" ? "正在优先查找开放获取版本…" : "正在从合规来源获取文献…";
  await startModeRun("paper_download", { identifier: byId("paperIdentifier").value, strategy }, message);
}

const BATCH_IDENTIFIER_PATTERN = /\b(?:10\.\d{4,9}\/\S+?)(?=[\s"'}\],]|$)|(?:arxiv:\s*)?\d{4}\.\d{4,5}(?:v\d+)?|[a-z]+-[a-z]+\/\d{7}/gi;

function extractBatchIdentifiers(text) {
  const matches = String(text || "").match(BATCH_IDENTIFIER_PATTERN) || [];
  const seen = new Set();
  const cleaned = [];
  for (const raw of matches) {
    const id = raw.trim().replace(/[.,;:)]+$/, "");
    if (!id || seen.has(id)) continue;
    seen.add(id);
    cleaned.push(id);
  }
  return cleaned;
}

async function parseBatchFile(file) {
  const MAX_BYTES = 5 * 1024 * 1024;
  if (file.size > MAX_BYTES) throw new Error("文件过大（上限 5MB）");
  const text = await file.text();
  return extractBatchIdentifiers(text);
}

async function handlePaperBatchDownload(identifiers) {
  const list = (identifiers && identifiers.length ? identifiers : state.pendingBatchIdentifiers) || [];
  if (!list.length) {
    toast("请先上传包含 DOI 或 arXiv ID 的文件", true);
    return;
  }
  const strategy = state.downloadStrategy;
  const payload = { identifiers: list, strategy };
  if (state.useTor) {
    payload.use_tor = true;
    payload.rotate_every = Math.max(1, Number(state.torRotateEvery) || 3);
    payload.tor_transport = state.torTransport;
  }
  state.pendingBatchIdentifiers = [];
  const loadingMsg = state.useTor ? `正在通过 Tor 批量获取 ${list.length} 篇文献（首次需下载 Tor）…` : `正在批量获取 ${list.length} 篇文献…`;
  await startModeRun("paper_download_batch", payload, loadingMsg);
}

async function handlePptOutline(event) {
  event.preventDefault();
  await startModeRun("ppt_outline", { topic: byId("pptTopic").value, template_id: state.selectedSlideTemplateId }, "正在把来源组织成汇报叙事…");
}

async function createPptProject() {
  if (!state.notebook) throw new Error("请先打开一个资料库");
  await startModeRun("ppt_project", { topic: byId("pptTopic")?.value || "", template_id: state.selectedSlideTemplateId }, "正在创建 EasySlides 项目并导入来源…");
}

async function startModeRun(workflowType, input, loadingMessage) {
  setModeLoading(loadingMessage);
  const run = await createResearchRun(workflowType, input);
  state.activeTaskId = run.run_id;
  window.localStorage.setItem("scansci.active.task", run.run_id);
  upsertRun(run);
  renderModeRun(run);
  watchRun(run.run_id, (next) => {
    if (state.activeView === "mode" && state.activeTaskId === next.run_id) renderModeRun(next);
  });
}

function batchItemMarkup(items) {
  const ICON = { pending: "○", downloading: "·", completed: "✓", failed: "×", cancelled: "—" };
  return (items || []).map((item) => {
    const status = item.status || "pending";
    return `<li class="paper-batch-item is-${escapeHtml(status)}"><span class="paper-batch-item-icon">${ICON[status] || "○"}</span><div class="paper-batch-item-body"><strong>${escapeHtml(item.identifier || "")}</strong>${item.error ? `<small>${escapeHtml(item.error)}</small>` : Array.isArray(item.files) && item.files.length ? `<small>${item.files.map((f) => escapeHtml(f.split(/[\\/]/).pop())).join("，")}</small>` : ""}</div></li>`;
  }).join("");
}

function renderModeRun(run) {
  if (run.status === "completed" && run.output_artifact) {
    renderModeArtifact(run);
    return;
  }
  const stages = (run.stages || []).map((stage) => `<li class="${escapeHtml(stage.status)}"><span>${stage.status === "completed" ? "✓" : stage.status === "running" ? "·" : stage.position + 1}</span><div><strong>${escapeHtml(stage.title)}</strong><small>${escapeHtml(stage.error_message || stage.summary || "等待执行")}</small></div></li>`).join("");
  const action = run.cancellable ? `<button type="button" class="run-action stop" data-action="cancel-run" data-run-id="${escapeHtml(run.run_id)}">停止任务</button>` : run.resumable ? `<button type="button" class="run-action" data-action="resume-run" data-run-id="${escapeHtml(run.run_id)}">${run.status === "needs_confirmation" ? "确认计划并执行" : "从当前阶段继续"}</button>` : "";
  const executeStage = (run.stages || []).find((stage) => stage.kind === "tool");
  const batchItems = run.workflow_type === "paper_download_batch" && executeStage && executeStage.output && Array.isArray(executeStage.output.items) ? `<ul class="paper-batch-progress">${batchItemMarkup(executeStage.output.items)}</ul>` : "";
  byId("modeResults").innerHTML = `<section class="mode-run"><header><div><span>${escapeHtml(runStatusLabel(run))}</span><strong>${escapeHtml(run.title)}</strong></div>${action}</header><div class="run-progress"><i class="${progressWidthClass(Number(run.progress || 0) * 100)}"></i></div><ol>${stages}</ol>${batchItems}${run.status === "failed" ? `<p class="mode-run-error">${escapeHtml(runFailureSummary(run))}</p>` : ""}</section>`;
}

function renderModeArtifact(run) {
  const artifact = run.output_artifact;
  const payload = artifact.payload || {};
  if (run.workflow_type === "journal_search") renderJournalResults(payload);
  else if (run.workflow_type === "citation_analysis") renderReferenceResults(payload);
  else if (run.workflow_type === "paper_atlas") renderAtlasResults(payload);
  else if (run.workflow_type === "paper_download") {
    const files = (payload.files || []).map((file) => `<code>${escapeHtml(file)}</code>`).join("");
    byId("modeResults").innerHTML = `<div class="download-result"><span>✓</span><div><strong>文献已保存</strong><p>${escapeHtml(payload.identifier || run.title)}</p>${files || `<code>${escapeHtml(payload.output_dir || artifact.file_path)}</code>`}</div></div>`;
  } else if (run.workflow_type === "paper_download_batch") {
    const items = Array.isArray(payload.items) ? payload.items : [];
    const completed = Number(payload.completed || 0);
    const failed = Number(payload.failed || 0);
    const failedIds = items.filter((item) => item.status === "failed").map((item) => item.identifier);
    const retry = failedIds.length ? `<button type="button" class="run-action" data-action="retry-batch-download" data-identifiers="${escapeHtml(failedIds.join("\n"))}">重试失败项 (${failedIds.length})</button>` : "";
    const rotations = Number(payload.tor_rotations || 0);
    const torNote = rotations ? `<small class="paper-batch-tor-note">Tor 轮换 ${rotations} 次</small>` : "";
    byId("modeResults").innerHTML = `<section class="mode-run"><header><div><span>批量完成</span><strong>${escapeHtml(run.title)}</strong></div>${retry}</div></header><p class="paper-batch-summary">成功 ${completed}/${payload.total || items.length}，失败 ${failed}${torNote}</p><ul class="paper-batch-progress">${batchItemMarkup(items)}</ul></section>`;
  } else if (["ppt_outline", "ppt_project"].includes(run.workflow_type)) {
    renderPptOutline(payload);
    if (run.workflow_type === "ppt_project") toast("PPT 项目已创建");
  } else if (run.workflow_type === "pdf_to_ppt") {
    byId("modeResults").innerHTML = slideProjectArtifactMarkup(payload, run.run_id);
    toast("可编辑 PPTX 已生成");
  } else byId("modeResults").innerHTML = genericArtifactMarkup(artifact);
}

async function cancelRun(runId) {
  const run = await request(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", body: "{}" });
  upsertRun(run);
  if (state.activeView === "conversation") renderRun(run);
  else if (state.activeView === "mode") renderModeRun(run);
  toast(run.cancel_requested ? "停止请求已发送" : "任务已停止");
}

async function respondAgentInteraction(element) {
  const runId = String(element.dataset.runId || state.activeStreamRunId || "");
  const interactionId = String(element.dataset.interactionId || "");
  const kind = String(element.dataset.interactionKind || "ask_user");
  let response;
  if (element.dataset.freeform === "true") {
    const value = String(element.closest(".agent-interaction-card")?.querySelector("[data-interaction-input]")?.value || "").trim();
    if (!value) throw new Error("请输入回答后再继续");
    response = { value, text: value };
  } else {
    const selected = String(element.dataset.responseId || "");
    response = kind === "plan"
      ? { decision: selected, action: selected }
      : { selected: [selected], value: selected };
  }
  const result = await request("/api/chat/interactions/respond", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, interaction_id: interactionId, response }),
  });
  if (!result.ok) throw new Error(result.error || "这个选择点已经失效");
  state.directMessages.forEach((message) => {
    if (message.interaction?.interaction_id === interactionId) message.interaction.resolved = true;
  });
  renderDirectConversation();
  toast(kind === "plan" ? "计划决定已提交，任务继续执行" : "回答已提交，任务继续执行");
}

async function respondRunInteraction(element) {
  const runId = String(element.dataset.runId || "");
  const interactionId = String(element.dataset.interactionId || "");
  const decision = String(element.dataset.decision || "approve");
  const run = await request(`/api/runs/${encodeURIComponent(runId)}/interaction`, {
    method: "POST",
    body: JSON.stringify({ interaction_id: interactionId, response: { decision, action: decision } }),
  });
  upsertRun(run);
  renderRun(run);
  if (decision !== "cancel") watchRun(run.run_id, (next) => {
    if (state.activeTaskId === next.run_id) renderRun(next);
  });
}

async function recoverRun(element) {
  const runId = String(element.dataset.runId || "");
  const action = String(element.dataset.recoveryAction || "retry");
  const run = await request(`/api/runs/${encodeURIComponent(runId)}/recover`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
  upsertRun(run);
  state.activeTaskId = run.run_id;
  renderRun(run);
  watchRun(run.run_id, (next) => {
    if (state.activeTaskId === next.run_id) renderRun(next);
  });
}

async function advisorAction(element) {
  const runId = String(element.dataset.runId || "");
  const action = String(element.dataset.advisorAction || "");
  const run = await request(`/api/runs/${encodeURIComponent(runId)}/advisor-action`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
  upsertRun(run);
  state.activeTaskId = run.run_id;
  window.localStorage.setItem("scansci.active.task", run.run_id);
  renderRun(run);
  watchRun(run.run_id, (next) => {
    if (state.activeTaskId === next.run_id) renderRun(next);
  });
}

async function branchRun(element) {
  const runId = String(element.dataset.runId || "");
  const run = await request(`/api/runs/${encodeURIComponent(runId)}/branch`, {
    method: "POST",
    body: JSON.stringify({ background: true, execute: true }),
  });
  upsertRun(run);
  state.activeTaskId = run.run_id;
  window.localStorage.setItem("scansci.active.task", run.run_id);
  renderRun(run);
  watchRun(run.run_id, (next) => {
    if (state.activeTaskId === next.run_id) renderRun(next);
  });
  toast("已建立独立分支，原任务保持不变");
}

async function resumeRun(runId) {
  const run = await request(`/api/runs/${encodeURIComponent(runId)}/resume`, { method: "POST", body: "{}" });
  upsertRun(run);
  if (state.activeView === "conversation") renderRun(run);
  else if (state.activeView === "mode") renderModeRun(run);
  watchRun(runId, (next) => {
    if (state.activeTaskId !== next.run_id) return;
    if (state.activeView === "conversation") renderRun(next);
    else if (state.activeView === "mode") renderModeRun(next);
  });
  toast("已从保存的阶段继续");
}

async function compactSession() {
  if (state.streaming) { toast("对话进行中，无法压缩上下文"); return; }
  const sessionId = state.sessionId || state.activeTaskId;
  if (!sessionId) { toast("暂无活跃对话"); return; }
  toast("正在压缩上下文…");
  try {
    const result = await request("/api/chat/compact", { method: "POST", body: JSON.stringify({ session_id: sessionId }) });
    if (result.stats) updateSessionStats(result.stats);
    else if (result.tokens_after && state.sessionStats?.contextUsage) {
      const current = state.sessionStats.contextUsage;
      const contextWindow = Number(current.contextWindow || modelContextWindow() || 0);
      updateSessionStats({
        ...state.sessionStats,
        contextUsage: {
          ...current,
          tokens: Number(result.tokens_after),
          contextWindow,
          percent: contextWindow ? Number(result.tokens_after) / contextWindow * 100 : 0,
        },
      });
    }
    if (result.ok && result.tokens_before) {
      toast(`上下文已压缩：${formatTokenCount(result.tokens_before)} → ${formatTokenCount(result.tokens_after || 0)} tokens`);
    } else {
      toast(result.error || "压缩完成");
    }
  } catch (error) {
    toast(`压缩失败：${error.message}`, true);
  }
}

byId("sourceFilter").addEventListener("input", (event) => {
  state.sourceQuery = event.target.value;
  renderSources();
});

byId("slideTemplateSearch").addEventListener("input", (event) => {
  state.slideTemplateQuery = event.target.value;
  renderSlideTemplateBrowser();
});

document.addEventListener("keydown", (event) => {
  if (!event.ctrlKey || event.altKey || event.metaKey) return;
  if (event.key.toLowerCase() === "n") {
    event.preventDefault();
    startTask();
  }
  if (event.key.toLowerCase() === "k") {
    event.preventDefault();
    setView("conversation");
    window.setTimeout(() => byId("sourceFilter").focus(), 0);
  }
});

installSidebarResizer();
installContextPanelResizer();
applySidebarState();
applyContextPanelWidth();
byId("answerArea")?.addEventListener("scroll", () => {
  const answerArea = byId("answerArea");
  if (!answerArea) return;
  const distanceFromBottom = answerArea.scrollHeight - answerArea.scrollTop - answerArea.clientHeight;
  state.conversationAutoFollow = distanceFromBottom < conversationFollowThreshold;
  updateConversationScrollAffordance();
}, { passive: true });
byId("taskList")?.addEventListener("scroll", () => {
  if (state.historyMenuRunId) positionTaskMenu();
});
window.addEventListener("resize", () => {
  if (state.historyMenuRunId) positionTaskMenu();
});
renderProfileAvatar();
updateChromeControls();
observeIcons();
setComposerMode(byId("homeModeSelect")?.value || "general");
setWebSearchMode(state.webSearchMode, { announce: false });
initialize();
renderAppUpdate();
if (state.autoCheckUpdates) refreshAppUpdate({ quiet: true });
window.addEventListener("pywebviewready", () => {
  state.updateNative = Boolean(window.pywebview?.api?.install_update);
  renderAppUpdate();
});
