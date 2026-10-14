#!/usr/bin/env python3
"""Fake Pi: model stream failure (502), retries exhausted, settles."""
import sys

import fake_pi_common as c

if c.version_cli():
    raise SystemExit(0)
c.serve(lambda req: c.model_error_events())
