#!/usr/bin/env python3
"""STUB worker that exits 0 but prints non-JSON garbage to stdout (bad-JSON path)."""
import sys

sys.stdout.write("this is not json at all <<<>>>\n")
sys.exit(0)
