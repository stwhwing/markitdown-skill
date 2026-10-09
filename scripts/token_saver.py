#!/usr/bin/env python3
"""
Token-Saving helper for the MarkItDown skill.

Converts a document to Markdown via markitdown and reports the token cost the AI actually
pays for the cleaned Markdown. It can ALSO estimate a saving %, but ONLY when a real raw
baseline is available (and the converted Markdown must contain real text — an output
shorter than content_detect's TEXT_THRESHOLD means the extraction failed, and no saving
is claimed):

  - text-like files (.txt/.md/.csv/.json/...)  -> baseline = source text / 4 (meaningful)
  - PDF / images                               -> pass --pages N  (baseline = N * 1500, estimate)
  - any format                                 -> pass --raw-estimate N (an explicit baseline)

For compressed binary formats (.pdf/.docx/.pptx/.xlsx/...) WITHOUT a baseline, the script
does NOT fabricate a saving — it just reports the Markdown token cost, because the AI
cannot ingest the raw binary anyway (Markdown is the only practical input).

All token counts use a chars/4 heuristic and are APPROXIMATE (order-of-magnitude), not bills.

Reporting to 自部署的接收端 (POST /api/savings):
  --report     best-effort auto push (spool-then-flush, agent auto-detected). Never fails
               the conversion. Safe even when the dashboard tunnel is down (data is spooled
               and flushed later, e.g. when the WorkBuddy dashboard script opens).
  --emit-json  print one JSON line (no human text) for manual piping to the dashboard POST.
  --agent      override the agent tag (openclaw / hermes / workbuddy). Optional; omitted =>
               auto-detected from this script's path.

Usage:
  python token_saver.py INPUT [-o OUTPUT.md] [--pages N] [--raw-estimate N] [--report]
"""
import sys
import os
import json
import argparse
from pathlib import Path

# Rough tokens per dense page for PDF/image estimation (heuristic only).
PAGE_TOKENS = 1500


def estimate_tokens(text: str) -> int:
    """Rough heuristic: ~4 chars per token (English-ish)."""
    return max(1, len(text) // 4)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert a document to Markdown and report token cost / saving."
    )
    ap.add_argument("input", help="File to convert")
    ap.add_argument("-o", "--output", help="Write the Markdown to this file")
    ap.add_argument(
        "--raw-estimate",
        type=int,
        help="Explicit raw-token baseline (e.g. a known billing count). Enables a "
        "saving %% even for binary sources.",
    )
    ap.add_argument(
        "--pages",
        type=int,
        help="For PDF/images: estimate raw baseline as pages * %d tokens." % PAGE_TOKENS,
    )
    ap.add_argument(
        "--agent",
        default=None,
        help="Agent tag for the savings dashboard (openclaw / hermes / workbuddy). "
        "Optional; auto-detected from this script's path when omitted.",
    )
    ap.add_argument(
        "--emit-json",
        action="store_true",
        help="Emit one JSON line (no human text) for piping to the savings dashboard POST.",
    )
    ap.add_argument(
        "--report",
        action="store_true",
        help="Also push the token-cost/saving record to 自部署的接收端 (best effort; "
        "never fails the conversion). Spool-then-flush so it survives a missing tunnel.",
    )
    args = ap.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        return 1

    # --- Convert via markitdown ---
    try:
        from markitdown import MarkItDown
    except ImportError:
        print(
            "Error: markitdown not installed. Install with: "
            "pip install 'markitdown[all]'",
            file=sys.stderr,
        )
        return 1

    md = MarkItDown()
    try:
        result = md.convert(str(input_path))
    except Exception as e:  # noqa: BLE001
        print(f"Conversion failed: {e}", file=sys.stderr)
        return 1

    markdown = result.text_content or ""
    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
        print(f"Markdown saved: {args.output}")

    md_tokens = estimate_tokens(markdown)
    ext = input_path.suffix.lower()
    text_like = ext in (
        ".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm",
        ".py", ".js", ".ts", ".java", ".c", ".cpp", ".go", ".rs",
        ".yaml", ".yml", ".toml", ".log",
    )

    # --- Resolve a raw baseline (only when honest) ---
    raw_tokens = None
    basis = ""
    if args.raw_estimate:
        raw_tokens = max(1, int(args.raw_estimate))
        basis = "explicit --raw-estimate"
    elif text_like:
        raw_text = input_path.read_text(encoding="utf-8", errors="ignore")
        raw_tokens = estimate_tokens(raw_text)
        basis = "source text (chars/4)"
    elif args.pages:
        raw_tokens = max(1, args.pages * PAGE_TOKENS)
        basis = f"--pages {args.pages} * {PAGE_TOKENS} (estimate)"

    # --- Compute saving (honest; only when a real baseline exists) ---
    saved_tokens = max(0, (raw_tokens - md_tokens)) if raw_tokens else 0
    saved_pct = (
        max(0.0, (raw_tokens - md_tokens)) / raw_tokens * 100
    ) if raw_tokens else 0.0

    # --- 诚实口径「门二」：产出过短 => 视为抓取失败，不宣称节省 ---
    # 阈值与 report_savings 同源（复用 content_detect.TEXT_THRESHOLD），避免两处口径漂移。
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import report_savings as _rs
        _min_tok = _rs.MIN_REAL_CONTENT_TOKENS
    except Exception:  # noqa: BLE001 - 极端情况下按下限兜底
        _min_tok = 30
    content_ok = md_tokens >= _min_tok
    suspect = bool(raw_tokens) and not content_ok
    if suspect:
        saved_tokens, saved_pct = 0, 0.0

    # --- Machine-readable output (for the savings dashboard) ---
    if args.emit_json:
        rec = {
            "agent": args.agent or "unknown",
            "source_file": input_path.name,
            "source_type": (ext or "unknown").lstrip("."),
            "raw_tokens": int(raw_tokens or 0),
            "md_tokens": int(md_tokens),
            "saved_tokens": int(saved_tokens),
            "saved_pct": round(saved_pct, 1),
            "basis": basis or "none",
        }
        if suspect:
            rec["quality"] = "suspect"
        print(json.dumps(rec, ensure_ascii=False))
        return 0

    # --- Human-readable report ---
    print("--- Token cost (approximate) ---")
    print(f"Source           : {input_path.name} ({ext or 'unknown'})")
    print(f"Markdown tokens  : {md_tokens:,}   (actual AI cost)")
    if raw_tokens and suspect:
        print(f"Raw baseline     : {raw_tokens:,}   ({basis})")
        print("Estimated saving : n/a — output too short to be real content")
        print(f"  ({md_tokens} md tokens < {_min_tok}; the extraction likely failed,")
        print("   e.g. an anti-bot / empty-shell page, so no saving is claimed.)")
    elif raw_tokens:
        print(f"Raw baseline     : {raw_tokens:,}   ({basis})")
        print(f"Estimated saving : {saved_pct:.1f}%")
    else:
        print("Raw baseline     : not computed")
        print("  The source is binary/compressed; the AI cannot ingest the raw file,")
        print("  it is fed the Markdown above. For a saving estimate, re-run with")
        print("  --pages N (PDF/images) or --raw-estimate N.")
    print("Note: heuristic chars/4; CJK text differs. Numbers are order-of-magnitude.")

    # --- Optional: push to 自部署的接收端 (best effort) ---
    if args.report:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import report_savings
            report_savings.report(
                source_file=str(input_path),
                source_type=ext or "file",
                raw_tokens=raw_tokens or 0,
                md_tokens=md_tokens,
                basis=basis or "none",
                agent=args.agent,
            )
            print("[token_saver] 已（尝试）上报节省量至 自部署的接收端")
        except Exception as e:  # noqa: BLE001
            print(f"[token_saver] 上报被跳过（不影响转换结果）: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
