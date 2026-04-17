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

Two goals: services survive integration reloads, and failures surface to users as proper HA errors rather than bare Python exceptions.

### Move registration to `async_setup`

Services are currently registered inside `async_setup_entry`, which means they disappear on unload/reload. Modern HA pattern registers them once at startup:

```python
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services once at integration load."""

    async def handle_set_indicator(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        try:
            mode = call.data[ATTR_MODE]
            brightness = call.data.get(ATTR_BRIGHTNESS, 15)
            await _apply_indicator(runtime.client, mode, brightness)
        except ConnectionError as err:
            raise HomeAssistantError(
                f"Could not reach SAL Pixie mesh: {err}"
            ) from err

    async def handle_all_on(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        try:
            await runtime.client.turn_on(0xFFFF)
        except ConnectionError as err:
            raise HomeAssistantError(f"Command failed: {err}") from err

    async def handle_all_off(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        try:
            await runtime.client.turn_off(0xFFFF)
        except ConnectionError as err:
            raise HomeAssistantError(f"Command failed: {err}") from err

    hass.services.async_register(
        DOMAIN, SERVICE_SET_INDICATOR, handle_set_indicator, schema=SET_INDICATOR_SCHEMA,
    )
    hass.services.async_register(DOMAIN, SERVICE_ALL_ON, handle_all_on)
    hass.services.async_register(DOMAIN, SERVICE_ALL_OFF, handle_all_off)
    return True
```

### Runtime-data lookup helper

With `single_config_entry: true`, there's at most one loaded entry:

```python
def _get_runtime_data(hass: HomeAssistant) -> SalPixieRuntimeData:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError(
            "SAL Pixie integration is not configured or not yet loaded"
        )
    return entries[0].runtime_data
```

### Exception categories

- `HomeAssistantError` — for runtime failures (connection dropped, mesh unreachable)
- `ServiceValidationError` — for invalid parameters (caught by voluptuous schema in most cases; rarely needed here)
- Uncaught exceptions are silently eaten by HA's service dispatcher — never let that happen

### Translations

Add a `services` block to `strings.json` and mirror it to `translations/en.json`:

```json
"services": {
  "set_indicator": {
    "name": "Set indicator LED",
    "description": "Sets the indicator LED colour and brightness on all mesh switches.",
    "fields": {
      "mode": {
        "name": "Mode",
        "description": "Indicator colour (off, blue, orange, purple)."
      },
      "brightness": {
        "name": "Brightness",
        "description": "LED brightness (0-15). Only applies to orange and purple modes."
      }
    }
  },
  "all_on": {
    "name": "Turn all switches on",
    "description": "Sends an on command to every switch in the mesh."
  },
  "all_off": {
    "name": "Turn all switches off",
    "description": "Sends an off command to every switch in the mesh."
  }
}
```

### Acceptance criteria

- Services remain callable after `config_entries.async_reload(entry.entry_id)`
- Calling a service while the mesh is offline raises a visible error in the UI (not a silent failure)
- Service names and descriptions appear correctly in the Developer Tools → Services picker
- `strings.json` and `translations/en.json` pass `python -m script.translations develop` (HA's translations linter) when the integration is in HA core — smoke-test with `jq empty` for valid JSON during custom-component development

## Stage 4 — Config Flow Expansion

Adds reauth (credentials expired) and reconfigure (user wants to change home key without removing the integration) flows. Both use modern HA helpers that keep the entry identity stable.

### Shared connection-test helper

Currently `_test_connection_any` lives on the flow class. Extract it so the reauth/reconfigure steps can reuse the exact same validation logic:

```python
async def _test_connection(hass: HomeAssistant, password: str) -> str | None:
    """Return None on success, or an error key ('cannot_connect' / 'invalid_auth')."""
    candidates = [
        (info.rssi, info.address)
        for info in async_discovered_service_info(hass, connectable=True)
        if 0x0211 in (info.manufacturer_data or {})
    ]
    candidates.sort(reverse=True)
    if not candidates:
        return "cannot_connect"

    for _rssi, address in candidates:
        client = PixieClient(address)
        try:
            await client.connect()
        except Exception:
            continue
        try:
            await client.login(MESH_NAME, password)
            await client.disconnect()
            return None
        except LoginError:
            await client.disconnect()
            return "invalid_auth"
        except Exception:
            await client.disconnect()
    return "cannot_connect"
```

### Reauth flow

Triggered by `ConfigEntryAuthFailed` raised from the coordinator:

```python
# coordinator.py — already raises this in _async_update_data when LoginError occurs
except LoginError as err:
    raise ConfigEntryAuthFailed from err
```

```python
# config_flow.py
from collections.abc import Mapping

class SalPixieConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Entry point for the reauth flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _test_connection(self.hass, user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data={CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_MESH_PASSWORD): str}),
            errors=errors,
        )
```

### Reconfigure flow

Similar shape, user-initiated rather than auth-triggered:

```python
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _test_connection(self.hass, user_input[CONF_MESH_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data={CONF_MESH_PASSWORD: user_input[CONF_MESH_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_MESH_PASSWORD): str}),
            errors=errors,
        )
```

### Strings additions

Append to the `config.step` block in `strings.json`:

```json
"reauth_confirm": {
  "title": "Reauthenticate SAL Pixie",
  "description": "The stored home key is no longer working. Enter the current home key.",
  "data": { "home_key": "Home key" }
},
"reconfigure": {
  "title": "Reconfigure SAL Pixie",
  "description": "Enter the new home key for the mesh.",
  "data": { "home_key": "Home key" }
}
```

Mirror to `translations/en.json`.

### Acceptance criteria

- Triggering reauth via `entry.async_start_reauth(hass)` shows the correct form
- Completing reauth with a valid key reloads the entry and clears the reauth notification
- Completing reconfigure updates `entry.data[CONF_MESH_PASSWORD]` and reloads the entry
- Entry ID and unique_id remain stable across both flows (no duplicate entries created)
- Invalid keys show the `invalid_auth` error inline on the form

## Stage 5 — Observability

The `log-when-unavailable` Silver rule requires a single log line when the integration transitions to unavailable, and another when it recovers. Done naively inside entity `available` properties, this would fire thousands of times per minute — the property is polled constantly. Keep the logging in the coordinator, where transitions are naturally observable via `last_update_success`.

### Coordinator-level transition logging

```python
async def _async_update_data(self) -> dict[int, DeviceStatus]:
    try:
        result = await self.client.query_status()
    except LoginError as err:
        raise ConfigEntryAuthFailed from err
    except ConnectionError as err:
        if self.last_update_success:
            _LOGGER.warning("Connection to SAL Pixie mesh lost: %s", err)
        await self._try_reconnect()
        raise UpdateFailed(f"BLE connection lost: {err}") from err
    except Exception as err:
        raise UpdateFailed(f"Error querying status: {err}") from err

    if not self.last_update_success:
        _LOGGER.info("Connection to SAL Pixie mesh restored")

    # ... existing merge logic
    return merged
```

`self.last_update_success` is `True` before the current call's outcome is recorded, so testing it inside the except block tells you "were we previously successful?" — i.e. this is the transition.

### Disconnect-callback reaction

When the BLE disconnect callback fires, immediately mark entities unavailable by pushing `None` into the coordinator:

```python
def _on_disconnect(self, *_args: Any) -> None:
    _LOGGER.warning("SAL Pixie BLE connection dropped")
    self._disconnected = True
    # Push empty data so CoordinatorEntity.available returns False right away
    self.async_set_updated_data({})
```

An empty dict marks every address absent → every entity's `available` returns `False` without waiting for the next poll to fail. Restore happens naturally when push updates or the next poll succeed.

### Entity `available` property — minimal, no logging

```python
@property
def available(self) -> bool:
    return (
        super().available
        and self.coordinator.data is not None
        and self._address in self.coordinator.data
    )
```

No log calls here. The coordinator handles transitions.

### Acceptance criteria

- Pulling the BLE adapter logs **one** `WARNING` line about the connection loss (not one per entity)
- Restoring the adapter logs **one** `INFO` line about recovery
- All entities go unavailable within one coordinator cycle of the disconnect
- Repeated connection/disconnection cycles don't flood logs

---

## Stage 6 — Gold-Tier Platforms

Each item below can be its own commit.

### 6a. Diagnostics platform

**File:** `custom_components/sal_pixie/diagnostics.py`

```python
"""Diagnostics for SAL Pixie."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_MESH_PASSWORD
from . import SalPixieConfigEntry

TO_REDACT = {CONF_MESH_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: SalPixieConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    client = entry.runtime_data.client
    coordinator = entry.runtime_data.coordinator

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "connection": {
            "address": client.address,
            "firmware_version": client.firmware_version,
            "hardware_version": client.hardware_version,
            "is_connected": client.is_connected,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_s": coordinator.update_interval.total_seconds(),
            "device_count": len(coordinator.data or {}),
        },
        "devices": {
            str(addr): {
                "address": addr,
                "is_on": status.is_on,
                "mac": status.mac,
                "major_type": getattr(status, "major_type", None),
                "minor_type": getattr(status, "minor_type", None),
                "raw_manufacturer_data": (
                    status.raw_manufacturer_data.hex()
                    if getattr(status, "raw_manufacturer_data", None)
                    else None
                ),
            }
            for addr, status in (coordinator.data or {}).items()
        },
    }
```

**Library dependency:** `DeviceStatus` must expose `major_type`, `minor_type`, and `raw_manufacturer_data`. If the library can't easily provide raw bytes, fall back to just `major_type` / `minor_type` and a note in the diagnostic about needing a library version bump.

### 6b. Repairs platform

**File:** `custom_components/sal_pixie/repairs.py`

Surface long-lived disconnection as an actionable repair issue:

```python
"""Repairs flow for SAL Pixie."""
from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class MeshUnreachableRepairFlow(RepairsFlow):
    """Walk the user through recovering from a sustained mesh outage."""

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm")


async def async_create_fix_flow(hass, issue_id, data):
    if issue_id == "mesh_unreachable":
        return MeshUnreachableRepairFlow()
    return None
```

Raise the issue from the coordinator when disconnection persists past a threshold (e.g. 5 consecutive failed updates):

```python
async_create_issue(
    hass,
    DOMAIN,
    "mesh_unreachable",
    is_fixable=True,
    severity=IssueSeverity.WARNING,
    translation_key="mesh_unreachable",
)
```

And `async_delete_issue(...)` when the connection recovers.

### 6c. Stale-device cleanup

Track `last_seen` per device in the coordinator. On each successful poll, remove device registry entries for addresses absent longer than a threshold (e.g. 24 hours):

```python
STALE_THRESHOLD = timedelta(hours=24)

class SalPixieCoordinator(...):
    def __init__(self, ...):
        ...
        self._last_seen: dict[int, float] = {}

    async def _async_update_data(self) -> ...:
        ...
        now = time.monotonic()
        for addr in merged:
            self._last_seen[addr] = now

        # Prune stale entries from device registry
        registry = dr.async_get(self.hass)
        threshold = now - STALE_THRESHOLD.total_seconds()
        for addr, last_seen in list(self._last_seen.items()):
            if last_seen < threshold and addr not in merged:
                identifier = (DOMAIN, f"{self.config_entry.entry_id}_{addr}")
                device = registry.async_get_device(identifiers={identifier})
                if device:
                    registry.async_remove_device(device.id)
                del self._last_seen[addr]

        return merged
```

### 6d. Icon translations

**File:** `custom_components/sal_pixie/icons.json`

```json
{
  "services": {
    "set_indicator": "mdi:led-on",
    "all_on": "mdi:lightbulb-group",
    "all_off": "mdi:lightbulb-group-off"
  }
}
```

Per-entity icons are set via `_attr_icon` in the entity classes where needed (most use defaults from their device class).

### 6e. Connected-device sensor rename

Rename the existing `PixieGatewaySensor` to `PixieConnectedDeviceSensor` and update its state description from "current gateway" to "currently-connected device" — an honest description of what it reports. No architectural change.

### Acceptance criteria (per sub-stage)

- **6a**: Downloading diagnostics from the integration page produces valid JSON with the mesh password redacted
- **6b**: Killing BLE for >5 coordinator cycles raises a visible repair issue; recovering clears it
- **6c**: A switch removed from the mesh disappears from the device registry after 24h
- **6d**: Services show their icons in the Developer Tools picker
- **6e**: No code or UI string references "gateway" as a role — the word survives only in product/SKU comments if at all

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
