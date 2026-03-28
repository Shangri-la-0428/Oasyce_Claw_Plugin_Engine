"""Compatibility shim for the old local testnet simulation module path."""

from __future__ import annotations

from oasyce.services.sandbox import SandboxOnboardingService

# Backward-compatible alias for older imports.
OnboardingService = SandboxOnboardingService
