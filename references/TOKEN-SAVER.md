# Token-Saving Workflow — Methodology / Token 节省工作流 — 方法论

This document explains the "给 AI 减负" idea behind the skill's Token-Saving Workflow,
and how `scripts/token_saver.py` estimates the saving.

本文档解释本技能「Token 节省工作流」背后的「给 AI 减负」理念，以及 `scripts/token_saver.py` 如何估算节省量。

## The core idea / 核心理念

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

当 AI 智能体被要求「总结 / 分析 / 提取」一份 PDF、PPTX、DOCX 或扫描图时，朴素做法是把原始文件直接交给模型。但富格式文档编码的信息远超其含义：

- 页面版式、分栏、文本框
- 字体、颜色、字号
- 页眉、页脚、页码
- 内嵌图像、徽标、水印
- 跨页重复的样板内容

这些都不是用户想要的*信息*。然而模型读取的每一个 token 都消耗 token（往往还有金钱）。把文档转为**纯 Markdown** 能剥离噪声，只保留标题、列表、表格与正文——即语义内容。同样的分析任务通常能减少 **80%+ 的 token**。

## How token_saver.py estimates / token_saver.py 如何估算

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

1. 用 MarkItDown 把来源转为 Markdown。
2. 用 `chars / 4` 启发式统计 **Markdown token 数**——这是你把清洗后的 Markdown 喂给 AI 时*实际*支付的成本。
3. 仅在存在诚实基线时才推导 **原始基线**：
   - 类纯文本文件（`.txt/.md/.csv/.json/...`）：实际源文本 ÷ 4。（这类转换近乎无操作，节省通常约 0%——这是正确的。）
   - PDF / 图片：传 `--pages N`；基线 = `N * 1500`（粗略的密集页估算）。
   - 任意格式：用你信任的数字传 `--raw-estimate N`（例如一张已知账单）。
4. **仅当存在基线时**才报告 `节省 % = (原始 - markdown) / 原始`。对没有基线的压缩二进制格式，它**不会编造数字**——只报告 Markdown token 成本（AI 本就无法直接读取原始二进制）。

## Where the big savings actually come from / 真正的节省来自哪里

- **PDF (especially scanned / complex layouts) and images (image input):** the alternative to
  Markdown is feeding the model the full layout, fonts, or a multimodal image — often
  5–10× the tokens of the cleaned text. This is the article's hero case (~80%+).
- **DOCX / PPTX / XLSX:** the model can't read the binary directly; Markdown is the
  practical input. The saving vs. the *raw* is modest (mainly stripping XML/boilerplate),
  but the value is *enabling* the AI to read the file at all.
- **Plain text (.md/.txt/.csv/.json):** converting is a no-op; just feed it.

- **PDF（尤其扫描件 / 复杂版式）与图片（图像输入）**：Markdown 的替代方案是把完整版式、字体或多模态图像喂给模型——往往是清洗后文本的 5–10 倍 token。这是本文的旗舰案例（约 80%+）。
- **DOCX / PPTX / XLSX**：模型无法直接读二进制；Markdown 是实际可行的输入。相比*原始*的节省较温和（主要是剥离 XML/样板），但价值在于*让* AI 能读这个文件。
- **纯文本（.md/.txt/.csv/.json）**：转换是无操作；直接喂即可。

## Honesty notes (read before quoting numbers) / 诚实性说明（引用数字前必读）

- The `chars / 4` rule is an **approximation**. English text is ~4 chars/token; CJK text
  is often ~1.5–2 chars/token, so for Chinese-heavy documents the estimate may be low.
- The `--pages` baseline is a rough per-page token assumption, not a measurement.
- Treat any printed % as "order-of-magnitude saving", never as an invoice.
- Do NOT claim a saving % for a binary source unless you supplied `--pages` or
  `--raw-estimate`; otherwise report only the Markdown token cost.

- `chars / 4` 规则是**近似**。英文约 4 字符/token；中文（CJK）常约 1.5–2 字符/token，故对中文密集文档估算可能偏低。
- `--pages` 基线是粗略的每页 token 假设，并非实测。
- 任何打印出的百分比都只当「数量级节省」，绝不当发票。
- 除非你提供了 `--pages` 或 `--raw-estimate`，否则**不要**对二进制来源声称节省百分比；否则只报告 Markdown token 成本。

## When NOT to convert first / 何时不应先转换

- Already-plain text (`.md/.txt/.csv/.json`) — converting is a no-op; just feed it.
- When the task explicitly needs layout (e.g. "recreate this slide's design").
- When pixel-perfect fidelity of tables/figures matters more than token cost.

- 已是纯文本（`.md/.txt/.csv/.json`）——转换是无操作；直接喂即可。
- 当任务明确需要版式时（例如「复刻这张幻灯片的设计」）。
- 当表格/图的像素级保真比 token 成本更重要时。

## Example / 示例

```bash
python "<skill-dir>/scripts/token_saver.py" report.pdf -o report.md
# --- Token Saving Estimate (approximate) ---
# Source                 : report.pdf (.pdf)
# Markdown tokens (cost) : 12,340
# Raw estimate (upper)   : 84,500
# Estimated saving       : 85.4%
```
