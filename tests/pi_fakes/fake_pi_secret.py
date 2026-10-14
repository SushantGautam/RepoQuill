#!/usr/bin/env python3
"""Fake Pi: happy path, but a tool arg echoes $REPOQUILL_TEST_SECRET.

The value is placed under a secret-named key (api_key) exactly as
protocol.sanitize_args redacts it; tests assert the raw secret never
reaches the trace.
"""
import sys

import fake_pi_common as c

if c.version_cli():
    raise SystemExit(0)
c.serve(lambda req: c.happy_events(echo_secret=True))
