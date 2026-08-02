# CNKI Reader HTML 清洗能力

这个能力用于把知网在线阅读器的 `xml/data` 结构化 JSON 转成离线、干净、可索引的 HTML。它沉淀的是 reader 页面经验里的“清洗层”，而不是批量下载层。

## 边界

- 不点击 PDF、CAJ 或下载链接。
- 不保存 cookie、token、invoice、nonce、idenid 等临时凭据。
- 不把知网附件接口 URL 写进 HTML；图像只保留 `data-annexid` 和图题。
- 文内引用会改成本页锚点，例如 `href="#ref-68"`。
- MathML 里的常见视觉混淆字符会修正，例如 `GΡΡ` -> `GPP`、`VΡD` -> `VPD`。

## 用法

先在合规登录态下取得 reader 的 `ossapi/kreader-api/v1/xml/data` JSON 响应，并确认响应对应 `datatype=all`。不要把带凭据的原始响应提交到仓库。

```powershell
scansci cnki-reader `
  --input .\xml_data_all.json `
  --output .\html-papers\cnki\STXB202204021.clean.html `
  --tablename cjfdlast2022
```

如果希望把图也放进离线 HTML，显式开启图片本地化：

```powershell
scansci cnki-reader `
  --input .\xml_data_all.json `
  --output .\html-papers\cnki\STXB202204021.clean.html `
  --tablename cjfdlast2022 `
  --include-images
```

默认图片目录是 HTML 旁边的 `STXB202204021.clean_assets`。也可以手动指定：

```powershell
scansci cnki-reader `
  --input .\xml_data_all.json `
  --output .\html-papers\cnki\STXB202204021.clean.html `
  --include-images `
  --assets-dir .\html-papers\cnki\STXB202204021_assets
```

这一步会使用原始 JSON 里的知网附件 URL 请求图片一次，但输出 HTML 只写本地相对路径，例如：

```html
<img src="STXB202204021.clean_assets/STXB202204021_231.jpg" alt="图1 GPP">
```

命令输出 JSON 摘要：

```json
{
  "status": "success",
  "output_path": "html-papers/cnki/STXB202204021.clean.html",
  "image_assets": 8,
  "counts": {
    "paragraphs": 41,
    "sections": 9,
    "figures": 8,
    "tables": 1,
    "references": 61
  }
}
```

## 复用建议

把联网捕获和 HTML 清洗分成两步：捕获步骤只在本机临时目录里运行，清洗步骤只接收结构化 JSON 并输出可留存 HTML。清洗完成后，删除原始 JSON、网络日志和浏览器调试快照，再用下面的检查确认没有临时凭据：

```powershell
rg -n "invoice=|nonce=|idenid=|Cookie|Authorization" .\html-papers\cnki
```
