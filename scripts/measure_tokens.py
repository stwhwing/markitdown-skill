#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_tokens.py — Token 成本量级估算器（token-audit skill）

用 chars/4 启发式估算一段文本/文件进入上下文的 token 量（order-of-magnitude，非账单）。
支持：
  - 测单个/多个文件
  - 从 stdin 测
  - --compare A B：对比两条路径，输出 delta 与百分比

注意：CJK 文本通常 ~1.5-2 字符/token，启发式会偏低估；数字仅作量级参考。
"""
import sys
import os
import argparse


def estimate(text: str) -> int:
    """chars/4 启发式（与 markitdown-skill 的 token_saver 口径一致）。"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Estimate token cost (chars/4 heuristic) of files or stdin."
    )
    ap.add_argument("paths", nargs="*", help="Files to measure ('-' = stdin)")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"),
                    help="Compare two files: print delta and %% (A-B).")
    args = ap.parse_args()

    if args.compare:
        a, b = args.compare
        ta = estimate(_read(a))
        tb = estimate(_read(b))
        d = ta - tb
        pct = (d / ta * 100) if ta else 0.0
        smaller = "B" if d > 0 else "A"
        print(f"A ({os.path.basename(a)}): {ta:,} tokens")
        print(f"B ({os.path.basename(b)}): {tb:,} tokens")
        print(f"Delta (A-B): {d:+,} tokens  ({pct:+.1f}%)  -> {smaller} is smaller")
        return 0

    if not args.paths:
        ap.print_help()
        return 1

    total = 0
    for p in args.paths:
        if p == "-":
            t = estimate(sys.stdin.read())
            label = "(stdin)"
        else:
            t = estimate(_read(p))
            label = p
        print(f"{label}: {t:,} tokens")
        total += t

    if len(args.paths) > 1:
        print(f"TOTAL: {total:,} tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
