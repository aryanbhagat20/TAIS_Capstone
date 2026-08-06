"""
conftest.py — pytest configuration, repo root.

Centralizes the sys.path setup needed so tests can `import schema` and
`import simulator.telemetry_simulator` without each test file repeating
its own path-manipulation hack. pytest auto-discovers this file
automatically; nothing needs to import it explicitly.
"""
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")

if SRC not in sys.path:
    sys.path.insert(0, SRC)
