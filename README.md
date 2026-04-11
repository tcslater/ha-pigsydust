# Pixie Mesh for Home Assistant

Home Assistant integration for SAL Pixie BLE mesh wall switches.

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Pixie Mesh" and install
3. Restart Home Assistant

### Manual

Copy `custom_components/piggsydust/` to your Home Assistant `config/custom_components/` directory.

## Setup

The integration will auto-discover Pixie mesh gateways via Bluetooth. You can also add one manually via **Settings > Devices & Services > Add Integration > Pixie Mesh**.

You will need:
- **Home key** — found in the Pixie app under Home Management > Share Home (shown as "KEY")

## HomeKit

To expose your Pixie switches to Apple HomeKit, enable the [HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/) integration in Home Assistant. Your switches will appear as standard HomeKit switches.
