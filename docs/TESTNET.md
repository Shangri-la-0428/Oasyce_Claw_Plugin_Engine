# Oasyce Local Testnet Simulation Guide

> This document covers the Python CLI sandbox only. It does **not** onboard you onto the public `oasyce-testnet-1` chain.

For real public beta onboarding, use the chain-side guide on [chain.oasyce](https://chain.oasyce.com) or the companion doc in `oasyce-chain/docs/PUBLIC_BETA.md`.

## What `oas testnet` actually is

`oas testnet *` is a local simulation environment for demos, UX testing, and agent smoke tests.

- No real public-chain identity is created
- No real public beta tokens are minted
- Sample assets are synthetic
- State lives under `~/.oasyce-testnet`

## Quick Start

```bash
pip install oasyce
oas bootstrap
oas --json testnet status
oas --json testnet onboard
```

Expected `onboard` result shape:

- `mode = "LOCAL_SIMULATION"`
- `faucet_result`
- `sample_asset`
- `stake_result`

## Local Sandbox Commands

```bash
oas testnet start [--port 9528]          # start local simulation node
oas --json testnet status                # local simulation status
oas --json testnet onboard               # faucet + sample asset + stake (simulation only)
oas testnet faucet                       # local simulated faucet drip
oas testnet reset --force                # clear ~/.oasyce-testnet state
oas testnet faucet-serve [--port 8421]   # local faucet simulation HTTP server
```

## Public Beta Boundary

If you are onboarding a real public beta user:

1. Use `oas bootstrap` for local package setup, wallet readiness, and DataVault.
2. Use the chain-side public beta guide for PoW self-registration and faucet access.
3. Return to `oas` / `datavault` for asset registration, quoting, buying, and agent workflows.

Do not tell users that `oas testnet onboard` or `oas testnet faucet` joins the public network. That is currently false.
