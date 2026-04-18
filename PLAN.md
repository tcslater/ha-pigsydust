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
| 2 | Drop `DEVICE_TYPE_GATEWAY` usage, drop RSSI heuristic, typed runtime data | Remove `DEVICE_TYPE_GATEWAY`, rename parser access to `major_type`/`minor_type`, add `DeviceClass` enum + `(type, stype) → DeviceClass` lookup, migrate the device-type extraction tooling from `ha-pigsydust/scripts/`, add `py.typed` marker, bump to 0.2.0 |
| 2b | *Conditional.* If Phase A spike succeeds: resolve `BLEDevice` via HA, drop standalone path | *Conditional.* If Phase A succeeds: accept `BLEDevice`, use `bleak_retry_connector` |
| 3 | Service exception wrapping, translations (incl. `HomeAssistantError` translation keys) | — |
| 4 | Reauth + reconfigure flows | — |
| 5 | Availability logging | — |
| 6 | Diagnostics platform, repairs, icons, `device_class` translations in `strings.json` | `DeviceStatus` must expose `major_type`, `minor_type`, `device_class` (resolved enum member), raw manufacturer advert bytes |
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
- The `0x47` value was observed on a wall switch during an earlier reverse-engineering session, but its meaning was not yet understood at the time

### Follow-up findings from `bt_struct.framework` disassembly

Deeper analysis of `_BTDataHandle_manu2string`, `_BTDataHandle_manu_elem`, and `_BTDataHandle_dataParse` revealed that the byte the app labels `majorType` is **not a device-class enum at all**. It is a packed byte whose bits mirror the layout of byte[0xd] of a `fun=0x1b` device-info response packet:

- **bit 0** — "online" / "used" flag (exposed via `manu_elem(6)` as `& 0x1`).
- **bit 1** — `alarmDev` flag. Observed to flip between `0x47` and `0x45` on an otherwise-identical wall switch, most likely tracking whether the device currently participates in an alarm group/scene.
- **bits 2–7** — 6-bit firmware version (exposed via `manu_elem(7)` as `>> 2`). Every wall switch observed so far decodes to version 17 (`0b010001`).

So `0x47 = online + alarmDev + v17` and `0x45 = online + no alarmDev + v17`. Not a persistent identity, not a role.

The companion field the app labels `minjorType` (sic, with a `j`) is a **16-bit big-endian** value at bytes `[0xb..0xc]` of the raw Skytone blob — that is HA offsets `[15..16]` after the 4-byte Telink wrapping. This *is* the device class.

### Follow-up findings from Dart AOT extraction

The full `(type, stype) → DeviceType` table has now been extracted from `libapp.so` (SAL PIXIE Android v2.15.2375) using [blutter](https://github.com/worawit/blutter):

- `pixie_sdk.dart::getTypeStype()` is a switch statement over an 82-value `DeviceType` enum that returns `{type: <int>, stype: <int>}`.
- The 16-bit BE value at HA offsets `[15..16]` equals `(type << 8) | stype`. For wall switches (`SWITCH`): `(44, 22)` → `0x2c16` (decimal 11286). Verified against the bit layout that `bt_struct.framework`'s `_BTDataHandle_dataParse` (fun=0x1b) reveals.
- Indices that take the default branch in `getTypeStype()` (`UNKNOW`, `PCP5`, `RFD2_SCAN`, `ACF_*`, `CAP*`, `MTW*`, `MRC`, `DIAL`, `STC`, `SIC`, `SFI_*`, `DV02`, `SONOS`) route through `_getTypeStypeP3rd()` — third-party fallback. Their numeric encoding is constructed at runtime; covering them needs an extension to the extractor.
- The renderable table lives at `scripts/devicetype_table.txt` and the regenerator at `scripts/extract_devicetype_table.py`. **Both will migrate to `pigsydust-py` as part of Stage 2** so that any consumer of the library — not just HA — can identify Pixie hardware.

### Conclusions

- Byte[14] is a **packed flag byte**, not a device-class enum. Naming it `majorType` matches the Pixie app's own (misleading) label; internally, it decomposes into `online | alarmDev | version`.
- Drop the invented "gateway" terminology everywhere.
- Drop the `0x47` connection-preference heuristic — it was tracking the `alarmDev` flag, which is entirely unrelated to BLE reachability.
- `0x47` vs `0x45` vs other values do not identify a different *kind* of device. A non-wall-switch Pixie device shows a different value at bytes[15..16], not a different byte[14].
- The library should ship a `DeviceClass` enum keyed on the BE16 value at bytes[15..16]. The integration converts the enum identifier into a localised display name via `strings.json` (HA's translation pipeline), keeping the library presentation-neutral.

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

### Verification (post-completion)

- `custom_components/pigsydust/` is fully removed (the rename was a move, not a copy). If only `__pycache__` remains, delete the directory.
- `grep -r "pigsydust" custom_components/sal_pixie/` returns only the library import lines, never the old domain.

### Follow-up: hub-device pattern, config-entry title

The initial rename left user-facing surfaces calling the integration "Pixie Mesh" (config-entry title and config-flow step titles). The mesh-wide select/number/button entities are a deliberate feature — the Pixie protocol has a broadcast address, so one packet toggles every switch at once. Rather than drop that UI, adopt the hub-device pattern used by Hue/Unifi/Fritzbox: the integration is **SAL Pixie**; the hub device inside it is **Pixie Mesh** (because that's what the mesh is called in the product docs).

Changes:

- `config_flow.py` — `async_create_entry(title="Pixie Mesh")` → `title="SAL Pixie"` in both user and bluetooth-confirm paths.
- `strings.json` + `translations/en.json` — step titles `"Pixie Mesh"` / `"Pixie Mesh Discovered"` → `"SAL Pixie"` / `"SAL Pixie discovered"` (HA sentence-case convention).
- `const.py` `MESH_DEVICE_INFO` — left unchanged; `name="Pixie Mesh"` is correct for the hub device.
- Module docstrings referring to "Pixie Mesh" — left unchanged (not user-facing); Stage 2 will touch most of these files anyway.

Acceptance:

- A fresh install shows an entry titled "SAL Pixie" in Settings › Devices & Services, containing a "Pixie Mesh" hub device plus per-switch light devices.

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

**8a. Tighten `unique_id` handling in the config flow.**

`manifest.json` already declares `single_config_entry: true`, which enforces "at most one entry" at creation time. That's enough for the user-initiated `async_step_user` path, so the `async_set_unique_id(DOMAIN)` + `_abort_if_unique_id_configured()` calls there are redundant — remove them.

`async_step_bluetooth` is different: every Pixie switch in the mesh broadcasts matching manufacturer data, and each advert initiates a separate discovery flow. Without `async_set_unique_id(DOMAIN)` + `_abort_if_unique_id_configured()` in the bluetooth step, the user sees one "Discovered" card per switch (8+ in a typical install) rather than a single one. Keep the calls on the bluetooth step; they force second-and-subsequent flows to abort with `already_in_progress` / `already_configured`.

**9. Pass `mypy --strict`** on the integration:

```bash
mypy --strict custom_components/sal_pixie/
```

Add any necessary `# type: ignore[...]` comments with specific error codes, not blanket ignores. The `pigsydust` library needs a `py.typed` marker for this to work cleanly.

### Library-side changes (`pigsydust-py`)

**1. Remove `DEVICE_TYPE_GATEWAY` from `pigsydust/const.py`** — no code references it in the library, it was only imported by the integration.

**2. Rename the advertisement-parser field access.** Wherever the library currently refers to byte[14] as `device_type` or similar, rename to `major_type` — matching the Pixie app's own (misleading) label. Per the Stage 0 follow-up findings, byte[14] is actually a packed `online | alarmDev | version` flag byte, but keeping the app's terminology makes cross-referencing disassembly easier for future contributors. Also expose `minor_type` as a 16-bit big-endian integer from bytes[15..16] — the app's `minjorType`, strongest candidate for the real device-class code.

**3. Expose raw manufacturer advert bytes on `DeviceStatus`** (needed for Stage 6 diagnostics):

```python
@dataclass
class DeviceStatus:
    address: int
    is_on: bool
    mac: str | None = None
    major_type: int = 0  # byte[14] of manufacturer advert
    minor_type: int | None = None  # bytes[15..16] as 16-bit BE int
    device_class: DeviceClass | None = None  # resolved from minor_type
    raw_manufacturer_data: bytes | None = None  # entire blob
```

All new fields must have defaults so existing callers (including test fixtures that construct `DeviceStatus` positionally) don't break on the 0.2.0 bump. The same `device_class` field should also appear on `PixieAdvert` (the scan-result parser), populated by `DeviceClass.from_minor_type(minor_type)`.

**3a. Ship the `DeviceClass` enum** in a new module `pigsydust/device_class.py`:

```python
from enum import IntEnum

class DeviceClass(IntEnum):
    """Pixie device class, encoded as the 16-bit BE int at advert bytes [15..16]."""
    SWITCH = 0x2c16
    TSWITCH = 0x2a18
    TSWITCHG2 = 0x2a1a
    DIMMER = 0x2e16
    DIMMER_G2 = 0x2e18
    DIMMER_G3 = 0x2e1a
    BRIDGE = 0x0216
    BRIDGE_G2 = 0x0204
    STRIP_W = 0x3004
    STRIP_RGB = 0x3604
    STRIP2_RGBCCT = 0x3408
    STRIP2_RGB = 0x3608
    STRIP2_CCT = 0x3208
    # ... 50+ more entries — see scripts/devicetype_table.txt for the full list
    # ECL_AC, FCS, FCR, POL, SPO2/3, DRC, BSC, FAN_*, VFAN_*, BFAN_ONLY,
    # RGB_X, IR12/IR36, SMR, RFD/RFD_CT/RFD2/RFD2_CT, DM10, DALI_DT6,
    # GDC1/GDC1_SW/GDC1_SL/GDC1_W/GDC2/GDC1_M2*, RCT_W/RCT_CCT/RCT_RGB*,
    # ZCL, ACF_VRV, ACF_DUCTED, SGB/SGB3/SGBX*, DELAY

    @classmethod
    def from_minor_type(cls, value: int | None) -> "DeviceClass | None":
        """Look up the device class for a 16-bit minor_type value. None if unknown."""
        if value is None:
            return None
        try:
            return cls(value)
        except ValueError:
            return None
```

The library deliberately ships the enum identifier (`SWITCH`, `DIMMER_G3`, `STRIP2_RGBCCT`, ...) rather than human-readable names. Identifiers are stable opaque protocol keys; localised display strings ("Wall Switch", "Dimmer (Gen 3)", ...) live in the integration's `strings.json` so HA can translate them. CLI / non-HA consumers of `pigsydust-py` get the canonical identifier and can render it however they like.

**3b. Migrate the lookup-table tooling** from `ha-pigsydust/scripts/` to `pigsydust-py/scripts/`:

- `scripts/extract_devicetype_table.py` — the blutter-output parser that produces the (idx, enum_name, type, stype) table. Used to regenerate the enum when SAL ships a new app version.
- `scripts/devicetype_table.txt` — the rendered table from the most-recent extraction. Committed for review.
- Add a CONTRIBUTING (or README) note explaining how to bump the enum from a new APK release.

The `ha-pigsydust` copies of those files should be deleted once the library has them — no need to maintain two copies.

**4. Add `py.typed` marker file** to the package so downstream users benefit from the library's type hints.

**5. Bump version to `0.2.0`** — breaking change due to removed constant. The new `DeviceClass` enum and the additional `DeviceStatus` / `PixieAdvert` fields are additive; they don't move the bump higher.

**6. Release to PyPI** before updating the integration's `manifest.json` requirement.

### Acceptance criteria

- `mypy --strict custom_components/sal_pixie/` passes with zero errors
- `grep -rE "DEVICE_TYPE_GATEWAY|is_gateway|Gateway|0x47" custom_components/sal_pixie/` returns no results (except perhaps comments about the history)
- `hass.data[DOMAIN]` is not set or read by any integration code
- `grep -r "async_set_unique_id\|_abort_if_unique_id_configured" custom_components/sal_pixie/config_flow.py` returns no results (single_config_entry handles it)
- Integration loads, all entities appear, light toggles work end-to-end in a live HA instance
- Integration unloads and reloads cleanly without resource leaks (check `hass.data` is empty afterwards)
- `manifest.json` requires `pigsydust==0.2.0` (once released)

## Stage 2b — BLE Transport Investigation

**Status:** Open question. This stage is an **investigation**, not a pre-decided implementation.

### Why this is a stage at all

The current integration uses a standalone `BleakClient` (via the `pigsydust` library) that bypasses HA's Bluetooth stack. Core reviewers are likely to object — first-party BLE integrations are expected to resolve a `BLEDevice` through `homeassistant.components.bluetooth` and open the connection via `bleak_retry_connector.establish_connection(...)`.

### Why it isn't already done

The project has been down this road. In prior work (see `pigsydust-py` commit `7281f57` "Use BleakClientBlueZDBus directly on Linux to bypass HA wrapper", and `ha-pigsydust` commit `fa9fba6` "Use standalone BleakClient instead of HA's wrapper") the following chain of failures was hit:

1. **HA-wrapped `BleakClient.connect()`** — logs a warning and drops connections.
2. **`bleak_retry_connector.establish_connection(BleakClient, ble_device, ...)`** — connect succeeds but later writes fail with `BleakError: Service Discovery has not been performed yet`. Root cause: HA's `BleakClientWithServiceCache` returns a cached service collection that is empty-or-stale for Telink mesh devices, because our chip advertises different service sets than the cache was populated with.
3. **Forcing service discovery explicitly after connect** — helped on macOS/CoreBluetooth but failed on Linux/BlueZ, where HA monkey-patches `BleakClient` in a way that made the forced path impossible in the same shape.
4. **Final shipped solution:** skip HA's wrapper entirely, construct `BleakClient` directly (or `BleakClientBlueZDBus` on Linux) from an address string.

That "final solution" is what's in `__init__.py` and `config_flow.py` today and is what we need a core-acceptable alternative for.

### What we don't know yet

- Whether `establish_connection(..., cache_services=False, use_services_cache=False)` (and/or `disconnect_on_missing_services=True`) resolves the stale-cache pathology for Telink specifically. Earlier attempts predate consistent availability of those flags or didn't exercise them in combination.
- Whether the Linux/BlueZ monkey-patching still blocks forced discovery in current HA + bleak versions. Much has changed in `habluetooth` since commit `7281f57`.
- How other Telink-based core integrations solve this. Candidates to study: `led_ble`, `yalexs_ble`, `bthome`, `leaone_ble`, `xiaomi_ble`. At least one of these is known to interoperate with Telink chips under HA's wrapper.

### Phase A — Spike (1–2 days, before committing to any implementation path)

Small experimental PR in `pigsydust-py` on a branch. No release, no integration changes.

1. Add a second `connect()` code path that uses `establish_connection` with `cache_services=False` and `disconnect_on_missing_services=True`.
2. Run against one switch on both platforms:
   - macOS CoreBluetooth (laptop, easiest to iterate on).
   - Linux/BlueZ (NUC — production target).
3. For each platform, verify:
   - Initial connect + `login()` + `query_status()` + `turn_on/off()` succeed.
   - A disconnect/reconnect cycle (pull-and-replug adapter, or put laptop to sleep) recovers cleanly.
   - Service discovery doesn't regress on the second connection.
4. Read the source of one reference Telink integration (`led_ble` is the most self-contained) to confirm no flag we're missing.

**Success criterion for Phase A:** one clean `establish_connection`-based path that works on both platforms across a reconnect. Failure criterion: either platform breaks in a way that can't be resolved with public flags.

### Phase B — If Phase A succeeds

Then — and only then — does the implementation in the earlier draft of this stage apply:

- Library: `PixieClient.__init__` accepts `BLEDevice | str`; `connect()` uses `establish_connection` on the `BLEDevice` path and retains the legacy `BleakClient(address)` path for stand-alone CLI use.
- Library: declare `bleak-retry-connector` as a dependency; bump to `0.3.0`.
- Integration: resolve via `async_ble_device_from_address(hass, address, connectable=True)` in `__init__.py` and `config_flow.py`; pass the `BLEDevice` into `PixieClient`.
- Remove all "bypass HA's wrapper" code paths and comments.

Acceptance criteria (Phase B only):
- No `BleakClient(...)` or `PixieClient(address_str)` call sites remain in the integration.
- `grep -rE "bypass|standalone" custom_components/sal_pixie/` returns no results.
- Live end-to-end functionality on both macOS and Linux hosts, including a reconnect cycle.
- `manifest.json` requires `pigsydust>=0.3.0`.

### Phase C — If Phase A fails

Two options, pick one based on how the failure looks:

1. **Upstream fix, then wait.** File an issue on `home-assistant/core` (or `bluetooth-devices/bleak-retry-connector`, whichever is the right layer) with a minimal repro — ideally a tiny script that connects to a Telink device and demonstrates the stale-cache path. Submit a fix if the root cause is tractable. Park Stage 11 until it lands.

2. **Submit anyway, with documented workaround.** Open the core PR keeping the standalone-`BleakClient` transport, with a detailed comment in `__init__.py` linking to the upstream issue and the bleak-retry-connector commit history that shows why. This might be rejected by reviewers, but it's a legitimate basis for a conversation and may even force the upstream fix. Requires that we've already filed the upstream issue so we have something concrete to point at.

Under both options, Stage 7 tests continue in parallel — they mock the transport layer and don't depend on the real BLE path.

### Amendments to other stages under each outcome

- **Phase B outcome:** library bump becomes `0.3.0` and the manifest pin updates accordingly. Stage 2 library-side changes merge into the same release.
- **Phase C outcome:** library stays at `0.2.0`. Stage 9's `discovery` / `docs-data-update` rules still hold; none of the quality-scale declarations are gated on the transport choice, but a prominent `comment:` on the closest applicable rule (probably a custom `comment` block at the top of `quality_scale.yaml`) should point reviewers at the reasoning.

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

### Exception translations (satisfy `exception-translations` Gold rule now)

Raise with `translation_domain` + `translation_key` rather than interpolated strings, so Frontend can localize:

```python
raise HomeAssistantError(
    translation_domain=DOMAIN,
    translation_key="mesh_unreachable",
    translation_placeholders={"error": str(err)},
) from err
```

Add a matching `exceptions` block to `strings.json` (mirror to `translations/en.json`):

```json
"exceptions": {
  "mesh_unreachable": {
    "message": "Could not reach the SAL Pixie mesh: {error}"
  },
  "command_failed": {
    "message": "Command failed: {error}"
  }
}
```

Updating all three service handlers at once means Stage 9 can mark `exception-translations: done` instead of carrying it as a todo.

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

### Log-level audit (do this in the same stage)

The current code logs chattily at INFO — every login attempt, every discovery candidate, every reconnect. HA core is strict about log-level hygiene: INFO is for state transitions the user cares about; everything else is DEBUG. Sweep the whole integration and demote:

- `_LOGGER.info("Trying %s (%s, RSSI=%d)", ...)` in `config_flow.py` → DEBUG
- `_LOGGER.info("Connected to %s, attempting login", ...)` → DEBUG
- `_LOGGER.info("Login to %s successful", ...)` → DEBUG (the entry creation itself is the user-visible event)
- `_LOGGER.info("Found %d Pixie candidates: ...")` → DEBUG
- `_LOGGER.info("Selected Pixie device: %s ...")` in `__init__.py` → DEBUG
- `_LOGGER.info("Attempting reconnect after disconnect")` in `coordinator.py` → DEBUG
- `_LOGGER.info("Reconnected successfully")` → keep as INFO (user-relevant transition) — but emit only when coming back from a previously-logged failure
- `_LOGGER.info("New device discovered: address=%d")` → keep as INFO (user-relevant, rare)

Rule of thumb: if the line would fire more than a handful of times per day on a healthy mesh, it's DEBUG.

### Acceptance criteria

- Pulling the BLE adapter logs **one** `WARNING` line about the connection loss (not one per entity)
- Restoring the adapter logs **one** `INFO` line about recovery
- All entities go unavailable within one coordinator cycle of the disconnect
- Repeated connection/disconnection cycles don't flood logs
- At default (INFO) log level, a healthy 24h period produces only startup/shutdown/new-device/reconnect lines — no per-poll or per-command chatter

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
                # Byte[14] of the raw manuf-data blob. The Pixie app
                # calls this "majorType" but it's actually a packed
                # flag byte (bit 0 = online, bit 1 = alarmDev,
                # bits 2-7 = firmware version). See Stage 0 findings.
                "major_type_raw": getattr(status, "major_type", None),
                "major_type_decoded": _decode_major_type(
                    getattr(status, "major_type", None)
                ),
                # Bytes[15..16] of the raw blob (2-byte BE int). The
                # app calls this "minjorType" (sic). This is the device
                # class code; the resolved DeviceClass identifier lives
                # in `device_class` below.
                "minor_type": getattr(status, "minor_type", None),
                "device_class": (
                    status.device_class.name.lower()
                    if getattr(status, "device_class", None)
                    else None
                ),
                "raw_manufacturer_data": (
                    status.raw_manufacturer_data.hex()
                    if getattr(status, "raw_manufacturer_data", None)
                    else None
                ),
            }
            for addr, status in (coordinator.data or {}).items()
        },
    }


def _decode_major_type(value: int | None) -> dict | None:
    """Decompose the packed majorType byte per Stage 0 disassembly."""
    if value is None:
        return None
    return {
        "online": bool(value & 0x01),
        "alarm_dev": bool((value >> 1) & 0x01),
        "version": value >> 2,
    }
```

The diagnostics emit the lowercased enum identifier (`"switch"`, `"dimmer_g3"`, ...). Unknown classes (`device_class is None` because the BE16 isn't in the enum) come through as `null` alongside the raw `minor_type` value, which is what users would report when asking us to add a new entry to the enum.

**Library dependency:** `DeviceStatus` must expose `major_type` (byte[14], the packed flag byte), `minor_type` (bytes[15..16] as a 16-bit BE integer), `device_class` (a `DeviceClass` enum member resolved from `minor_type`, or `None` if unknown), and `raw_manufacturer_data` (the entire blob, kept for forensics on unknown classes).

### 6a-i. Device-class translation strings

The diagnostics surface emits enum identifiers; user-facing UI also needs them. Add a `device_class` block to `strings.json` (mirror to `translations/en.json`) with one entry per `DeviceClass` member — lowercased identifier as the key, the localised name as the value:

```json
"device_class": {
  "switch": "Wall Switch",
  "tswitch": "Touch Switch",
  "tswitchg2": "Touch Switch (Gen 2)",
  "dimmer": "Dimmer",
  "dimmer_g2": "Dimmer (Gen 2)",
  "dimmer_g3": "Dimmer (Gen 3)",
  "bridge": "Bridge",
  "strip_w": "White LED Strip",
  "strip_rgb": "RGB LED Strip",
  "strip2_rgbcct": "RGBCCT LED Strip (Gen 2)",
  "fan_only": "Fan",
  "fan_ct": "Fan with CCT Light",
  "gdc1": "Garage Door Controller",
  "rct_rgb": "RGB Remote Control",
  "zcl": "ZCL Controller"
  // ... mirror every DeviceClass member shipped in pigsydust-py 0.2.0
}
```

Light entities can pull a friendlier device-name suffix from this lookup once the device class is known — fall back to `"Pixie device {minor_type:#06x}"` when unknown. This is purely a presentation layer; the protocol-level identification stays in the library.

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

## Stage 7 — Test Suite

The single biggest stage. Enables Bronze (basic tests) and the Silver `config-flow-test-coverage` rule (≥95% of `config_flow.py`). We also aim for ≥95% coverage overall, which is the Gold `test-coverage` rule — framing it as Silver in earlier drafts conflated the two. Uses `pytest-homeassistant-custom-component` which mirrors the HA core test harness, so tests written here transplant cleanly into `tests/components/sal_pixie/` in Stage 11.

### Directory layout

```
tests/
├── __init__.py
├── conftest.py
├── test_config_flow.py
├── test_init.py
├── test_coordinator.py
├── test_diagnostics.py
├── test_light.py
├── test_select.py
├── test_number.py
├── test_button.py
├── test_sensor.py
└── snapshots/
    └── test_diagnostics.ambr
requirements-test.txt
.github/workflows/test.yml
```

### Test dependencies (`requirements-test.txt`)

```
pytest
pytest-asyncio
pytest-homeassistant-custom-component
syrupy
```

### Core fixtures (`tests/conftest.py`)

```python
"""Shared fixtures for SAL Pixie tests."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sal_pixie.const import CONF_MESH_PASSWORD, DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom_components loading for all tests."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A MockConfigEntry for the sal_pixie domain."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_MESH_PASSWORD: "1234"},
        unique_id=DOMAIN,
        title="SAL Pixie",
    )


@pytest.fixture
def mock_device_statuses():
    """Two switches: one on, one off."""
    from pigsydust import DeviceStatus
    # `major_type` / `minor_type` / `raw_manufacturer_data` are added in Stage 2
    # with defaults on the library side, so this construction stays valid either way.
    return {
        1: DeviceStatus(address=1, is_on=True, mac="AA:BB:CC:DD:EE:01"),
        2: DeviceStatus(address=2, is_on=False, mac="AA:BB:CC:DD:EE:02"),
    }


@pytest.fixture
def mock_pixie_client(mock_device_statuses) -> Generator[MagicMock, None, None]:
    """Patch PixieClient everywhere it's imported in the integration."""
    with patch(
        "custom_components.sal_pixie.PixieClient", autospec=True,
    ) as client_cls, patch(
        "custom_components.sal_pixie.config_flow.PixieClient", new=client_cls,
    ):
        instance = client_cls.return_value
        instance.connect = AsyncMock()
        instance.disconnect = AsyncMock()
        instance.login = AsyncMock()
        instance.query_status = AsyncMock(return_value=mock_device_statuses)
        instance.turn_on = AsyncMock()
        instance.turn_off = AsyncMock()
        instance.firmware_version = "1.0"
        instance.hardware_version = "1.0"
        instance.is_connected = True
        instance.address = "AA:BB:CC:DD:EE:01"
        instance.on_status_update = MagicMock(return_value=lambda: None)
        instance.set_disconnect_callback = MagicMock()
        yield instance


@pytest.fixture
def mock_bluetooth_discovery():
    """Simulate HA's Bluetooth discovery finding a Pixie device."""
    mock_info = MagicMock()
    mock_info.address = "AA:BB:CC:DD:EE:01"
    mock_info.name = "Pixie Switch"
    mock_info.rssi = -50
    mock_info.manufacturer_data = {0x0211: bytes(16)}

    with patch(
        "custom_components.sal_pixie.async_discovered_service_info",
        return_value=[mock_info],
    ), patch(
        "custom_components.sal_pixie.config_flow.async_discovered_service_info",
        return_value=[mock_info],
    ):
        yield mock_info


@pytest.fixture
async def init_integration(
    hass, mock_config_entry, mock_pixie_client, mock_bluetooth_discovery,
):
    """A fully loaded integration ready for platform tests."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
```

### Config flow tests (`tests/test_config_flow.py`)

Coverage target: 100% of `config_flow.py`.

Minimum cases:

- `test_user_flow_happy_path` — user enters correct key, entry created with correct data
- `test_user_flow_invalid_auth` — wrong key, form re-shows with `invalid_auth` error
- `test_user_flow_cannot_connect` — no devices discovered, form shows `cannot_connect`
- `test_user_flow_already_configured` — second attempt aborts with `already_configured`
- `test_bluetooth_discovery_confirm` — discovery triggers confirm step, user completes
- `test_bluetooth_discovery_already_configured` — discovery aborts if already configured
- `test_reauth_flow_happy_path` — triggered by `ConfigEntryAuthFailed`, completes successfully, reloads entry
- `test_reauth_flow_invalid_auth` — wrong key during reauth, form re-shows
- `test_reconfigure_flow_happy_path` — user changes key, entry data updated, reload happens
- `test_reconfigure_flow_invalid_auth` — wrong key, form re-shows

Example:

```python
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

async def test_user_flow_happy_path(hass, mock_pixie_client, mock_bluetooth_discovery):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MESH_PASSWORD: "1234"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MESH_PASSWORD: "1234"}
    assert mock_pixie_client.login.await_count == 1
```

### Init tests (`tests/test_init.py`)

- `test_setup_and_unload` — full lifecycle, verify `runtime_data` populated then cleaned up
- `test_setup_no_device_found` — `ConfigEntryNotReady` raised when no discovery hits
- `test_setup_login_failure` — `ConfigEntryNotReady` raised on bad credentials during initial setup
- `test_coordinator_auth_failure_triggers_reauth` — coordinator raises `ConfigEntryAuthFailed`, reauth flow starts
- `test_services_registered` — the three domain services are callable after setup
- `test_service_raises_home_assistant_error_on_connection_failure` — service failures surface as `HomeAssistantError`

### Coordinator tests (`tests/test_coordinator.py`)

- `test_push_update_merges_into_data` — push callback updates `coordinator.data`
- `test_poll_fallback_when_push_stale` — force stale timestamp, verify poll runs
- `test_poll_skipped_when_push_fresh` — fresh push, poll is a no-op
- `test_command_grace_period_suppresses_overwrite` — recent command, poll returns stale data but coordinator keeps commanded state
- `test_reconnect_after_disconnect` — disconnect callback fires, next update attempts reconnect
- `test_stale_device_pruned_from_registry` — device absent beyond threshold is removed
- `test_new_device_fires_dispatcher_signal` — new mesh address triggers `SIGNAL_NEW_DEVICE`

### Platform tests (one file each)

Each file verifies: entities are created, state reflects coordinator data, commands reach the mocked client, availability tracks coordinator state.

Example for `tests/test_light.py`:

```python
async def test_light_turn_on(hass, init_integration, mock_pixie_client):
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.pixie_switch_1"}, blocking=True,
    )
    mock_pixie_client.turn_on.assert_awaited_once_with(1)

async def test_light_reflects_coordinator_data(hass, init_integration):
    state = hass.states.get("light.pixie_switch_1")
    assert state is not None
    assert state.state == "on"

async def test_light_unavailable_when_absent(hass, init_integration):
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    entry.runtime_data.coordinator.async_set_updated_data({})
    await hass.async_block_till_done()
    state = hass.states.get("light.pixie_switch_1")
    assert state.state == "unavailable"
```

### Diagnostics tests (`tests/test_diagnostics.py`)

Uses `syrupy` for snapshot comparison:

```python
from syrupy import SnapshotAssertion
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

async def test_diagnostics(
    hass, hass_client, init_integration, snapshot: SnapshotAssertion,
):
    result = await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration,
    )
    assert result == snapshot
```

First run records the snapshot; subsequent runs verify stability. The snapshot must show the mesh password redacted.

### CI workflow (`.github/workflows/test.yml`)

```yaml
name: Tests
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -r requirements-test.txt
      - run: pytest --cov=custom_components.sal_pixie --cov-report=xml
      - uses: codecov/codecov-action@v4
```

### Acceptance criteria

- `pytest` passes locally and in CI on Python 3.12 and 3.13
- Coverage of `custom_components/sal_pixie/` ≥ 95% (Silver requirement)
- Every branch of every `config_flow.py` function is exercised
- No test talks to real BLE hardware — all I/O is mocked

## Stage 8 — Documentation

The custom-component README already covers installation. For core inclusion, the content needs restructuring into the sections HA core docs expect. These will be ported into markdown under `home-assistant.io/source/_integrations/sal_pixie.markdown` when Stage 11 lands — but drafting them in the README now means less rewriting later and satisfies the Gold `docs-*` rules in the quality scale.

### Target section structure

Required sections, in order:

1. **Short description** (top paragraph, single sentence)
2. **Supported devices** — explicit list of models confirmed working. Currently just "SAL Pixie wall switches". Include a clear "not yet supported" subsection naming RGB strips, dimmers, power points.
3. **Prerequisites** — BLE adapter, HA Bluetooth integration enabled, the mesh already configured via the vendor's PIXIE app (the integration doesn't do initial device pairing — it joins an existing mesh)
4. **Installation** — HACS + manual steps
5. **Configuration** — where to find the home key in the Pixie app (Home Management → Share Home → KEY)
6. **Data updates** — short paragraph explaining the push-primary, poll-fallback model
7. **Supported functionality** — the entities and services provided
8. **Known limitations** — no OTA updates, no device pairing, only wall switches verified (device-class table in bytes[15..16] not yet extracted), single-config-entry (one mesh per HA)
9. **Troubleshooting** — common issues: BLE adapter permissions in Docker, invalid home key, entities unavailable
10. **Removing the integration** — standard HA flow, no special cleanup
11. **Unofficial / unaffiliated disclaimer** — keep at top where it already is

### Acceptance criteria

- Every section listed above exists in the README
- The "Supported devices" section matches the device-type routing in code (no lies)
- A fresh user can follow the README end-to-end without needing to read source code

## Stage 9 — Quality Scale Declaration

**File:** `custom_components/sal_pixie/quality_scale.yaml`

Declares per-rule status against the Integration Quality Scale. Target tier at submission: **Silver** (with most Gold rules already satisfied to ease the follow-up promotion).

### Structure

```yaml
rules:
  # Bronze
  action-setup: done
  appropriate-polling: done
  brands:
    status: todo
    comment: Pending submission to home-assistant/brands (Stage 10)
  common-modules: done
  config-flow: done
  config-flow-test-coverage: done
  dependency-transparency: done
  docs-actions: done
  docs-high-level-description: done
  docs-installation: done
  docs-installation-parameters: done
  entity-event-setup: done
  entity-unique-id: done
  has-entity-name: done
  runtime-data: done
  test-before-configure: done
  unique-config-entry: done

  # Silver
  action-exceptions: done
  config-entry-unloading: done
  docs-configuration-parameters: done
  docs-installation-parameters: done
  entity-unavailable: done
  integration-owner: done
  log-when-unavailable: done
  parallel-updates: done
  reauthentication-flow: done
  test-coverage: done

  # Gold
  devices: done
  diagnostics: done
  discovery: done
  discovery-update-info:
    status: exempt
    comment: unique_id is the domain string (single_config_entry), not a per-device identifier; there is nothing to update on rediscovery.
  docs-data-update: done
  docs-examples: done
  docs-known-limitations: done
  docs-supported-devices: done
  docs-supported-functions: done
  docs-troubleshooting: done
  docs-use-cases: done
  dynamic-devices: done
  entity-category: done
  entity-device-class:
    status: exempt
    comment: Lights and buttons don't have applicable device classes; sensors use appropriate classes.
  entity-disabled-by-default:
    status: exempt
    comment: All exposed entities are useful by default.
  entity-translations: done
  exception-translations: done  # implemented in Stage 3
  icon-translations: done
  reconfiguration-flow: done
  repair-issues: done
  stale-devices: done

  # Platinum
  async-dependency: done
  inject-websession:
    status: exempt
    comment: Integration uses local BLE, not HTTP.
  strict-typing: done  # gated on Stage 2 (pigsydust py.typed + mypy --strict)
```

### Acceptance criteria

- Every rule in the Bronze + Silver sets has status `done`
- Any `exempt` rule has a plain-English justification
- File is valid YAML (`python -c 'import yaml; yaml.safe_load(open("quality_scale.yaml"))'`)
- `python -m script.hassfest --integration-path <abs path to custom_components/sal_pixie>` (run from a local `home-assistant/core` checkout) exits cleanly. This catches ~90% of Stage 11 surprises — missing translation keys, manifest errors, config-flow registration issues — before forking core.

## Stage 10 — Brands Repo Submission

A separate PR to `home-assistant/brands`. Must merge **before** the core integration PR.

### Assets needed

- `core_integrations/sal_pixie/icon.png` — 256×256, square, transparent background
- `core_integrations/sal_pixie/icon@2x.png` — 512×512 retina variant
- `core_integrations/sal_pixie/logo.png` — wide format, transparent background
- `core_integrations/sal_pixie/logo@2x.png` — retina variant
- Dark-mode variants under `core_integrations/sal_pixie/dark/` if the light-mode assets don't render well on dark backgrounds

Use SAL's official Pixie product branding. The brands repo README specifies exact pixel dimensions and transparency requirements.

### PR content

- Title: `Add SAL Pixie brand`
- Description: brief note that this is for a new community integration targeting HA core, linking to the integration PR (to be filed after this one merges)

### Acceptance criteria

- PR merged into `home-assistant/brands`
- Assets visible at `https://brands.home-assistant.io/sal_pixie/icon.png` etc.

## Stage 11 — Core PR Preparation

Final stage. Work happens in a fork of `home-assistant/core`, not in this repo.

### Mechanical steps

1. **Fork + clone** `home-assistant/core`; create branch `sal_pixie-integration`.
2. **Copy integration** from `custom_components/sal_pixie/` to `homeassistant/components/sal_pixie/`.
3. **Copy tests** from `tests/` to `tests/components/sal_pixie/`.
4. **Adjust imports** in test files: `custom_components.sal_pixie` → `homeassistant.components.sal_pixie`.
5. **Manifest cleanup for core** — adjust three fields:
   - Remove `version` (core integrations don't include it; only custom components do).
   - Remove `issue_tracker` (core uses `home-assistant/core/issues` implicitly).
   - Change `documentation` to `https://www.home-assistant.io/integrations/sal_pixie`.
6. **Add to `homeassistant/generated/bluetooth.py`** — run `python -m script.hassfest` to regenerate from the manifest's `bluetooth` entries.
7. **Add dependency** to `requirements_all.txt` and `requirements_test_all.txt` — both files are auto-generated by `python -m script.gen_requirements_all`.
8. **Strict typing** — add `homeassistant.components.sal_pixie.*` to `.strict-typing` if Platinum tier is targeted.
9. **Run hassfest** — `python -m script.hassfest` validates manifest, config flow, translations, etc.
10. **Run tests** — `pytest tests/components/sal_pixie/ --cov=homeassistant.components.sal_pixie`.

### PR content

- Title: `Add SAL Pixie integration`
- Description checklist per HA's PR template
- Link to the merged brands PR
- Link to the `pigsydust` PyPI release
- Declare target quality scale tier

### Acceptance criteria

- `python -m script.hassfest` passes with zero errors
- All tests pass, coverage ≥ 95%
- `mypy --strict homeassistant/components/sal_pixie/` passes (if Platinum pursued)
- PR accepted by at least one HA core maintainer review

---

## Execution order

```
0 (user investigation, non-blocking)
  → 1 → 2 → 2b.PhaseA (spike)
                ├─ success → 2b.PhaseB → 3 → 4 → 5 → 6 (a/b/c/d parallel) → 7 → 8 → 9 → 10 → 11
                └─ failure → 2b.PhaseC (upstream issue / documented workaround)
                               → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 (11 may stall)
```

Stages 3–10 are independent of the Phase A outcome. Only Stage 11 (core submission) is gated on having a transport story reviewers will accept.

### Recommended first milestone

Stages 1 + 2 + 3 + 4 + 7a-7c. That produces a rebranded, modernized, tested integration still shipping as a custom component — a safe v0.2.0 checkpoint before committing to the core submission path.

## Known open questions

- **`majorType` semantics** — resolved (Stage 0 follow-up). Byte[14] is a packed `online | alarmDev | version` flag byte, not a device-class code. `0x47` vs `0x45` almost certainly reflects the `alarmDev` bit toggling based on whether the device currently participates in an alarm group/scene.
- **`(type, stype)` → device-class table** — still open. The class code lives in bytes[15..16] (the app's `minjorType`) and the mapping table is embedded in the Pixie app's Dart AOT binary. Extracting it cleanly requires Dart-AOT-specific tooling. Until then, the integration only supports what it has been empirically verified against (wall switches).
- **Slave switches** — PIXIE app treats all switches identically, so HA does too. No architectural branching needed. The term "slave" does not appear in any user-facing surface.
