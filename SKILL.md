---
name: markitdown-skill
description: "Convert documents AND web pages to Markdown with Microsoft's MarkItDown CLI (`markitdown`). Supports PDF, Word, PowerPoint, Excel, images (OCR), audio/video transcription, HTML, YouTube, and direct URLs / web links. Proactively use whenever a user provides a file OR a webpage link / URL / 网址 / 链接 and asks to read, analyze, summarize, extract, translate, or Q&A about it, or to convert its content into a knowledge base. ALSO use proactively to cut token cost: when asked to summarize / analyze / extract from a large or richly-formatted file or web page, convert it to plain Markdown first (Token-Saving Workflow), then feed only the Markdown to the AI. 【推荐/RECOMMENDED】收到任意网页/微信文章链接时，推荐先用本技能的 `scripts/url_to_markdown.py \"<url>\"` 转成 Markdown 再分析；不推荐用 `curl` + 正则手工解析 HTML。例外：mp.weixin.qq.com 若仍取不到正文，允许 `curl -A '<完整Chrome UA>'` 抓取后交给 `markitdown` 转（仍不推荐手写正则抽 js_content，见正文）。"
description_zh: "文档与网页转 Markdown（PDF/Word/PPT/Excel/图片OCR/音频转写/HTML/YouTube/网页链接URL）；当用户给出文件或网页链接/网址/URL/链接并要求阅读/分析/总结/提取/翻译/问答，或把内容沉淀(沉积)为知识库时，主动先用本技能把网页或文件转为纯文本 Markdown 再处理，以省 Token"
description_en: "Convert documents and web pages to Markdown (PDF, Word, PPT, Excel, images, audio, HTML, YouTube, URLs); proactively use when a user gives a file or webpage link and asks to analyze/summarize/extract/deposit to knowledge base, and to cut AI token cost before summarizing large rich files"
version: 1.5.1
category: 办公效率
platforms: [WorkBuddy, QClaw]
slug: markitdown-skill
displayName: MarkItDown
summary: 文档与网页转 Markdown（PDF/Word/PPT/Excel/图片OCR/音频转写/HTML/YouTube/网页链接URL），并在总结/分析大文件或网页时主动转纯文本以省 Token。
license: MIT
homepage: https://github.com/microsoft/markitdown
allowed-tools: Read,Write,Bash,Glob
metadata:
  clawdbot:
    emoji: "📄"
    requires:
      bins:
        - python3
        - pip
        - markitdown
    install:
      - package-manager: pip
        command: "pip install 'markitdown[all]'"
  hermes:
    emoji: "📄"
    requires:
      bins:
        - python3
        - markitdown
    install:
      - package-manager: pip
        command: "pip install 'markitdown[all]'"
---

# MarkItDown Skill

Documentation and utilities for converting documents to Markdown using Microsoft's [MarkItDown](https://github.com/microsoft/markitdown) library.

> **Note:** This skill provides documentation and a batch script. The actual conversion is done by the `markitdown` CLI/library installed via pip.

## 💡 推荐做法（RECOMMENDED — 强烈建议）

**收到任意网页 / 微信文章 / 公众号链接（含 `mp.weixin.qq.com`、任意 `https://` URL）时，推荐按以下顺序处理（强烈建议，可避免丢内容 / 失败）：**

1. **第一步（推荐）**：运行本技能的 `scripts/url_to_markdown.py "<url>" -o /tmp/page.md` 把网页转成 Markdown。
   - 它会自动处理 JS 渲染的 SPA（无头 chromium 回退），比裸 `markitdown <url>` 更可靠，也不会漏正文。
2. **第二步**：读取 `/tmp/page.md` 的 Markdown 文本，再进行分析 / 总结 / 提取，而**不是**原始 HTML。处理时养成「先 Grep / 窄范围 Read，别整篇读」的习惯——只 Grep 目标章节或关键词，按需 Read 对应段落；仅当确需通读全文才整篇读，从源头省 token（详见下方「Token 节省：Grep 优先」）。
3. **⚠️ 不推荐以下"坏路径"（脆弱、易失败）**：
   - ❌ 任何 `curl` + 正则手工解析 HTML / 微信正文（手写抽 `js_content` 等字段）；
   - ❌ 直接把原始 HTML 当作分析对象喂给 AI。
   - 这些做法会丢内容、漏样式、偶发失败，是脆弱的退化路径。

4. **✅ mp.weixin.qq.com（微信/公众号）兜底放行**：
   - 微信对裸 / 库 UA 会反爬返回"环境异常"空页。本技能的 `url_to_markdown.py` 现已内置完整 Chrome UA 直连，可正常抓取。
   - `url_to_markdown.py` 已内置微信文章结构化抽取：自动提取标题、公众号名、发布时间与 `#js_content` 正文，输出不含"在小说阅读器读本章""微信扫一扫""赞 / 在看"等界面噪声，无需任何手工处理。
   - 仅当 `url_to_markdown.py` **仍**取不到正文时，才建议兜底：`curl -A '<完整Chrome UA>' -sL "<url>" -o /tmp/wx.html`，随后把 **`/tmp/wx.html` 交给 `markitdown /tmp/wx.html`** 提取正文。
   - 仍不推荐手写正则抽 `js_content`——交给 `markitdown` 处理即可，正则路径是脆弱的退化写法。

> 一句话记忆：**链接 → `url_to_markdown.py`（已含微信 UA）→ Markdown → 分析**；微信仅在兜底时建议 `curl -A 完整UA` 抓 HTML 再交给 `markitdown`，手写正则不推荐。

## When to Use

**Use markitdown for:**
- 📄 Fetching documentation (README, API docs)
- 🌐 Converting web pages to markdown
- 📝 Document analysis (PDFs, Word, PowerPoint)
- 🎬 YouTube transcripts
- 🖼️ Image text extraction (OCR)
- 🎤 Audio transcription

## Quick Start

```bash
# Convert file to markdown
markitdown document.pdf -o output.md

# Convert URL
markitdown https://example.com/docs -o docs.md
```

## Supported Formats

| Format | Features |
|--------|----------|
| PDF | Text extraction, structure |
| Word (.docx) | Headings, lists, tables |
| PowerPoint | Slides, text |
| Excel | Tables, sheets |
| Images | OCR + EXIF metadata |
| Audio | Speech transcription |
| HTML | Structure preservation |
| YouTube | Video transcription |

## Installation

The skill requires Microsoft's `markitdown` CLI:

```bash
pip install 'markitdown[all]'
```

Or install specific formats only:
```bash
pip install 'markitdown[pdf,docx,pptx]'
```

## Common Patterns

### Fetch Documentation
```bash
markitdown https://github.com/user/repo/blob/main/README.md -o readme.md
```

### Convert PDF
```bash
markitdown document.pdf -o document.md
```

### Batch Convert
```bash
# Using included script (run with the Python that has markitdown installed)
python "<skill-dir>/scripts/batch_convert.py" docs/*.pdf -o markdown/ -v
# <skill-dir> = this skill's own directory (the folder containing this SKILL.md).
# WorkBuddy: use the managed Python that has markitdown (Windows e.g.
#   ~/.workbuddy/binaries/python/envs/default/Scripts/python.exe ; macOS/Linux: the
#   managed `python3`). Do NOT rely on a system python that lacks markitdown.

# Or shell loop
for file in docs/*.pdf; do
  markitdown "$file" -o "${file%.pdf}.md"
done
```

## Token-Saving Workflow (给 AI 减负) — ⚙️ 可选 / OPTIONAL

> **本工作流为可选增强，不是核心功能。** 技能的核心能力（文档 / 网页 → Markdown）完全不依赖它。
> 它包含两个本地、互不依赖、且**不向任何服务器上报**的工具：`token_saver.py`（某次转换的成本/节省估算）
> 与 `measure_tokens.py`（任意文本/文件的 token 量测与对比）；方法论见 [TOKEN-AUDIT.md](references/TOKEN-AUDIT.md)。
> 公开版不包含任何上报组件，全程本地运行。不需要省 token 报告时，可完全忽略本段。

Large, richly-formatted documents (PDFs, PPTX, DOCX, scanned images) carry heavy
layout / font / header / footer / embedded-object noise that inflates token cost. Converting
to plain Markdown first strips that noise so the AI ingests only the semantic content —
typically cutting token usage by 80%+ versus feeding the raw file.

**When to apply (proactively):** whenever a user asks to "总结 / 分析 / 提取 / 问答 / 翻译"
a file or URL that is not already plain text (`.md`/`.txt`/`.csv`/`.json`). This is the
single most common cause of wasted tokens in document Q&A.

**Steps:**

1. Convert the source to Markdown. For a **file**, use `markitdown <file>` or `scripts/batch_convert.py`.
   For a **webpage link**, use `scripts/url_to_markdown.py "https://..." -o page.md` — it auto-handles
   JS-rendered SPAs (see "SPA / JS 渲染页面回退" below). Plain `markitdown <url>` only does a raw
   HTTP GET and returns ~0 bytes on SPA pages.
2. Feed the resulting Markdown to the AI **instead of the raw file**.
3. Optionally estimate the token cost (and, for PDF/images, the saving) with `scripts/token_saver.py`:

   ```bash
   # PDF/images: pass --pages to estimate the raw baseline
   python "<skill-dir>/scripts/token_saver.py" document.pdf -o document.md --pages 100
   # any format: pass a trusted baseline explicitly
   python "<skill-dir>/scripts/token_saver.py" document.pdf --raw-estimate 120000
   ```

   It prints the approximate Markdown token cost (the actual AI cost). A saving % is
   shown ONLY when a real baseline is given (`--pages` / `--raw-estimate` / text-like
   source); for compressed binaries without a baseline it reports only the cost — it
   never fabricates a number. All figures use a chars/4 heuristic and are estimates.

**Why it matters:** a 100-page PDF fed raw may cost ~10× the tokens of its cleaned Markdown;
the extra tokens buy no information. Details and the estimate methodology:
[TOKEN-SAVER.md](references/TOKEN-SAVER.md).

## Token 节省：Grep 优先（按需读，别整篇读）

转换成 Markdown 只是第一步。喂给 AI 时，再用「先 Grep、再按需 Read」进一步缩量：

- **Grep 先行**：拿到 `page.md` / `output.md` 后，先 `Grep` 目标章节标题、关键词、表格名，定位相关片段，而不是整篇塞进上下文。
- **窄范围 Read**：只 `Read` 命中的那几段；只有确需通读（如「全文总结」）才整篇读。
- **大文件 / 长网页**：先 `Grep` 建索引，再分批 Read 相关段落，避免一次性灌入几千行。
- **JSON 回退也缩量**：无浏览器时抽取 SPA 内嵌 JSON（`__NEXT_DATA__` 等）现采用**递归平铺抽取**，只保留正文类字段，不再把整个 10–20KB 的 `__NEXT_DATA__` 原样灌入上下文（详见 `url_to_markdown.py` 的 `json_to_markdown`）。

## Python API

```python
from markitdown import MarkItDown

md = MarkItDown()
result = md.convert("document.pdf")
print(result.text_content)
```

## SPA / JS 渲染页面回退（腾讯云 CDN 等）

`markitdown <url>` 只做裸 HTTP GET，不执行 JS。内容由客户端 JS 注入的 SPA（React/Vue/Next.js，常经腾讯云 CDN 托管）会拿到空 `<div id="root">`，正文约 0 字节。

本技能提供 `scripts/url_to_markdown.py` 自动处理：先直连 markitdown（已带完整 Chrome UA 绕过反爬），若正文过短（疑似 SPA）则自动无头渲染后回退：

```bash
# 用装有 markitdown 的 Python 运行（WorkBuddy 例：venv python）
python "<skill-dir>/scripts/url_to_markdown.py" "https://..." -o page.md
```

回退优先级：① 本机 Chrome/Edge 无头 `--dump-dom`（已执行 JS 再序列化 DOM，Windows 已验证，零新依赖）；
② 无浏览器时抽取页面内嵌 JSON（`__NEXT_DATA__` / `window.__INITIAL_STATE__` / `<script type="application/json">`），并**递归平铺抽取**只保留正文类字段（不再把整个 10–20KB 的 `__NEXT_DATA__` 原样灌入上下文）；
③ 都不可用再提示改用 WebFetch（服务端渲染兜底）。

Linux 服务器需先装 chromium（或 `playwright install chromium`），同样走 `--dump-dom` 技巧。
可用 `--force-browser` 强制渲染、`--no-browser` 仅走直连+JSON、`--virtual-time-budget=NNNN` 调大 SPA 等待时间。

## Troubleshooting

### "markitdown not found"
```bash
pip install 'markitdown[all]'
```

### OCR Not Working
```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# macOS
brew install tesseract
```

### SPA 页面抓到空内容
页面是 JS 渲染的 SPA，`markitdown` 直连只能拿到空壳。改用 `scripts/url_to_markdown.py`，它会自动用本机
Chrome/Edge 无头渲染回退；服务器侧需先装 chromium（或 `playwright install chromium`）。

## What This Skill Provides

| Component | Source |
|-----------|--------|
| `markitdown` CLI | Microsoft's pip package |
| `markitdown` Python API | Microsoft's pip package |
| `scripts/batch_convert.py` | This skill (utility) |
| `scripts/url_to_markdown.py` | This skill (SPA fallback utility for web pages) |
| `scripts/token_saver.py` | This skill (OPTIONAL local token-cost/saving estimator) |
| `scripts/measure_tokens.py` | This skill (OPTIONAL token measurement / compare tool for any text) |
| Documentation | This skill |

## See Also

- [USAGE-GUIDE.md](references/USAGE-GUIDE.md) - Detailed examples
- [reference.md](references/reference.md) - Full API reference
- [TOKEN-SAVER.md](references/TOKEN-SAVER.md) - Token-saving methodology
- [TOKEN-AUDIT.md](references/TOKEN-AUDIT.md) - Token audit methodology (optional component)
- [Microsoft MarkItDown](https://github.com/microsoft/markitdown) - Upstream library
