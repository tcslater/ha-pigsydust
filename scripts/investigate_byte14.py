"""Observe byte[14] of Pixie BLE advertisements over time.

Stage 0 diagnostic: determines whether byte[14] of the manufacturer data
advertisement is stable per device (hardware/firmware identifier) or changes
over time (mesh state indicator).

Usage:
    pip install bleak
    python scripts/investigate_byte14.py [--duration SECONDS]

Stop HA (or at least the sal_pixie integration) before running so the scanner
has free access to the BLE adapter.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime

from bleak import BleakScanner

PIXIE_MANUFACTURER_ID = 0x0211


async def observe(duration: int) -> None:
    observations: dict[str, list[tuple[str, int]]] = defaultdict(list)

    def callback(device, advertisement_data) -> None:
        mfr_data = advertisement_data.manufacturer_data.get(PIXIE_MANUFACTURER_ID)
        if not mfr_data or len(mfr_data) < 15:
            return
        byte14 = mfr_data[14]
        timestamp = datetime.now().strftime("%H:%M:%S")
        observations[device.address].append((timestamp, byte14))
        print(
            f"{timestamp}  {device.address}  "
            f"byte[14]=0x{byte14:02x}  RSSI={advertisement_data.rssi}"
        )

    print(f"Scanning for {duration}s. Press Ctrl+C to stop early.")
    print(f"Watching manufacturer ID 0x{PIXIE_MANUFACTURER_ID:04x}\n")

    scanner = BleakScanner(detection_callback=callback)
    await scanner.start()
    try:
        await asyncio.sleep(duration)
    except KeyboardInterrupt:
        pass
    finally:
        await scanner.stop()

    print("\n=== Summary ===")
    if not observations:
        print("No Pixie advertisements captured. Is BLE working?")
        return

    for address in sorted(observations):
        entries = observations[address]
        values = {byte14 for _, byte14 in entries}
        stability = "STABLE" if len(values) == 1 else "CHANGING"
        values_str = ", ".join(f"0x{v:02x}" for v in sorted(values))
        print(
            f"{address}: {stability}  "
            f"({len(entries)} adverts, values seen: {values_str})"
        )

    all_stable = all(
        len({byte14 for _, byte14 in entries}) == 1
        for entries in observations.values()
    )
    print()
    if all_stable:
        print("Conclusion: byte[14] appears STABLE per device.")
        print("Likely meaning: hardware/firmware identifier or capability flag.")
    else:
        print("Conclusion: byte[14] CHANGES over time for at least one device.")
        print("Likely meaning: mesh state (active advertiser, wake, or relay role).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="Scan duration in seconds (default: 300)",
    )
    args = parser.parse_args()
    asyncio.run(observe(args.duration))


if __name__ == "__main__":
    main()
