#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_savings.py — Token 节省量「计算 + 落盘 + 上报」共用模块（markitdown-skill）

本模块随 skill 一起部署到三端（OpenClaw / Hermes / 本机 WorkBuddy），
把「原始内容 -> Markdown」这一步省下的 token 量上报到 自部署的接收端。

设计原则
--------
1. **诚实口径（两道门，缺一不可）**：
   - **门一 · 有真实基线**：`basis` 非空且 != 'none' 且 `raw_tokens > 0`。
     二进制（pdf/docx/pptx/xlsx…）拿不到原始文本基线时 `basis='none'`、
     `raw_tokens=0`、`saved_tokens=0`，**绝不编造节省**。
   - **门二 · 产出真的是内容**（2026-09-14 新增）：转出来的 Markdown 必须达到
     `content_detect.TEXT_THRESHOLD`（默认 120 个有效字符）才算"抓到了正文"。
     否则——例如只抓到微信反爬页 / SPA 空壳 / 仅页眉页脚（实测 md≈22 tok ≈88 字符）——
     **`saved_tokens` 与 `saved_pct` 一律记 0**（`quality='suspect'`），
     避免把"**抓取失败**"记成"省了几千 token"。
     ⚠️ 只加"有基线"这一道门是不够的：原始 HTML 抓到了（raw>0），
     但正文没抓到，仍然会虚增节省（2026-09-13 实测 5 条此类记录虚增 28,850）。
   这与接收端服务 的聚合口径（`aggregateSavings`：按 `basis`+`raw>0` 判定
   是否计入、并对 `saved_tokens` 取原值）保持一致——本模块把值算对，服务端照实累加。
2. **绝不阻断主流程**：任何异常一律静默吞掉。转换是否成功不受上报影响。
3. **先落盘，再上送**：事件先 append 到本地 spool 文件，再尝试 POST；
   上送失败就留在 spool 里等下次 flush —— 数据绝不丢。
   本机 WorkBuddy 没有常驻连接，正是靠这一点：转换时落 spool，
   等 `你自带的端口转发脚本` 建好连接后统一 flush。

接收端接口契约（POST /api/savings，权威）
------------------------------------------------
  - agent       必填，且只能是 workbuddy / openclaw / hermes（否则 403）
  - source_file 必填（否则 400）
  - 可选：source_type(<=32) / raw_tokens / md_tokens / saved_tokens /
          saved_pct / basis(默认 'none') / date（服务端兜底为当天）
  - 服务端补 ts

环境变量（可选覆盖）
--------------------
  SAVINGS_URL     上报地址（严格 opt-in）：未设置 = 完全禁用（默认零请求，含回环）；
                  显式设置为你的自部署接收端才启用；设为空 / off / none / disabled = 禁用
  SAVINGS_AGENT   强制指定 agent（openclaw / hermes / workbuddy）
  SAVINGS_SPOOL   强制指定 spool 文件路径

命令行用法
----------
  # 上报一条（也可被其它脚本 import 后调用 report()）
  python report_savings.py --emit-json --agent hermes --source-file page.html \
      --source-type html --raw-tokens 821028 --md-tokens 845 \
      --basis "html source (chars/4)"

  # 把 spool 里积压的事件全部上送（成功即从 spool 移除）
  python report_savings.py --flush

  # 只看不动
  python report_savings.py --stats
  python report_savings.py --dry-run --source-file a.html --raw-tokens 100 --md-tokens 20 --basis x
"""
import json
import os
import sys
import tempfile
import urllib.request

ALLOWED_AGENTS = ("workbuddy", "openclaw", "hermes")
# v1.8.9 起上报为严格 opt-in：历史默认地址已移除——未设置 SAVINGS_URL 即完全禁用，
# 零网络请求（含本机回环）；仅显式设置 SAVINGS_URL 指向自部署接收端才启用。
DEFAULT_TIMEOUT = 3  # 秒；接收端在本机时应秒回，不可达时 rapid-fail

TOKENS_PER_CHAR = 4  # 与 token_saver.py 一致的 chars/4 启发式

# 「门二 · 产出真的是内容」的阈值：优先复用 content_detect 的既有判据（同一包内），
# 取不到时退回同值常量。详见模块 docstring。
try:  # pragma: no cover - content_detect 正常随包分发
    from content_detect import TEXT_THRESHOLD as _MIN_REAL_CONTENT_CHARS
except Exception:  # noqa: BLE001
    _MIN_REAL_CONTENT_CHARS = 120

# 同一门槛的 token 表示（与 estimate_tokens 共用除数），供只拿得到 token 数的调用方使用
MIN_REAL_CONTENT_TOKENS = max(1, -(-_MIN_REAL_CONTENT_CHARS // TOKENS_PER_CHAR))


def estimate_tokens(text):
    """chars/4 启发式（与 token_saver.py 保持一致，避免三端口径打架）。"""
    if not text:
        return 0
    return max(0, len(text) // TOKENS_PER_CHAR)


def estimate_tokens_from_chars(n):
    """已知字符数时的换算，保证与 estimate_tokens 使用同一除数。"""
    return max(0, int(n or 0) // TOKENS_PER_CHAR)


# ---------------------------------------------------------------------------
# 环境识别
# ---------------------------------------------------------------------------
def detect_runtime():
    """按本文件所在路径推断 agent；可用 SAVINGS_AGENT 覆盖。"""
    env = os.environ.get("SAVINGS_AGENT", "").strip().lower()
    if env:
        return env
    p = os.path.abspath(__file__).replace("\\", "/").lower()
    if "/.openclaw/" in p:
        return "openclaw"
    if "/.hermes/" in p:
        return "hermes"
    if "/.workbuddy/" in p:
        return "workbuddy"
    return ""


def spool_path(agent=""):
    """spool 文件位置：优先 SAVINGS_SPOOL，否则按 agent 落到各自主目录。"""
    env = os.environ.get("SAVINGS_SPOOL", "").strip()
    if env:
        return env
    home = os.path.expanduser("~")
    mapping = {
        "openclaw": os.path.join(home, ".openclaw", "savings_spool.jsonl"),
        "hermes": os.path.join(home, ".hermes", "savings_spool.jsonl"),
        "workbuddy": os.path.join(home, ".workbuddy", "savings_spool.jsonl"),
    }
    if agent in mapping:
        return mapping[agent]
    return os.path.join(tempfile.gettempdir(), "savings_spool.jsonl")


# 上报为严格 opt-in：未设置 SAVINGS_URL 时完全禁用（默认零网络请求，含本机回环）；
# 显式设置正常 URL 才启用；空串 / off / none / disabled（大小写不敏感）一律关闭。
_DISABLE_KEYWORDS = ("off", "none", "disabled")
DISABLED = object()  # report() 在关闭时返回的哨兵，区别于 None（agent 非法）


def api_url():
    """解析上报地址（v1.8.9 起默认禁用：未设置 = 完全不上报）。

    返回:
      - None      : 未设置 SAVINGS_URL（默认，零请求含回环）或显式关闭
                    （空串 / off / none / disabled）→ 不 POST、不写 spool
      - 正常 URL  : 仅当显式设置 SAVINGS_URL（opt-in）时启用
    """
    raw = os.environ.get("SAVINGS_URL")
    if raw is None:
        return None
    v = raw.strip()
    if v == "" or v.lower() in _DISABLE_KEYWORDS:
        return None
    return v


# ---------------------------------------------------------------------------
# 落盘 / 上送
# ---------------------------------------------------------------------------
def _append_spool(rec, path):
    try:
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _post(rec, timeout=DEFAULT_TIMEOUT):
    url = api_url()
    if not url:
        return None
    data = json.dumps(rec).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def caller_info():
    """调用方归因信息（2026-09-14 加）。

    背景：2026-09-13 有 5 笔来源不明的上报（OpenClaw / Hermes 会话库均查不到），
    无法定位是"谁"触发的。带上 cwd / 父进程 / argv 之后，同类事件可直接归因。

    任何一项取不到都不影响上报（各自兜底为空/0）。
    """
    try:
        cwd = os.getcwd()
    except Exception:  # noqa: BLE001
        cwd = ""
    try:
        ppid = os.getppid()
    except Exception:  # noqa: BLE001
        ppid = 0
    try:
        argv = " ".join(sys.argv[:4])
    except Exception:  # noqa: BLE001
        argv = ""
    return {"caller_cwd": cwd, "caller_ppid": ppid, "caller_argv": argv}


def build_record(agent, source_file, source_type="", raw_tokens=0, md_tokens=0,
                 basis="none"):
    """按接收端契约构造记录，并套用诚实口径计算 saved_tokens。"""
    raw = int(raw_tokens or 0)
    md = int(md_tokens or 0)
    # 门一：有真实基线（否则无从谈节省）
    has_baseline = bool(basis) and basis != "none" and raw > 0
    # 门二：产出真的是内容。产出过短说明抓到的是反爬页/空壳，
    #        此时 raw 虽然存在，但"节省"名不副实 → 不计。
    content_ok = md >= MIN_REAL_CONTENT_TOKENS
    claim_valid = has_baseline and content_ok
    saved = max(0, raw - md) if claim_valid else 0
    pct = round(saved / raw * 100, 1) if (claim_valid and raw > 0) else 0.0
    rec = {
        "agent": agent,
        "source_file": str(source_file)[:256],
        "source_type": str(source_type or "")[:32],
        "raw_tokens": raw,
        "md_tokens": md,
        "saved_tokens": saved,
        "saved_pct": pct,
        "basis": basis or "none",
    }
    # 调用方归因：写入 spool 与 POST JSON。接收端 按字段白名单落库，
    # 会忽略这三个字段（不会 400），故无需改前端；本地 spool 里可直接看到来源。
    rec.update(caller_info())
    if has_baseline and not content_ok:
        # 仅本地可见的标记：接收端 按字段白名单落库，会忽略该字段，
        # 不影响接口契约；但本机 spool 里能直接看出"这条是抓取失败"。
        rec["quality"] = "suspect"
    return rec


def enqueue(rec, agent=""):
    """只落盘，不入网。返回 spool 路径；关闭状态下返回 None（不写 spool）。"""
    if api_url() is None:
        return None
    path = spool_path(agent or rec.get("agent", ""))
    _append_spool(rec, path)
    return path


def flush(timeout=DEFAULT_TIMEOUT, verbose=False):
    """把 spool 中积压事件全部上送；成功的移除，失败的原样留下。

    返回 (ok, remain)。网络不可达时第一条就失败并立即停止，避免超时叠加。
    关闭状态下直接返回 (0, 0)，不 POST。
    """
    if api_url() is None:
        if verbose:
            print("[savings] reporting disabled (SAVINGS_URL=%s)"
                  % repr(os.environ.get("SAVINGS_URL")), file=sys.stderr)
        return 0, 0
    agent = detect_runtime()
    path = spool_path(agent)
    if not os.path.exists(path):
        return 0, 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = [l.strip() for l in fh if l.strip()]
    except Exception:
        return 0, 0
    if not lines:
        return 0, 0

    remain = []
    ok = 0
    for idx, ln in enumerate(lines):
        try:
            rec = json.loads(ln)
        except Exception:
            continue  # 坏行直接丢弃，不阻塞后续
        try:
            _post(rec, timeout)
            ok += 1
        except Exception:
            # 第一条失败 => 后续大概率也失败，整体保留，等下次 flush
            remain.extend(lines[idx:])
            break

    try:
        if remain:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write("\n".join(remain) + "\n")
            os.replace(tmp, path)
        else:
            os.remove(path)
    except Exception:
        pass

    if verbose:
        print("[savings] flush: ok=%d remain=%d (%s)" % (ok, len(remain), path))
    return ok, len(remain)


def report(source_file, source_type="", raw_tokens=0, md_tokens=0, basis="none",
           agent=None, do_post=True, verbose=False):
    """主入口：落盘 +（可选）立即上送。任何异常都被吞掉，绝不抛给调用方。"""
    try:
        if api_url() is None:
            print("reporting disabled (SAVINGS_URL=%s)"
                  % repr(os.environ.get("SAVINGS_URL")), file=sys.stderr)
            return DISABLED
        ag = (agent or detect_runtime() or "").strip().lower()
        if ag not in ALLOWED_AGENTS:
            if verbose:
                print("[savings] 跳过：agent 非法或未识别 -> %r" % ag, file=sys.stderr)
            return None
        if not source_file:
            return None
        rec = build_record(ag, source_file, source_type, raw_tokens, md_tokens, basis)
        enqueue(rec, ag)
        if do_post:
            flush(verbose=verbose)
        return rec
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="Token 节省量上报（markitdown-skill）")
    ap.add_argument("--source-file")
    ap.add_argument("--source-type", default="")
    ap.add_argument("--raw-tokens", type=int, default=0)
    ap.add_argument("--md-tokens", type=int, default=0)
    ap.add_argument("--basis", default="none")
    ap.add_argument("--agent", default=None)
    ap.add_argument("--flush", action="store_true", help="上送 spool 中积压的事件")
    ap.add_argument("--stats", action="store_true", help="查看 spool 现状，不做任何改动")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要上报的记录")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.flush:
        ok, remain = flush(verbose=True)
        return 0 if remain == 0 else 1

    if args.stats:
        ag = detect_runtime()
        path = spool_path(ag)
        print("agent     :", ag or "(未识别)")
        print("api url   :", api_url() or "(disabled)")
        print("spool path:", path)
        if os.path.exists(path):
            lines = [l for l in open(path, encoding="utf-8", errors="ignore") if l.strip()]
            print("待上送事件: %d" % len(lines))
            tot = sum(json.loads(l).get("saved_tokens", 0) for l in lines if l.strip())
            print("待上送节省: %d tokens" % tot)
            for l in lines[-10:]:
                print("   ", l.strip()[:160])
        else:
            print("待上送事件: 0（spool 不存在）")
        return 0

    if not args.source_file:
        ap.error("需要 --source-file，或用 --flush / --stats")

    rec = build_record(args.agent or detect_runtime(), args.source_file,
                       args.source_type, args.raw_tokens, args.md_tokens, args.basis)
    if args.dry_run:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0
    got = report(args.source_file, args.source_type, args.raw_tokens,
                 args.md_tokens, args.basis, agent=args.agent, verbose=True)
    if got is DISABLED:
        return 0
    if got is None:
        print("[savings] 未上报（agent 非法/未识别）", file=sys.stderr)
        return 1
    print("[savings] 已记录:", json.dumps(got, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
