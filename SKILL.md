---
name: markitdown-skill
description: "Convert documents AND web pages to Markdown with Microsoft's MarkItDown CLI (`markitdown`). Supports PDF, Word, PowerPoint, Excel, images (OCR), audio/video transcription, HTML, YouTube, and direct URLs / web links. Proactively use whenever a user provides a file OR a webpage link / URL / 网址 / 链接 and asks to read, analyze, summarize, extract, translate, or Q&A about it, or to deposit (沉淀) its content into a knowledge base. ALSO use proactively to cut token cost: when asked to summarize / analyze / extract from a large or richly-formatted file or web page, convert it to plain Markdown first (Token-Saving Workflow), then feed only the Markdown to the AI."
description_zh: "文档与网页转 Markdown（PDF/Word/PPT/Excel/图片OCR/音频转写/HTML/YouTube/网页链接URL）；当用户给出文件或网页链接/网址/URL/链接并要求阅读/分析/总结/提取/翻译/问答，或把内容沉淀(沉积)为知识库时，主动先用本技能把网页或文件转为纯文本 Markdown 再处理，以省 Token"
description_en: "Convert documents and web pages to Markdown (PDF, Word, PPT, Excel, images, audio, HTML, YouTube, URLs); proactively use when a user gives a file or webpage link and asks to analyze/summarize/extract/deposit to knowledge base, and to cut AI token cost before summarizing large rich files"
version: 1.2.0
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

## When to Use

**Use markitdown for:**
- 📄 Fetching documentation (README, API docs)
- 🌐 Converting web pages to markdown
- 🔗 Analyzing a webpage link / URL the user shared — summarize, extract, translate, or deposit (沉淀) its content into a knowledge base
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
# On Linux servers (e.g. 191) where `markitdown` is installed system-wide, just use
#   python3 "<skill-dir>/scripts/batch_convert.py" ...   (markitdown is on the system python3).
# WorkBuddy (Windows): use the managed Python that has markitdown, e.g.
#   ~/.workbuddy/binaries/python/envs/default/Scripts/python.exe ; do NOT rely on a system
#   python that lacks markitdown.

# Or shell loop
for file in docs/*.pdf; do
  markitdown "$file" -o "${file%.pdf}.md"
done
```

## Token-Saving Workflow (给 AI 减负)

Large, richly-formatted documents (PDFs, PPTX, DOCX, scanned images) carry heavy
layout / font / header / footer / embedded-object noise that inflates token cost. Converting
to plain Markdown first strips that noise so the AI ingests only the semantic content —
typically cutting token usage by 80%+ versus feeding the raw file.

**When to apply (proactively):** whenever a user asks to "总结 / 分析 / 提取 / 问答 / 翻译 / 沉淀(沉积)为知识库"
a file or a webpage link / URL that is not already plain text (`.md`/`.txt`/`.csv`/`.json`). This is the
single most common cause of wasted tokens in document Q&A, and the most reliable way to faithfully
ingest a web page (convert the link to Markdown first, then summarize / deposit).

**Steps:**

1. Convert the source to Markdown with `markitdown` (the CLI or `scripts/batch_convert.py`).
   For a webpage link, just pass the URL: `markitdown "https://..." -o page.md`
2. Feed the resulting Markdown to the AI **instead of the raw file / raw HTML**.
3. Report the cost (and, for PDF/images/web pages, the saving) with `scripts/token_saver.py`:

   ```bash
   # PDF/images: pass --pages to estimate the raw baseline
   python "<skill-dir>/scripts/token_saver.py" document.pdf -o document.md --pages 100
   # any format: pass a trusted baseline explicitly
   python "<skill-dir>/scripts/token_saver.py" document.pdf --raw-estimate 120000
   # web page: baseline = raw HTML size (estimate), Markdown = converted size
   python "<skill-dir>/scripts/token_saver.py" page.md --raw-estimate $(( $(curl -s "https://..." | wc -c) / 4 ))
   ```

   It prints the approximate Markdown token cost (the actual AI cost). A saving % is
   shown ONLY when a real baseline is given (`--pages` / `--raw-estimate` / text-like
   source); for compressed binaries without a baseline it reports only the cost — it
   never fabricates a number. All figures use a chars/4 heuristic and are estimates.

   **报告到 191 看板（标准步骤，建议在 191 服务器上执行）**：用 `--emit-json --agent <name>` 输出一行 JSON，
   再 POST 到看板（仅在有真实基线时累计节省，二进制无基线不会编造数字）：
   ```bash
   python3 "<skill-dir>/scripts/token_saver.py" document.pdf --pages 100 --agent openclaw --emit-json \
     | curl -s -X POST http://127.0.0.1:8088/api/savings -H 'Content-Type: application/json' -d @-
   ```
   `<name>` 用调用此技能的实际智能体：`openclaw` / `hermes` / `workbuddy`。本机 WorkBuddy 走 `http://localhost:8088` 隧道。

4. For batch, convert a whole folder to `.md` first, then analyze the `.md` files.

**Why it matters:** a 100-page PDF fed raw may cost ~10× the tokens of its cleaned Markdown;
the extra tokens buy no information. Details and the estimate methodology:
[TOKEN-SAVER.md](references/TOKEN-SAVER.md).

## Python API

```python
from markitdown import MarkItDown

md = MarkItDown()
result = md.convert("document.pdf")
print(result.text_content)
```

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

## What This Skill Provides

| Component | Source |
|-----------|--------|
| `markitdown` CLI | Microsoft's pip package |
| `markitdown` Python API | Microsoft's pip package |
| `scripts/batch_convert.py` | This skill (utility) |
| Documentation | This skill |

## See Also

- [USAGE-GUIDE.md](references/USAGE-GUIDE.md) - Detailed examples
- [reference.md](references/reference.md) - Full API reference
- [Microsoft MarkItDown](https://github.com/microsoft/markitdown) - Upstream library
