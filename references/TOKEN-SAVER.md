# Token-Saving Workflow — Methodology

This document explains the "给 AI 减负" idea behind the skill's Token-Saving Workflow,
and how `scripts/token_saver.py` estimates the saving.

## The core idea

When an AI agent is asked to "总结 / 分析 / 提取" a PDF, PPTX, DOCX, or scanned image,
the naive approach is to hand the model the raw file. But richly-formatted documents
encode far more than their meaning:

- Page layout, columns, text boxes
- Fonts, colors, sizes
- Headers, footers, page numbers
- Embedded images, logos, watermarks
- Repeated boilerplate across pages

None of that is the *information* the user wants. Yet every token the model reads costs
tokens (and often money). Converting the document to **plain Markdown** strips the noise
and keeps headings, lists, tables, and prose — the semantic content. The result is
typically **80%+ fewer tokens** for the same analytical task.

## How token_saver.py estimates

1. It converts the source to Markdown with MarkItDown.
2. It counts **Markdown tokens** with a `chars / 4` heuristic — this is the *actual* cost
   the AI pays when you feed it the cleaned Markdown.
3. It derives a **raw baseline** ONLY when one is honest:
   - Plain-text-like files (`.txt/.md/.csv/.json/...`): actual source text ÷ 4.
     (For these, converting is a near no-op, so the saving is usually ~0% — correct.)
   - PDF / images: pass `--pages N`; baseline = `N * 1500` (a rough dense-page estimate).
   - Any format: pass `--raw-estimate N` with a number you trust (e.g. a known bill).
4. It reports `saving % = (raw - markdown) / raw` **only when a baseline exists**.
   For compressed binary formats without a baseline, it does NOT fabricate a number —
   it just reports the Markdown token cost (the AI cannot ingest the raw binary anyway).

## Where the big savings actually come from

- **PDF (especially scanned / complex layouts) and images (image input):** the alternative to
  Markdown is feeding the model the full layout, fonts, or a multimodal image — often
  5–10× the tokens of the cleaned text. This is the article's hero case (~80%+).
- **DOCX / PPTX / XLSX:** the model can't read the binary directly; Markdown is the
  practical input. The saving vs. the *raw* is modest (mainly stripping XML/boilerplate),
  but the value is *enabling* the AI to read the file at all.
- **Plain text (.md/.txt/.csv/.json):** converting is a no-op; just feed it.

## Honesty notes (read before quoting numbers)

- The `chars / 4` rule is an **approximation**. English text is ~4 chars/token; CJK text
  is often ~1.5–2 chars/token, so for Chinese-heavy documents the estimate may be low.
- The `--pages` baseline is a rough per-page token assumption, not a measurement.
- Treat any printed % as "order-of-magnitude saving", never as an invoice.
- Do NOT claim a saving % for a binary source unless you supplied `--pages` or
  `--raw-estimate`; otherwise report only the Markdown token cost.

## When NOT to convert first

- Already-plain text (`.md/.txt/.csv/.json`) — converting is a no-op; just feed it.
- When the task explicitly needs layout (e.g. "recreate this slide's design").
- When pixel-perfect fidelity of tables/figures matters more than token cost.

## 如何审计 token 成本（Grep 优先方法）

`token_saver.py` 给出「Markdown 实际成本」的单点估算。要审计一次真实任务的省 token 效果，建议配合**链路级**方法：

1. **转换前先测基线**：对大文件/网页，先看原始体量。文本类（`.txt/.md/.csv/.json`）基线 = 源文本 ÷ 4；PDF/图片用 `--pages N`；或用 `--raw-estimate N` 代入你已知的账单数。
2. **转换 → Grep → 按需 Read**：转成 Markdown 后，不要整篇读。先 `Grep` 目标章节/关键词，只 `Read` 命中段落。这一步的节省往往比「转换」本身更大，但 `token_saver.py` 不计入——它只量化「文件 → Markdown」这一段。
3. **实测对比法（最可靠）**：同一份材料，分别用「整篇原文/HTML 喂 AI」与「转换后 Grep+按需读」两种方式，让模型跑同一任务，对比两次回复的实际 token 用量（多数平台/网关可在用量明细里看到）。差值才是端到端真实节省。
4. **JSON 回退也缩量**：网页 SPA 兜底抽取 `__NEXT_DATA__` 时，`url_to_markdown.py` 已改用**递归平铺抽取**，只留正文类字段，避免把 10–20KB 的原生 JSON 灌进上下文。

> 注意：`token_saver.py` 是**本地**估算器，公开版不会向任何服务器上报任何数据。跨端聚合上报属于私有版能力，公开版不涉及。

## 配套：通用 Token 审计（可选组件）

Token-Saving 工作流整体为**可选 / OPTIONAL**。除上面的「单次转换成本估算」外，本技能还附带
**通用 token 审计**能力，同样可选、同样不向任何服务器上报：

- `scripts/measure_tokens.py` — **任意文本/文件**的 token 量级量测与 `--compare` 对比（不限于转换产物）。
- `references/TOKEN-AUDIT.md` — 审计流程、缩量技术排序、WebFetch-vs-skill 实测案例与诚实口径。

核心能力（文档/网页 → Markdown）不依赖以上任何一项。详见 [TOKEN-AUDIT.md](TOKEN-AUDIT.md)。

## Example

```bash
python "<skill-dir>/scripts/token_saver.py" report.pdf -o report.md
# --- Token cost (approximate) ---
# Source                 : report.pdf (.pdf)
# Markdown tokens (cost) : 12,340
# Raw estimate (upper)   : 84,500
# Estimated saving       : 85.4%
```
