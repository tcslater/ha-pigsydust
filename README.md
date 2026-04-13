# Pixie Mesh for Home Assistant

Home Assistant custom integration for [SAL Pixie](https://pixieplus.com.au/) BLE mesh wall switches — fully local, no cloud.

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
2. Search for "Pixie Mesh" and install
3. Restart Home Assistant

### Manual

Copy `custom_components/pigsydust/` to your Home Assistant `config/custom_components/` directory and restart.

## Finding your mesh password

The integration needs your mesh password (called "Home Key" in the Pixie app) to authenticate with the switches.

1. Open the **Pixie** app on your phone
2. Go to **Home Management** (tap the gear icon)
3. Tap **Share Home**
4. The password is the numeric code shown as **"KEY"**

<!-- TODO: add screenshot of Pixie app Share Home screen -->

## Setup

The integration will auto-discover Pixie mesh devices via Bluetooth. You can also add manually via **Settings > Devices & Services > Add Integration > Pixie Mesh**.

Enter your mesh password when prompted. The integration will connect to the strongest available gateway device and discover all switches on the mesh.

## What you get

- **Light entities** — on/off control for each switch on the mesh
- **Sensor entities** — mesh signal strength and current gateway
- **LED indicator controls** — set the indicator LED mode (off/blue/orange/purple) and brightness per switch
- **Identify button** — flash a switch's LED for 15 seconds to find it
- **All on / All off buttons** — mesh-wide control
- **Real-time status** — push notifications from the mesh, no polling delay

## Supported devices

Currently supports **Pixie wall switches** only. Support for RGB lights, power points, and smart plugs may be added in the future once I have access to those devices.

## HomeKit

To expose your Pixie switches to Apple HomeKit, enable the [HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/) integration in Home Assistant. Your switches will appear as standard HomeKit lights.

## Protocol

See the [protocol reference](https://github.com/tcslater/pigsydust-py/blob/main/docs/PROTOCOL-REFERENCE.md) for details of the reverse-engineered Telink mesh BLE protocol.
