# Simplification TODO

Goal: make Oasyce easier to change by reducing duplicated truth, hardening release gates, and deleting transitional surfaces instead of preserving them forever.

## Current focus

- [x] Move public beta entrypoint text into a single package-level doc contract.
- [x] Generate the README public beta block from that contract instead of hand-editing two copies.
- [x] Make `oas info` read the same beta onboarding contract.

## Next simplification moves

- [x] Generate chain-side website/public beta entrypoint copy from a chain-side contract instead of editing `README + website + docs` separately.
- [x] Turn public beta release verification into one executable smoke command/script, not a checklist plus manual memory.
- [x] Remove the deprecated `oas testnet *` alias so only `sandbox` and real public beta remain.
- [x] Shrink duplicated onboarding copy in README/AGENTS/SKILL so one canonical guide owns the full flow and other surfaces stay short.
- [x] Keep release artifacts and generated docs reproducible from scripts, never hand-edited after publish.
