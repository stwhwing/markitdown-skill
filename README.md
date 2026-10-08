# markitdown-skill — 文档/网页转 Markdown 安全技能 / Documents & web pages → Markdown, security-hardened

![Security](https://img.shields.io/badge/security-CLEAN-brightgreen)
![SkillHub eval](https://img.shields.io/badge/SkillHub%20eval-4.7%2F5-blue)
![License](https://img.shields.io/badge/license-MIT-blue)
![Platforms](https://img.shields.io/badge/platforms-GitHub%20%7C%20skillhub%20%7C%20ClawHub-lightgrey)

**安全加固的文档/网页转 Markdown 技能**——内置 SSRF 守卫、资源上限、提示注入边界，并附带本地 token 省耗估算（云鼎安全评测 100/100「可信」）。

**A security-hardened document/web → Markdown skill** — built-in SSRF guard, resource caps, and a prompt-injection boundary, plus a local token-cost estimator (Yunding security audit: 100/100, "trusted").

---

## 概述 / Overview

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

可复用的 Agent 技能，基于[微软 MarkItDown](https://github.com/microsoft/markitdown) 将**文档与网页**转为 Markdown，并加了两件实用增强：

1. **网页 → Markdown 流水线**（`scripts/url_to_markdown.py` 编排五个专注模块）——攻克 JS 渲染的 SPA 外壳与反爬挑战（典型如微信 `mp.weixin.qq.com`），否则只会返回空页。它用完整浏览器 User-Agent 抓取，回退到无头 Chrome/Edge 的 `--dump-dom` 渲染，再退化为内嵌 JSON 抽取，从而稳定得到干净 Markdown，而非空白的 `<div id="root">`。
2. **`token_saver.py`**——本地估算器，告诉你把清洗后的 Markdown（而非原始文件）喂给 AI 时*实际*省了多少 token（且仅在存在真实基线时才给出诚实的节省百分比）。

核心理念：**先转换，再分析。** 富格式文档（PDF/PPTX/DOCX、扫描图）带有巨大的版式/噪声开销；转为纯 Markdown 通常能砍掉 80%+ 的 AI token 成本。

> Version note / 版本说明：the skill version lives **only** in the `SKILL.md` frontmatter
> (`version:`); this README intentionally carries no version number so it cannot go stale.
> 技能版本**仅**存在于 `SKILL.md` 的 frontmatter（`version:`）；本 README 刻意不带版本号，以免过期。Since v1.7.0 the web converter is split into the modules listed below — `url_to_markdown.py` itself is a thin CLI orchestrator.自 v1.7.0 起网页转换器已拆分为下方模块——`url_to_markdown.py` 本身只是薄封装的 CLI 编排器。

---

## 内含什么 / What's inside

| File / 文件 | Purpose / 用途 |
|------|---------|
| `SKILL.md` | Skill manifest + usage instructions (used by WorkBuddy / ClawBot-style agents) · 技能清单与使用说明（供 WorkBuddy / ClawBot 类 Agent 使用） |
| `scripts/url_to_markdown.py` | Web URL → Markdown — CLI orchestrator wiring the modules below · 网页 URL → Markdown 的 CLI 编排器 |
| `scripts/url_security.py` | SSRF guard: target validation, internal/private address blocking · SSRF 守卫：目标校验、内网/私有地址拦截 |
| `scripts/url_fetch.py` | HTTP fetching with full browser User-Agent · 带完整浏览器 User-Agent 的 HTTP 抓取 |
| `scripts/content_detect.py` | Content-type / SPA-shell / anti-bot page detection · 内容类型 / SPA 外壳 / 反爬页检测 |
| `scripts/spa_extract.py` | Headless-browser rendering fallback + embedded-JSON extraction · 无头浏览器渲染回退 + 内嵌 JSON 抽取 |
| `scripts/media_detect.py` | Media/link handling within pages · 页面内媒体/链接处理 |
| `scripts/token_saver.py` | Local token-cost / saving estimator · 本地 token 成本 / 节省估算器 |
| `scripts/measure_tokens.py` | Token counter / cost measurement for any text · 任意文本的 token 计数 / 成本测算 |
| `scripts/batch_convert.py` | Batch file → Markdown helper · 批量文件 → Markdown 辅助 |
| `scripts/tests/` | Regression tests — run all with `python scripts/tests/run_all.py` (plain Python 3, no pytest needed) · 回归测试——用 `python scripts/tests/run_all.py` 全跑（纯 Python 3，无需 pytest） |
| `requirements.txt` | Bounded dependency spec (`pip install -r requirements.txt`) · 上界锁定的依赖声明 |
| `references/reference.md` | MarkItDown API reference · MarkItDown API 参考 |
| `references/USAGE-GUIDE.md` | Detailed CLI / API examples · 详细 CLI / API 示例 |
| `references/TOKEN-SAVER.md` | Token-saving methodology & honesty notes · token 节省方法论与诚实性说明 |
| `references/SECURITY.md` | Security model & threat model (SSRF, resource caps, prompt-injection boundary) · 安全模型与威胁模型 |

---

## 环境要求 / Requirements

- Python 3.10+
- `markitdown` (install with `pip install 'markitdown[all]'`)
- *(Optional, for SPA fallback)* a headless browser — Chrome/Edge on Windows, or
  `chromium` / `playwright install chromium` on Linux/macOS.

---

## 快速开始 / Quick start

```bash
# Install the engine / 安装引擎
pip install 'markitdown[all]'

# Web page → Markdown (handles SPA + WeChat anti-bot)
# 网页 → Markdown（处理 SPA + 微信反爬）
python scripts/url_to_markdown.py "https://example.com/article" -o page.md

# File → Markdown
markitdown document.pdf -o document.md

# Estimate the token saving of converting a PDF
# 估算转换某 PDF 能省下的 token
python scripts/token_saver.py document.pdf --pages 40
```

---

## 作为 Agent 技能使用 / Using it as an agent skill

Drop this folder into your agent's skill directory (e.g. `~/.workbuddy/skills/markitdown-skill/`
for WorkBuddy, or your platform's equivalent). The agent will then proactively convert
files and links to Markdown before analysing them, and will route every web link through
`url_to_markdown.py` rather than hand-rolled `curl` + regex parsing.

把本目录放进 Agent 的技能目录（例如 WorkBuddy 的 `~/.workbuddy/skills/markitdown-skill/` 或各平台的等价路径）。此后 Agent 会在分析前主动把文件与链接转成 Markdown，并把每个网页链接都经由 `url_to_markdown.py` 处理，而非手搓 `curl` + 正则解析。

---

## 为什么选这个技能（而不是又一个 markitdown 封装）/ Why this skill (and not just another markitdown wrapper)

There are several `markitdown` skill wrappers on the marketplaces. This one is built
around **defence-in-depth and honesty**, not just convenience:

- **SSRF guard on by default** — refuses loopback / private / link-local / cloud-metadata
  targets and credential-embedded URLs; re-checks every redirect hop.
- **Resource caps** — 32 MiB raw / 64 MiB decompressed limits and a 10-hop redirect cap
  defeat decompression bombs and runaway fetches (see [SECURITY.md](references/SECURITY.md)).
- **Prompt-injection boundary** — converted text is treated as untrusted data; `--sanitize`
  strips script/style and wraps payloads in `EXTERNAL CONTENT` markers.
- **Sandbox-first headless rendering** — Chromium sandbox stays on unless root / restricted
  container forces a safe fallback (never silent).
- **Local token estimator** — `token_saver.py` reports an *honest* saving % only when a real
  baseline exists; it never fabricates a number.
- **Audited** — SkillHub 云鼎 (Yunding) security report: **100/100, 可信, 0 发现**; ClawHub
  moderation: **CLEAN**.

It still wraps Microsoft's MarkItDown 1:1 — the guards are additive, they don't replace the
engine.

市面上已有多个 `markitdown` 技能封装。本技能围绕**纵深防御与诚实**构建，而非仅图方便：

- **SSRF 守卫默认开启**——拒绝 loopback / 私有 / 链路本地 / 云元数据目标及内嵌凭据的 URL；每一跳重定向都复检。
- **资源上限**——原始 32 MiB / 解压 64 MiB 上限，加 10 跳重定向上限，抵御解压炸弹与失控抓取（见 [SECURITY.md](references/SECURITY.md)）。
- **提示注入边界**——转换文本被视为不可信数据；`--sanitize` 剥离 script/style 并用 `EXTERNAL CONTENT` 标记包裹载荷。
- **sandbox-first 无头渲染**——Chromium 沙箱默认开启，仅当 root / 受限容器被迫安全回退（绝不静默）。
- **本地 token 估算器**——`token_saver.py` 仅在有真实基线时才报告*诚实*的节省百分比；绝不编造数字。
- **经审计**——SkillHub 云鼎（Yunding）安全报告：**100/100、可信、0 发现**；ClawHub 审核：**CLEAN**。

它仍 1:1 封装微软 MarkItDown——守卫是叠加的，不替换引擎。

---

## 安装 / Install

| 平台 / Platform | 命令 / Command |
|---|---|
| ClawHub | `clawhub install @stwhwing/markitdown-skill` |
| SkillHub | `skillhub install markitdown-skill --namespace indiv-stwhwing` |
| GitHub | 下载 [Release](https://github.com/stwhwing/markitdown-skill/releases) 的 zip 解压到 agent 的 skills 目录；或 `git clone https://github.com/stwhwing/markitdown-skill.git` |

WorkBuddy 用户直接把目录放到 `~/.workbuddy/skills/markitdown-skill/` 即可（详见上方 "Using it as an agent skill" / 作为 Agent 技能使用）。

---

## 安全 / Security

- **SSRF guard (on by default).** `scripts/url_to_markdown.py` only fetches `http`/`https`
  URLs. By default it refuses targets that resolve to the loopback address, private address
  space, link-local, reserved, or carrier-grade NAT ranges, the cloud instance-metadata
  endpoint, or internal hostnames (`*.local`, `*.internal`, `*.corp`, `*.lan`, `*.home`,
  `*.intranet`). It also refuses URLs that embed credentials (`user:pass@host`). Every redirect
  hop is re-checked by the guard, and redirect chains longer than 10 hops are refused.
  · **SSRF 守卫（默认开启）**：仅抓取 `http`/`https` URL；默认拒绝解析到 loopback、私有地址空间、链路本地、保留段、运营商级 NAT、云元数据端点或内网主机名（`*.local`/`*.internal`/`*.corp`/`*.lan`/`*.home`/`*.intranet`）的目标，也拒绝内嵌凭据的 URL（`user:pass@host`）；每一跳重定向都复检，超过 10 跳的链拒绝。
- **Resource-exhaustion limits.** Raw responses larger than 32 MiB are rejected before being
  buffered; gzip/deflate/br bodies are decoded with a streaming, bounded reader that aborts past
  64 MiB of decompressed data (defeats decompression bombs).
  · **资源耗尽上限**：大于 32 MiB 的原始响应在缓冲前即被拒绝；gzip/deflate/br 正文用流式有界读取器解码，解压数据超过 64 MiB 即中止（抵御解压炸弹）。
- **Prompt-injection boundary.** Converted text is treated as untrusted data, not instructions.
  `url_to_markdown.py --sanitize` strips `<script>`/`<style>` blocks, neutralises
  `javascript:`/`data:` URIs, and wraps the payload between `--- EXTERNAL CONTENT ---` markers.
  `--manifest` records a sha256 + heuristic quality score per conversion for provenance.
  · **提示注入边界**：转换文本被视为不可信数据而非指令。`--sanitize` 剥离 `<script>`/`<style>`、中和 `javascript:`/`data:` URI，并用 `--- EXTERNAL CONTENT ---` 标记包裹载荷；`--manifest` 为每次转换记录 sha256 + 启发式质量分以便溯源。
- **Sandbox-first headless rendering.** The SPA fallback launches the browser with
  Chromium's sandbox enabled by default; `--no-sandbox` is only used automatically
  when running as root (where Chromium's sandbox cannot start) or when the sandboxed
  launch crashes in restricted containers. The fallback is never silent — a notice is
  printed to stderr — and there is no user-facing flag that turns the sandbox off.
  · **sandbox-first 无头渲染**：SPA 回退默认带 Chromium 沙箱启动；`--no-sandbox` 仅在 root（沙箱无法启动）或受限容器崩溃时自动回退，且从不静默——会向 stderr 打印提示，也没有任何用户可关沙箱的标志。
- **`MARKITDOWN_BIN` is validated before use.** If that environment variable is set, it
  is honoured only when it is an absolute path to a regular, executable file that is not
  writable by group or other users; otherwise it is ignored and the trusted
  `python -m markitdown` module path is used. This closes the "redirect execution via a
  writable env var" hole.
  · **`MARKITDOWN_BIN` 使用前先校验**：仅当其是常规、可执行、且非组/其他用户可写的文件的绝对路径时才采纳；否则忽略，改用受信任的 `python -m markitdown` 模块路径。堵上「通过可写环境变量重定向执行」的漏洞。
- **`--allow-internal` is an explicit, off-by-default opt-in.** It exists solely for trusted
  local development against loopback/intranet pages, must be passed deliberately on the
  command line, and should never be used on shared, production, or sensitive hosts.
  · **`--allow-internal` 是显式、默认关闭的 opt-in**：仅用于针对 loopback/内网的受信任本地开发，必须命令行显式传入，绝不可用于共享/生产/敏感主机。
- **Network boundary, stated honestly.** Direct fetches are pinned to the validated IP
  (DNS-rebinding defence) and every redirect hop is re-checked; the browser fallback maps the
  target host to that same IP. Pinning is skipped when an HTTP proxy performs the connection,
  and sub-resource hosts inside a rendered page are not network-filtered (accepted limitation).
  · **网络边界，如实声明**：直连抓取绑定到已校验 IP（防 DNS 重绑定），每跳复检；浏览器回退把目标主机映射到同一 IP。使用 HTTP 代理时代理会完成连接，pinning 被跳过；渲染页内的子资源主机不做网络过滤（已接受的局限）。
- **Optional external capabilities are off by default.** The skill can optionally use
  OpenAI image descriptions, Azure Document Intelligence, or third-party plugins, but these
  are disabled unless you explicitly enable them and they require your consent. Never feed
  private documents to an external service; local `markitdown` conversion does not phone
  home.
  · **可选外部能力默认关闭**：可选择性使用 OpenAI 图像描述、Azure 文档智能或三方插件，但除非你显式开启并授权否则不启用。切勿把私有文档喂给外部服务；本地 `markitdown` 转换不会外联。

The full threat model is in [references/SECURITY.md](references/SECURITY.md). · 完整威胁模型见 [references/SECURITY.md](references/SECURITY.md)。

---

## 更新日志 / Changelog

完整的中英双语更新日志见 GitHub Releases（每个版本均含中文与英文说明）。 · The full bilingual (zh + en) changelog lives in the GitHub [Releases](https://github.com/stwhwing/markitdown-skill/releases) — every version carries both Chinese and English notes.

---

## 反馈 / Feedback

问题、建议与 bug 反馈请走这两个入口： · Questions, suggestions and bug reports:

- **GitHub Issues**：<https://github.com/stwhwing/markitdown-skill/issues>
- **技能页 / Skill pages**：skillhub.cn / ClawHub 上的 MarkItDown 技能页（评论与评分 / comments & ratings）

文档与代码同源于本仓库；技能的三平台发布版本（GitHub / skillhub.cn / ClawHub）保持一致。 · Docs and code share this repo; the three-platform releases (GitHub / skillhub.cn / ClawHub) stay in sync.

---

## 许可 / License

MIT — see [LICENSE](LICENSE). This skill wraps Microsoft's MarkItDown (also MIT); the
wrappers and documentation here are released independently under MIT. · 本技能封装微软 MarkItDown（同为 MIT）；此处的封装与文档以 MIT 独立发布。
