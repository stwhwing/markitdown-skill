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

- **PDF (especially scanned / complex layouts) and images (OCR):** the alternative to
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

## Example

```bash
python "<skill-dir>/scripts/token_saver.py" report.pdf -o report.md
# --- Token cost (approximate) ---
# Source                 : report.pdf (.pdf)
# Markdown tokens (cost) : 12,340
# Raw estimate (upper)   : 84,500
# Estimated saving       : 85.4%
```
