# Home Assistant Core Inclusion Plan

Roadmap for evolving this integration from a custom component into a candidate for inclusion in the Home Assistant core repository.

## Target outcome

Submission to `home-assistant/core` under domain `sal_pixie`, meeting at least **Silver** tier of the Integration Quality Scale, with **Gold** as a realistic follow-up target.

## Branding and positioning

- **Domain:** `sal_pixie`
- **Integration name:** `SAL Pixie`
- **Positioning:** Unofficial, community-developed. Not affiliated with or endorsed by SAL.
- **Rationale:** HA convention is to name integrations after the product they integrate with. "PigsyDust" is opaque to users searching "SAL Pixie home assistant". Using the product name is standard nominative use; HA routinely accepts reverse-engineered integrations with manufacturer branding.

## Scope

### Supported at v1

- SAL Pixie wall switches (on/off)

Every mesh address becomes an independent on/off light entity, matching how the official PIXIE app presents them.

### Not yet supported

- RGB LED strips
- Dimmer switches
- Power points

The mesh protocol is believed to be the same across the product line. These can be added in follow-up PRs once the v1 architecture is merged. Document this openly in the README.

---

## Stage 0 — Reverse-engineering investigation (complete)

**Status:** Complete. Findings recorded below.

The original code named a constant `DEVICE_TYPE_GATEWAY` with value `0x47`, inferred to mean "gateway role" because observed devices with that byte value appeared to be better connection targets. The ASCII coincidence (`0x47` = 'G', `0x45` = 'E') made "gateway / endpoint" a plausible reading.

### Findings from app disassembly

- The Pixie app's own parser names the field `majorType` (with a companion `minorType`)
- **No** constants `0x47` / `0x45` are compared anywhere in the app binary
- The string "gateway" does not appear anywhere in the app binary
- The "gateway" label was entirely our inference — not from the app

### Findings from live BLE observation

- Observed 8 wall switches over 5 minutes with HA and Pixie app both active
- All 8 devices advertised `majorType = 0x45` throughout
- No device advertised `0x47` during the observation window
- The `0x47` value was observed on a wall switch during an earlier reverse-engineering session, but its meaning remains unknown

### Conclusions

- Treat byte[14] as an opaque `majorType` value with no known semantics
- Drop the invented "gateway" terminology everywhere
- Drop the `0x47` connection-preference heuristic — no empirical or documentary basis
- Expose `majorType` / `minorType` in `diagnostics.py` (Stage 6) so future contributors with different hardware can report what they see

---

## Stage 1 — Domain & Branding Rename

Do this first. Everything downstream (tests, docs, quality scale declaration) embeds the domain string.

- Rename `custom_components/pigsydust/` → `custom_components/sal_pixie/`
- Update `manifest.json`: `domain` → `sal_pixie`, `name` → `SAL Pixie`
- Update `const.py`: `DOMAIN = "sal_pixie"`
- Update `strings.json` + `translations/en.json`: title → `SAL Pixie`
- Update `hacs.json` if it contains a name field
- Update `README.md`: project title, install paths, disclaimer
- Keep `pigsydust==0.1.10` as the Python requirement (library can retain its codename)
- Add a breaking-change note to the README for existing users

## Stage 2 — Foundational Modernization

Low-risk, no behavior change. Groundwork for strict typing.

- Typed `SalPixieConfigEntry = ConfigEntry[SalPixieRuntimeData]` alias
- `SalPixieRuntimeData` dataclass replaces the `hass.data[DOMAIN][entry.entry_id]` dict
- `FlowResult` → `ConfigFlowResult`
- `callable` → `Callable` from `collections.abc`
- `from __future__ import annotations` everywhere
- Remove `DEVICE_TYPE_GATEWAY` from the `pigsydust` library entirely; replace the parser field naming with `major_type` / `minor_type` to match the app's own terminology
- Drop all "Gateway" branding from device names — every entity becomes `Pixie Switch {address}`
- Drop the `0x47` connection-preference heuristic in `_find_best_pixie_device`; select purely by RSSI
- Audit `PARALLEL_UPDATES`: `1` on write platforms (light, select, number, button), `0` on sensor
- Pass `mypy --strict`

## Stage 3 — Service Action Hardening

- Wrap service handlers in `try/except` converting to `HomeAssistantError`
- Move service registration into `async_setup()` so services survive entry reloads
- Add service-action translations to `strings.json` / `translations/en.json`

## Stage 4 — Config Flow Expansion

- Extract shared connection-test helper
- Add `async_step_reauth()` + `async_step_reauth_confirm()` triggered on `ConfigEntryAuthFailed`
- Add `async_step_reconfigure()` for in-place home key updates
- Add corresponding strings

## Stage 5 — Observability

- Per-entity availability logging that transitions cleanly (`WARNING` once on unavailable, `INFO` once on recovery)
- Every entity's `available` property checks both `coordinator.last_update_success` and device presence
- Disconnect callback triggers `coordinator.async_set_updated_data(None)` so entities go unavailable immediately

## Stage 6 — Gold-Tier Platforms

Each item can be a separate commit.

- **Diagnostics** (`diagnostics.py`) — redacted config entry + coordinator dump
- **Repairs** (`repairs.py`) — surface long-running disconnection as an actionable repair
- **Stale devices** — cleanup of mesh addresses absent beyond a threshold
- **Icon translations** (`icons.json`) — for services and entity states
- **Connected-device sensor** (mesh-level) — rename existing gateway sensor to report which device HA is currently talking to, without claiming anything about roles

## Stage 7 — Test Suite

The single biggest task. Enables Bronze (basic tests) through Silver (95%+ coverage).

### Infrastructure
- `tests/` directory scaffold
- `conftest.py` with fixtures (`mock_pixie_client`, `mock_bluetooth_discovery`, `init_integration`)
- `requirements-test.txt`
- CI workflow in `.github/workflows/test.yml`

### Coverage
- `test_config_flow.py` — all steps, all error paths, reauth, reconfigure
- `test_init.py` — setup, unload, reload, auth failure
- `test_coordinator.py` — push updates, poll fallback, reconnect, grace period, stale pruning
- One file per platform
- `test_diagnostics.py` using snapshot testing

## Stage 8 — Documentation

README gets expanded into:
- Supported devices (explicit list)
- Prerequisites
- Installation
- Configuration parameters (home key, where to find it)
- Data updates (push + fallback poll)
- Known limitations
- Troubleshooting
- Removing the integration
- Use cases
- Unofficial / unaffiliated disclaimer

## Stage 9 — Quality Scale Declaration

- `quality_scale.yaml` in the integration directory
- Declare target tier with per-rule status (`done`, `todo`, `exempt` with justification)
- Initial target: Silver

## Stage 10 — Brands Repo Submission

Separate PR to `home-assistant/brands`:
- `core_integrations/sal_pixie/icon.png` (256×256)
- `core_integrations/sal_pixie/logo.png`
- Dark mode variants if needed

**Must be merged before the core PR.**

## Stage 11 — Core PR Preparation

Separate fork of `home-assistant/core`:
- Move integration into `homeassistant/components/sal_pixie/`
- Move tests into `tests/components/sal_pixie/`
- Run the codegen scripts to register bluetooth discovery and requirements
- Submit PR referencing `quality_scale.yaml`

---

## Execution order

```
0 (user investigation, non-blocking) 
  → 1 → 2 → 3 → 4 → 5 → 6 (a/b/c/d parallel) → 7 → 8 → 9 → 10 → 11
```

### Recommended first milestone

Stages 1 + 2 + 3 + 4 + 7a-7c. That produces a rebranded, modernized, tested integration still shipping as a custom component — a safe v0.2.0 checkpoint before committing to the core submission path.

## Known open questions

- **`majorType` semantics** — settled as unknown, treated as opaque. `0x45` is the common value observed on wall switches; `0x47` was observed once with unknown meaning. Exposed via diagnostics for future investigation.
- **Slave switches** — PIXIE app treats all switches identically, so HA does too. No architectural branching needed. The term "slave" does not appear in any user-facing surface.
