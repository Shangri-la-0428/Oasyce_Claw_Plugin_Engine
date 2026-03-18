"""
Global test configuration.

Disables Ed25519 signature enforcement for the test suite so that
unsigned Operations (used throughout existing tests) continue to work.
Production code defaults to signatures ON; set OASYCE_REQUIRE_SIGNATURES=0
to opt out (local dev / testing only).
"""

import os

os.environ.setdefault("OASYCE_REQUIRE_SIGNATURES", "0")
