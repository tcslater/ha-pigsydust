<p align="center">
  <img src="splash.png" alt="SAL Pixie" width="400">
</p>

Home Assistant custom integration for [SAL Pixie](https://pixieplus.com.au/) BLE mesh wall switches — fully local, no cloud.

> **Unofficial.** This is a community-developed integration based on reverse engineering of the Pixie protocol. It is not affiliated with, endorsed by, or supported by SAL. "Pixie" and "SAL" are used here solely to identify the hardware this integration is compatible with.

## Supported devices

**Verified working:**

- **Pixie wall switches** — tested with the standard in-wall switch. Exposed in Home Assistant as a `light` entity (on/off).

**Not yet supported:**

The Pixie mesh protocol covers a wider range of hardware, and the integration decodes the device-class identifier broadcast by every device, but no entity types have been wired up yet beyond the switch. The following have been identified in the protocol but are untested and will not produce useful entities today:

- Pixie dimmers (`DIMMER`, `DIMMER_G2`, `DIMMER_G3`)
- Pixie RGB / RGBCCT / CCT LED strips (`STRIP_RGB`, `STRIP2_RGBCCT`, `STRIP2_CCT`, `STRIP_W`, …)
- Power points and smart plugs
- Garage door controllers, fans, and the remaining ~50 device classes in the SAL range

If you own one of the above and want to help get it working, open an issue — the integration already reports the device class in diagnostics, which is the first step.

## Prerequisites

- **Bluetooth LE adapter** on the machine running Home Assistant (built-in or USB). The HA [Bluetooth](https://www.home-assistant.io/integrations/bluetooth/) integration must be enabled.
- **Mesh already configured via the vendor's Pixie app.** This integration joins an existing mesh; it does not perform initial device commissioning. Pair and name your switches in the Pixie app first, then hand the mesh off to Home Assistant.
- **Docker:** if running HA in a container, it must have access to the Bluetooth adapter. Use `--privileged` and `--network=host`, and mount the D-Bus socket:
  ```bash
  docker run -d --name homeassistant --privileged --network=host \
    -v /path/to/config:/config \
    -v /run/dbus:/run/dbus:ro \
    --restart unless-stopped \
    ghcr.io/home-assistant/home-assistant:stable
  ```

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS.
2. Search for "SAL Pixie" and install.
3. Restart Home Assistant.

### Manual

Copy `custom_components/sal_pixie/` to your Home Assistant `config/custom_components/` directory and restart.

## Configuration

### Finding your mesh password

The integration needs your mesh password — the **Home Key** — to authenticate with the switches.

1. Open the **Pixie** app on your phone.
2. Tap the gear icon to open **Home Management**.
3. Tap **Share Home**.
4. The password is the numeric code shown as **"KEY"**.

<!-- TODO: add screenshot of Pixie app Share Home screen -->

### Adding the integration

The integration auto-discovers Pixie mesh devices via Bluetooth, so a "SAL Pixie discovered" card typically appears in **Settings → Devices & Services** within a minute of restarting Home Assistant. Alternatively add it manually via **Settings → Devices & Services → Add Integration → SAL Pixie**.

Enter your mesh password when prompted. The integration connects to the strongest-signal switch currently advertising and discovers all other switches from there. Only one mesh per Home Assistant instance is supported.

## Data updates

The integration is **push-primary**: every switch broadcasts state changes over the mesh as soon as they happen, and Home Assistant reflects them without polling delay. A periodic poll (5 minutes) acts as a fallback — it fires only if no push update has arrived in the last two minutes, so under normal operation the radio stays quiet.

If the BLE link drops, the coordinator immediately marks all Pixie entities as unavailable and begins reconnecting. After roughly 25 minutes of sustained outage (five consecutive failed polls) a repair issue appears in **Settings → Repairs** prompting a manual reload.

## Supported functionality

### Entities

- **`light.pixie_switch_*`** — on/off control for each switch on the mesh.
- **`sensor.pixie_mesh_connected_device`** — the mesh-connected device Home Assistant is currently talking to.
- **`sensor.pixie_switch_*_mesh_signal`** — routing metric (mesh signal strength) per switch.
- **`number.pixie_mesh_indicator_brightness`** + per-switch equivalents — indicator LED brightness (0–15).
- **`select.pixie_mesh_indicators`** + per-switch equivalents — indicator LED mode (`Off` / `Blue` / `Orange` / `Purple`).
- **`button.pixie_mesh_all_on`** / **`button.pixie_mesh_all_off`** — mesh-wide control.
- **`button.pixie_switch_*_identify`** — flash a switch's LED for 15 seconds to locate it.

### Services

- `sal_pixie.all_on` / `sal_pixie.all_off` — mesh-wide power control.
- `sal_pixie.set_indicator` — set indicator LED mode + brightness on one device or the whole mesh.

### HomeKit

To expose your Pixie switches to Apple HomeKit, enable the [HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/) integration. Your switches appear as standard HomeKit lights.

## Known limitations

- **Wall switches only.** Other Pixie device classes (dimmers, RGB strips, power points) are recognised by the integration but no matching entity types have been implemented yet — see *Supported devices*.
- **No device commissioning.** The integration joins an existing mesh configured via the vendor's Pixie app; it cannot pair new switches or rename them. Use the Pixie app for that.
- **No firmware updates.** The mesh supports OTA via the vendor's app; this integration does not.
- **One mesh per Home Assistant instance.** The integration declares `single_config_entry`, so you can't run two meshes side-by-side through one HA.
- **Bluetooth only.** If your HA host has no BLE adapter (or the adapter is in use by another tool), the integration can't connect.

## Troubleshooting

### Entities show as "unavailable"

Usually means the BLE link dropped. Check **Settings → Repairs**: if a `mesh_unreachable` issue is showing, the coordinator has been unable to reach the mesh for ~25 minutes. Pressing **Submit** on the repair forces a reconnect. If it keeps coming back, see the Bluetooth checks below.

### "Invalid home key" during setup

Reopen the Pixie app and re-check the KEY field under **Home Management → Share Home**. The key is numeric only, no spaces. Entering a new key via the integration's reauth flow updates the stored credential without a full re-install.

### No discovery card appears

Confirm the [Bluetooth](https://www.home-assistant.io/integrations/bluetooth/) integration is enabled and at least one adapter is listed. On Linux / Docker, check that HA can see the adapter:

```yaml
# Developer Tools → States → bluetooth.adapter_*
```

If you run HA in Docker without `--privileged` and a shared D-Bus socket (see *Prerequisites*), discovery will fail silently.

### Newly added switches don't appear

The integration only knows about switches it has seen report state. New devices usually surface within the 5-minute poll cycle. If not, reload the integration from **Settings → Devices & Services** to trigger an immediate poll.

### Diagnostics

For bug reports, download a diagnostics dump: **Settings → Devices & Services → SAL Pixie → ⋯ → Download diagnostics**. The dump redacts the mesh password and includes per-device state, the gateway advertisement, and the decoded device class — paste it into the issue.

## Removing the integration

Standard Home Assistant flow — **Settings → Devices & Services → SAL Pixie → ⋯ → Delete**. No manual cleanup is required; the integration does not touch files outside `config/.storage` and will forget the mesh password and device registry on deletion.

## Protocol

See the [protocol reference](https://github.com/tcslater/pigsydust-py/blob/main/docs/PROTOCOL-REFERENCE.md) for details of the reverse-engineered Telink mesh BLE protocol. The underlying Python library is published as [`pigsydust`](https://pypi.org/project/pigsydust/) on PyPI.

## Upgrading from pre-0.2 versions

Version 0.2 renames the integration from `pigsydust` to `sal_pixie` in preparation for potential submission to the Home Assistant core repository. This is a breaking change:

1. **Before upgrading:** remove the existing PigsyDust integration from **Settings → Devices & Services**.
2. Update the integration (HACS or manual copy).
3. Restart Home Assistant.
4. **Re-add** the integration under its new name (SAL Pixie).
5. Update any automations that referenced `pigsydust.*` services to use `sal_pixie.*`.
