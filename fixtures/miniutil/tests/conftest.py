"""Pytest path setup so `miniutil` imports when tests run standalone.

When this fixture is executed from the repo root (e.g.
`uv run pytest -q fixtures/miniutil/tests`), put the fixture package
directory on sys.path so `import miniutil` works without installation.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
