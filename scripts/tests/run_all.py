#!/usr/bin/env python3
"""Discover and run every test_*.py module in this directory (no pytest needed).

Usage:
    python scripts/tests/run_all.py
Exits non-zero if any test module fails.
"""
import glob
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(mod_path):
    name = os.path.splitext(os.path.basename(mod_path))[0]
    spec = importlib.util.spec_from_file_location(name, mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    modules = sorted(glob.glob(os.path.join(_HERE, "test_*.py")))
    failed = 0
    for mod_path in modules:
        print("=== %s ===" % os.path.basename(mod_path))
        try:
            mod = _load(mod_path)
            if hasattr(mod, "main"):
                failed += (mod.main() or 0)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %s" % (os.path.basename(mod_path), exc))
    print("\n%d module(s) run; %d failed" % (len(modules), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
