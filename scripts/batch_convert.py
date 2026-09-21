#!/usr/bin/env python3
"""
Batch convert multiple files to markdown using MarkItDown
"""

import sys
import os
import argparse
import datetime
import hashlib
import json
import tempfile
from pathlib import Path
from markitdown import MarkItDown


def _atomic_write(path, text):
    """Write `text` to `path` atomically (temp file + os.replace).

    A crash mid-write leaves no half-written file behind. os.replace is atomic
    on both POSIX and Windows.
    """
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _meaningful_len(text):
    """Count non-whitespace characters (cheap proxy for content volume)."""
    return sum(1 for ch in (text or "") if not ch.isspace())


def _write_manifest(path, record):
    """Append one conversion record (JSON line) to the manifest at `path`."""
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        print("[manifest] could not write %s: %s" % (path, e), file=sys.stderr)


def convert_file(md_converter, input_path, output_dir=None, verbose=False,
                 manifest_path=None):
    """Convert a single file to markdown (atomically) and log a manifest record."""
    input_path = Path(input_path)
    _now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        if manifest_path:
            _write_manifest(manifest_path, {
                "source": str(input_path), "output": None,
                "converted_at": _now, "success": False,
                "md_bytes": 0, "md_sha256": None, "meaningful_chars": 0,
            })
        return False

    # Determine output path
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{input_path.stem}.md"
    else:
        output_path = input_path.with_suffix(".md")

    try:
        if verbose:
            print(f"Converting: {input_path}")

        result = md_converter.convert(str(input_path))
        text = result.text_content or ""

        # Atomic write (P1-G): no half-written .md left behind on a crash.
        _atomic_write(str(output_path), text)

        if manifest_path:
            _write_manifest(manifest_path, {
                "source": str(input_path),
                "output": str(output_path),
                "converted_at": _now,
                "success": True,
                "md_bytes": len(text.encode("utf-8", "ignore")),
                "md_sha256": hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest(),
                "meaningful_chars": _meaningful_len(text),
            })

        if verbose:
            print(f"Saved to: {output_path}")

        return True

    except Exception as e:
        print(f"Error converting {input_path}: {e}", file=sys.stderr)
        if manifest_path:
            _write_manifest(manifest_path, {
                "source": str(input_path), "output": None,
                "converted_at": _now, "success": False,
                "md_bytes": 0, "md_sha256": None, "meaningful_chars": 0,
            })
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Batch convert files to markdown using MarkItDown"
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Files to convert (supports glob patterns)"
    )
    parser.add_argument(
        "-o", "--output-dir",
        help="Output directory (default: same as input file)"
    )
    parser.add_argument(
        "-p", "--plugins",
        action="store_true",
        help="Enable plugins"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--llm-model",
        help="LLM model for image descriptions (e.g., gpt-4o)"
    )
    parser.add_argument(
        "--docintel-endpoint",
        help="Azure Document Intelligence endpoint"
    )
    parser.add_argument(
        "--manifest",
        help="Append a JSON-lines provenance record per converted file to this file"
    )

    args = parser.parse_args()

    # Initialize MarkItDown
    md_kwargs = {"enable_plugins": args.plugins}

    if args.llm_model:
        print(
            "[consent notice] --llm-model is enabled: document content and "
            "embedded images WILL BE SENT to the configured OpenAI-compatible "
            "endpoint for image descriptions. Do not use it on private or "
            "sensitive documents unless you explicitly accept this data flow. "
            "(This feature is off by default; see SKILL.md '隐私与数据流向' / "
            "'Security' for the full data-handling policy.)",
            file=sys.stderr,
        )
        try:
            from openai import OpenAI
            client = OpenAI()
            md_kwargs["llm_client"] = client
            md_kwargs["llm_model"] = args.llm_model
        except ImportError:
            print("Error: openai package required for LLM features", file=sys.stderr)
            print("Install with: pip install openai", file=sys.stderr)
            sys.exit(1)

    if args.docintel_endpoint:
        md_kwargs["docintel_endpoint"] = args.docintel_endpoint

    md = MarkItDown(**md_kwargs)

    # Process files
    success_count = 0
    total_count = 0

    for file_pattern in args.files:
        # Handle glob patterns
        if "*" in file_pattern or "?" in file_pattern:
            files = list(Path(".").glob(file_pattern))
        else:
            files = [Path(file_pattern)]

        for file_path in files:
            total_count += 1
            if convert_file(md, file_path, args.output_dir, args.verbose,
                            args.manifest):
                success_count += 1

    # Summary
    if args.verbose or total_count > 1:
        print(f"\nConverted {success_count}/{total_count} files")

    sys.exit(0 if success_count == total_count else 1)


if __name__ == "__main__":
    main()
