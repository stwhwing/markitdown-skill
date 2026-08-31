# markitdown-skill

A reusable agent skill that converts **documents and web pages** to Markdown using
[Microsoft's MarkItDown](https://github.com/microsoft/markitdown), with two practical
additions:

1. **`url_to_markdown.py`** — a web-page converter that defeats JS-rendered SPA shells
   and anti-bot challenges (notably WeChat / `mp.weixin.qq.com`) that otherwise return
   empty pages. It fetches with a full browser User-Agent, falls back to headless
   Chrome/Edge `--dump-dom` rendering, then to embedded-JSON extraction, so you reliably
   get clean Markdown instead of a blank `<div id="root">`.
2. **`token_saver.py`** — a local estimator that shows how many tokens you *actually* pay
   when you feed the AI the cleaned Markdown instead of the raw file (and an honest
   saving % only when a real baseline exists).

The core idea: **convert first, then analyse.** Richly-formatted docs (PDF/PPTX/DOCX,
scanned images) carry huge layout/noise overhead; converting to plain Markdown typically
cuts AI token cost by 80%+.

## What's inside

| File | Purpose |
|------|---------|
| `SKILL.md` | Skill manifest + usage instructions (used by WorkBuddy / ClawBot-style agents) |
| `scripts/url_to_markdown.py` | Web URL → Markdown with SPA + anti-bot fallback |
| `scripts/token_saver.py` | Local token-cost / saving estimator |
| `scripts/batch_convert.py` | Batch file → Markdown helper |
| `references/reference.md` | MarkItDown API reference |
| `references/USAGE-GUIDE.md` | Detailed CLI / API examples |
| `references/TOKEN-SAVER.md` | Token-saving methodology & honesty notes |

## Requirements

- Python 3.10+
- `markitdown` (install with `pip install 'markitdown[all]'`)
- *(Optional, for SPA fallback)* a headless browser — Chrome/Edge on Windows, or
  `chromium` / `playwright install chromium` on Linux/macOS.

## Quick start

```bash
# Install the engine
pip install 'markitdown[all]'

# Web page → Markdown (handles SPA + WeChat anti-bot)
python scripts/url_to_markdown.py "https://example.com/article" -o page.md

# File → Markdown
markitdown document.pdf -o document.md

# Estimate the token saving of converting a PDF
python scripts/token_saver.py document.pdf --pages 40
```

## Using it as an agent skill

Drop this folder into your agent's skill directory (e.g. `~/.workbuddy/skills/markitdown-skill/`
for WorkBuddy, or your platform's equivalent). The agent will then proactively convert
files and links to Markdown before analysing them, and will route every web link through
`url_to_markdown.py` rather than hand-rolled `curl` + regex parsing.

## License

MIT — see [LICENSE](LICENSE). This skill wraps Microsoft's MarkItDown (also MIT); the
wrappers and documentation here are released independently under MIT.
