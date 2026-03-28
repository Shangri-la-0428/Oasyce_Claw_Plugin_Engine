# Oasyce Local Testnet Simulation Guide

> This document covers the Python CLI sandbox only. It does **not** onboard you onto the public `oasyce-testnet-1` chain.

For real public beta onboarding, use the chain-side guide on [chain.oasyce](https://chain.oasyce.com) or the companion doc in `oasyce-chain/docs/PUBLIC_BETA.md`.

## What `oas testnet` actually is

`oas sandbox *` is the canonical local simulation environment for demos, UX testing, and agent smoke tests. `oas testnet *` remains only as a deprecated compatibility alias.

- No real public-chain identity is created
- No real public beta tokens are minted
- Sample assets are synthetic
- State lives under `~/.oasyce-sandbox`

## Quick Start

```bash
pip install oasyce
oas bootstrap
oas --json sandbox status
oas --json sandbox onboard
```

Expected `onboard` result shape:

- `mode = "LOCAL_SIMULATION"`
- `faucet_result`
- `sample_asset`
- `stake_result`

## Local Sandbox Commands

```bash
oas sandbox start [--port 9528]          # start local simulation node
oas --json sandbox status                # local simulation status
oas --json sandbox onboard               # faucet + sample asset + stake (simulation only)
oas sandbox faucet                       # local simulated faucet drip
oas sandbox reset --force                # clear ~/.oasyce-sandbox state
oas sandbox faucet-serve [--port 8421]   # local faucet simulation HTTP server
```

## Public Beta Boundary

If you are onboarding a real public beta user:

1. Use `oas bootstrap` for local package setup, wallet readiness, and DataVault.
2. Use the chain-side public beta guide for PoW self-registration and faucet access.
3. Return to `oas` / `datavault` for asset registration, quoting, buying, and agent workflows.

Do not tell users that `oas sandbox onboard` or `oas sandbox faucet` joins the public network. That is currently false.
