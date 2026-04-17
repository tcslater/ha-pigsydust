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

## Cross-repository coordination

Several stages require coordinated changes across two repositories:

| Repo | Purpose |
|------|---------|
| `ha-pigsydust` | The Home Assistant integration (this repo) |
| `pigsydust-py` | The PyPI library implementing the Telink mesh BLE protocol |

### Which stages touch which repo

| Stage | `ha-pigsydust` | `pigsydust-py` |
|-------|----------------|----------------|
| 0 | Investigation script | — |
| 1 | Rename to `sal_pixie` | — |
| 2 | Drop `DEVICE_TYPE_GATEWAY` usage, drop RSSI heuristic, typed runtime data | Remove `DEVICE_TYPE_GATEWAY`, rename parser access to `major_type`/`minor_type`, add `py.typed` marker, bump to 0.2.0 |
| 3 | Service exception wrapping, translations | — |
| 4 | Reauth + reconfigure flows | — |
| 5 | Availability logging | — |
| 6 | Diagnostics platform, repairs, icons | `DeviceStatus` must expose `major_type`, `minor_type`, raw manufacturer advert bytes |
| 7 | Integration tests | Library tests (if not already adequate) |
| 8 | Expanded README | README update for PyPI landing page |
| 9 | `quality_scale.yaml` | — |
| 10 | — (brands is a third repo) | — |
| 11 | Submit to `home-assistant/core` | Ensure latest release pinned in HA core requirements |

### Release ordering

Whenever a stage changes both repos, the library must be released to PyPI **before** the integration's `manifest.json` pins the new version. Typical flow:

1. Local Claude makes both changes simultaneously
2. Tag and release `pigsydust-py` to PyPI (e.g. `0.2.0`)
3. Update `ha-pigsydust/custom_components/sal_pixie/manifest.json` `requirements` to the new version
4. Commit the integration-side changes

The integration's `requirements` field in `manifest.json` is the pin.

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

## Stage 1 — Domain & Branding Rename (complete)

**Status:** Complete in commit `cae47d2`.

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

Low-risk, no user-facing behavior change. Groundwork for strict typing and all downstream stages.

### Integration-side changes

**1. Typed runtime data** (`__init__.py`):

```python
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from pigsydust import PixieClient
    from .coordinator import SalPixieCoordinator

@dataclass
class SalPixieRuntimeData:
    client: "PixieClient"
    coordinator: "SalPixieCoordinator"
    password: str
    indicator_modes: dict[int, str] = field(default_factory=dict)

type SalPixieConfigEntry = ConfigEntry[SalPixieRuntimeData]
```

**2. Updated `async_setup_entry` signature**:

```python
async def async_setup_entry(hass: HomeAssistant, entry: SalPixieConfigEntry) -> bool:
    password = entry.data[CONF_MESH_PASSWORD]
    client = await _connect_and_login(hass, password)

    coordinator = SalPixieCoordinator(hass, entry, client)
    client.set_disconnect_callback(coordinator._on_disconnect)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SalPixieRuntimeData(
        client=client,
        coordinator=coordinator,
        password=password,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
```

**3. `async_unload_entry` simplification** — no more `hass.data` dict to clean up:

```python
async def async_unload_entry(hass: HomeAssistant, entry: SalPixieConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.async_shutdown()
        await entry.runtime_data.client.disconnect()
    return unload_ok
```

**4. Coordinator gets `config_entry` kwarg** (modern HA pattern, 2024.x+):

```python
class SalPixieCoordinator(DataUpdateCoordinator[dict[int, DeviceStatus]]):
    config_entry: SalPixieConfigEntry  # typed parent attribute

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SalPixieConfigEntry,
        client: PixieClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="SAL Pixie",
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
            always_update=False,
        )
        self.client = client
        ...
```

This removes the current hacky `_try_reconnect` lookup through `hass.data[DOMAIN]`. The coordinator reads `self.config_entry.data[CONF_MESH_PASSWORD]` directly.

**5. Platform setup functions** — each platform reads runtime data from the entry:

```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: SalPixieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    ...
```

**6. Drop invented gateway taxonomy** in `light.py`:

- Remove `from pigsydust.const import DEVICE_TYPE_GATEWAY`
- Remove the `is_gateway = status.device_type == DEVICE_TYPE_GATEWAY` logic
- Device name becomes unconditionally `f"Pixie Switch {address}"`

**7. Drop `0x47` preference** in `__init__.py:_find_best_pixie_device`:

```python
def _find_best_pixie_device(hass: HomeAssistant) -> str | None:
    """Find the highest-RSSI Pixie device visible to HA's bluetooth stack."""
    best_address: str | None = None
    best_rssi = -999

    for info in async_discovered_service_info(hass, connectable=True):
        if 0x0211 not in (info.manufacturer_data or {}):
            continue
        if info.rssi > best_rssi:
            best_rssi = info.rssi
            best_address = info.address

    return best_address
```

The `is_gateway` parameter and logging are removed. The function's docstring stops claiming to prefer gateway devices.

**8. Type annotation modernization**:

- `FlowResult` → `ConfigFlowResult` (import from `homeassistant.config_entries`)
- `callable` (lowercase) → `Callable` from `collections.abc` (in `_connect_and_login` signature)
- `from __future__ import annotations` at the top of every module that lacks it
- Replace `Any` with concrete types wherever possible
- Set `PARALLEL_UPDATES = 1` in `select.py`, `number.py`, `button.py` (writing platforms)
- Set `PARALLEL_UPDATES = 0` in `sensor.py` (read-only, coordinator-driven)

**9. Pass `mypy --strict`** on the integration:

```bash
mypy --strict custom_components/sal_pixie/
```

Add any necessary `# type: ignore[...]` comments with specific error codes, not blanket ignores. The `pigsydust` library needs a `py.typed` marker for this to work cleanly.

### Library-side changes (`pigsydust-py`)

**1. Remove `DEVICE_TYPE_GATEWAY` from `pigsydust/const.py`** — no code references it in the library, it was only imported by the integration.

**2. Rename the advertisement-parser field access.** Wherever the library currently refers to byte[14] as `device_type` or similar, rename to `major_type` to match the Pixie app's own parser naming. Also expose `minor_type` if the adjacent byte is parsed. The naming matches what `bt_struct` disassembly revealed.

**3. Expose raw manufacturer advert bytes on `DeviceStatus`** (needed for Stage 6 diagnostics):

```python
@dataclass
class DeviceStatus:
    address: int
    is_on: bool
    mac: str | None
    major_type: int  # byte[14] of manufacturer advert
    minor_type: int | None  # byte[15] if present
    raw_manufacturer_data: bytes | None  # entire blob
```

**4. Add `py.typed` marker file** to the package so downstream users benefit from the library's type hints.

**5. Bump version to `0.2.0`** — breaking change due to removed constant.

**6. Release to PyPI** before updating the integration's `manifest.json` requirement.

### Acceptance criteria

- `mypy --strict custom_components/sal_pixie/` passes with zero errors
- `grep -r "DEVICE_TYPE_GATEWAY\|is_gateway\|Gateway" custom_components/sal_pixie/` returns no results (except perhaps comments about the history)
- `hass.data[DOMAIN]` is not set or read by any integration code
- Integration loads, all entities appear, light toggles work end-to-end in a live HA instance
- Integration unloads and reloads cleanly without resource leaks (check `hass.data` is empty afterwards)
- `manifest.json` requires `pigsydust==0.2.0` (once released)

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
