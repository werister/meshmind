#!/usr/bin/env python3
"""STUB worker that fails: nonzero exit with a JSON error on stdout (worker-down)."""
import json
import sys

json.dump({"error": "stub: model weights not found"}, sys.stdout)
sys.exit(1)
