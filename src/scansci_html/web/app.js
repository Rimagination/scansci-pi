const state = {
  workspace: null,
  notebook: null,
  settings: null,
  presets: { providers: [], local_models: [] },
  localModelMarket: { installed: [], catalog: [], source: "", query: "", loading: false },
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
  reviewDocument: null,
  contextPanel: "sources",
  evidenceReturnPanel: "sources",
  activeEvidence: null,
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
  slideTemplates: [],
  slideTemplatesAvailable: false,
  selectedSlideTemplateId: window.localStorage.getItem("scansci.slides.template") || "",
  previewSlideTemplateId: "",
  previewSlidePage: "",
  slideTemplateQuery: "",
  lastRunRenderKey: "",
  sidebarCollapsed: window.localStorage.getItem("scansci.sidebar.collapsed") === "true",
  sidebarWidth: Math.max(260, Math.min(520, Number(window.localStorage.getItem("scansci.sidebar.width")) || 352)),
  thinkingLevel: ["auto", "low", "medium", "high"].includes(window.localStorage.getItem("scansci.thinking.level"))
    ? window.localStorage.getItem("scansci.thinking.level")
    : "auto",
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
    if (eventType === "error" || eventType === "RUN_ERROR") throw new Error(event.message || "The streaming response could not be completed.");
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

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character]));
}

function renderAssistantInline(value = "") {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderAssistantContent(value = "") {
  const lines = String(value).replace(/\r\n/g, "\n").split("\n");
  const output = [];
  let listType = "";
  let paragraph = [];
  const flushParagraph = () => {
    if (!paragraph.length) return;
    output.push(`<p>${renderAssistantInline(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (!listType) return;
    output.push(`</${listType}>`);
    listType = "";
  };
  lines.forEach((line) => {
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (heading) {
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
  });
  flushParagraph(); closeList();
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

// A local, Lucide-style icon adapter. Keeping the small used subset in the
// application makes the desktop build deterministic: no icon font, CDN, or
// operating-system glyph fallback is needed.
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
  "arrow-left": '<path d="m11 6-6 6 6 6M5.5 12h13"></path>',
  "arrow-right": '<path d="m13 6 6 6-6 6M18.5 12h-13"></path>',
  "chevron-down": '<path d="m7 9 5 5 5-5"></path>',
  "chevron-right": '<path d="m9 7 5 5-5 5"></path>',
  plus: '<path d="M12 5v14M5 12h14"></path>',
  minus: '<path d="M5 12h14"></path>',
  check: '<path d="m5.5 12 4.1 4 8.9-8.5"></path>',
  x: '<path d="m7 7 10 10M17 7 7 17"></path>',
  refresh: '<path d="M19 8.5A7.5 7.5 0 1 0 19.5 14"></path><path d="M19.5 4.5v4.8h-4.8"></path>',
  send: '<path d="M12 20V4"></path><path d="m6 10 6-6 6 6"></path>',
  "file-plus": '<path d="M6 3.5h7l4.5 4.5v12H6z"></path><path d="M13 3.5V8h4.5M11.5 12v5M9 14.5h5"></path>',
  "folder-open": '<path d="M3.5 7h6l2-2h3.2a2 2 0 0 1 1.8 1.1l.5.9H20a1.5 1.5 0 0 1 1.4 2l-2 8a2 2 0 0 1-1.9 1.5H4.7a1.5 1.5 0 0 1-1.45-1.9l1.7-7A2 2 0 0 1 6.9 8H20"></path>',
  image: '<rect x="3.5" y="4" width="17" height="16" rx="2"></rect><circle cx="9" cy="9" r="1.3"></circle><path d="m4.5 17 5-4.8 3.2 2.9 2-2 4.3 3.9"></path>',
  book: '<path d="M4.5 5.5A2.5 2.5 0 0 1 7 3h11v16H7a2.5 2.5 0 0 0-2.5 2.5v-16Z"></path><path d="M4.5 18.5A2.5 2.5 0 0 1 7 16h11"></path>',
  "message-circle": '<path d="M19.5 11.5a7.5 7.5 0 0 1-8 7.5 8.4 8.4 0 0 1-3.5-.8L4.5 19l.9-3a7.5 7.5 0 1 1 14.1-4.5Z"></path>',
  pen: '<path d="m5 19 1.4-4.5L15.8 5a2.1 2.1 0 0 1 3 3l-9.4 9.5L5 19Z"></path><path d="m13.8 7 3.2 3.2"></path>',
  presentation: '<rect x="4" y="4" width="16" height="12" rx="1.5"></rect><path d="M8 20h8M12 16v4M8 8h8M8 11h5"></path>',
  layout: '<rect x="3.5" y="4" width="17" height="16" rx="2"></rect><path d="M3.5 9h17M9 9v11"></path>',
  search: '<circle cx="10.7" cy="10.7" r="5.8"></circle><path d="m15 15 4.5 4.5"></path>',
  filter: '<path d="M4 5h16l-6.2 7v5.2L10.2 19v-7L4 5Z"></path>',
  info: '<circle cx="12" cy="12" r="8.5"></circle><path d="M12 10.5V16M12 7.7h.01"></path>',
  sliders: '<path d="M4 6h16M4 12h16M4 18h16"></path><circle cx="9" cy="6" r="1.6"></circle><circle cx="15" cy="12" r="1.6"></circle><circle cx="11" cy="18" r="1.6"></circle>',
  server: '<rect x="4" y="4.5" width="16" height="6" rx="1.5"></rect><rect x="4" y="13.5" width="16" height="6" rx="1.5"></rect><path d="M7.5 7.5h.01M7.5 16.5h.01M11 7.5h5M11 16.5h5"></path>',
  terminal: '<polyline points="4 17 10 11 4 5"></polyline><line x1="12" x2="20" y1="19" y2="19"></line>',
  globe: '<circle cx="12" cy="12" r="8.5"></circle><path d="M3.8 12h16.4M12 3.5c2.2 2.2 3.3 5 3.3 8.5S14.2 18.3 12 20.5C9.8 18.3 8.7 15.5 8.7 12S9.8 5.7 12 3.5Z"></path>',
  "shield-check": '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3v5"></path><path d="m9 12 2 2 4-4"></path>',
  "lock-keyhole": '<rect width="18" height="11" x="3" y="10" rx="2"></rect><path d="M7 10V7a5 5 0 0 1 10 0v3"></path><circle cx="12" cy="15.5" r="1"></circle><path d="M12 16.5v1.6"></path>',
  brain: '<path d="M9.2 5.3A3 3 0 0 0 4.5 7.8a3 3 0 0 0 .3 5.7 3.2 3.2 0 0 0 4.7 3.2 3.1 3.1 0 0 0 5 0 3.2 3.2 0 0 0 4.7-3.2 3 3 0 0 0 .3-5.7 3 3 0 0 0-4.7-2.5 3.1 3.1 0 0 0-5.6 0Z"></path><path d="M12 5.5v12.7M8 9.5a2.2 2.2 0 0 0 2.2 2.2M16 9.5a2.2 2.2 0 0 1-2.2 2.2M8 14a2.2 2.2 0 0 1 2.2 2.2M16 14a2.2 2.2 0 0 0-2.2 2.2"></path>',
  eye: '<path d="M3.5 12s3-5.2 8.5-5.2 8.5 5.2 8.5 5.2-3 5.2-8.5 5.2S3.5 12 3.5 12Z"></path><circle cx="12" cy="12" r="2.3"></circle>',
  "arrow-up-right": '<path d="M7 17 17 7M9 7h8v8"></path>',
  "arrow-up-down": '<path d="m8 6 4-4 4 4M16 18l-4 4-4-4M12 2v20"></path>',
  wrench: '<path d="M14.5 6a4 4 0 0 0-5 5l-5 5a2 2 0 1 0 2.8 2.8l5-5a4 4 0 0 0 5-5L14 12l-2-2 2.5-4Z"></path>',
  code: '<path d="m8.5 7-4 5 4 5M15.5 7l4 5-4 5"></path>',
  audio: '<path d="M4 13h2M8 9v6M12 6v12M16 9v6M20 13h-2"></path>',
  "grip-vertical": '<path d="M9 7h.01M15 7h.01M9 12h.01M15 12h.01M9 17h.01M15 17h.01"></path>',
  square: '<rect x="6" y="6" width="12" height="12" rx="1.5"></rect>',
  copy: '<rect x="8" y="8" width="10" height="10" rx="1.5"></rect><path d="M6 15H5.5A1.5 1.5 0 0 1 4 13.5v-8A1.5 1.5 0 0 1 5.5 4h8A1.5 1.5 0 0 1 15 5.5V6"></path>',
  download: '<path d="M12 4v10M8 11l4 4 4-4M5 19.5h14"></path>',
  expand: '<path d="M8 4H4v4M16 4h4v4M20 16v4h-4M4 16v4h4"></path>',
  archive: '<path d="M4 7h16v13H4zM3 4h18v3H3zM9 11h6"></path>',
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

function citationMarkerMarkup(citationId) {
  const marker = escapeHtml(citationId);
  return `<button class="citation-marker" type="button" data-citation-id="${marker}" aria-label="查看引用 ${marker}" aria-haspopup="dialog">[${marker}]</button>`;
}

function safeReaderUrl(record = {}) {
  const supplied = String(record.reader_url || "");
  if (supplied.startsWith("/api/sources/")) return supplied;
  const docId = String(record.doc_id || "").trim();
  return docId ? readerUrl(docId, String(record.html_anchor || "")) : "";
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
  state.evidenceReturnPanel = options.returnPanel || (current === "review" ? "review" : "sources");
  state.activeEvidence = { ...citation, reader_url: reader, sourceOnly: Boolean(options.sourceOnly) };
  const quote = String(citation.exact_quote || "已打开来源全文；被回答使用的原文会以高亮显示。") || "已打开来源全文。";
  const meta = evidenceMeta(citation);
  const anchorNote = citation.html_anchor ? "已定位至该回答使用的原文片段" : "正在显示来源全文";
  const original = String(citation.original_url || "");
  const tabs = original ? `<div class="evidence-reader-tabs"><button type="button" class="is-active" data-action="show-evidence-blocks">证据定位</button><button type="button" data-action="show-evidence-original" data-original-url="${escapeHtml(original)}">原始文件</button></div>` : "";
  target.innerHTML = `<header class="evidence-reader-head"><button type="button" class="evidence-reader-back" data-action="close-evidence-reader" aria-label="返回来源列表">←</button><div><span>${options.sourceOnly ? "来源全文" : "引用证据"}</span><h2>${escapeHtml(sourceTitle(citation))}</h2><p>${escapeHtml(meta || anchorNote)}</p></div></header>${tabs}<div class="evidence-reader-summary"><span>${escapeHtml(anchorNote)}</span><blockquote>${escapeHtml(compact(quote, 680))}</blockquote></div><div class="evidence-reader-frame-wrap"><iframe class="evidence-reader-frame" id="evidenceReaderFrame" title="${escapeHtml(sourceTitle(citation))} 的来源全文" src="${escapeHtml(reader)}" sandbox="allow-same-origin"></iframe></div>`;
  setContextPanel("evidence");
}

function closeEvidenceReader() {
  const returnPanel = state.evidenceReturnPanel === "review" && state.reviewDocument ? "review" : "sources";
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

async function initialize() {
  try {
    const [workspace, settings, presets, capabilities, runsPayload, slideTemplatesPayload, localInstalled, localCatalog, skillsPayload] = await Promise.all([
      request("/api/workspace"),
      request("/api/settings"),
      request("/api/settings/presets"),
      request("/api/capabilities"),
      request("/api/runs?view=all&limit=200"),
      request("/api/slides/templates").catch(() => ({ available: false, templates: [] })),
      request("/api/local-models/installed").catch(() => ({ models: [] })),
      request("/api/local-models/market").catch(() => ({ items: [] })),
      request("/api/skills").catch(() => ({ skills: [], library_path: "" })),
    ]);
    state.workspace = workspace;
    state.notebook = (workspace.notebooks || [])[0] || null;
    state.settings = settings;
    state.presets = presets;
    state.capabilities = capabilities;
    state.runs = runsPayload.runs || [];
    state.slideTemplates = slideTemplatesPayload.templates || [];
    state.localModelMarket = { installed: localInstalled.models || [], catalog: localCatalog.items || [], source: localCatalog.source || "", loading: false };
    state.extensions.skills = skillsPayload.skills || [];
    state.extensions.libraryPath = skillsPayload.library_path || "";
    state.slideTemplatesAvailable = Boolean(slideTemplatesPayload.available && state.slideTemplates.length);
    if (!state.slideTemplates.some((item) => item.id === state.selectedSlideTemplateId)) {
      state.selectedSlideTemplateId = state.slideTemplates[0]?.id || "";
    }
    state.previewSlideTemplateId = state.selectedSlideTemplateId;
    state.selectedProviderId = settings.active_model?.provider_id || settings.providers?.[0]?.id || "";
    renderWorkspace();
  } catch (error) {
    const homeSubline = byId("homeSubline");
    if (homeSubline) homeSubline.textContent = `无法加载本地工作区：${error.message}`;
    toast(error.message, true);
  }
}

function renderWorkspace() {
  const title = state.notebook?.title || state.notebook?.notebook_id || "未打开资料库";
  const sidebarTitle = byId("sidebarNotebookTitle");
  if (sidebarTitle) sidebarTitle.textContent = title;
  const sourceCount = state.notebook?.counts?.sources || 0;
  const homeSubline = byId("homeSubline");
  if (homeSubline) homeSubline.textContent = sourceCount ? `${sourceCount} 篇来源 · 证据追溯已就绪` : "打开资料库后即可开始研究";
  renderModelSelectors();
  syncSlideTemplateDocks();
  renderSources();
  renderTasks();
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
  const label = currentThinkingLabel();
  const menu = thinkingMenuMarkup();
  document.querySelectorAll("[data-composer-thinking]").forEach((picker) => {
    const trigger = picker.querySelector("[data-action='toggle-composer-thinking']");
    picker.querySelector("[data-thinking-label]")?.replaceChildren(document.createTextNode(label));
    picker.querySelector(".composer-thinking-popover").innerHTML = menu;
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

function thinkingMenuMarkup() {
  const current = currentThinkingLevel();
  const options = thinkingLevels.map((item) => {
    const selected = item.value === current;
    return `<button type="button" class="composer-thinking-option ${selected ? "is-selected" : ""}" data-action="select-composer-thinking" data-thinking-value="${item.value}" role="option" aria-selected="${selected ? "true" : "false"}"><span class="thinking-level-icon">${uiIcon(item.value === "auto" ? "wand" : "brain")}</span><span><strong>${item.label}</strong><small>${item.detail}</small></span><span class="composer-thinking-check" aria-hidden="true">${uiIcon("check")}</span></button>`;
  }).join("");
  return `${options}<p class="composer-thinking-note">\u6bcf\u6b21\u4efb\u52a1\u90fd\u4f1a\u8bb0\u5f55\u8be5\u6863\u4f4d\u3002\u6240\u6709\u6a21\u578b\u5747\u4f1a\u6539\u53d8 Agent \u8bc1\u636e\u9884\u7b97\uff1b\u5df2\u8bc6\u522b\u7684\u76f4\u8fde\u670d\u52a1\u4f1a\u989d\u5916\u4f7f\u7528\u539f\u751f API \u53c2\u6570\u3002</p>`;
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
    const models = (provider.models || []).filter(isConversationModel);
    if (!models.length) return "";
    const rows = models.map((model) => {
      const selected = provider.id === current.provider_id && model.id === current.model_id;
      const tags = model.capabilities?.includes("vision") ? '<span class="composer-model-tag">视觉</span>' : "";
      return `<button type="button" class="composer-model-option ${selected ? "is-selected" : ""}" data-action="select-composer-model" data-model-value="${escapeHtml(`${provider.id}::${model.id}`)}" role="option" aria-selected="${selected ? "true" : "false"}"><span class="composer-model-option-main"><strong>${escapeHtml(model.name || model.id)}</strong><small>${escapeHtml(provider.name)}</small></span>${tags}<span class="composer-model-check" aria-hidden="true">${uiIcon("check")}</span></button>`;
    }).join("");
    return `<section class="composer-model-group"><span>${escapeHtml(provider.name)}</span>${rows}</section>`;
  }).join("");
  const empty = groups || '<div class="composer-model-empty">尚未配置可用模型</div>';
  return `${empty}<div class="composer-model-manage"><button type="button" data-action="open-settings" data-settings-panel="models">${uiIcon("library")}管理模型</button></div>`;
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

function renderComposerSources(key) {
  const target = byId(`${key}SourceAttachments`);
  if (!target) return;
  const sources = state.composerSources[key] || [];
  target.hidden = !sources.length;
  target.innerHTML = sources.map((source) => `<article class="composer-source-card"><span>${uiIcon("file-plus")}</span><span><strong>${escapeHtml(source.name)}</strong><small>${escapeHtml(sourceTypeLabel(source.name))}${source.size ? ` · ${Math.max(1, Math.round(source.size / 1024))} KB` : ""}</small></span><button type="button" data-action="remove-composer-source" data-composer-key="${escapeHtml(key)}" data-source-id="${escapeHtml(source.id)}" aria-label="移除 ${escapeHtml(source.name)}">×</button></article>`).join("");
}

async function addComposerSources(key, files) {
  const incoming = [...files].filter(Boolean);
  if (!incoming.length) return;
  const existing = state.composerSources[key] || [];
  if (existing.length + incoming.length > COMPOSER_SOURCE_LIMIT) {
    toast(`一次最多可添加 ${COMPOSER_SOURCE_LIMIT} 份演示材料`, true);
    return;
  }
  const accepted = [];
  let totalBytes = existing.reduce((sum, item) => sum + Number(item.size || 0), 0);
  for (const file of incoming) {
    const suffix = sourceSuffix(file.name);
    if (!COMPOSER_SOURCE_SUFFIXES.has(suffix)) {
      toast("制作幻灯片支持 PDF、Word、Markdown、TXT 或 HTML", true);
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
    toast(`一次最多可添加 ${COMPOSER_SOURCE_LIMIT} 份演示材料`, true);
    return;
  }
  const accepted = incoming.slice(0, remaining).filter((path) => COMPOSER_SOURCE_SUFFIXES.has(sourceSuffix(path))).map((path, index) => ({
    id: `source-${Date.now()}-${index}`,
    name: path.split(/[\\/]/).pop() || "未命名材料",
    path,
    size: 0,
  }));
  if (!accepted.length) {
    toast("制作幻灯片支持 PDF、Word、Markdown、TXT 或 HTML", true);
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
  return `<span class="provider-logo provider-logo-${escapeHtml(key)} ${large ? "is-large" : ""}" aria-label="${escapeHtml(provider?.name || "服务商")} 品牌标识">${escapeHtml(mark)}</span>`;
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
  male: { label: "男熊猫", src: "/avatar-panda-male.png" },
  female: { label: "女熊猫", src: "/avatar-panda-female.png" },
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
  state.directMessages = [];
  setContextPanel("sources");
  setView("home");
  window.setTimeout(() => byId("homeQuestionInput").focus(), 0);
}

function setContextPanel(kind = "sources") {
  const safeKind = ["sources", "evidence", "review", "none"].includes(kind) ? kind : "sources";
  const review = safeKind === "review";
  const evidence = safeKind === "evidence";
  const hidden = safeKind === "none";
  state.contextPanel = safeKind;
  byId("sourcePanelView")?.classList.toggle("is-active", safeKind === "sources");
  byId("evidenceReaderPanel")?.classList.toggle("is-active", evidence);
  byId("reviewDocumentPanel")?.classList.toggle("is-active", review);
  byId("contextPanel")?.classList.toggle("is-hidden", hidden);
  byId("conversationLayout")?.classList.toggle("is-review-workbench", review);
  byId("conversationLayout")?.classList.toggle("is-direct-conversation", hidden);
  if (!review) byId("conversationLayout")?.classList.remove("is-review-focus");
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
  const listRect = list.getBoundingClientRect();
  const rowRect = row.getBoundingClientRect();
  const neededHeight = menu.offsetHeight + 8;
  const roomAbove = rowRect.top - listRect.top;
  menu.classList.toggle("opens-downward", roomAbove < neededHeight);
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
  return ({ queued: "排队中", planning: "规划中", running: "执行中", verifying: "核验中", needs_confirmation: "待确认", paused: "已暂停", completed: "已完成", failed: "失败", cancelled: "已停止" })[run.status] || run.status;
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
  setContextPanel(isDirectConversation || isStandaloneSlides ? "none" : mode === "writing" ? "review" : "sources");
  setView("conversation");
  byId("answerArea").innerHTML = `<div class="conversation-thread"><div class="user-turn"><div class="user-turn-bubble">${composerSourcePreviewMarkup(sourceFiles)}${composerImagePreviewMarkup(images)}<p>${escapeHtml(question)}</p></div></div><p class="loading-line">${isDirectConversation ? "正在生成回复…" : isStandaloneSlides ? "正在解析材料并制作可编辑 PPTX…" : "正在建立研究任务…"}</p></div>`;
  if (mode === "writing") renderReviewDocument({ title: question, status: "planning", progress: 0 }, null);
  try {
    if (isDirectConversation) {
      const messages = [...state.directMessages, { role: "user", content: question }].slice(-16);
      const startedAt = performance.now();
      streamingMessage = { role: "assistant", content: "", streaming: true };
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
          const message = { ...event.message, processing_ms: Math.max(0, Math.round(performance.now() - startedAt)) };
          const messageIndex = state.directMessages.indexOf(streamingMessage);
          if (messageIndex >= 0) state.directMessages[messageIndex] = message;
          completed = true;
          scheduleDirectConversationRender();
        }
      });
      if (!completed) throw new Error("The model stream ended before a final response was received.");
      input.value = "";
      return;
    }
    const { workflowType, workflowInput } = composerRun(mode, question, images, sourceFiles);
    const run = await createResearchRun(workflowType, workflowInput);
    state.activeTaskId = run.run_id;
    upsertRun(run);
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
  const input = byId(inputId);
  const key = composerKey(inputId);
  const mode = composerMode(inputId);
  const images = imagePayloadForComposer(key);
  const sourceFiles = sourcePayloadForComposer(key);
  const activeRun = state.runs.find((item) => item.run_id === state.activeTaskId);
  const isPptTask = inputId === "chatQuestionInput" && state.activeView === "conversation" && activeRun?.workflow_type === "pdf_to_ppt";
  const originalSlideSources = Array.isArray(activeRun?.input?.source_files) ? activeRun.input.source_files : [];
  let question = input.value.trim() || (sourceFiles.length
    ? mode === "slides"
      ? `请将《${sourceFiles[0].name}》制作成一份科研幻灯片。`
      : `请阅读《${sourceFiles[0].name}》并概括最重要的信息。`
    : images.length ? "请分析我粘贴的图片。" : "");
  if (!question && isPptTask && mode === "slides") question = activeRun.input?.question || activeRun.title;
  if (!question) return;

  const isTaskFollowUp = isPptTask && mode === "general";
  const isPptRecreate = isPptTask && mode === "slides";
  if (isTaskFollowUp && (sourceFiles.length || images.length)) {
    toast("继续 PPT 任务暂不添加新素材；请新建一个 PPT 任务后再上传文件。", true);
    return;
  }
  const isDirectConversation = mode === "general" || mode === "writing";
  const isStandaloneSlides = mode === "slides" && sourceFiles.length > 0;
  if (mode === "knowledge" && !state.notebook) {
    toast("知识库问答需要先选择一个知识库；通用和写作模式可直接使用。", true);
    return;
  }
  if (mode === "slides" && !state.notebook && !sourceFiles.length && !isPptRecreate) {
    toast("请先添加一份演示材料；制作幻灯片不需要资料库。", true);
    return;
  }
  if (images.length && mode !== "general") {
    toast("图片提问目前仅支持通用模式。", true);
    return;
  }
  if (images.length && !currentModelSupportsVision()) {
    toast("请先选择带有视觉能力的模型。", true);
    return;
  }

  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  let streamingMessage = null;
  byId("conversationTitle").textContent = compact(question, 80);
  setContextPanel(mode === "knowledge" ? "sources" : "none");
  setView("conversation");
  byId("answerArea").innerHTML = `<div class="conversation-thread"><div class="user-turn"><div class="user-turn-bubble">${composerSourcePreviewMarkup(sourceFiles)}${composerImagePreviewMarkup(images)}<p>${escapeHtml(question)}</p></div></div><p class="loading-line">${isDirectConversation ? "正在生成回复…" : isStandaloneSlides ? "正在解析材料并制作可编辑 PPTX…" : "正在建立研究任务…"}</p></div>`;
  try {
    if (isTaskFollowUp) {
      const result = await continueTaskConversation(activeRun.run_id, question);
      const run = result.run;
      state.activeTaskId = run.run_id;
      upsertRun(run);
      state.lastRunRenderKey = "";
      renderRun(run);
      input.value = "";
      return;
    }
    if (isPptRecreate) {
      if (!originalSlideSources.length) throw new Error("原 PPT 任务没有可复用的源文件，请重新添加材料后制作。");
      const run = await createResearchRun("pdf_to_ppt", {
        topic: question,
        source_files: originalSlideSources,
        template_id: state.selectedSlideTemplateId,
      });
      state.activeTaskId = run.run_id;
      upsertRun(run);
      renderRun(run);
      watchRun(run.run_id, (next) => {
        if (state.activeView === "conversation" && state.activeTaskId === next.run_id) renderRun(next);
      });
      input.value = "";
      return;
    }
    if (isDirectConversation) {
      const userMessage = { role: "user", content: question, sources: sourceFiles, images };
      const messages = [...state.directMessages, userMessage].filter((message) => !message.streaming).slice(-16);
      const startedAt = performance.now();
      streamingMessage = { role: "assistant", content: "", streaming: true, mode, trace: [] };
      state.directMessages = [...messages, streamingMessage].slice(-16);
      renderDirectConversation();
      let completed = false;
      activeDirectChatController = new AbortController();
      await streamChat(
        {
          messages,
          images,
          source_files: sourceFiles,
          thinking_level: currentThinkingLevel(),
          chat_mode: mode,
          skills: extractSkillMentions(question),
        },
        (eventType, payload) => {
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
          if (eventType === "CUSTOM" && payload.name === "process_trace") {
            streamingMessage.trace = Array.isArray(payload.value) ? payload.value : [];
            scheduleDirectConversationRender();
            return;
          }
          if (eventType === "done" || eventType === "RUN_FINISHED") {
            const result = payload.result || payload;
            const message = { ...result.message, processing_ms: Math.max(0, Math.round(performance.now() - startedAt)) };
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

    const { workflowType, workflowInput } = composerRun(mode, question, images, sourceFiles);
    const run = await createResearchRun(workflowType, workflowInput);
    state.activeTaskId = run.run_id;
    upsertRun(run);
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
    activeDirectChatController = null;
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

function answerUsageMarkup(usage) {
  if (!usage || typeof usage !== "object") return "";
  const promptTokens = formatTokenCount(usage.prompt_tokens);
  const completionTokens = formatTokenCount(usage.completion_tokens);
  const totalTokens = formatTokenCount(usage.total_tokens);
  const parts = [];
  if (promptTokens) parts.push(`输入 ${promptTokens}`);
  if (completionTokens) parts.push(`输出 ${completionTokens}`);
  if (totalTokens) parts.push(`总计 ${totalTokens}`);
  if (!parts.length) return "";
  return `<p class="answer-usage" aria-label="本次模型 Tokens 用量">Tokens · ${parts.join(" · ")}</p>`;
}

function processTraceMarkup(message, duration) {
  const trace = Array.isArray(message.trace) ? message.trace : [];
  if (!duration && !trace.length) return "";
  const status = duration > 0 ? `已处理 <time>${formatProcessingDuration(duration)}</time>` : "正在处理";
  const rows = trace.map((item) => `<li><strong>${escapeHtml(item.title || "处理步骤")}</strong><span>${escapeHtml(item.detail || "")}</span></li>`).join("");
  return `<details class="answer-processing" aria-label="本次对话处理过程"><summary>${status}${uiIcon("chevron-right", "answer-processing-chevron")}</summary>${rows ? `<ol>${rows}</ol>` : ""}</details>`;
}

function renderDirectConversation() {
  const turns = state.directMessages.map((message) => {
    if (message.role === "user") {
      return `<div class="user-turn"><div class="user-turn-bubble">${composerSourcePreviewMarkup(message.sources || [])}${composerImagePreviewMarkup(message.images || [])}<p>${escapeHtml(message.content)}</p></div></div>`;
    }
    const duration = Number(message.processing_ms || 0);
    const processing = processTraceMarkup(message, duration);
    const usage = answerUsageMarkup(message.usage);
    const cursor = message.streaming && message.content ? '<span class="stream-caret" aria-label="正在生成"></span>' : "";
    const answer = message.content ? `<div class="answer-sentence">${renderAssistantContent(message.content)}${cursor}</div>` : "";
    const generation = message.streaming ? '<div class="generation-indicator" role="status" aria-label="正在生成回复"><span class="generation-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>' : "";
    const error = message.error ? `<p class="stream-error">${escapeHtml(message.error)}</p>` : "";
    const modeLabel = composerModeLabels[message.mode] || "通用对话";
    return `<div class="assistant-turn direct-answer"><div class="answer-meta"><span>ScanSci Pi</span><b>${escapeHtml(modeLabel)}</b></div>${processing}${answer}${generation}${usage}${error}</div>`;
  }).join("");
  byId("answerArea").innerHTML = `<article class="conversation-thread">${turns}</article>`;
  byId("answerArea").scrollTop = byId("answerArea").scrollHeight;
}

function composerMode(inputId) {
  if (inputId === "reviewQuestionInput") return "writing";
  const selectId = inputId === "homeQuestionInput" ? "homeModeSelect" : "chatModeSelect";
  return byId(selectId)?.value || "general";
}

function composerRun(mode, text, images = [], sourceFiles = []) {
  const definitions = {
    general: { workflowType: "ask", workflowInput: { question: text, ...(images.length ? { images } : {}) } },
    writing: { workflowType: "literature_review", workflowInput: { question: text } },
    knowledge: { workflowType: "ask", workflowInput: { question: text, task_mode: "evidence" } },
    slides: sourceFiles.length
      ? { workflowType: "pdf_to_ppt", workflowInput: { topic: text, source_files: sourceFiles, template_id: state.selectedSlideTemplateId } }
      : { workflowType: "ppt_project", workflowInput: { topic: text, template_id: state.selectedSlideTemplateId } },
  };
  return definitions[mode] || definitions.general;
}

const composerModeLabels = { general: "通用", writing: "写作", knowledge: "知识库", slides: "幻灯片" };
const composerModeIcons = { general: "message-circle", writing: "pen", knowledge: "book", slides: "presentation" };

function closeComposerModePickers() {
  document.querySelectorAll("[data-mode-picker]").forEach((picker) => {
    picker.classList.remove("is-open");
    picker.querySelector("[data-action='toggle-composer-mode']")?.setAttribute("aria-expanded", "false");
  });
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
      title: "添加文献文件",
      label: "文件路径（每行一个）",
      hint: "支持 HTML 或 Markdown；文件会复制到搜索科学管理的资料目录。",
      placeholder: "例如 D:\\Research\\paper.html",
    },
    folder: {
      title: "导入本地文件夹",
      label: "文件夹路径",
      hint: "文件夹会成为当前知识库，支持递归索引 HTML 与 Markdown。",
      placeholder: "例如 D:\\Research\\papers",
    },
    obsidian: {
      title: "导入 Obsidian Vault",
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
  };
  state.libraryImportKind = Object.hasOwn(descriptors, kind) ? kind : "folder";
  const descriptor = descriptors[state.libraryImportKind];
  byId("libraryPathTitle").textContent = descriptor.title;
  byId("libraryPathLabel").textContent = descriptor.label;
  byId("libraryPathHint").textContent = descriptor.hint;
  input.placeholder = descriptor.placeholder;
  input.value = state.libraryImportKind === "files" ? "" : state.libraryImportKind === "folder" ? String(state.notebook?.root_path || "") : "";
  if (!dialog.open) dialog.showModal();
  window.setTimeout(() => input.focus(), 0);
}

function closeLibraryPathDialog() {
  const dialog = byId("libraryPathDialog");
  if (dialog?.open) dialog.close();
}

async function chooseLibraryFolder(kind = "folder") {
  closeAttachmentMenus();
  const nativePicker = window.pywebview?.api?.choose_library_folder;
  if (typeof nativePicker !== "function") {
    openLibraryPathDialog(kind);
    return;
  }
  const path = String(await nativePicker() || "").trim();
  if (!path) return;
  if (kind === "zotero") await registerZoteroLibrary(path);
  else await importLibraryFolder(path, kind);
}

async function chooseLibraryFiles() {
  closeAttachmentMenus();
  const nativePicker = window.pywebview?.api?.choose_library_files;
  if (typeof nativePicker !== "function") {
    openLibraryPathDialog("files");
    return;
  }
  const paths = Array.from(await nativePicker() || []).map(String).filter(Boolean);
  if (paths.length) await importLibraryFiles(paths);
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

async function importLibraryFolder(path, kind = "folder") {
  toast(kind === "obsidian" ? "正在读取 Obsidian 笔记并建立索引…" : "正在建立资料索引…");
  const result = await request("/api/library/folder", {
    method: "POST",
    body: JSON.stringify({ notebook_id: "", path, library_kind: kind }),
  });
  await applyLibraryImport(result, kind === "obsidian" ? "Obsidian 知识库已导入" : "知识库已更新");
}

async function importLibraryFiles(paths) {
  toast(`正在导入 ${paths.length} 个文件…`);
  const result = await request("/api/library/files", {
    method: "POST",
    body: JSON.stringify({ notebook_id: state.notebook?.notebook_id || "", paths }),
  });
  await applyLibraryImport(result, `已添加 ${result.added_files || paths.length} 个文件`);
}

async function registerZoteroLibrary(path) {
  toast("正在连接 Zotero 文献书架…");
  const result = await request("/api/library/zotero", {
    method: "POST",
    body: JSON.stringify({ notebook_id: state.notebook?.notebook_id || "", path }),
  });
  await applyLibraryImport(result, `已连接 Zotero 文献库 · ${result.zotero?.pdf_count || 0} 篇 PDF`);
}

async function connectLocalZotero() {
  toast("正在读取本机 Zotero 文献元数据…");
  const result = await request("/api/library/zotero/local", {
    method: "POST",
    body: JSON.stringify({ notebook_id: state.notebook?.notebook_id || "" }),
  });
  await applyLibraryImport(result, `已连接本机 Zotero · ${result.zotero?.item_count || 0} 条文献`);
}

async function applyLibraryImport(result, message) {
  state.workspace = result.workspace || await request("/api/workspace");
  const notebookId = result.notebook?.notebook_id || state.notebook?.notebook_id;
  state.notebook = (state.workspace.notebooks || []).find((item) => item.notebook_id === notebookId) || result.notebook || null;
  state.capabilities = await request("/api/capabilities");
  closeLibraryPathDialog();
  renderWorkspace();
  if (state.activeView === "mode" && state.activeMode === "library") renderMode();
  toast(`${message} · ${state.notebook?.counts?.sources || 0} 篇来源`);
}

function toggleComposerModePicker(trigger) {
  const picker = trigger.closest("[data-mode-picker]");
  if (!picker) return;
  const shouldOpen = !picker.classList.contains("is-open");
  closeAttachmentMenus();
  closeComposerModePickers();
  if (shouldOpen) {
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
  }
}

function setComposerMode(mode) {
  const safeMode = composerModeLabels[mode] ? mode : "general";
  const label = composerModeLabels[safeMode];
  document.querySelectorAll("[data-mode-picker]").forEach((picker) => {
    const input = picker.querySelector("input[type='hidden']");
    const trigger = picker.querySelector("[data-action='toggle-composer-mode']");
    if (input) input.value = safeMode;
    picker.querySelector("[data-mode-label]").textContent = label;
    const currentIcon = picker.querySelector(".mode-trigger .mode-option-icon");
    if (currentIcon) currentIcon.outerHTML = uiIcon(composerModeIcons[safeMode], "mode-option-icon");
    trigger?.setAttribute("aria-label", `选择研究模式，当前${label}`);
    picker.querySelectorAll("[data-mode-value]").forEach((option) => {
      const selected = option.dataset.modeValue === safeMode;
      option.classList.toggle("is-selected", selected);
      option.setAttribute("aria-selected", String(selected));
    });
  });
  syncSlideTemplateDocks();
}

function selectedSlideTemplate() {
  return state.slideTemplates.find((item) => item.id === state.selectedSlideTemplateId) || state.slideTemplates[0] || null;
}

function previewSlideTemplate() {
  return state.slideTemplates.find((item) => item.id === state.previewSlideTemplateId) || selectedSlideTemplate();
}

function syncSlideTemplateDocks() {
  const template = selectedSlideTemplate();
  document.querySelectorAll("[data-slide-template-dock]").forEach((dock) => {
    const key = dock.dataset.composerKey || "home";
    const mode = byId(`${key}ModeSelect`)?.value || "general";
    // Source-to-PPT is a first-class presentation flow as well: choosing a
    // source must not make template selection disappear.
    dock.hidden = mode !== "slides";
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
  state.selectedSlideTemplateId = template.id;
  window.localStorage.setItem("scansci.slides.template", template.id);
  syncSlideTemplateDocks();
  closeSlideTemplateDialog();
  if (state.activeView === "mode" && state.activeMode === "ppt") renderMode();
  toast(`已选择「${template.name}」`);
}

async function createResearchRun(workflowType, input = {}) {
  const standalone = workflowType === "pdf_to_ppt" || workflowType === "paper_download";
  if (!state.notebook && !standalone) throw new Error("请先打开一个资料库");
  return request("/api/runs", {
    method: "POST",
    body: JSON.stringify({ workflow_type: workflowType, ...(state.notebook ? { notebook_id: state.notebook.notebook_id } : {}), ...input, thinking_level: currentThinkingLevel() }),
  });
}

async function continueTaskConversation(runId, content) {
  return request(`/api/runs/${encodeURIComponent(runId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ content, thinking_level: currentThinkingLevel() }),
  });
}

async function watchRun(runId, onUpdate = () => {}) {
  let run = state.runs.find((item) => item.run_id === runId);
  const terminal = new Set(["completed", "failed", "cancelled", "paused", "needs_confirmation"]);
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
  setContextPanel("sources");
  const reader = result.reader_answer || {};
  const sentences = reader.sentences || [];
  const answerMarkup = sentences.length ? sentences.map((sentence) => {
    const citations = (sentence.citation_ids || []).map(citationMarkerMarkup).join("");
    return `<p class="answer-sentence">${escapeHtml(sentence.text)} ${citations}</p>`;
  }).join("") : '<p class="answer-sentence">当前资料不足以生成可核验回答。</p>';
  const limitations = (result.answer?.limitations || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const sufficient = result.adequacy?.is_sufficient;
  byId("answerArea").innerHTML = `<article class="conversation-thread"><div class="user-turn"><p>${escapeHtml(result.question)}</p></div><div class="assistant-turn"><div class="answer-meta"><span>ScanSci</span><b>${sufficient ? "资料可支持" : "资料不足"}</b></div>${answerMarkup}${limitations ? `<div class="answer-limitations"><strong>限制</strong><ul>${limitations}</ul></div>` : ""}</div></article>`;
  bindCitationInteractions(result);
  byId("answerArea").scrollTop = byId("answerArea").scrollHeight;
}

function renderRun(run) {
  const renderKey = JSON.stringify({
    runId: run.run_id,
    status: run.status,
    progress: Math.round(Number(run.progress || 0) * 100),
    stages: (run.stages || []).map((stage) => [stage.stage_id, stage.status, stage.summary, stage.error_message]),
    artifact: run.output_artifact?.file_path || run.output_artifact?.summary || "",
    messages: (run.messages || []).map((message) => [message.message_id, message.role, message.content, message.processing_ms]),
  });
  if (state.lastRunRenderKey === renderKey) return;
  state.lastRunRenderKey = renderKey;
  const answerArea = byId("answerArea");
  const distanceFromBottom = answerArea.scrollHeight - answerArea.scrollTop - answerArea.clientHeight;
  const shouldFollow = distanceFromBottom < 72;
  byId("conversationTitle").textContent = run.workflow_type === "literature_review" ? "文献综述" : compact(runDisplayTitle(run), 80);
  const percent = Math.round((run.progress || 0) * 100);
  const stageCalls = new Map((run.tool_calls || []).map((call) => [call.stage_id, call]));
  const stages = (run.stages || []).map((stage) => {
    const call = stageCalls.get(stage.stage_id);
    const detail = stage.error_message || stage.summary || (call ? `${call.tool_name}${call.status === "running" ? " · 调用中" : ""}` : "等待执行");
    return `<li class="run-stage ${escapeHtml(stage.status)}"><span class="stage-node">${stage.status === "completed" ? "✓" : stage.status === "running" ? "·" : stage.status === "failed" ? "!" : stage.position + 1}</span><div><strong>${escapeHtml(stage.title)}</strong><small>${escapeHtml(detail)}</small></div>${call ? `<code>${escapeHtml(call.tool_name)}</code>` : ""}</li>`;
  }).join("");
  const artifact = run.output_artifact;
  let resultMarkup = "";
  if (artifact?.payload && ["evidence_answer", "literature_review"].includes(artifact.artifact_type)) {
    resultMarkup = evidenceArtifactMarkup(artifact.payload);
  } else if (artifact?.payload && ["slide_outline", "slide_deck_project", "presentation_deck"].includes(artifact.artifact_type)) {
    resultMarkup = slideProjectArtifactMarkup(artifact.payload, run.run_id);
  } else if (artifact) {
    resultMarkup = genericArtifactMarkup(artifact);
  } else if (run.status === "failed") {
    resultMarkup = `<div class="run-state-message is-error"><strong>这个阶段没有完成</strong><p>${escapeHtml(run.error?.message || "执行失败，可从当前阶段重新继续。")}</p></div>`;
  } else if (run.status === "cancelled") {
    resultMarkup = '<div class="run-state-message"><strong>任务已停止</strong><p>已完成的阶段和工具记录仍然保留，可以继续。</p></div>';
  } else if (run.status === "paused") {
    resultMarkup = `<div class="run-state-message"><strong>任务已暂停</strong><p>${escapeHtml(run.error?.message || "可以从当前阶段继续。")}</p></div>`;
  } else {
    resultMarkup = `<div class="run-live"><span></span><div><strong>${escapeHtml(runStatusLabel(run))}</strong><p>${escapeHtml((run.stages || []).find((stage) => stage.status === "running")?.title || "正在准备下一阶段")}</p></div></div>`;
  }
  const actions = [
    run.cancellable ? `<button type="button" class="run-action stop" data-action="cancel-run" data-run-id="${escapeHtml(run.run_id)}">停止</button>` : "",
    run.resumable ? `<button type="button" class="run-action" data-action="resume-run" data-run-id="${escapeHtml(run.run_id)}">继续</button>` : "",
  ].join("");
  if (run.workflow_type === "literature_review") {
    const reviewModel = artifact?.payload ? buildReviewDocumentModel(run, artifact) : null;
    state.reviewDocument = reviewModel;
    setContextPanel("review");
    renderReviewDocument(run, artifact, reviewModel);
    byId("answerArea").innerHTML = reviewTaskMarkup(run, reviewModel, { percent, stages, actions });
    byId("answerArea").scrollTop = run.status === "completed" ? 0 : byId("answerArea").scrollHeight;
    return;
  }
  state.reviewDocument = null;
  // A source-to-PPT task has no citation panel to interact with. Keeping it
  // closed gives the generated deck room and prevents an empty panel from
  // looking like an unfinished result.
  setContextPanel(run.workflow_type === "pdf_to_ppt" ? "none" : "sources");
  byId("answerArea").innerHTML = `<article class="run-shell"><div class="user-turn"><div>${composerSourcePreviewMarkup(run.input?.source_files || [])}${composerImagePreviewMarkup(run.input?.images || [])}<p>${escapeHtml(run.input?.question || run.title)}</p></div></div><section class="run-card"><header class="run-card-head"><div><span class="run-kind">${escapeHtml(({ ask: "证据问答", literature_review: "文献综述", ppt_outline: "幻灯片大纲", ppt_project: "EasySlides", pdf_to_ppt: "PPTX" })[run.workflow_type] || "科研任务")}</span><h2>${escapeHtml(run.title)}</h2></div><div class="run-head-actions"><span class="run-status ${escapeHtml(run.status)}">${escapeHtml(runStatusLabel(run))}</span>${actions}</div></header><div class="run-progress"><i style="width:${percent}%"></i></div><ol class="run-stage-list">${stages}</ol></section><section class="run-result">${resultMarkup}</section></article>`;
  const taskConversation = taskConversationMarkup(run);
  if (taskConversation) answerArea.querySelector(".run-shell")?.insertAdjacentHTML("beforeend", taskConversation);
  bindRunCitations(artifact?.payload || {});
  if (shouldFollow) answerArea.scrollTop = answerArea.scrollHeight;
}

function taskConversationMarkup(run) {
  const messages = Array.isArray(run.messages) ? run.messages : [];
  if (!messages.length) return "";
  const turns = messages.map((message) => {
    if (message.role === "user") {
      return `<div class="user-turn"><div class="user-turn-bubble"><p>${escapeHtml(message.content)}</p></div></div>`;
    }
    const processing = Number(message.processing_ms || 0) > 0
      ? `<div class="answer-processing">已处理 <time>${formatProcessingDuration(message.processing_ms)}</time><span aria-hidden="true">›</span></div>`
      : "";
    return `<div class="assistant-turn direct-answer"><div class="answer-meta"><span>ScanSci Pi</span><b>PPT 任务续聊</b></div>${processing}<p class="answer-sentence">${escapeHtml(message.content)}</p>${answerUsageMarkup(message.usage)}</div>`;
  }).join("");
  return `<section class="task-conversation" aria-label="PPT 任务续聊"><div class="task-conversation-head"><span>任务续聊</span><small>继续提问会保留在此 PPT 任务中</small></div><div class="conversation-thread">${turns}</div></section>`;
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
  state.activeSlidePlan = payload.slide_plan || null;
  if (payload.pptx_path) {
    const download = runId ? `<button type="button" class="primary-button slide-download-button" data-action="save-presentation" data-presentation-path="${escapeHtml(payload.pptx_path)}" data-presentation-name="${escapeHtml(payload.download_name || "ScanSci-演示文稿.pptx")}">下载 PPTX</button>` : "";
    const enhancedDownload = payload.slide_plan ? '<button type="button" class="secondary-button slide-enhanced-button" data-action="export-pptxgenjs">重新排版导出</button>' : "";
    const sourceNames = (payload.sources || []).map((source) => source.name).filter(Boolean).join(" · ");
    const preview = runId
      ? `<img class="slide-project-cover" src="/api/runs/${encodeURIComponent(runId)}/preview" alt="${escapeHtml(outline.title || "演示文稿预览")}" />`
      : (template?.preview_url ? `<img class="slide-project-cover" src="${escapeHtml(template.preview_url)}" alt="${escapeHtml(template.name || "所选模板预览")}" />` : `<div class="slide-project-cover">${uiIcon("presentation")}<b>PPTX</b></div>`);
    const templateName = template?.name ? ` · ${template.name}` : "";
    return `<div class="slide-project-artifact is-pptx">${preview}<div class="slide-project-copy"><span>ScanSci Presentation Studio</span><h3>${escapeHtml(outline.title || "科研幻灯片")}</h3><p>${escapeHtml(`${slides.length} 页${templateName} · ${payload.planning?.mode === "skill-aware-model" ? "已应用内置科研技能" : "基于源文件生成"}`)}</p>${sourceNames ? `<small>${escapeHtml(sourceNames)}</small>` : ""}<p class="slide-export-hint">“下载 PPTX”保存当前成品；“重新排版导出”用新版排版器生成另一份可编辑 PPTX。</p><div class="slide-download-actions">${enhancedDownload}${download}</div></div></div>`;
  }
  const preview = template?.preview_url ? `<img class="slide-project-cover" src="${escapeHtml(template.preview_url)}" alt="${escapeHtml(template.name || "幻灯片模板")}" />` : '<div class="slide-project-cover"></div>';
  const slideSummary = slides.length ? `${slides.length} 页 · ${outline.evidence_linked ? "已绑定来源" : "待绑定来源"}` : "EasySlides 项目";
  return `<div class="slide-project-artifact">${preview}<div class="slide-project-copy"><span>EasySlides project</span><h3>${escapeHtml(template?.name || "学术幻灯片")}</h3><p>${escapeHtml(slideSummary)}</p>${payload.project_path ? `<code title="${escapeHtml(payload.project_path)}">${escapeHtml(payload.project_path)}</code>` : ""}</div></div>`;
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

function normalizeReviewParagraph(value, index = 0) {
  if (typeof value === "string") return { id: `paragraph-${index + 1}`, text: value, citation_ids: [] };
  return {
    id: String(value?.id || `paragraph-${index + 1}`),
    text: String(value?.text || value?.rendered_text || ""),
    citation_ids: (value?.citation_ids || []).map(String),
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

function runDisplayTitle(run) {
  if (run?.workflow_type !== "literature_review") return String(run?.title || "未命名研究");
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
  const documentCount = Number(payload.adequacy?.document_count || new Set(citations.map((item) => item.doc_id).filter(Boolean)).size || 0);
  const verified = !legacy && Boolean(payload.citation_verification?.passed ?? payload.answer?.citation_verification?.passed ?? payload.verification?.supported_claims?.length);
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
    documentCount,
    citationCount: Number(reader.citation_count || citations.length || 0),
    verified,
    legacy,
    generatedAt: artifact?.created_at || run.updated_at || "",
  };
  model.outline = [
    { id: "review-abstract", title: "摘要" },
    ...sections.map((section) => ({ id: section.id, title: section.title })),
    ...(comparisonTable.rows.length ? [{ id: "review-comparison", title: "研究对比" }] : []),
    ...(controversies.length ? [{ id: "review-controversies", title: "证据分歧与争议" }] : []),
    ...(openQuestions.length ? [{ id: "review-open-questions", title: "开放问题" }] : []),
    { id: "review-limitations", title: "证据边界" },
    { id: "review-references", title: "参考文献" },
  ];
  model.markdown = reviewDocumentMarkdown(model);
  return model;
}

function reviewDocumentMarkdown(model) {
  const citationSuffix = (ids = []) => ids.length ? ` ${ids.map((id) => `[${id}]`).join("")}` : "";
  const lines = [
    `# ${model.title}`,
    "",
    "## 摘要",
    "",
    `${model.abstract.text}${citationSuffix(model.abstract.citation_ids)}`,
  ];
  model.sections.forEach((section) => {
    lines.push("", `## ${section.title}`, "");
    section.paragraphs.forEach((paragraph) => lines.push(`${paragraph.text}${citationSuffix(paragraph.citation_ids)}`, ""));
  });
  if (model.comparisonTable.rows.length) {
    const escapeCell = (value) => String(value).replaceAll("|", "\\|").replaceAll("\n", " ");
    const tableHeaders = [...model.comparisonTable.columns, "证据"];
    lines.push("", "## 研究对比", "", `| ${tableHeaders.map(escapeCell).join(" | ")} |`, `| ${tableHeaders.map(() => "---").join(" | ")} |`);
    model.comparisonTable.rows.forEach((row) => lines.push(`| ${[...row.cells, citationSuffix(row.citation_ids).trim()].map(escapeCell).join(" | ")} |`));
  }
  if (model.controversies.length) {
    lines.push("", "## 证据分歧与争议", "");
    model.controversies.forEach((item) => lines.push(`- ${item.text}${citationSuffix(item.citation_ids)}`));
  }
  if (model.openQuestions.length) {
    lines.push("", "## 开放问题", "");
    model.openQuestions.forEach((item) => lines.push(`- ${item.text}${citationSuffix(item.citation_ids)}${item.basis ? `\n  - 依据：${item.basis}` : ""}`));
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
  const failure = run.status === "failed" ? `<div class="review-workflow-error"><strong>综述没有生成</strong><p>${escapeHtml(run.error?.message || "写作阶段执行失败，请检查模型与资料范围。")}</p><button type="button" data-action="open-settings" data-settings-panel="models">配置写作模型</button></div>` : "";
  return `<article class="review-task-shell"><div class="review-agent-head"><div class="review-agent-identity"><img src="/scansci-mark.png" alt="" /><span>ScanSci 写作智能体</span></div><span class="review-agent-meta">${percent}% · ${escapeHtml(runStatusLabel(run))}</span></div>${failure}<section class="review-outline-card"><span>Review outline</span><h2>${escapeHtml(model?.title || runDisplayTitle(run))}</h2><ol class="review-outline-list">${outlineMarkup}</ol><div class="review-run-actions">${actions}<button type="button" class="review-open-document" data-action="open-review-document" ${model ? "" : "disabled"}>打开稿件</button></div></section><details class="review-steps"><summary>${escapeHtml(summary)}<span>${completed}/${total}</span></summary><ol class="run-stage-list">${stages}</ol></details></article>`;
}

function renderReviewDocument(run, artifact, model = null) {
  const target = byId("reviewDocumentPanel");
  if (!target) return;
  const ready = Boolean(model);
  const title = ready ? "综述稿件" : compact(runDisplayTitle(run) || "正在生成综述", 72);
  const summary = ready ? (model.legacy ? "旧版任务 · 仅包含证据摘录，请重新生成" : `${model.documentCount} 篇来源 · ${model.citationCount} 个证据锚点${model.verified ? " · 引用已核验" : ""}`) : "研究步骤完成后将在这里形成可编辑稿件";
  const tabButtons = `<nav class="review-document-tabs" aria-label="稿件视图"><button type="button" class="is-active" data-action="review-document-tab" data-review-tab="preview" ${ready ? "" : "disabled"}>预览</button><button type="button" data-action="review-document-tab" data-review-tab="source" ${ready ? "" : "disabled"}>Markdown</button></nav>`;
  const toolbar = `<header class="review-panel-toolbar"><div class="review-document-identity"><span class="review-file-icon">${uiIcon("file-plus")}</span><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(summary)}</small></div></div><div class="review-toolbar-cluster">${tabButtons}<div class="review-toolbar-actions"><button type="button" class="review-icon-button" data-action="copy-review-document" aria-label="复制稿件" title="复制稿件" ${ready ? "" : "disabled"}>${uiIcon("copy")}</button><button type="button" class="review-icon-button" data-action="refresh-review-document" aria-label="刷新稿件" title="刷新稿件">${uiIcon("refresh")}</button><button type="button" class="review-icon-button" data-action="download-review-document" aria-label="下载 Markdown" title="下载 Markdown" ${ready ? "" : "disabled"}>${uiIcon("download")}</button><button type="button" class="review-icon-button" data-action="close-review-document" aria-label="关闭稿件" title="关闭稿件">${uiIcon("x")}</button></div></div></header>`;
  if (!ready) {
    const failed = run.status === "failed";
    target.innerHTML = `${toolbar}<div class="review-document-body"><div class="review-document-empty ${failed ? "is-error" : ""}"><div>${failed ? "" : "<span></span>"}<strong>${escapeHtml(failed ? "未生成稿件" : runStatusLabel(run))}</strong><p>${escapeHtml(failed ? (run.error?.message || "请检查写作模型配置后继续任务。") : "正在整理结构、引用与证据锚点")}</p></div></div></div>`;
    return;
  }
  const sections = model.sections.map((section) => `<section id="${escapeHtml(section.id)}"><h2>${escapeHtml(section.title)}</h2>${section.paragraphs.map((paragraph) => `<p>${escapeHtml(paragraph.text)}${reviewCitationButtons(paragraph.citation_ids)}</p>`).join("")}</section>`).join("");
  const comparison = model.comparisonTable.rows.length ? `<section id="review-comparison"><h2>研究对比</h2><div class="review-table-wrap"><table class="review-comparison-table"><thead><tr>${model.comparisonTable.columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}<th>证据</th></tr></thead><tbody>${model.comparisonTable.rows.map((row) => `<tr>${row.cells.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}<td class="review-table-citations">${reviewCitationButtons(row.citation_ids)}</td></tr>`).join("")}</tbody></table></div></section>` : "";
  const controversies = model.controversies.length ? `<section id="review-controversies"><h2>证据分歧与争议</h2><div class="review-finding-list">${model.controversies.map((item, index) => `<article><span>${String(index + 1).padStart(2, "0")}</span><p>${escapeHtml(item.text)}${reviewCitationButtons(item.citation_ids)}</p></article>`).join("")}</div></section>` : "";
  const openQuestions = model.openQuestions.length ? `<section id="review-open-questions"><h2>开放问题</h2><div class="review-question-grid">${model.openQuestions.map((item, index) => `<article><span>Q${index + 1}</span><h3>${escapeHtml(item.text)}${reviewCitationButtons(item.citation_ids)}</h3>${item.basis ? `<p>${escapeHtml(item.basis)}</p>` : ""}</article>`).join("")}</div></section>` : "";
  const limitations = model.limitations.length ? model.limitations.map((item) => `<p>${escapeHtml(item)}</p>`).join("") : "<p>本综述仅综合当前项目资料库中的可核验证据；未覆盖的研究方向不代表不存在相关工作。</p>";
  const references = model.citations.length ? model.citations.map((citation) => `<li><strong>${escapeHtml(citation.paper)}</strong><span>${escapeHtml([citation.section, citation.doi].filter(Boolean).join(" · "))}</span><br /><button type="button" data-action="open-review-citation" data-citation-id="${escapeHtml(citation.citation_id)}">查看证据与原文锚点</button></li>`).join("") : "<li>当前稿件没有可回跳引用。</li>";
  const legacyNotice = model.legacy ? `<div class="review-legacy-notice"><strong>这不是完整综述</strong><p>该任务由旧版流程生成，只包含检索摘录。请回到写作模式重新生成，新的流程会完成章节检索、跨论文比较、争议分析和开放问题。</p></div>` : "";
  const preview = `<div class="review-document-view review-preview-view is-active" data-review-view="preview"><article class="review-paper"><div class="review-paper-kicker">Evidence-linked review <span>${model.legacy ? "Legacy draft" : model.verified ? "Verified" : "Needs review"}</span></div><h1>${escapeHtml(model.title)}</h1><div class="review-paper-meta"><span><b>${model.documentCount}</b> 篇来源</span><span><b>${model.citationCount}</b> 个证据锚点</span><span>${model.verified ? "引用核验通过" : model.legacy ? "旧版摘录" : "建议人工复核"}</span></div>${legacyNotice}<section id="review-abstract"><h2>摘要</h2><p class="review-lead">${escapeHtml(model.abstract.text)}${reviewCitationButtons(model.abstract.citation_ids)}</p></section>${sections}${comparison}${controversies}${openQuestions}<section id="review-limitations"><h2>证据边界</h2><div class="review-limitations">${limitations}</div></section><section id="review-references"><h2>参考文献</h2><ol class="review-reference-list">${references}</ol></section></article></div>`;
  const source = `<div class="review-document-view review-source-view" data-review-view="source"><pre><code>${escapeHtml(model.markdown)}</code></pre></div>`;
  target.innerHTML = `${toolbar}<div class="review-document-body">${preview}${source}<aside class="review-evidence-drawer" id="reviewEvidenceDrawer" aria-live="polite"></aside></div>`;
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
  const filePath = artifact.file_path ? `<code class="artifact-path">${escapeHtml(artifact.file_path)}</code>` : "";
  const external = payload.external_url ? `<button type="button" class="secondary-button" data-action="open-external" data-url="${escapeHtml(payload.external_url)}">在网页中继续 ↗</button>` : "";
  return `<article class="artifact-card"><span class="artifact-type">${escapeHtml(artifact.artifact_type)}</span><h3>${escapeHtml(artifact.title)}</h3><p>${escapeHtml(artifact.summary || payload.message || "研究产物已保存")}</p>${filePath}${rowMarkup}${external}</article>`;
}

function bindRunCitations(result) {
  bindCitationInteractions(result);
}

async function openTask(id, { record = true } = {}) {
  try {
    const run = await request(`/api/runs/${encodeURIComponent(id)}`);
    upsertRun(run);
    state.activeTaskId = run.run_id;
    if (run.workflow_type === "pdf_to_ppt") {
      const composer = byId("chatQuestionInput");
      if (composer) composer.placeholder = "通用模式可继续讨论；幻灯片模式可选择模板后重新制作";
    }
    byId("conversationTitle").textContent = run.workflow_type === "literature_review" ? "文献综述" : compact(runDisplayTitle(run), 80);
    setView("conversation", { record });
    renderRun(run);
    if (!["completed", "failed", "cancelled", "paused"].includes(run.status)) {
      watchRun(run.run_id, (next) => {
        if (state.activeView === "conversation" && state.activeTaskId === next.run_id) renderRun(next);
      });
    }
  } catch (error) {
    toast(error.message, true);
  }
}

const modeDefinitions = {
  library: { overline: "本地研究空间", title: "知识库" },
  tools: { overline: "ScanSci Suite", title: "轻工具" },
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
  if (state.activeMode === "library") target.innerHTML = renderLibraryMode();
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

function libraryKindCopy(kind) {
  if (kind === "obsidian") return { title: "Obsidian Vault", detail: "Markdown 笔记知识库", icon: "book" };
  return { title: "本地文件夹", detail: "HTML / Markdown 知识库", icon: "folder-open" };
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
  const sources = state.notebook?.sources || [];
  const notes = state.notebook?.notes || [];
  const rootPath = String(state.notebook?.root_path || "");
  const metadata = state.notebook?.metadata || {};
  const libraryKind = String(metadata.library_kind || "folder");
  const zotero = metadata.zotero && typeof metadata.zotero === "object" ? metadata.zotero : null;
  const zoteroTitles = Array.isArray(zotero?.sample_titles) ? zotero.sample_titles : [];
  const sourceBooks = sources.slice(0, 30).map((source, index) => libraryBookMarkup(source, index)).join("");
  const zoteroBooks = zoteroTitles.slice(0, 6).map((title, index) => libraryBookMarkup({ title }, index + 2, { external: true })).join("");
  const emptyShelf = `<button type="button" class="knowledge-empty-shelf" data-action="choose-library-folder">${uiIcon("folder-open")}<span>从本地文件夹建立第一个知识库</span></button>`;
  const remainder = sources.length > 30 ? `<span class="knowledge-shelf-remainder">+${sources.length - 30}</span>` : "";
  const zoteroCollection = zotero?.connected || zotero?.path
    ? `<article class="knowledge-collection zotero-collection"><span class="knowledge-collection-icon">${uiIcon("book")}</span><div><small>外部文献书架</small><h3>Zotero 文献库</h3><p>${zotero?.connection === "local-api" ? "本机 Zotero" : escapeHtml(pathLeaf(String(zotero.path)))} · ${Number(zotero.item_count || zotero.pdf_count || 0)} 条文献</p></div><button type="button" data-action="choose-zotero-library">重新连接</button></article>`
    : `<button type="button" class="knowledge-collection zotero-collection is-empty" data-action="choose-zotero-library"><span class="knowledge-collection-icon">${uiIcon("book")}</span><span><small>外部文献书架</small><strong>连接 Zotero 文献库</strong><em>保留本机 PDF，不移动原文件</em></span><i>${uiIcon("plus")}</i></button>`;
  const notebookCollections = (state.workspace?.notebooks || []).map((notebook) => {
    const notebookKind = libraryKindCopy(String(notebook.metadata?.library_kind || "folder"));
    const active = notebook.notebook_id === state.notebook?.notebook_id;
    return `<article class="knowledge-collection ${active ? "is-active" : ""}"><span class="knowledge-collection-icon">${uiIcon(notebookKind.icon)}</span><div><small>${active ? "当前知识库" : "本地知识库"}</small><h3>${escapeHtml(notebook.title || pathLeaf(notebook.root_path))}</h3><p title="${escapeHtml(notebook.root_path || "")}">${escapeHtml(pathLeaf(notebook.root_path))} · ${Number(notebook.counts?.sources || 0)} 篇来源</p></div><button type="button" data-action="select-notebook" data-notebook-id="${escapeHtml(notebook.notebook_id)}">${active ? "已选择" : "打开"}</button></article>`;
  }).join("");
  return `<section class="knowledge-library"><header class="knowledge-library-hero"><div><span>SEARCH SCIENCE · LOCAL FIRST</span><h2>我的知识书架</h2><p>把 Obsidian 笔记、本地文件夹和 Zotero 文献放进同一个研究空间。</p></div><div class="knowledge-library-stat"><b>${sources.length}</b><span>当前库来源</span><i>${(state.workspace?.notebooks || []).length} 个知识库</i></div></header><section class="knowledge-import-grid" aria-label="导入知识库"><button type="button" class="knowledge-import-card obsidian" data-action="choose-obsidian-vault"><span>${uiIcon("book")}</span><strong>导入 Obsidian Vault</strong><p>递归读取 Markdown 笔记，保留原有文件夹层级。</p><em>选择 Vault ${uiIcon("chevron-right")}</em></button><button type="button" class="knowledge-import-card folder" data-action="choose-library-folder"><span>${uiIcon("folder-open")}</span><strong>从文件夹建立知识库</strong><p>PDF、Office、网页和文本会统一解析为可追溯证据。</p><em>选择文件夹 ${uiIcon("chevron-right")}</em></button><button type="button" class="knowledge-import-card zotero" data-action="choose-zotero-library"><span>${uiIcon("library")}</span><strong>连接本机 Zotero</strong><p>直接读取 Zotero 7 本机接口，不需要 API 密钥或选择 storage 文件夹。</p><em>连接 Zotero ${uiIcon("chevron-right")}</em></button></section><section class="knowledge-collections">${notebookCollections || `<button type="button" class="knowledge-collection is-empty" data-action="choose-library-folder"><span class="knowledge-collection-icon">${uiIcon("folder-open")}</span><span><small>本地知识库</small><strong>建立第一个知识库</strong><em>选择一个文献文件夹</em></span><i>${uiIcon("plus")}</i></button>`}${zoteroCollection}</section><section class="knowledge-shelf"><header><div><span>SEARCHABLE SHELF</span><h3>${escapeHtml(pathLeaf(rootPath))}</h3></div><div><button type="button" data-action="choose-library-files">添加文献</button><span>${sources.length} 册</span></div></header><div class="knowledge-books">${sourceBooks || emptyShelf}${remainder}</div></section>${zotero?.connected || zotero?.path ? `<section class="knowledge-shelf knowledge-zotero-shelf"><header><div><span>ZOTERO · READ ONLY</span><h3>${zotero?.connection === "local-api" ? "本机 Zotero 文献" : escapeHtml(pathLeaf(String(zotero.path)))}</h3></div><div><button type="button" data-action="choose-zotero-library">刷新</button><span>${Number(zotero.item_count || zotero.pdf_count || 0)} 条文献</span></div></header><div class="knowledge-books is-external">${zoteroBooks || '<div class="knowledge-shelf-placeholder">已连接 Zotero；文献标题会在这里出现。</div>'}</div></section>` : ""}</section>`;
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
  const sourceCount = state.notebook?.counts?.sources || 0;
  return `${modeIntro("先构建问题与证据矩阵，再写段落；每个结论保留原文跳转。", `${sourceCount} 篇来源`)}
    <section class="workflow-strip"><div><b>1</b><span>定义问题</span></div><div><b>2</b><span>检索证据</span></div><div><b>3</b><span>比较研究</span></div><div><b>4</b><span>写作与核验</span></div></section>
    <form class="mode-form review-form" id="reviewAskForm"><label><span>综述问题</span><textarea id="reviewQuestionInput" rows="4" placeholder="例如：AI 在生态监测中的主要应用、证据强度与研究空白是什么？"></textarea></label><button type="submit" class="primary-button">开始证据检索</button></form>`;
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
  return `<section class="paper-fetch-stage"><div class="paper-fetch-card"><span class="paper-fetch-eyebrow">SCANSCI · FULL TEXT</span><h1>获取论文全文</h1><p>输入 DOI 或 arXiv ID，优先从开放获取与灰色文献存档中查找可直接保存的 PDF。</p><form id="paperDownloadForm" class="paper-fetch-composer"><input id="paperIdentifier" required placeholder="输入 DOI 或 arXiv ID，例如 10.1038/..." autofocus /><button type="submit">获取</button></form><div class="paper-fetch-options"><label>来源策略<select id="downloadStrategy"><option value="oa_first">开放获取优先</option><option value="gray_oa">灰色文献与开放存档</option><option value="legal_only">仅开放与出版商直链</option></select></label><span>保存至 ${escapeHtml(directory)}</span></div><p class="paper-fetch-footnote">无需资料库、无需模型 API。灰色文献包括机构仓储、预印本和公开报告；不会绕过付费墙。</p></div><div class="mode-results paper-fetch-results" id="modeResults"></div></section>`;
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

function renderSettings() {
  if (state.activeSettings === "routing") state.activeSettings = "general";
  document.querySelectorAll(".settings-nav").forEach((button) => button.classList.toggle("is-active", button.dataset.settingsPanel === state.activeSettings));
  const target = byId("settingsContent");
  if (!state.settings) {
    target.innerHTML = '<div class="error-state">设置尚未载入。</div>';
    return;
  }
  if (state.activeSettings === "models") target.innerHTML = renderModelsSettings();
  else if (state.activeSettings === "local-models") target.innerHTML = renderLocalModelsSettings();
  else if (state.activeSettings === "document-processing") target.innerHTML = renderDocumentProcessingSettings();
  else if (state.activeSettings === "skills") target.innerHTML = renderRecordsSettings("skills");
  else if (state.activeSettings === "mcp") target.innerHTML = renderMcpMarketplaceSettings();
  else if (state.activeSettings === "plugins") target.innerHTML = renderRecordsSettings("plugins");
  else if (state.activeSettings === "about") target.innerHTML = renderAboutSettings();
  else target.innerHTML = renderGeneralSettings();
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
  return `<div class="extension-detail-backdrop" data-action="close-extension-detail"><section class="extension-detail-card" data-action="extension-detail-content" role="dialog" aria-modal="true" aria-label="${escapeHtml(item.name)} 详情"><header><div class="extension-record-mark ${detail.kind === "skills" ? "skill-mark" : "plugin-mark"}">${uiIcon(detail.kind === "skills" ? "wand" : "puzzle")}</div><div><span>${title}</span><h2>${escapeHtml(item.name)}</h2></div><button type="button" data-action="close-extension-detail" aria-label="关闭">${uiIcon("x")}</button></header><p>${escapeHtml(item.description || "尚未添加说明")}</p><dl><div><dt>原始名称</dt><dd><code>${escapeHtml(item.id)}</code></dd></div><div><dt>来源</dt><dd><code>${escapeHtml(source)}</code></dd></div><div><dt>状态</dt><dd>${item.enabled ? "已启用" : "已停用"}</dd></div></dl><footer><button type="button" class="extension-remove" data-action="uninstall-extension" data-extension-kind="${detail.kind}" data-extension-id="${escapeHtml(item.id)}">卸载</button><label class="extension-switch"><input type="checkbox" data-action="toggle-record" data-record-kind="${detail.kind}" data-record-id="${escapeHtml(item.id)}" ${item.enabled ? "checked" : ""} /><span>${item.enabled ? "启用" : "已停用"}</span></label></footer></section></div>`;
}

function renderExtensionPlugins(plugins) {
  const rows = plugins.length ? plugins.map((plugin) => `<article class="extension-record"><button type="button" class="extension-record-main" data-action="open-extension-detail" data-extension-kind="plugins" data-extension-id="${escapeHtml(plugin.id)}"><div class="extension-record-mark plugin-mark">${uiIcon("puzzle")}</div><div class="extension-record-copy"><div class="extension-record-title"><h3>${escapeHtml(plugin.name)}</h3><span>插件</span></div><p>${escapeHtml(plugin.description || "尚未添加说明")}</p><code>${escapeHtml(plugin.source || "未指定来源")}</code></div></button><div class="extension-record-actions"><label class="extension-switch"><input type="checkbox" data-action="toggle-record" data-record-kind="plugins" data-record-id="${escapeHtml(plugin.id)}" ${plugin.enabled ? "checked" : ""} /><span>${plugin.enabled ? "启用" : "已停用"}</span></label></div></article>`).join("") : `<div class="extension-empty"><span>${uiIcon("puzzle")}</span><strong>还没有插件来源</strong><p>登记受信任的本地路径或远程来源后，可在这里统一启停和维护。</p></div>`;
  return `<div class="extension-panel-head"><div><p class="panel-kicker">PLUGINS</p><h2>插件</h2><p>插件来源与技能包分开管理；MCP 服务仍在设置中单独配置。</p></div><span class="panel-count">${plugins.length} 项</span></div>
    <section class="extension-record-list">${rows}</section>
    <form class="extension-form plugin-form" id="extensionPluginForm"><div class="extension-form-copy"><strong>登记插件来源</strong><span>仅保存元数据，不会自动启动或执行插件。</span></div><label><span>名称</span><input name="plugin-name" required maxlength="100" placeholder="例如：文献管理连接器" /></label><label><span>来源</span><input name="plugin-source" required maxlength="500" placeholder="本地路径或受信任的插件地址" /></label><label class="extension-form-wide"><span>说明（可选）</span><input name="plugin-description" maxlength="400" placeholder="它会为研究流程提供什么能力？" /></label><button type="submit" class="extension-primary">登记插件</button></form>`;
}

function renderExtensionSkills(skills) {
  const rows = skills.length ? skills.map((skill) => {
    const sourceLabel = skill.builtin ? "内置能力" : ({ local: "本地导入", git: "Git 仓库", archive: "压缩包", marketplace: "skills.sh 市场" }[skill.source_type] || "手动登记");
    const status = skill.available ? "可用" : "缺少文件";
    return `<article class="extension-record skill-record"><button type="button" class="extension-record-main" data-action="open-extension-detail" data-extension-kind="skills" data-extension-id="${escapeHtml(skill.id)}"><div class="extension-record-mark skill-mark">${uiIcon("wand")}</div><div class="extension-record-copy"><div class="extension-record-title"><h3>${escapeHtml(skill.id)}</h3><span>${escapeHtml(sourceLabel)}</span></div><p>${escapeHtml(skill.description || "尚未添加说明")}</p><code>${escapeHtml(skill.path || "未指定路径")}</code></div></button><div class="extension-record-actions"><span class="extension-status ${skill.available ? "is-ready" : "is-missing"}">${status}</span><label class="extension-switch"><input type="checkbox" data-action="toggle-record" data-record-kind="skills" data-record-id="${escapeHtml(skill.id)}" ${skill.enabled ? "checked" : ""} /><span>${skill.enabled ? "启用" : "已停用"}</span></label></div></article>`;
  }).join("") : `<div class="extension-empty"><span>${uiIcon("wand")}</span><strong>还没有可用技能</strong><p>从本地文件夹、Git 仓库、压缩包或市场中安装一个 Skill。</p></div>`;
  return `<div class="extension-panel-head"><div><p class="panel-kicker">SKILLS</p><h2>技能</h2><p>每个包以 <code>SKILL.md</code> 为入口，统一复制到当前工作区旁的本地技能库。</p></div><span class="panel-count">${skills.length} 项</span></div>
    <form class="skill-install-form" id="skillInstallForm"><div class="skill-install-copy"><span class="skill-install-spark">＋</span><div><strong>安装 Skill</strong><p>支持文件夹、GitHub / Git URL，以及 <code>.zip</code> 或 <code>.skill</code> 压缩包。</p></div></div><div class="skill-install-fields"><label><span>来源类型</span><select name="source-type"><option value="local">本地文件夹</option><option value="git">Git 仓库</option><option value="archive">压缩包</option></select></label><label class="skill-source-field"><span>来源</span><input name="source" required maxlength="1000" placeholder="本地路径、owner/repo、Git URL 或压缩包路径" /></label><button type="submit" class="extension-primary">安装</button></div></form>
    <section class="extension-record-list skill-list">${rows}</section>`;
}

function renderExtensionMarket() {
  const query = state.marketplaceQuery.trim().toLowerCase();
  const allItems = state.extensions.marketplace || [];
  const items = allItems.filter((item) => !query || [item.name, item.slug, item.source].join(" ").toLowerCase().includes(query));
  const sources = [...new Set(allItems.map((item) => item.source).filter(Boolean))].slice(0, 8);
  const sourceChips = sources.map((source) => `<span>${escapeHtml(source)}</span>`).join("");
  const empty = state.extensions.marketplaceLoaded ? `<div class="extension-empty market-empty"><span>${uiIcon("search")}</span><strong>没有匹配的市场技能</strong><p>换一个关键词，或点击刷新市场以同步公开目录。</p></div>` : `<div class="extension-empty market-empty"><span>${uiIcon("refresh")}</span><strong>正在连接技能市场</strong><p>首次加载会同步公开目录；之后可手动刷新。</p></div>`;
  const cards = items.length ? items.map((item) => `<article class="market-card"><div class="market-card-top"><span class="market-orb">${uiIcon("wand")}</span><a href="${escapeHtml(safeExternalUrl(item.url))}" target="_blank" rel="noopener" aria-label="在浏览器打开 ${escapeHtml(item.name || item.slug)}">${uiIcon("arrow-up-right")}</a></div><h3>${escapeHtml(item.name || item.slug)}</h3><p>${escapeHtml(item.source || "公开来源")}</p><div class="market-card-meta"><span>${item.installs ? `${Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(item.installs)} 安装` : "待同步安装数"}</span><span>${escapeHtml(item.sourceType || "Skill")}</span></div><button type="button" class="market-install" data-action="install-market-skill" data-market-skill-id="${escapeHtml(item.id)}">安装到技能库 <b>${uiIcon("plus")}</b></button></article>`).join("") : empty;
  return `<div class="extension-panel-head market-panel-head"><div><p class="panel-kicker">MARKETPLACE</p><h2>市场</h2><p>浏览 skills.sh 的公开目录。市场安装按单个 Skill 下载快照，避免把整个仓库混入技能库。</p></div><span class="market-connection ${state.extensions.marketplaceOffline ? "is-offline" : ""}">${state.extensions.marketplaceOffline ? "离线示例" : "已连接 skills.sh"}</span></div>
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
  return `<header class="settings-heading"><div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div><span class="save-indicator">本地保存</span></header>`;
}

function renderGeneralSettings() {
  const counts = state.notebook?.counts || {};
  const { provider, model } = activeModel();
  const readyTools = (state.capabilities?.tools || []).filter((tool) => ["ready", "external"].includes(tool.status)).length;
  return `${settingsHeading("设置", "此设备上的工作区与应用设置。")} 
    <section class="settings-card"><h2>当前工作区</h2><p>${escapeHtml(state.notebook?.title || "未打开资料库")}</p><div class="setting-metrics"><div class="setting-metric"><b>${escapeHtml(counts.sources || 0)}</b><span>资料来源</span></div><div class="setting-metric"><b>${escapeHtml(counts.citations || 0)}</b><span>已保存引文</span></div><div class="setting-metric"><b>${escapeHtml(counts.layers || 0)}</b><span>标注图层</span></div></div><p class="local-note">当前模型：${escapeHtml(provider ? `${provider.name} · ${model?.name || ""}` : "未选择")}。模型密钥不会写入工作区文件。</p></section>
    <section class="settings-card"><h2>运行状态</h2><p>${readyTools} 个工具可用。模型与本地模型的配置可分别在对应页面查看。</p></section>`;
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
        <div class="about-product-copy"><h2>ScanSci Pi</h2><p>由 Pi Agent 驱动的可追溯 AI 研究工作台</p><span class="about-version">v${escapeHtml(version)}</span></div>
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
  const keyField = isManaged ? `<p class="cherry-field-hint">此模型由 ScanSci 托管提供，使用时无需配置 API 密钥。</p>` : provider.kind !== "local" ? `<div class="cherry-key-row"><label class="cherry-field"><span>API 密钥</span><input name="provider-api-key" type="password" autocomplete="new-password" placeholder="${provider.api_key_configured ? "已保存；输入新值以替换" : "输入后仅保存在系统凭据管理器"}" /></label><button type="button" class="cherry-detect-button" data-action="test-provider" ${!provider.api_key_configured ? "disabled" : ""}>检 测</button></div><p class="cherry-field-hint">${provider.api_key_configured ? "密钥已安全保存，不会显示或返回。" : "多个密钥可用英文逗号分隔。"}</p>` : `<p class="cherry-field-hint">内置证据引擎不需要 API 密钥。</p>`;
  const restoreDefaultButton = isBuiltInProvider(provider) ? '<button type="button" class="cherry-restore-default" data-action="restore-provider-default">恢复默认</button>' : "";
  return `<section class="cherry-model-services"><aside class="cherry-provider-catalog"><label class="cherry-provider-search"><svg class="cherry-search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.75" cy="10.75" r="6.75"></circle><path d="m16 16 5 5"></path></svg><input id="modelServiceSearch" type="search" value="${escapeHtml(state.providerQuery)}" placeholder="搜索模型平台..." autocomplete="off" /></label><div class="cherry-provider-scroll">${providerItems || '<div class="cherry-provider-empty">没有匹配的模型平台</div>'}${localProviders.length ? `<div class="cherry-provider-divider">本地</div>${localProviders.map((item) => providerRow(item, false)).join("")}` : ""}</div><button class="cherry-add-provider" type="button" data-action="add-provider">＋&nbsp; 添加</button></aside><main class="cherry-provider-panel"><form id="modelProviderForm"><header class="cherry-provider-header"><div><div class="cherry-provider-name">${providerLogo(provider)}<h1>${escapeHtml(provider.name)}</h1><button type="button" class="cherry-mini-gear" aria-label="服务商设置">⚙</button></div>${kindField}</div><label class="cherry-toggle"><input name="provider-enabled" type="checkbox" ${provider.enabled ? "checked" : ""} /><span></span></label></header><section class="cherry-connection-section">${customNameField}${keyField}<label class="cherry-field"><span>API 地址 <i>⌁</i></span><input name="provider-base-url" value="${escapeHtml(provider.base_url || "")}" placeholder="https://api.example.com/v1" maxlength="500" ${isManaged ? "readonly" : ""} /></label><p class="cherry-endpoint-preview">预览：${escapeHtml(provider.base_url ? `${provider.base_url.replace(/\/$/, "")}/chat/completions` : "请填写服务商 API 地址")}</p></section><section class="cherry-model-section"><header><div class="cherry-model-section-title"><h2>模型</h2><b>${provider.models.length}</b></div><label class="cherry-model-search"><span>⌕</span><input id="modelListSearch" type="search" value="${escapeHtml(state.modelQuery)}" placeholder="搜索模型..." aria-label="搜索模型" autocomplete="off" /></label><div class="cherry-model-actions"><button type="button" class="cherry-fetch-button" data-action="fetch-provider-models" ${provider.kind === "local" || !provider.model_listing ? "disabled" : ""}>↻&nbsp; 获取模型列表</button><button type="button" class="cherry-plus-button" data-action="add-model" aria-label="添加模型">＋</button></div></header><div class="cherry-model-list">${modelRows || `<div class="cherry-provider-empty">${modelQuery ? "没有匹配的模型" : "尚未添加模型"}</div>`}</div></section><footer class="cherry-provider-footer"><button type="button" class="cherry-remove-provider" data-action="remove-provider" ${isBuiltInProvider(provider) ? "disabled" : ""}>移除服务商</button><div>${restoreDefaultButton}${provider.api_key_configured && !isManaged ? `<button type="button" class="cherry-text-button" data-action="remove-provider-key">移除密钥</button>` : ""}<button type="submit" class="cherry-save-button">保存</button></div></footer>${modelEditorMarkup(provider)}</form></main></section>`;
}

function renderLocalModelsSettings() {
  const presets = (state.presets?.local_models || []).map((item) => `<button type="button" class="quiet-add-chip" data-action="add-local-preset" data-preset-id="${escapeHtml(item.id)}">＋ ${escapeHtml(item.name)}</button>`).join("");
  const builtin = (state.settings.local_models || []).find((item) => item.runtime === "builtin");
  const installedItems = state.localModelMarket?.installed || [];
  const capabilityLabel = (kind) => ({ chat: "对话", embedding: "嵌入", reranking: "重排", vision: "视觉", audio: "语音" }[kind] || "通用");
  const installed = installedItems.map((item) => {
    const size = `${(Number(item.size_bytes || 0) / 1024 / 1024 / 1024).toFixed(1)} GB`;
    const kind = item.kind || (/(embedding|embed|bge|gte|e5-)/i.test(item.id || "") ? "embedding" : /(rerank)/i.test(item.id || "") ? "reranking" : "chat");
    return `<article class="quiet-model-row"><span class="quiet-model-mark">${kind === "chat" ? "◎" : "◇"}</span><div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.architecture || item.model_type || "Hugging Face")} · 自动发现</p><div class="local-capability-tags"><span>${capabilityLabel(kind)}</span>${item.format ? `<span>${escapeHtml(item.format)}</span>` : ""}</div></div><span class="quiet-row-note">${item.ready ? "已就绪" : "下载未完成"}</span><span class="quiet-row-size">${size}</span></article>`;
  }).join("") || '<div class="quiet-empty">未发现本地 Hugging Face 快照。</div>';
  const catalog = (state.localModelMarket?.catalog || []).map((item) => `<article class="quiet-model-row"><span class="quiet-model-mark is-muted">↓</span><div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.description || "Hugging Face")}${item.size_hint ? ` · ${escapeHtml(item.size_hint)}` : ""}</p><div class="local-capability-tags"><span>${capabilityLabel(item.kind)}</span>${item.downloads ? `<span>${Intl.NumberFormat("zh-CN", { notation: "compact" }).format(item.downloads)} 下载</span>` : ""}</div></div>${item.installed ? `<span class="quiet-row-note">${item.ready ? "已安装" : "未完成"}</span>` : `<button type="button" class="quiet-text-button" data-action="download-local-model" data-model-repo="${escapeHtml(item.id)}">下载</button>`}</article>`).join("") || '<div class="quiet-empty">市场目录暂不可用。</div>';
  const runtimeRows = (state.settings.local_models || []).map((item, index) => ({ item, index })).filter(({ item }) => item.runtime !== "builtin").map(({ item, index }) => `<details class="quiet-runtime-row"><summary><span class="quiet-model-mark">◌</span><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.runtime)} · ${item.enabled ? "可用" : "已停用"}</small></span><span class="quiet-row-note">配置</span></summary><div class="quiet-runtime-fields"><label><span>名称</span><input data-local-name="${index}" value="${escapeHtml(item.name)}" /></label><label><span>运行时</span><input data-local-runtime="${index}" value="${escapeHtml(item.runtime)}" /></label><label><span>地址</span><input data-local-url="${index}" value="${escapeHtml(item.base_url || "")}" placeholder="http://127.0.0.1:11434/v1" /></label><label><span>模型 ID</span><input data-local-model="${index}" value="${escapeHtml(item.model_id || "")}" placeholder="例如 qwen3:8b" /></label><label class="quiet-switch"><input type="checkbox" data-local-enabled="${index}" ${item.enabled ? "checked" : ""} /><span>启用</span></label><div><button type="button" class="quiet-text-button" data-action="test-local-model" data-local-id="${escapeHtml(item.id)}">测试连接</button><button type="button" class="quiet-danger-button" data-action="remove-local-model" data-local-index="${index}">移除</button></div></div></details>`).join("") || '<div class="quiet-empty">尚未添加外部本地运行时。</div>';
  const roles = state.settings.model_roles || {};
  const roleOptions = (capability, selected) => modelTargetOptions(selected, capability);
  return `<section class="quiet-settings-page local-models-page"><header class="quiet-page-heading"><div><span>LOCAL MODELS</span><h1>本地模型</h1><p>自动发现已连接磁盘中的 Hugging Face 快照；模型移动目录后，刷新即可重新识别。</p></div><button type="button" class="quiet-text-button" data-action="refresh-local-model-market">刷新发现</button></header>
    <section class="quiet-section local-defaults"><header><div><h2>资料库默认模型</h2><p>可选本地模型或已配置 API 服务商的兼容模型；保存后用于新资料的嵌入与检索重排。</p></div></header><div class="local-role-tabs"><label><span>默认嵌入模型</span><select data-model-role="embedding">${roleOptions("embedding", roles.embedding || "")}</select></label><label><span>默认重排模型</span><select data-model-role="reranking">${roleOptions("reranking", roles.reranking || "")}</select></label><button type="button" class="quiet-primary-button" data-action="save-local-model-roles">保存默认项</button></div></section>
    <section class="quiet-section"><header><div><h2>内置检索能力</h2><p>无需额外下载的语义检索与重排基线，可随时被上方默认项替代。</p></div><span class="quiet-row-note">${builtin?.enabled ? "已启用" : "已停用"}</span></header><div class="quiet-model-list"><article class="quiet-model-row"><span class="quiet-model-mark">◇</span><div><strong>${escapeHtml(builtin?.name || "ScanSci Evidence Engine")}</strong><p>本机处理</p><div class="local-capability-tags"><span>嵌入</span><span>重排</span></div></div><span class="quiet-row-note">内置</span></article></div></section>
    <section class="quiet-section"><header><div><h2>已发现的模型</h2><p>扫描 F:\\AI\\Models、Hugging Face 缓存和已连接磁盘的常见模型目录，不会遍历整个磁盘。</p></div><span class="quiet-row-note">${installedItems.length} 个快照</span></header><div class="quiet-model-list">${installed}</div></section>
    <section class="quiet-section"><header><div><h2>添加运行时</h2><p>已安装的 Ollama、LM Studio 或 llama.cpp 可作为额外本地服务接入。</p></div><div class="quiet-add-chips">${presets}</div></header><form id="localModelsForm" class="quiet-runtime-list">${runtimeRows}<footer><button type="submit" class="quiet-primary-button">保存更改</button></footer></form></section>
    <section class="quiet-section"><header><div><h2>模型市场</h2><p>来自 Hugging Face 的热门模型目录；按需搜索后下载，首次使用时才载入内存。</p></div><span class="quiet-row-note">${escapeHtml(state.localModelMarket?.source || "Hugging Face")}</span></header><form id="localModelMarketSearch" class="local-model-market-search"><input name="query" type="search" value="${escapeHtml(state.localModelMarket?.query || "")}" placeholder="搜索 Hugging Face 模型，例如 embedding、reranker、Qwen" /><button type="submit" class="quiet-text-button">搜索</button></form><div class="quiet-model-list">${catalog}</div></section></section>`;
}

function renderDocumentProcessingSettings() {
  const processing = state.settings.document_processing || {};
  const ocr = processing.ocr || { provider: "system", base_url: "", languages: ["zh", "en"], enabled: true };
  const mineru = processing.mineru || { provider: "mineru", base_url: "https://mineru.net", enabled: false };
  const ocrLanguages = new Set(ocr.languages || []);
  const ocrConnection = ocr.provider === "custom" ? `<div class="document-service-fields"><label class="setting-field"><span>API 地址</span><input name="ocr-base-url" value="${escapeHtml(ocr.base_url || "")}" placeholder="https://ocr.example.com/v1" maxlength="500" /></label><label class="setting-field"><span>API 密钥</span><input name="ocr-api-key" type="password" autocomplete="new-password" placeholder="${ocr.api_key_configured ? "已保存在系统凭据管理器；输入新值以替换" : "可选，保存后仅存于系统凭据管理器"}" /></label></div>` : `<p class="document-service-note">使用系统 OCR 识别扫描页与图片中的中英文文字，无需填写 API 密钥。</p>`;
  const mineruName = mineru.provider === "mineru" ? "MinerU" : "自定义文档解析服务";
  return `${settingsHeading("文档处理", "配置扫描页识别与学术 PDF 解析服务。密钥不会写入工作区文件。")}
    <form id="documentProcessingForm" class="document-processing-form">
      <section class="document-service-card"><div class="document-service-heading"><div><span class="document-service-icon">O</span><div><h2>OCR 服务</h2><p>从扫描 PDF、图像和无法直接复制的页面提取文字。</p></div></div><label class="switch-label"><input name="ocr-enabled" type="checkbox" ${ocr.enabled ? "checked" : ""} />启用</label></div><div class="document-service-rule"></div><label class="document-select-row"><span>OCR 服务提供商</span><select name="ocr-provider"><option value="system" ${ocr.provider === "system" ? "selected" : ""}>系统 OCR</option><option value="custom" ${ocr.provider === "custom" ? "selected" : ""}>自定义 OCR API</option></select></label><div class="document-language-row"><span>识别语言</span><div class="language-chips"><label><input name="ocr-language" type="checkbox" value="zh" ${ocrLanguages.has("zh") ? "checked" : ""} />中文</label><label><input name="ocr-language" type="checkbox" value="en" ${ocrLanguages.has("en") ? "checked" : ""} />English</label></div></div>${ocrConnection}</section>
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
  const records = servers.length ? servers.map((server) => `<article class="mcp-owned-record"><span class="mcp-owned-icon">${uiIcon("server")}</span><div><header><h2>${escapeHtml(server.name)}</h2><span>${escapeHtml(server.source || "自定义 MCP")}</span></header><p>${escapeHtml(server.description || "未添加说明")}</p><small>${escapeHtml(server.transport === "streamable-http" ? server.endpoint : [server.command, server.args].filter(Boolean).join(" ") || "等待填写连接信息")}</small></div><div class="mcp-owned-actions"><label class="mcp-enabled-switch"><input type="checkbox" data-action="toggle-record" data-record-kind="mcp" data-record-id="${escapeHtml(server.id)}" ${server.enabled ? "checked" : ""} /><span>${server.enabled ? "启用" : "停用"}</span></label><button type="button" data-action="remove-record" data-record-kind="mcp" data-record-id="${escapeHtml(server.id)}" aria-label="移除 ${escapeHtml(server.name)}">${uiIcon("x")}</button></div></article>`).join("") : `<div class="mcp-market-empty is-mine">${uiIcon("server")}<strong>还没有已保存的 MCP</strong><p>从“发现 MCP”添加官方目录中的服务器，或登记自己的本地/远程连接。</p></div>`;
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
  const form = `<form id="mcpManualForm" class="mcp-create-form" data-mcp-create-mode="${escapeHtml(mode)}"><header><button type="button" class="mcp-create-back" data-action="mcp-create-back">${uiIcon("arrow-left")}返回类型</button><div><span>${isStdio ? "本地 stdio MCP" : "远程 MCP 服务"}</span><h2>填写连接信息</h2></div></header><div class="mcp-create-form-grid"><section class="mcp-create-basics"><label><span>名称</span><input name="mcp-name" required maxlength="100" placeholder="例如：实验室数据服务" autofocus /></label><label><span>适用学科</span><select name="mcp-discipline">${disciplines.filter((item) => item.id !== "all").map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("")}</select></label><label class="is-wide"><span>用途说明</span><textarea name="mcp-description" maxlength="400" rows="3" placeholder="它会为研究流程提供什么能力？"></textarea></label><label class="is-wide"><span>标签（可选）</span><input name="mcp-tags" maxlength="200" placeholder="例如：实验数据、实验室、内部工具（用逗号分隔）" /></label></section>${fields}</div><aside class="mcp-create-review"><span>${uiIcon("lock-keyhole")}配置预览</span><p>保存后会出现在“我的服务器”，默认处于启用状态；你可以随时停用或移除。</p></aside><footer><button type="button" data-action="close-mcp-manual">取消</button><button type="submit" class="mcp-create-save">${uiIcon("check")}保存到我的服务器</button></footer></form>`;
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
    tags,
    source: "自定义 MCP",
    enabled: true,
  });
  state.mcpManualOpen = false;
  state.mcpCreateMode = "";
  state.mcpMarketplaceTab = "mine";
  await persistSettings("已保存 MCP 配置；没有启动任何进程");
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
  const [installed, catalog] = await Promise.all([
    request("/api/local-models/installed"),
    request(`/api/local-models/market${query ? `?q=${encodeURIComponent(query)}` : ""}`),
  ]);
  state.localModelMarket = { installed: installed.models || [], catalog: catalog.items || [], source: catalog.source || "", query, loading: false };
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
  if (action === "save-local-model-roles") {
    collectModelRoleForm();
    await persistSettings("资料库默认嵌入与重排模型已保存");
    return;
  }
  if (action === "download-local-model") {
    const repoId = element.dataset.modelRepo || "";
    if (!repoId) return;
    element.disabled = true;
    element.textContent = "下载中…";
    request("/api/local-models/download", { method: "POST", body: JSON.stringify({ id: repoId }) })
      .then(() => refreshLocalModelMarket())
      .then(() => toast(`${repoId} 已下载到本地模型目录`))
      .catch((error) => toast(error.message, true))
      .finally(() => { if (element.isConnected) element.disabled = false; });
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
  drawer.innerHTML = `<div class="review-evidence-head"><div><span>Evidence ${escapeHtml(citation.citation_id)}</span><strong>${escapeHtml(citation.paper)}</strong></div><button type="button" class="review-icon-button" data-action="close-review-evidence" aria-label="关闭证据">×</button></div><div class="review-evidence-body"><small>${escapeHtml(sourceMeta)}</small><blockquote>${escapeHtml(compact(citation.exact_quote || "当前引用没有保存原文摘录。", 900))}</blockquote>${readerButton}</div>`;
  drawer.classList.add("is-open");
}

async function copyReviewDocument() {
  if (!state.reviewDocument?.markdown) return;
  await navigator.clipboard.writeText(state.reviewDocument.markdown);
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

document.addEventListener("click", (event) => {
  if (state.updateCardOpen && !event.target.closest("[data-app-update]")) toggleAppUpdateCard(false);
  if (!event.target.closest("[data-mode-picker]")) closeComposerModePickers();
  if (!event.target.closest("[data-composer-model]")) closeComposerModelPickers();
  if (!event.target.closest("[data-composer-thinking]")) closeComposerThinkingPickers();
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
  else if (action === "minimize-window") controlDesktopWindow("minimize_window").catch((error) => toast(error.message, true));
  else if (action === "toggle-maximize-window") controlDesktopWindow("toggle_maximize_window").catch((error) => toast(error.message, true));
  else if (action === "close-window") controlDesktopWindow("close_window").catch((error) => toast(error.message, true));
  else if (action === "toggle-app-update") toggleAppUpdateCard();
  else if (action === "close-app-update") toggleAppUpdateCard(false);
  else if (action === "check-app-update") refreshAppUpdate().catch((error) => toast(error.message, true));
  else if (action === "install-app-update") installAppUpdate().catch((error) => toast(error.message, true));
  else if (action === "toggle-attachment-menu") {
    event.preventDefault();
    toggleAttachmentMenu(element);
  }
  else if (action === "choose-composer-image") {
    const key = element.dataset.composerKey === "home" ? "home" : "chat";
    byId(`${key}ImageFileInput`)?.click();
  }
  else if (action === "choose-presentation-sources") choosePresentationSources(element.dataset.composerKey === "home" ? "home" : "chat").catch((error) => toast(error.message, true));
  else if (action === "remove-composer-image") removeComposerImage(element.dataset.composerKey === "home" ? "home" : "chat", element.dataset.imageId || "");
  else if (action === "remove-composer-source") removeComposerSource(element.dataset.composerKey === "home" ? "home" : "chat", element.dataset.sourceId || "");
  else if (action === "open-ingestion-source") {
    const url = element.dataset.sourceUrl || "";
    const name = element.dataset.sourceName || "附件";
    if (name.toLowerCase().endsWith(".pdf") && window.ScanSciPdfViewer) window.ScanSciPdfViewer.open(url, name);
    else window.open(url, "_blank", "noopener,noreferrer");
  }
  else if (action === "choose-library-folder") chooseLibraryFolder().catch((error) => toast(error.message, true));
  else if (action === "choose-obsidian-vault") chooseLibraryFolder("obsidian").catch((error) => toast(error.message, true));
  else if (action === "choose-zotero-library") connectLocalZotero().catch((error) => toast(error.message, true));
  else if (action === "choose-library-files") chooseLibraryFiles().catch((error) => toast(error.message, true));
  else if (action === "select-notebook") {
    const notebook = (state.workspace?.notebooks || []).find((item) => item.notebook_id === element.dataset.notebookId);
    if (notebook) {
      state.notebook = notebook;
      renderWorkspace();
      renderMode();
      toast(`已切换到 ${notebook.title || pathLeaf(notebook.root_path)}`);
    }
  }
  else if (action === "export-pptxgenjs") exportActiveSlidePlan(element).catch((error) => toast(error.message, true));
  else if (action === "save-presentation") savePresentationToDevice(element.dataset.presentationPath, element.dataset.presentationName).then((result) => { if (!result?.cancelled) toast(`已保存 ${result.path || element.dataset.presentationName}`); }).catch((error) => toast(error.message, true));
  else if (action === "close-library-dialog") closeLibraryPathDialog();
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
  else if (action === "open-library") {
    closeAttachmentMenus();
    openMode("library");
  }
  else if (action === "toggle-composer-mode") {
    event.preventDefault();
    toggleComposerModePicker(element);
  }
  else if (action === "select-composer-mode") {
    event.preventDefault();
    setComposerMode(element.dataset.modeValue || "general");
    closeComposerModePickers();
    element.closest("[data-mode-picker]")?.querySelector("[data-action='toggle-composer-mode']")?.focus();
  }
  else if (action === "toggle-composer-model") {
    event.preventDefault();
    toggleComposerModelPicker(element);
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
    if (frame && state.activeEvidence?.reader_url) frame.src = state.activeEvidence.reader_url;
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
  else if (action === "copy-review-document") copyReviewDocument().catch((error) => toast(error.message, true));
  else if (action === "download-review-document") downloadReviewDocument();
  else if (action === "refresh-review-document") {
    if (state.activeTaskId) openTask(state.activeTaskId, { record: false });
  }
  else if (action === "toggle-review-focus") {
    const focused = byId("conversationLayout")?.classList.toggle("is-review-focus");
    element.textContent = focused ? "↙" : "↗";
    element.setAttribute("aria-label", focused ? "退出专注阅读" : "专注阅读");
  }
  else if (action === "close-review-document") setContextPanel("sources");
  else if (action === "open-review-document") setContextPanel("review");
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
  else if (action === "open-mode") openMode(element.dataset.mode || "tools");
  else if (action === "open-external") {
    const url = element.dataset.url || "";
    if (url.startsWith("/") || /^https?:\/\//i.test(url)) window.open(url, "_blank", "noopener");
  }
  else if (action === "create-ppt-project") createPptProject().catch((error) => toast(error.message, true));
  else if (action === "cancel-run") cancelRun(element.dataset.runId).catch((error) => toast(error.message, true));
  else if (action === "resume-run") resumeRun(element.dataset.runId).catch((error) => toast(error.message, true));
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
  const row = event.target.closest?.("[data-provider-drag-id]");
  if (!row || !state.draggedProviderId || row.dataset.providerDragId === state.draggedProviderId) return;
  event.preventDefault();
  document.querySelectorAll(".cherry-provider-item.is-drop-target").forEach((item) => item.classList.remove("is-drop-target"));
  row.classList.add("is-drop-target");
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
});

document.addEventListener("dragleave", (event) => {
  event.target.closest?.("[data-provider-drag-id]")?.classList.remove("is-drop-target");
});

document.addEventListener("dragend", clearProviderDragFeedback);

document.addEventListener("drop", (event) => {
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
    if (activeDirectChatController) {
      activeDirectChatController.abort();
      activeDirectChatController = null;
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
  else if (event.target.id === "libraryPathForm") {
    event.preventDefault();
    const value = byId("libraryPathInput").value.trim();
    if (!value) return;
    const operation = state.libraryImportKind === "files"
      ? importLibraryFiles(value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))
      : state.libraryImportKind === "zotero"
        ? registerZoteroLibrary(value)
        : importLibraryFolder(value, state.libraryImportKind);
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
  const strategy = byId("downloadStrategy").value;
  const message = strategy === "oa_first" ? "正在优先查找开放获取版本…" : "正在从合规来源获取文献…";
  await startModeRun("paper_download", { identifier: byId("paperIdentifier").value, strategy }, message);
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
  upsertRun(run);
  renderModeRun(run);
  watchRun(run.run_id, (next) => {
    if (state.activeView === "mode" && state.activeTaskId === next.run_id) renderModeRun(next);
  });
}

function renderModeRun(run) {
  if (run.status === "completed" && run.output_artifact) {
    renderModeArtifact(run);
    return;
  }
  const stages = (run.stages || []).map((stage) => `<li class="${escapeHtml(stage.status)}"><span>${stage.status === "completed" ? "✓" : stage.status === "running" ? "·" : stage.position + 1}</span><div><strong>${escapeHtml(stage.title)}</strong><small>${escapeHtml(stage.error_message || stage.summary || "等待执行")}</small></div></li>`).join("");
  const action = run.cancellable ? `<button type="button" class="run-action stop" data-action="cancel-run" data-run-id="${escapeHtml(run.run_id)}">停止任务</button>` : run.resumable ? `<button type="button" class="run-action" data-action="resume-run" data-run-id="${escapeHtml(run.run_id)}">从当前阶段继续</button>` : "";
  byId("modeResults").innerHTML = `<section class="mode-run"><header><div><span>${escapeHtml(runStatusLabel(run))}</span><strong>${escapeHtml(run.title)}</strong></div>${action}</header><div class="run-progress"><i style="width:${Math.round((run.progress || 0) * 100)}%"></i></div><ol>${stages}</ol>${run.status === "failed" ? `<p class="mode-run-error">${escapeHtml(run.error?.message || "任务失败")}</p>` : ""}</section>`;
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
applySidebarState();
renderProfileAvatar();
updateChromeControls();
observeIcons();
initialize();
renderAppUpdate();
if (state.autoCheckUpdates) refreshAppUpdate({ quiet: true });
window.addEventListener("pywebviewready", () => {
  state.updateNative = Boolean(window.pywebview?.api?.install_update);
  renderAppUpdate();
});
