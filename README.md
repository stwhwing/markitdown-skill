# markitdown-skill

A reusable agent skill that converts **documents and web pages** to Markdown using
[Microsoft's MarkItDown](https://github.com/microsoft/markitdown), with two practical
additions:

1. **Web page → Markdown pipeline** (`scripts/url_to_markdown.py` orchestrating five
   focused modules) — defeats JS-rendered SPA shells and anti-bot challenges (notably
   WeChat / `mp.weixin.qq.com`) that otherwise return empty pages. It fetches with a
   full browser User-Agent, falls back to headless Chrome/Edge `--dump-dom` rendering,
   then to embedded-JSON extraction, so you reliably get clean Markdown instead of a
   blank `<div id="root">`.
2. **`token_saver.py`** — a local estimator that shows how many tokens you *actually* pay
   when you feed the AI the cleaned Markdown instead of the raw file (and an honest
   saving % only when a real baseline exists).

The core idea: **convert first, then analyse.** Richly-formatted docs (PDF/PPTX/DOCX,
scanned images) carry huge layout/noise overhead; converting to plain Markdown typically
cuts AI token cost by 80%+.

> Version note: the skill version lives **only** in the `SKILL.md` frontmatter
> (`version:`); this README intentionally carries no version number so it cannot go
> stale. Since v1.7.0 the web converter is split into the modules listed below —
> `url_to_markdown.py` itself is a thin CLI orchestrator.

## What's inside

| File | Purpose |
|------|---------|
| `SKILL.md` | Skill manifest + usage instructions (used by WorkBuddy / ClawBot-style agents) |
| `scripts/url_to_markdown.py` | Web URL → Markdown — CLI orchestrator wiring the modules below |
| `scripts/url_security.py` | SSRF guard: target validation, internal/private address blocking |
| `scripts/url_fetch.py` | HTTP fetching with full browser User-Agent |
| `scripts/content_detect.py` | Content-type / SPA-shell / anti-bot page detection |
| `scripts/spa_extract.py` | Headless-browser rendering fallback + embedded-JSON extraction |
| `scripts/media_detect.py` | Media/link handling within pages |
| `scripts/token_saver.py` | Local token-cost / saving estimator |
| `scripts/measure_tokens.py` | Token counter / cost measurement for any text |
| `scripts/batch_convert.py` | Batch file → Markdown helper |
| `scripts/tests/test_url_fetch.py` | Regression tests for the URL fetcher (plain Python 3, no pytest needed) |
| `requirements.txt` | Bounded dependency spec (`pip install -r requirements.txt`) |
| `references/reference.md` | MarkItDown API reference |
| `references/USAGE-GUIDE.md` | Detailed CLI / API examples |
| `references/TOKEN-SAVER.md` | Token-saving methodology & honesty notes |
| `references/TOKEN-AUDIT.md` | Token audit methodology (optional component) |
| `references/SECURITY.md` | Security model & threat model (SSRF, resource caps, prompt-injection boundary) |

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

## Security

- **SSRF guard (on by default).** `scripts/url_to_markdown.py` only fetches `http`/`https`
  URLs. By default it refuses targets that resolve to the loopback address, private address
  space, link-local, reserved, or carrier-grade NAT ranges, the cloud instance-metadata
  endpoint, or internal hostnames (`*.local`, `*.internal`, `*.corp`, `*.lan`, `*.home`,
  `*.intranet`). It also refuses URLs that embed credentials (`user:pass@host`). Every redirect
  hop is re-checked by the guard, and redirect chains longer than 10 hops are refused.
- **Resource-exhaustion limits.** Raw responses larger than 32 MiB are rejected before being
  buffered; gzip/deflate/br bodies are decoded with a streaming, bounded reader that aborts past
  64 MiB of decompressed data (defeats decompression bombs).
- **Prompt-injection boundary.** Converted text is treated as untrusted data, not instructions.
  `url_to_markdown.py --sanitize` strips `<script>`/`<style>` blocks, neutralises
  `javascript:`/`data:` URIs, and wraps the payload between `--- EXTERNAL CONTENT ---` markers.
  `--manifest` records a sha256 + heuristic quality score per conversion for provenance. The
  full threat model is in [references/SECURITY.md](references/SECURITY.md).
- **Sandbox-first headless rendering.** The SPA fallback launches the browser with
  Chromium's sandbox enabled by default; `--no-sandbox` is only used automatically
  when running as root (where Chromium's sandbox cannot start) or when the sandboxed
  launch crashes in restricted containers. The fallback is never silent — a notice is
  printed to stderr — and there is no user-facing flag that turns the sandbox off.
- **`MARKITDOWN_BIN` is validated before use.** If that environment variable is set, it
  is honoured only when it is an absolute path to a regular, executable file that is not
  writable by group or other users; otherwise it is ignored and the trusted
  `python -m markitdown` module path is used. This closes the "redirect execution via a
  writable env var" hole.
- **`--allow-internal` is an explicit, off-by-default opt-in.** It exists solely for trusted
  local development against loopback/intranet pages, must be passed deliberately on the
  command line, and should never be used on shared, production, or sensitive hosts.
- **Network boundary, stated honestly.** Direct fetches are pinned to the validated IP
  (DNS-rebinding defence) and every redirect hop is re-checked; the browser fallback maps the
  target host to that same IP. Pinning is skipped when an HTTP proxy performs the connection,
  and sub-resource hosts inside a rendered page are not network-filtered (accepted limitation).
- **Optional external capabilities are off by default.** The skill can optionally use
  OpenAI image descriptions, Azure Document Intelligence, or third-party plugins, but these
  are disabled unless you explicitly enable them and they require your consent. Never feed
  private documents to an external service; local `markitdown` conversion does not phone
  home.

## Feedback

问题、建议与 bug 反馈请走这两个入口：

- **GitHub Issues**：<https://github.com/stwhwing/markitdown-skill/issues>
- **技能页**：skillhub.cn / ClawHub 上的 MarkItDown 技能页（评论与评分）

文档与代码同源于本仓库；技能的三平台发布版本（GitHub / skillhub.cn / ClawHub）保持一致。

## License

MIT — see [LICENSE](LICENSE). This skill wraps Microsoft's MarkItDown (also MIT); the
wrappers and documentation here are released independently under MIT.
