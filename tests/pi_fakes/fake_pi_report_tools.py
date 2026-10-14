#!/usr/bin/env python3
"""Fake Pi: happy path; get_state reports the active (allowlisted) tools."""
import sys

import fake_pi_common as c

if c.version_cli():
    raise SystemExit(0)
c.serve(lambda req: c.happy_events(),
        extra_state={"tools": list(c.ALLOWED_TOOLS)})
