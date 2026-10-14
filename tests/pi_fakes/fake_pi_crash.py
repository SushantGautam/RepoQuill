#!/usr/bin/env python3
"""Fake Pi: prompt accepted, then hard exit(3) with a stderr marker."""
import sys

import fake_pi_common as c

if c.version_cli():
    raise SystemExit(0)
c.serve(lambda req: c.crash_events())
