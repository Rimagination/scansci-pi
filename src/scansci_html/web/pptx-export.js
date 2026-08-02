(() => {
  "use strict";

  const color = (theme, key, fallback) => String(theme?.[key] || fallback).replace(/^#/, "");
  const cleanFileName = (value) => `${String(value || "ScanSci-presentation").replace(/[\\/:*?"<>|]+/g, "-").slice(0, 70) || "ScanSci-presentation"}.pptx`;
  const shadow = () => ({ type: "outer", color: "000000", blur: 2, angle: 45, offset: 1, opacity: 0.12 });

  function buildPresentation(plan) {
    if (!plan || plan.schema !== "scansci.slide-plan.v1" || !Array.isArray(plan.slides) || !plan.slides.length) {
      throw new Error("幻灯片计划无效，请重新生成后再导出。");
    }
    if (typeof window.PptxGenJS !== "function") throw new Error("PPTX 导出组件尚未加载。");

    const pptx = new window.PptxGenJS();
    const theme = plan.theme || {};
    const colors = {
      cover: color(theme, "cover", "091B2A"),
      background: color(theme, "background", "F7F8F7"),
      ink: color(theme, "ink", "132431"),
      muted: color(theme, "muted", "667781"),
      accent: color(theme, "accent", "14897D"),
      white: "FFFFFF",
      line: "DDE5E3",
    };
    const fontHead = theme.font_head || "Microsoft YaHei";
    const fontBody = theme.font_body || "Microsoft YaHei";
    pptx.layout = "LAYOUT_WIDE";
    pptx.author = "ScanSciAI";
    pptx.company = "ScanSci";
    pptx.subject = "Evidence-linked scientific presentation";
    pptx.title = plan.title || "ScanSci Presentation";
    pptx.lang = "zh-CN";
    pptx.theme = { headFontFace: fontHead, bodyFontFace: fontBody, lang: "zh-CN" };

    plan.slides.forEach((item, index) => {
      const slide = pptx.addSlide();
      const isCover = item.layout === "cover" || index === 0;
      slide.background = { color: isCover ? colors.cover : colors.background };
      if (isCover) {
        slide.addShape(pptx.ShapeType.rect, { x: 0.82, y: 0.8, w: 1.56, h: 0.08, line: { color: colors.accent, transparency: 100 }, fill: { color: colors.accent } });
        slide.addShape(pptx.ShapeType.ellipse, { x: 10.7, y: 0.75, w: 1.6, h: 1.6, line: { color: colors.accent, width: 3, transparency: 18 }, fill: { color: colors.cover, transparency: 100 } });
        slide.addText(item.title || plan.title, { x: 0.84, y: 1.42, w: 10.7, h: 1.7, margin: 0, fontFace: fontHead, fontSize: 36, bold: true, color: colors.white, valign: "mid", fit: "shrink" });
        const question = plan.central_question || item.takeaway || "";
        if (question) slide.addText(question, { x: 0.86, y: 3.38, w: 10.2, h: 1.22, margin: 0, fontFace: fontBody, fontSize: 19, color: "CFE8E6", fit: "shrink" });
        const sourceNames = (item.source_names || []).join(" / ");
        slide.addText(sourceNames || "Source-grounded · Editable PPTX", { x: 0.86, y: 6.64, w: 10.7, h: 0.28, margin: 0, fontFace: fontBody, fontSize: 10, color: "A7BEC7" });
        return;
      }

      slide.addShape(pptx.ShapeType.rect, { x: 0.72, y: 0.55, w: 0.1, h: 0.76, line: { color: colors.accent, transparency: 100 }, fill: { color: colors.accent } });
      slide.addText(item.title, { x: 1.02, y: 0.58, w: 11.1, h: 0.68, margin: 0, fontFace: fontHead, fontSize: 27, bold: true, color: colors.ink, fit: "shrink" });
      if (item.takeaway) slide.addText(item.takeaway, { x: 1.03, y: 1.34, w: 10.8, h: 0.62, margin: 0, fontFace: fontBody, fontSize: 15.5, color: colors.muted, fit: "shrink" });
      const bullets = (item.blocks || []).flatMap((block) => block.type === "bullets" ? (block.items || []) : []).slice(0, 6);
      const columns = bullets.length > 3 ? 2 : 1;
      const rows = Math.ceil(Math.max(1, bullets.length) / columns);
      const cardW = columns === 2 ? 5.48 : 11.16;
      const cardH = Math.min(1.02, 3.9 / rows);
      bullets.forEach((bullet, bulletIndex) => {
        const column = bulletIndex % columns;
        const row = Math.floor(bulletIndex / columns);
        const x = 0.92 + column * 5.7;
        const y = 2.18 + row * (cardH + 0.18);
        slide.addShape(pptx.ShapeType.rect, { x, y, w: cardW, h: cardH, line: { color: colors.line, width: 0.8 }, fill: { color: colors.white }, shadow: shadow() });
        slide.addShape(pptx.ShapeType.ellipse, { x: x + 0.24, y: y + 0.28, w: 0.28, h: 0.28, line: { color: colors.accent, transparency: 100 }, fill: { color: colors.accent } });
        slide.addText(String(bullet), { x: x + 0.7, y: y + 0.18, w: cardW - 0.95, h: cardH - 0.3, margin: 0, fontFace: fontBody, fontSize: 14.5, color: colors.ink, valign: "mid", fit: "shrink" });
      });
      const pages = (item.source_pages || []).join(", ");
      slide.addText(pages ? `原文第 ${pages} 页` : "基于本次上传材料", { x: 1.02, y: 7.05, w: 9.6, h: 0.2, margin: 0, fontFace: fontBody, fontSize: 9.5, color: colors.muted });
      slide.addText(`${index + 1}/${plan.slides.length}`, { x: 11.6, y: 7.02, w: 0.72, h: 0.2, margin: 0, align: "right", fontFace: fontBody, fontSize: 9.5, color: colors.muted });
    });
    return pptx;
  }

  async function exportPresentation(plan, requestedName = "") {
    const fileName = cleanFileName(requestedName || plan?.title);
    const base64 = await buildPresentation(plan).write({ outputType: "base64", compression: true });
    const response = await fetch("/api/studio/ppt/rendered", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_name: fileName, base64 }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result?.message || result?.error?.message || "PPTX 保存失败");
    return result;
  }

  window.ScanSciPptxExporter = { buildPresentation, export: exportPresentation };
})();
