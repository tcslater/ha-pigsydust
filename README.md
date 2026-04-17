<p align="center">
  <img src="splash.png" alt="SAL Pixie" width="400">
</p>

Home Assistant custom integration for [SAL Pixie](https://pixieplus.com.au/) BLE mesh wall switches — fully local, no cloud.

> **Unofficial.** This is a community-developed integration based on reverse engineering of the Pixie protocol. It is not affiliated with, endorsed by, or supported by SAL. "Pixie" and "SAL" are used here solely to identify the hardware this integration is compatible with.

## Requirements

- **Bluetooth LE adapter** on the machine running Home Assistant (built-in or USB). The HA [Bluetooth](https://www.home-assistant.io/integrations/bluetooth/) integration must be enabled.
- **Docker**: if running HA in a container, it must have access to the Bluetooth adapter. Use `--privileged` and `--network=host`, and mount the D-Bus socket:
  ```bash
  docker run -d --name homeassistant --privileged --network=host \
    -v /path/to/config:/config \
    -v /run/dbus:/run/dbus:ro \
    --restart unless-stopped \
    ghcr.io/home-assistant/home-assistant:stable
  ```

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Search for "SAL Pixie" and install
3. Restart Home Assistant

### Manual

Copy `custom_components/sal_pixie/` to your Home Assistant `config/custom_components/` directory and restart.

## Finding your mesh password

The integration needs your mesh password (called "Home Key" in the Pixie app) to authenticate with the switches.

1. Open the **Pixie** app on your phone
2. Go to **Home Management** (tap the gear icon)
3. Tap **Share Home**
4. The password is the numeric code shown as **"KEY"**

<!-- TODO: add screenshot of Pixie app Share Home screen -->

## Setup

The integration will auto-discover Pixie mesh devices via Bluetooth. You can also add manually via **Settings > Devices & Services > Add Integration > SAL Pixie**.

Enter your mesh password when prompted. The integration will connect to the strongest available switch on the mesh and discover all other switches from there.

## What you get

- **Light entities** — on/off control for each switch on the mesh
- **Sensor entities** — mesh signal strength and currently-connected device
- **LED indicator controls** — set the indicator LED mode (off/blue/orange/purple) and brightness per switch
- **Identify button** — flash a switch's LED for 15 seconds to find it
- **All on / All off buttons** — mesh-wide control
- **Real-time status** — push notifications from the mesh, no polling delay

## Supported devices

Currently supports **Pixie wall switches** only. Support for RGB lights, power points, and smart plugs may be added in the future once hardware is available for testing. The underlying mesh protocol is believed to be the same across the product line; contributions welcome.

## HomeKit

To expose your Pixie switches to Apple HomeKit, enable the [HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/) integration in Home Assistant. Your switches will appear as standard HomeKit lights.

## Protocol

See the [protocol reference](https://github.com/tcslater/pigsydust-py/blob/main/docs/PROTOCOL-REFERENCE.md) for details of the reverse-engineered Telink mesh BLE protocol. The underlying Python library is published as [`pigsydust`](https://pypi.org/project/pigsydust/) on PyPI.

## Upgrading from pre-0.2 versions

Version 0.2 renames the integration from `pigsydust` to `sal_pixie` in preparation for potential submission to the Home Assistant core repository. This is a breaking change:

1. **Before upgrading:** remove the existing PigsyDust integration from **Settings > Devices & Services**
2. Update the integration (HACS or manual copy)
3. Restart Home Assistant
4. **Re-add** the integration under its new name (SAL Pixie)
5. Update any automations that referenced `pigsydust.*` services to use `sal_pixie.*`
