"""Phase A probe: does bleak-retry-connector's establish_connection work with Telink?

Run inside the HA Docker container (or any env with bleak, bleak-retry-connector,
and pigsydust installed). The script exercises several combinations of
client class + flags, reports which support the full Pixie workflow, and
then runs a reconnect cycle on any combo that passed the first pass.

Usage:

    docker exec -it homeassistant python3 /config/phase_a_ble_probe.py <HOME_KEY>

Or directly on the host, after ``scp``-ing this file into the container.

Exit code 0 if at least one combo completes the full workflow twice in
a row (initial + reconnect). Exit code 1 otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import sys
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)
from pigsydust import PixieClient
from pigsydust.const import MANUFACTURER_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
)
_LOGGER = logging.getLogger("phase_a")

# Quiet bleak's spammy per-characteristic discovery DEBUG if enabled.
logging.getLogger("bleak").setLevel(logging.INFO)
logging.getLogger("bleak_retry_connector").setLevel(logging.INFO)

MESH_NAME = "Smart Light"
SCAN_TIMEOUT = 10.0
RECONNECT_PAUSE = 8.0
SCAN_RETRIES = 3


@dataclass
class ComboResult:
    name: str
    initial_connect: bool = False
    initial_login: bool = False
    initial_query: bool = False
    initial_toggle: bool = False
    reconnect: bool = False
    reconnect_login: bool = False
    reconnect_query: bool = False
    error: str | None = None

    @property
    def first_pass(self) -> bool:
        return all((self.initial_connect, self.initial_login,
                    self.initial_query, self.initial_toggle))

    @property
    def full_pass(self) -> bool:
        return self.first_pass and self.reconnect and self.reconnect_login and self.reconnect_query


def _extract_mac_from_manufacturer_data(mfr_data: dict[int, bytes]) -> bytes | None:
    data = mfr_data.get(MANUFACTURER_ID)
    if data is None or len(data) < 6:
        return None
    mac = bytearray(6)
    mac[5] = data[2]
    mac[4] = data[3]
    mac[3] = data[4]
    mac[2] = data[5]
    return bytes(mac)


def _mac_from_linux_address(address: str) -> bytes | None:
    """On Linux, the BLE address string IS the MAC."""
    try:
        parts = address.split(":")
        if len(parts) == 6:
            return bytes(int(p, 16) for p in parts)
    except ValueError:
        return None
    return None


async def _find_pixie() -> tuple[BLEDevice, dict[int, bytes]]:
    """Scan once with retries; return the best candidate found."""
    last_err: Exception | None = None
    for attempt in range(1, SCAN_RETRIES + 1):
        _LOGGER.info("Scanning for Pixie devices (attempt %d/%d, timeout=%.0fs)...",
                     attempt, SCAN_RETRIES, SCAN_TIMEOUT)
        try:
            devices = await BleakScanner.discover(timeout=SCAN_TIMEOUT, return_adv=True)
        except Exception as err:
            last_err = err
            _LOGGER.warning("  scan failed: %s", err)
            await asyncio.sleep(3.0)
            continue

        best: tuple[BLEDevice, int, dict[int, bytes]] | None = None
        for d, adv in devices.values():
            mfr_data = dict(adv.manufacturer_data or {})
            if MANUFACTURER_ID not in mfr_data:
                continue
            _LOGGER.info("  candidate %s (%s) RSSI=%d", d.address, d.name, adv.rssi)
            if best is None or adv.rssi > best[1]:
                best = (d, adv.rssi, mfr_data)

        if best is not None:
            device, rssi, mfr_data = best
            _LOGGER.info("Picked %s (%s) RSSI=%d", device.address, device.name, rssi)
            return device, mfr_data

        _LOGGER.warning("  scan returned 0 Pixie devices; retrying after pause")
        await asyncio.sleep(5.0)

    raise RuntimeError(
        f"No Pixie device found in BLE advertisements after {SCAN_RETRIES} attempts"
        + (f" (last error: {last_err})" if last_err else "")
    )


async def _run_workflow(
    combo: ComboResult,
    password: str,
    client_class: type,
    connect_kwargs: dict,
    is_reconnect: bool,
) -> None:
    """One full workflow pass. Mutates ``combo`` with results."""
    device, mfr_data = await _find_pixie()

    bleak_client = await establish_connection(
        client_class,
        device,
        name=device.name or "SAL Pixie",
        **connect_kwargs,
    )
    if is_reconnect:
        combo.reconnect = True
    else:
        combo.initial_connect = True

    try:
        svc_count = len(list(bleak_client.services))
        _LOGGER.info("  services visible after establish_connection: %d", svc_count)
    except Exception as err:
        _LOGGER.warning("  services introspection failed: %s", err)

    # Hand the connected BleakClient to PixieClient via the HA-managed path.
    pixie = PixieClient(device.address)
    pixie.set_ble_client(bleak_client)

    # Seed the gateway MAC; login reads DIS later and may overwrite.
    if platform.system() == "Linux":
        mac = _mac_from_linux_address(device.address)
    else:
        mac = _extract_mac_from_manufacturer_data(mfr_data)
    if mac:
        pixie._gw_mac = mac

    await pixie.login(MESH_NAME, password)
    if is_reconnect:
        combo.reconnect_login = True
    else:
        combo.initial_login = True

    statuses = await pixie.query_status()
    _LOGGER.info("  query_status returned %d devices", len(statuses))
    if is_reconnect:
        combo.reconnect_query = True
    else:
        combo.initial_query = True

    if not is_reconnect and statuses:
        addr = next(iter(statuses))
        _LOGGER.info("  toggling address %d (on/off round-trip)", addr)
        current_is_on = statuses[addr].is_on
        await pixie.turn_on(addr) if not current_is_on else await pixie.turn_off(addr)
        await asyncio.sleep(0.5)
        await pixie.turn_off(addr) if not current_is_on else await pixie.turn_on(addr)
        combo.initial_toggle = True
    elif not is_reconnect:
        # No devices to toggle — mark the toggle step as trivially passed
        # (login + query is the real signal).
        combo.initial_toggle = True

    # PixieClient.disconnect() is a no-op in HA-managed mode (it won't
    # close the bleak_client we fed it via set_ble_client), so we must
    # close the BleakClient ourselves to release the adapter.
    await pixie.disconnect()
    try:
        if bleak_client.is_connected:
            await bleak_client.disconnect()
    except Exception:
        _LOGGER.debug("  bleak_client.disconnect() raised; continuing", exc_info=True)


async def _run_combo(
    name: str,
    password: str,
    client_class: type,
    connect_kwargs: dict,
) -> ComboResult:
    combo = ComboResult(name=name)
    _LOGGER.info("=" * 72)
    _LOGGER.info("COMBO: %s", name)
    _LOGGER.info("  client_class=%s kwargs=%s", client_class.__name__, connect_kwargs)
    _LOGGER.info("=" * 72)

    try:
        await _run_workflow(combo, password, client_class, connect_kwargs, is_reconnect=False)
    except Exception:
        combo.error = traceback.format_exc()
        _LOGGER.error("  initial pass FAILED\n%s", combo.error)
        return combo

    if not combo.first_pass:
        return combo

    _LOGGER.info("  initial pass OK — pausing %.1fs before reconnect test",
                 RECONNECT_PAUSE)
    await asyncio.sleep(RECONNECT_PAUSE)

    try:
        await _run_workflow(combo, password, client_class, connect_kwargs, is_reconnect=True)
    except Exception:
        combo.error = (combo.error or "") + "\nreconnect:\n" + traceback.format_exc()
        _LOGGER.error("  reconnect pass FAILED\n%s", combo.error)

    return combo


def _print_versions() -> None:
    from importlib.metadata import PackageNotFoundError, version

    def _safe_version(name: str) -> str:
        try:
            return version(name)
        except PackageNotFoundError:
            return "(not installed)"

    _LOGGER.info("platform: %s %s", platform.system(), platform.release())
    _LOGGER.info("python: %s", sys.version.split()[0])
    _LOGGER.info("bleak: %s", _safe_version("bleak"))
    _LOGGER.info("bleak-retry-connector: %s", _safe_version("bleak-retry-connector"))
    _LOGGER.info("pigsydust: %s", _safe_version("pigsydust"))
    _LOGGER.info("habluetooth: %s", _safe_version("habluetooth"))


async def main(password: str) -> int:
    _print_versions()

    combos: list[tuple[str, type, dict]] = [
        (
            "BleakClientWithServiceCache + use_services_cache=False",
            BleakClientWithServiceCache,
            {"use_services_cache": False},
        ),
        (
            "BleakClient (plain) + use_services_cache=False",
            BleakClient,
            {"use_services_cache": False},
        ),
        (
            "BleakClientWithServiceCache + defaults (use_services_cache=True)",
            BleakClientWithServiceCache,
            {"use_services_cache": True},
        ),
    ]

    results: list[ComboResult] = []
    for name, klass, kwargs in combos:
        result = await _run_combo(name, password, klass, kwargs)
        results.append(result)
        await asyncio.sleep(RECONNECT_PAUSE)

    _LOGGER.info("=" * 72)
    _LOGGER.info("SUMMARY")
    _LOGGER.info("=" * 72)
    for r in results:
        flags = [
            f"connect={'Y' if r.initial_connect else 'N'}",
            f"login={'Y' if r.initial_login else 'N'}",
            f"query={'Y' if r.initial_query else 'N'}",
            f"toggle={'Y' if r.initial_toggle else 'N'}",
            f"reconn={'Y' if r.reconnect else 'N'}",
            f"relogin={'Y' if r.reconnect_login else 'N'}",
            f"requery={'Y' if r.reconnect_query else 'N'}",
        ]
        verdict = "PASS" if r.full_pass else ("PARTIAL" if r.first_pass else "FAIL")
        _LOGGER.info("  %-8s %s  [%s]", verdict, r.name, " ".join(flags))

    any_full_pass = any(r.full_pass for r in results)
    return 0 if any_full_pass else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 phase_a_ble_probe.py <HOME_KEY>", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
