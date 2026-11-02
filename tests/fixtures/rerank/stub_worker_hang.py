#!/usr/bin/env python3
"""STUB worker that sleeps past the endpoint timeout, to exercise the 60s guard.

The test invokes it with a short injected timeout so the suite stays fast.
"""
import sys
import time

time.sleep(30)
sys.stdout.write('{"scores": []}')
sys.exit(0)
