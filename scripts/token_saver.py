#!/usr/bin/env python3
"""
Token-cost estimator for the MarkItDown skill.

Converts a document to Markdown via markitdown and reports the approximate token cost
the AI actually pays for the cleaned Markdown. It can ALSO estimate a saving %, but ONLY
when a real raw baseline is available:

  - text-like files (.txt/.md/.csv/.json/...)  -> baseline = source text / 4 (meaningful)
  - PDF / images                               -> pass --pages N  (baseline = N * 1500, estimate)
  - any format                                 -> pass --raw-estimate N (an explicit baseline)

For compressed binary formats (.pdf/.docx/.pptx/.xlsx/...) WITHOUT a baseline, the script
does NOT fabricate a saving — it just reports the Markdown token cost, because the AI
cannot ingest the raw binary anyway (Markdown is the only practical input).

A baseline alone is still not enough: the converted Markdown must also contain real text.
If the output is shorter than content_detect's TEXT_THRESHOLD (a failed / anti-bot /
empty-shell extraction), the script reports no saving instead of a fictitious one.

All token counts use a chars/4 heuristic and are APPROXIMATE (order-of-magnitude), not bills.

Usage:
  python token_saver.py INPUT [-o OUTPUT.md] [--pages N] [--raw-estimate N]
"""
import sys
import json
import argparse
from pathlib import Path

# Rough tokens per dense page for PDF/image estimation (heuristic only).
PAGE_TOKENS = 1500

# "Did we actually get content?" threshold, reused from content_detect (shipped in the
# same package) so the two never drift; fallback is the same value. Output shorter than
# this means the conversion produced no real text (anti-bot / empty-shell page), and a
# "saving" would be fiction — see the docstring note on honest accounting.
try:  # pragma: no cover - content_detect ships with this package
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from content_detect import TEXT_THRESHOLD as _MIN_REAL_CHARS
except Exception:  # noqa: BLE001
    _MIN_REAL_CHARS = 120

MIN_REAL_CONTENT_TOKENS = max(1, -(-_MIN_REAL_CHARS // 4))


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

    # --- Compute saving (honest; needs a real baseline AND real output) ---
    # A baseline alone is not enough: if the Markdown is too short to be content, the
    # extraction failed and no saving may be claimed (raw HTML may still be large).
    content_ok = md_tokens >= MIN_REAL_CONTENT_TOKENS
    saved_tokens = max(0, (raw_tokens - md_tokens)) if (raw_tokens and content_ok) else 0
    saved_pct = (
        max(0.0, (raw_tokens - md_tokens)) / raw_tokens * 100
    ) if (raw_tokens and content_ok) else 0.0

    # --- Human-readable report ---
    print("--- Token cost (approximate) ---")
    print(f"Source           : {input_path.name} ({ext or 'unknown'})")
    print(f"Markdown tokens  : {md_tokens:,}   (actual AI cost)")
    if raw_tokens and not content_ok:
        print(f"Raw baseline     : {raw_tokens:,}   ({basis})")
        print("Estimated saving : n/a — output too short to be real content")
        print(f"  ({md_tokens} md tokens < {MIN_REAL_CONTENT_TOKENS}; the extraction likely")
        print("   failed, e.g. an anti-bot / empty-shell page, so no saving is claimed.)")
    elif raw_tokens:
        print(f"Raw baseline     : {raw_tokens:,}   ({basis})")
        print(f"Estimated saving : {saved_pct:.1f}%")
    else:
        print("Raw baseline     : not computed")
        print("  The source is binary/compressed; the AI cannot ingest the raw file,")
        print("  it is fed the Markdown above. For a saving estimate, re-run with")
        print("  --pages N (PDF/images) or --raw-estimate N.")
    print("Note: heuristic chars/4; CJK text differs. Numbers are order-of-magnitude.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
