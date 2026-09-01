# Token 审计方法论（Token-Saving 可选组件）

本文档是 markitdown-skill **可选** Token-Saving 工作流的方法论配套。它与 `token_saver.py`
（某次转换的成本/节省估算）互补：`measure_tokens.py` 提供**任意文本/文件**的 token 量级量测与对比，
本文档讲「何时测、怎么比、如何缩量、以及诚实口径」。

> 本组件为 **可选 / OPTIONAL**：技能核心（文档/网页 → Markdown）不依赖它；不调用就完全无感，
> 也**不会向任何服务器上报**（上报属于私有版能力，公开版不涉及）。

## 一、审计流程（标准）

1. **定对象**：明确要比的是什么——同一份材料在「路径 A」与「路径 B」下进入上下文的文本。
2. **测基线**：用 `measure_tokens.py` 对每条路径的文本分别测 token 量级（chars/4 启发式，CJK 有偏差，属量级）。
3. **对靶实测**：确保两条路径测的是**同一断言**（同一份源、同一任务），不是随便找个支持性证据。
4. **算 delta**：`measure_tokens.py --compare A B` 给出差值与百分比；端到端可再用平台/网关实际用量明细交叉验证。
5. **标 [A]/[C]**：实测/亲跑 = `[A] 实证`；文档/印象 = `[C] 待核查`。确定性结论只用 `[A]`。

## 二、缩量技术（按收益排序）

| 技术 | 做法 | 典型收益 |
|------|------|----------|
| 转换优先 | PDF/PPT/DOCX/网页 → 纯文本 Markdown（`markitdown` / `url_to_markdown.py`） | 比喂原始文件省 80%+（剥离 layout/字体/样式噪声） |
| Grep 优先 / 按需读 | 拿 Markdown 后先 Grep 章节/关键词，只 Read 命中段，不整篇读 | 大文件/长网页尤其明显 |
| 递归平铺抽取 | SPA 兜底抽 `__NEXT_DATA__` 等内嵌 JSON 时只留正文类字段 | 实测 30,693→281 字符（≈99%） |
| 别整篇 Read | 仅「全文总结」类任务才整篇读 | 避免一次性灌入几千行 |

## 三、完整案例：WebFetch vs markitdown-skill（实测推翻误判）

**误判（已纠正）**：曾认为「WebFetch 只回精炼答案、不把整页塞进上下文」。

**对靶实测**（同一页面 `skillhub.cn/skills/user_b364a4e5/markitdown-skill`）：
- WebFetch 实际回传内容 → `measure_tokens.py` 量得 **297 token**（该公开渲染页本身小）。
- `url_to_markdown.py` 输出 19,256 字节 → **4,025 token**（若 Read 全量即进入上下文的量）。
- 结论：本次 WebFetch ≈ 技能的 1/13.5。

**根因**（非正式「WebFetch 更聪明」）：
- (a) 该公开渲染页本身小；
- (b) `url_to_markdown.py` 的 SPA 回退把整段 `__NEXT_DATA__` 内嵌 JSON（19KB）原样塞进 Markdown。
  差距来自「技能捞了整包 Next.js 数据」，非 WebFetch 更优。

**修复**：`url_to_markdown.py` 的 JSON 回退改用 `json_to_markdown`（递归平铺抽取），只保留正文类字段。
实测同一构造样本 30,693 字符 → 281 字符，≈99% 缩量；boilerplate 全丢、prose 全留。

**通用结论（不可一概而论）**：token 优劣取决于页面结构与消费方式——
技能侧若只 Grep 版本而不整篇 Read，也能压很小；重内容页面（如大 SKILL.md）两边会接近。
所有数字用 chars/4 启发性估算（CJK 有偏差），属量级估计，不当作账单。

## 四、诚实口径（铁律）

- 没有真实基线时，二进制源一律 `saved_tokens=0`、`basis="none"`，只报 Markdown 实际成本，绝不编造。
- 脚本判定 ≠ 真相：自写脚本 FAIL/异常，先读原始证据（文件/日志）再报。
- 删除/变更前三问：前提断言实测过吗？副作用范围追踪完整吗？用独立查询核验生效了吗？

## 五、相关脚本

- `scripts/token_saver.py`：转换某文件的 Markdown 实际成本 / 节省估算（见 [TOKEN-SAVER.md](TOKEN-SAVER.md)）。
- `scripts/measure_tokens.py`：任意文本/文件的 token 量级量测与 `--compare` 对比。
- `scripts/url_to_markdown.py`：网页 → Markdown（含递归平铺抽取的 JSON 回退）。
