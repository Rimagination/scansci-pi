const notebooks = {
  rag: {
    title: {
      zh: "Evidence-first RAG 综述",
      en: "Evidence-first RAG Review",
    },
    reader: "PaperQA2 retrieval study",
  },
  cnki: {
    title: {
      zh: "CNKI clean HTML 转换评估",
      en: "CNKI Clean HTML Conversion Review",
    },
    reader: "CNKI clean HTML parser notes",
  },
  methods: {
    title: {
      zh: "PaperQA2 / MiniRAG / OpenScholar 对比",
      en: "PaperQA2 / MiniRAG / OpenScholar Comparison",
    },
    reader: "Comparative method matrix",
  },
};

const sourceTitles = {
  paperqa: "PaperQA2 retrieval study",
  minirag: "MiniRAG reproduction notes",
  cite: "Citation object model",
};

const translations = {
  zh: {
    notebookTitle: "Evidence-first RAG 综述",
    createNotebook: "创建笔记本",
    analyze: "分析",
    share: "分享",
    settings: "设置",
    sources: "来源",
    addSource: "添加来源",
    searchSources: "在文献库中搜索新来源",
    webSearch: "Web 检索",
    fastSearch: "快速研究",
    selectAll: "全选",
    sourceOneMeta: "18 条证据 · 6 条引用 · 待审阅",
    sourceTwoMeta: "21 条证据 · benchmark trace 已关联",
    sourceThreeMeta: "9 条证据 · selector anchors 稳定",
    conversation: "对话",
    modeAsk: "对话",
    modeRead: "阅读",
    modeEvidence: "证据",
    modeReview: "审阅",
    questionLine: "PaperQA2 类项目对 ScanSci 最值得吸收的是什么？",
    answerOne:
      "最值得吸收的是 notebook/source/chat 的产品组织，而不是把底层变成通用 RAG。ScanSci 应保留 clean HTML/XML 与 evidence span 作为核心坐标，让回答、综述和导出都从可审计 evidence table 生成。",
    stepOneTitle: "先组织来源。",
    stepOneText: "Source 面板只放可信来源，并保留 HTML anchor、quote snapshot 与 citation audit。",
    stepTwoTitle: "再生成产物。",
    stepTwoText: "Studio 只能从 accepted 或 partial_support 证据生成摘要、矩阵和审阅集。",
    stepThreeTitle: "最后记录运行。",
    stepThreeText: "Codex 作为 control plane，本地小模型只做 action_decider，manifest 可复盘。",
    saveToNote: "保存到笔记",
    anchorSynced: "anchor 已同步",
    sourceExcerpt: "来源片段",
    highlightLine: "Notebook 产品的信任来自引用能够跳回精确来源区域。",
    readerParagraph: "对 ScanSci 来说，关键不是聊天框更聪明，而是每个事实都能被检查、接受、拒绝和重放。",
    readerNote: "当前证据：section 3.2，quote snapshot，html_anchor=#retrieval-audit",
    activeLayer: "当前 Layer",
    layerValue: "NotebookLM-like 产品形态",
    visibleProof: "可见证据",
    proofValue: "只显示 supported / partial_support",
    nextGate: "下一门槛",
    gateValue: "18 条 citation audit 后再 benchmark",
    claim: "Claim",
    source: "Source",
    verdict: "Verdict",
    audit: "Audit",
    claimOne: "Notebook/source 组织方式值得吸收。",
    claimTwo: "可点击引用必须绑定稳定来源位置。",
    claimThree: "Benchmark 应在人审 gold 之后运行。",
    accepted: "已接受",
    needsHuman: "需人审",
    reviewOneTitle: "Benchmark 是否必须等待 local gold？",
    reviewOneText: "1 条 partial_support citation · 需要人审",
    reviewTwoTitle: "Notebook shell 能降低产品理解成本。",
    reviewTwoText: "已由人审接受",
    composerPlaceholder: "开始输入...",
    sourceCount: "3 个来源",
    evidenceMatrix: "证据矩阵",
    reviewSet: "审阅集",
    reportDraft: "报告草稿",
    glossary: "术语表",
    timeline: "时间线",
    methodsTable: "方法对比",
    benchmarkRun: "Benchmark",
    manifest: "运行记录",
    studioOutputTitle: "等待产物",
    studioOutput: "证据产物会保存在此处。",
    studioHint: "只展示已接入的 ScanSci 输出：矩阵、审阅集、转换模板、benchmark 和 run manifest。",
    templateKicker: "矩阵模板",
    matrixTemplateName: "PaperQA2 类项目吸收点",
    runMatrixTemplate: "运行模板",
    colStudy: "Study",
    colFinding: "Finding",
    colEvidence: "Evidence",
    colReview: "Review",
    colStudyHint: "来源与年份",
    colFindingHint: "可吸收的产品机制",
    colEvidenceHint: "quote + selector",
    colReviewHint: "accepted / partial",
    matrixResultKicker: "输出预览",
    matrixResultTitle: "证据矩阵",
    matrixFindingOne: "把研究任务组织成 notebook/source/chat。",
    matrixFindingTwo: "引用必须能跳回稳定 HTML anchor。",
    matrixFindingThree: "benchmark 等待人工 gold 后再运行。",
    matrixTemplateTitle: "证据矩阵模板",
    addNote: "添加笔记",
    switcherKicker: "选择笔记本",
    switcherTitle: "继续一个研究项目",
    notebookRag: "Evidence-first RAG 综述",
    notebookRagMeta: "36 sources · 142 evidence spans",
    notebookCnki: "CNKI clean HTML 转换评估",
    notebookCnkiMeta: "12 sources · parser notes",
    notebookMethods: "PaperQA2 / MiniRAG / OpenScholar 对比",
    notebookMethodsMeta: "24 sources · benchmark matrix",
    manifestPreview: "运行记录预览",
    studioOutputPreview: "Studio 输出预览",
  },
  en: {
    notebookTitle: "Evidence-first RAG Review",
    createNotebook: "Create notebook",
    analyze: "Analyze",
    share: "Share",
    settings: "Settings",
    sources: "Sources",
    addSource: "Add source",
    searchSources: "Search for new sources in the library",
    webSearch: "Web search",
    fastSearch: "Fast research",
    selectAll: "Select all",
    sourceOneMeta: "18 evidence spans · 6 citations · audit pending",
    sourceTwoMeta: "21 evidence spans · benchmark trace linked",
    sourceThreeMeta: "9 evidence spans · selector anchors stable",
    conversation: "Chat",
    modeAsk: "Chat",
    modeRead: "Read",
    modeEvidence: "Evidence",
    modeReview: "Review",
    questionLine: "What should ScanSci absorb from PaperQA2-like projects?",
    answerOne:
      "The useful lesson is notebook/source/chat product organization, not turning the foundation into generic RAG. ScanSci should keep clean HTML/XML and evidence spans as the core coordinate system, so answers, reviews, and exports are generated from an auditable evidence table.",
    stepOneTitle: "Organize sources first.",
    stepOneText: "The Source panel keeps trusted documents, HTML anchors, quote snapshots, and citation audits.",
    stepTwoTitle: "Generate deliverables next.",
    stepTwoText: "Studio can only generate summaries, matrices, and review sets from accepted or partial_support evidence.",
    stepThreeTitle: "Record every run.",
    stepThreeText: "Codex remains the control plane, the local model only chooses typed actions, and the manifest is replayable.",
    saveToNote: "Save to note",
    anchorSynced: "anchor synced",
    sourceExcerpt: "Source excerpt",
    highlightLine: "Notebook products earn trust when citations jump back to precise source regions.",
    readerParagraph: "For ScanSci, the key is not a smarter chat box; every fact must be inspectable, acceptable, rejectable, and replayable.",
    readerNote: "Current evidence: section 3.2, quote snapshot, html_anchor=#retrieval-audit",
    activeLayer: "Active layer",
    layerValue: "NotebookLM-like product shape",
    visibleProof: "Visible proof",
    proofValue: "supported / partial_support only",
    nextGate: "Next gate",
    gateValue: "18 citation audits before benchmark",
    claim: "Claim",
    source: "Source",
    verdict: "Verdict",
    audit: "Audit",
    claimOne: "Notebook/source organization is worth absorbing.",
    claimTwo: "Clickable citations must bind to stable source locations.",
    claimThree: "Benchmarks should run after human-reviewed gold.",
    accepted: "accepted",
    needsHuman: "needs human",
    reviewOneTitle: "Should benchmark wait for local gold?",
    reviewOneText: "1 partial_support citation · human review required",
    reviewTwoTitle: "The notebook shell reduces product comprehension cost.",
    reviewTwoText: "accepted by human review",
    composerPlaceholder: "Start typing...",
    sourceCount: "3 sources",
    evidenceMatrix: "Evidence matrix",
    reviewSet: "Review set",
    reportDraft: "Report draft",
    glossary: "Glossary",
    timeline: "Timeline",
    methodsTable: "Methods table",
    benchmarkRun: "Benchmark",
    manifest: "Run manifest",
    studioOutputTitle: "Waiting for output",
    studioOutput: "Evidence outputs will be saved here.",
    studioHint: "Only connected ScanSci outputs are shown: matrices, review sets, transformation templates, benchmark, and run manifests.",
    templateKicker: "Matrix template",
    matrixTemplateName: "PaperQA2 lessons to absorb",
    runMatrixTemplate: "Run template",
    colStudy: "Study",
    colFinding: "Finding",
    colEvidence: "Evidence",
    colReview: "Review",
    colStudyHint: "source and year",
    colFindingHint: "product mechanism to absorb",
    colEvidenceHint: "quote + selector",
    colReviewHint: "accepted / partial",
    matrixResultKicker: "Output preview",
    matrixResultTitle: "Evidence matrix",
    matrixFindingOne: "Organize research work as notebook/source/chat.",
    matrixFindingTwo: "Citations must jump back to stable HTML anchors.",
    matrixFindingThree: "Run benchmarks after human-reviewed gold.",
    matrixTemplateTitle: "Evidence Matrix Template",
    addNote: "Add note",
    switcherKicker: "Choose notebook",
    switcherTitle: "Continue a research project",
    notebookRag: "Evidence-first RAG Review",
    notebookRagMeta: "36 sources · 142 evidence spans",
    notebookCnki: "CNKI Clean HTML Conversion Review",
    notebookCnkiMeta: "12 sources · parser notes",
    notebookMethods: "PaperQA2 / MiniRAG / OpenScholar Comparison",
    notebookMethodsMeta: "24 sources · benchmark matrix",
    manifestPreview: "Manifest Preview",
    studioOutputPreview: "Studio Output Preview",
  },
};

const studioEvents = {
  matrix: {
    zh: [
      ["template", "加载 matrix_template：Study、Finding、Evidence、Review。"],
      ["retrieve", "从 3 个已选来源读取 quote、DOI、section 与 selector。"],
      ["generate", "生成 evidence matrix cell，只写入 supported / partial_support。"],
      ["review", "partial_support 行进入人工审阅，不自动越过 gold 门槛。"],
      ["record", "保存 matrix artifact 与可复盘 run manifest。"],
    ],
    en: [
      ["template", "Load matrix_template: Study, Finding, Evidence, Review."],
      ["retrieve", "Read quote, DOI, section, and selector from 3 selected sources."],
      ["generate", "Create evidence matrix cells from supported / partial_support spans."],
      ["review", "Send partial_support rows to human review without crossing the gold gate."],
      ["record", "Save the matrix artifact and replayable run manifest."],
    ],
  },
  review: {
    zh: [
      ["observe", "读取 partial_support citations、weak candidates 和 citation audits。"],
      ["queue", "生成 acceptance/gold 人工审阅集，不自动越过人审门槛。"],
      ["record", "写入 acceptance workbench manifest，等待 reviewer 更新状态。"],
    ],
    en: [
      ["observe", "Read partial_support citations, weak candidates, and citation audits."],
      ["queue", "Create an acceptance/gold review set without crossing the human gate."],
      ["record", "Write the acceptance workbench manifest for reviewer updates."],
    ],
  },
  report: {
    zh: [
      ["observe", "读取 confirmed review matrix rows。"],
      ["transform", "运行 review-matrix --template report 生成证据绑定报告草稿。"],
      ["record", "保存 markdown/html 产物和 transformation metadata。"],
    ],
    en: [
      ["observe", "Read confirmed review matrix rows."],
      ["transform", "Run review-matrix --template report to generate an evidence-bound draft."],
      ["record", "Save markdown/html output and transformation metadata."],
    ],
  },
  glossary: {
    zh: [
      ["observe", "读取 confirmed review matrix rows 中的术语与定义证据。"],
      ["transform", "运行 review-matrix --template glossary 生成术语表。"],
      ["record", "保存每条术语对应的 quote、DOI 和 section。"],
    ],
    en: [
      ["observe", "Read terms and definition evidence from confirmed review matrix rows."],
      ["transform", "Run review-matrix --template glossary."],
      ["record", "Save quote, DOI, and section for each term."],
    ],
  },
  timeline: {
    zh: [
      ["observe", "读取 confirmed review matrix rows 中的年份、方法和结果。"],
      ["transform", "运行 review-matrix --template timeline 生成研究时间线。"],
      ["record", "保存带来源锚点的 timeline 产物。"],
    ],
    en: [
      ["observe", "Read year, method, and result rows from the confirmed review matrix."],
      ["transform", "Run review-matrix --template timeline."],
      ["record", "Save a source-anchored timeline output."],
    ],
  },
  methods: {
    zh: [
      ["observe", "读取 confirmed review matrix rows 中的方法、数据集和指标。"],
      ["transform", "运行 review-matrix --template methods 生成方法对比表。"],
      ["record", "保存方法、数据集、指标和证据引用。"],
    ],
    en: [
      ["observe", "Read methods, datasets, and metrics from confirmed review rows."],
      ["transform", "Run review-matrix --template methods."],
      ["record", "Save methods, datasets, metrics, and evidence citations."],
    ],
  },
  benchmark: {
    zh: [
      ["observe", "检查 local gold 与 acceptance workbench 状态。"],
      ["gate", "人审未完成时停止；通过后运行本地 retrieval benchmark。"],
      ["record", "保存 benchmark details、leaderboard 和 run manifest。"],
    ],
    en: [
      ["observe", "Check local gold and acceptance workbench status."],
      ["gate", "Stop if human review is incomplete; otherwise run local retrieval benchmark."],
      ["record", "Save benchmark details, leaderboard, and run manifest."],
    ],
  },
  manifest: {
    zh: [
      ["observe", "读取 evidence.sqlite、workspace.sqlite、acceptance manifest。"],
      ["decide", "本地小模型只能从 allowed_actions 选择 action_id。"],
      ["record", "Codex 监督并写入 L1 dry-run manifest。"],
    ],
    en: [
      ["observe", "Read evidence.sqlite, workspace.sqlite, and acceptance manifest."],
      ["decide", "The local model can only choose an action_id from allowed_actions."],
      ["record", "Codex supervises and writes an L1 dry-run manifest."],
    ],
  },
};

const studioFallback = studioEvents.manifest;
const studioTitleKeys = {
  matrix: "matrixTemplateTitle",
  review: "reviewSet",
  report: "reportDraft",
  glossary: "glossary",
  timeline: "timeline",
  methods: "methodsTable",
  benchmark: "benchmarkRun",
  manifest: "manifestPreview",
};
const manifestPayloads = {
  matrix: {
    control_plane: { type: "codex" },
    autonomy: "L1",
    artifact: "evidence_matrix",
    matrix_template: {
      name: "paperqa_lessons",
      columns: ["Study", "Finding", "Evidence", "Review"],
    },
    selected_sources: 3,
    generated_rows: 3,
    human_gate: "review_acceptance_gold",
    next_action: "open_review_set",
  },
  manifest: {
    control_plane: { type: "codex" },
    autonomy: "L1",
    worker_model: { role: "action_decider" },
    next_action: "build_acceptance_workbench",
    requires_human: false,
  },
};
const app = document.querySelector(".app");
const workspaceTitle = document.querySelector("#workspaceTitle");
const readerTitle = document.querySelector("#readerTitle");
const drawer = document.querySelector("#runDrawer");
const drawerBackdrop = document.querySelector(".drawer-backdrop");
const drawerTitle = document.querySelector("#drawerTitle");
const runEvents = document.querySelector("#runEvents");
const drawerViews = document.querySelectorAll("[data-drawer-view]");
const manifestCode = document.querySelector(".manifest-code");
const notebookSwitcher = document.querySelector(".notebook-switcher");
let currentLanguage = "zh";
let currentNotebook = "rag";
let currentDrawerType = "manifest";
let currentStudioType = "manifest";

function t(key) {
  return translations[currentLanguage][key] || translations.zh[key] || key;
}

function setLanguage(lang) {
  currentLanguage = lang === "en" ? "en" : "zh";
  app.dataset.lang = currentLanguage;
  document.documentElement.lang = currentLanguage === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
    element.setAttribute("placeholder", t(element.dataset.i18nPlaceholder));
  });
  document.querySelectorAll("[data-action='set-language']").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.langValue === currentLanguage);
  });
  document.querySelectorAll(".studio-lang-badge").forEach((badge) => {
    badge.textContent = currentLanguage === "zh" ? "中" : "EN";
  });
  workspaceTitle.textContent = notebooks[currentNotebook].title[currentLanguage];
  if (drawer.classList.contains("is-open")) {
    openStudioDrawer(currentStudioType);
  }
}

function openNotebook(id) {
  currentNotebook = notebooks[id] ? id : "rag";
  workspaceTitle.textContent = notebooks[currentNotebook].title[currentLanguage];
  readerTitle.textContent = notebooks[currentNotebook].reader;
  notebookSwitcher.hidden = true;
}

function setMode(mode) {
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.mode === mode);
  });
  document.querySelectorAll(".mode-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.panel === mode);
  });
}

function selectSource(sourceId) {
  document.querySelectorAll(".source-item").forEach((row) => {
    row.classList.toggle("is-active", row.dataset.source === sourceId);
  });
  readerTitle.textContent = sourceTitles[sourceId] || "Source excerpt";
  setMode("read");
  document.querySelector("#documentPreview")?.animate(
    [
      { outlineColor: "rgba(13, 115, 109, 0)" },
      { outlineColor: "rgba(13, 115, 109, 0.55)" },
      { outlineColor: "rgba(13, 115, 109, 0)" },
    ],
    { duration: 520, easing: "ease-out" }
  );
}

function drawerPayload(type) {
  return manifestPayloads[type] || manifestPayloads.manifest;
}

function openDrawer(title = t("manifestPreview"), events = studioFallback[currentLanguage], type = "manifest", studioType = type) {
  currentDrawerType = type;
  currentStudioType = studioType;
  drawerTitle.textContent = title;
  runEvents.innerHTML = "";
  events.forEach(([name, text]) => {
    const item = document.createElement("li");
    const eventName = document.createElement("strong");
    const eventText = document.createElement("span");
    eventName.textContent = name;
    eventText.textContent = text;
    item.append(eventName, eventText);
    runEvents.appendChild(item);
  });
  drawerViews.forEach((view) => {
    view.hidden = view.dataset.drawerView !== type;
  });
  if (manifestCode) {
    manifestCode.textContent = JSON.stringify(drawerPayload(type), null, 2);
  }
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  drawerBackdrop.hidden = false;
}

function openStudioDrawer(type = "manifest") {
  const eventGroup = studioEvents[type] || studioFallback;
  const titleKey = studioTitleKeys[type] || "studioOutputPreview";
  const drawerType = type === "matrix" ? "matrix" : "manifest";
  if (type === "matrix") setMode("evidence");
  openDrawer(t(titleKey), eventGroup[currentLanguage], drawerType, type);
}

function closeDrawer() {
  drawer.classList.remove("is-open");
  drawer.setAttribute("aria-hidden", "true");
  drawerBackdrop.hidden = true;
}

function applyHashState() {
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash) return;
  const params = new URLSearchParams(hash);
  const lang = params.get("lang");
  const notebook = params.get("notebook");
  const mode = params.get("mode");
  const drawerState = params.get("drawer");
  if (lang) setLanguage(lang);
  if (notebook) openNotebook(notebook);
  if (mode) setMode(mode);
  if (drawerState === "manifest") openStudioDrawer("manifest");
  if (drawerState === "matrix") openStudioDrawer("matrix");
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("button, a");
  if (!target) return;

  const action = target.dataset.action;
  if (action === "open-notebook-switcher") {
    event.preventDefault();
    notebookSwitcher.hidden = false;
  }
  if (action === "close-notebook-switcher") notebookSwitcher.hidden = true;
  if (action === "set-language") setLanguage(target.dataset.langValue);
  if (action === "open-run-drawer") openStudioDrawer("manifest");
  if (action === "open-studio-preview") openStudioDrawer("matrix");
  if (action === "open-matrix-flow") openStudioDrawer("matrix");
  if (action === "close-drawer") closeDrawer();

  if (target.dataset.notebook) openNotebook(target.dataset.notebook);
  if (target.dataset.mode) setMode(target.dataset.mode);
  if (target.dataset.source) selectSource(target.dataset.source);
  if (target.dataset.studio) {
    openStudioDrawer(target.dataset.studio);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeDrawer();
    notebookSwitcher.hidden = true;
  }
});

setLanguage("zh");
applyHashState();
