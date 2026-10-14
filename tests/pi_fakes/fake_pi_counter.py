#!/usr/bin/env python3
"""Fake Pi: happy path + counts prompt invocations (counter file)."""
import sys

import fake_pi_common as c

if c.version_cli():
    raise SystemExit(0)
c.serve(lambda req: c.happy_events())
