# ScanSci 桌面构建与按需模型安装

## 发行策略

ScanSci 主程序和本地模型推理栈具有不同的更新频率。界面、对话、知识库和文档功能经常更新；`torch` 与 `transformers` 只在本地推理兼容性变化时更新。把两者绑定会让每次主程序修改都重复复制和分发数百 MB 的依赖。

现在发行物分为：

- `core`：默认桌面包。包含界面、对话、知识库、文档、PPT、Skill 和 MCP；**不包含** PyTorch、Transformers 或任何模型权重。
- `local-transformers`：可选、版本化的本地 AI 组件，包含 PyTorch、Transformers 与回环 sidecar。
- 用户模型：由用户在“设置 · 本地模型”中按需下载或连接既有的 Ollama / LM Studio 运行时，保留在用户选择的位置，不属于应用包。
- `full`：仅用于内部支持或离线交付的技术包，必须显式指定，不是公开发行默认值。

轻量包的硬约束是：**先有可用运行时，再允许下载依赖该运行时的模型；下载完成后校验并启用。** 资料接入只建立文档与基础关键词索引，绝不偷偷下载大模型。这样用户不会出现“已经下载模型但程序无法运行”的状态。

## 日常开发

日常修改直接运行源码和针对性测试，不打包：

```powershell
python -m pytest tests/test_build_profiles.py tests/test_local_runtime_component.py -q
python -m scansci_html.desktop
```

确实需要桌面包时，默认生成轻量 `core` 包：

```powershell
.\scripts\build_desktop.ps1 -OutputDir dist-preview -BuildId preview
```

构建内部离线支持包时才显式选择 `full`：

```powershell
python -m pip install -e ".[desktop,local-gpu,rerank]"
.\scripts\build_desktop.ps1 -PackageProfile full -OutputDir dist-support -BuildId support
```

`BuildId` 只进入交付元数据。PyInstaller 的 `workpath` 使用由 Python 版本、PyInstaller 版本、依赖文件和构建配置计算的稳定 `CacheKey`，因此新的构建编号不会自动造成冷构建。并发构建同一缓存会被锁拒绝，避免缓存损坏。

只有正式门禁或确认缓存异常时才加 `-Clean`。

## 构建本地 AI 组件

本地组件只在其版本或推理依赖变化时构建：

```powershell
.\scripts\build_local_runtime.ps1 -Version 1.0.0 -Archive
```

输出目录包含：

- `ScanSciLocalRuntime\ScanSciLocalRuntime.exe`
- `ScanSciLocalRuntime-1.0.0.zip`
- `local-transformers.json`，记录版本、下载地址和 SHA256

上传 ZIP 后，可通过 `-PackageUrl` 写入正式 HTTPS 地址。主发行清单也可以直接包含：

```json
{
  "version": "0.3.0",
  "windows": {"url": "https://example/ScanSci-core.zip", "sha256": "..."},
  "components": {
    "local-transformers": {
      "version": "1.0.0",
      "windows": {"url": "https://example/ScanSciLocalRuntime-1.0.0.zip", "sha256": "..."}
    }
  }
}
```

用户在“设置 · 本地模型”中明确选择“安装运行组件”后，主程序读取同一发行清单，校验组件并安装到：

```text
%LOCALAPPDATA%\ScanSci\runtimes\local-transformers\versions\<version>\
```

`active.json` 指向当前版本。更新 core 不触碰该目录；只有组件版本变化才下载新的运行时。组件下载和启用均经过 SHA256 校验，失败时会保留已经可用的旧版本。

## 正式发行

正式门禁默认构建 `core`。它不携带大型推理依赖，也不预装模型权重：

- `build-info.json` 的 `package_profile` 为 `core`；
- 资料导入仅建立资料卡、章节和基础关键词索引；
- 用户可连接已经安装的本地运行时，或在发行方提供可信 HTTPS 清单时安装 `local-transformers` 组件；
- 只有运行时健康后，界面才允许下载 Qwen3 Embedding 0.6B 与 Qwen3 Reranker 0.6B；下载完成后自动校验并构建语义索引；
- 发行包必须低于 `core` 的体积门禁，原有桌面对话、知识库、模型和窗口验收继续通过。

官方按需运行组件必须使用国内可访问、带 SHA256 的发行清单构建：

```powershell
.\scripts\build_desktop.ps1 -PackageProfile core -RuntimeManifestUrl <国内可访问的清单地址> -OutputDir dist-core -BuildId compact
```
