# SAL Pixie for Home Assistant

Home Assistant integration for SAL Pixie BLE mesh wall switches.

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Search for "SAL Pixie" and install
3. Restart Home Assistant

### Manual

Copy `custom_components/piggsydust/` to your Home Assistant `config/custom_components/` directory.

## Setup

The integration will auto-discover SAL Pixie gateways via Bluetooth. You can also add one manually via **Settings > Devices & Services > Add Integration > SAL Pixie**.

You will need:
- **Mesh name** — the name of your Pixie mesh network
- **Mesh password** — the mesh password
- **Gateway BLE address** — the Bluetooth address of your gateway (manual setup only)

## HomeKit

To expose your Pixie switches to Apple HomeKit, enable the [HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/) integration in Home Assistant. Your switches will appear as standard HomeKit switches.
