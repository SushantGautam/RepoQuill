#!/usr/bin/env python3
"""Fake Pi: full happy path (3 tools incl. staged write_doc, settles)."""
import sys

import fake_pi_common as c

if c.version_cli():
    raise SystemExit(0)
c.serve(lambda req: c.happy_events())
