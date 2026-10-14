#!/usr/bin/env python3
"""Fake Pi: accepts the prompt, emits agent_start, never settles."""
import sys

import fake_pi_common as c

if c.version_cli():
    raise SystemExit(0)
c.serve(lambda req: c.hang_events())
