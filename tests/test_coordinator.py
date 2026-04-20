"""Tests for the SAL Pixie DataUpdateCoordinator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from pigsydust import DeviceStatus
from pigsydust.crypto import LoginError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sal_pixie.const import DOMAIN, SIGNAL_NEW_DEVICE
from custom_components.sal_pixie.coordinator import (
    _MISSES_BEFORE_OFFLINE,
    _PUSH_FRESH_SECS,
)


def _make_status(address: int, is_on: bool) -> DeviceStatus:
    return DeviceStatus(
        address=address,
        is_on=is_on,
        mac=bytes([0, 0, 0, 0, 0, address]),
        routing_metric=0,
    )


async def test_push_update_merges_into_data(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A push callback updates coordinator.data in place."""
    coordinator = init_integration.runtime_data.coordinator

    # The integration registered exactly one push subscriber during setup.
    push_callback = mock_pixie_client.on_status_update.call_args.args[0]
    push_callback(_make_status(3, True))
    await hass.async_block_till_done()

    assert 3 in coordinator.data
    assert coordinator.data[3].is_on is True


async def test_push_update_fires_new_device_signal(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """First sighting of an address fires SIGNAL_NEW_DEVICE."""
    seen: list[int] = []
    async_dispatcher_connect(
        hass,
        SIGNAL_NEW_DEVICE.format(entry_id=init_integration.entry_id),
        lambda address: seen.append(address),
    )

    push_callback = mock_pixie_client.on_status_update.call_args.args[0]
    push_callback(_make_status(99, True))
    await hass.async_block_till_done()

    assert 99 in seen


async def test_poll_skipped_when_push_is_fresh(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """query_status is skipped when a push arrived inside _PUSH_FRESH_SECS."""
    coordinator = init_integration.runtime_data.coordinator
    mock_pixie_client.query_status.reset_mock()

    # Simulate a very recent push, then force a poll.
    push_callback = mock_pixie_client.on_status_update.call_args.args[0]
    push_callback(_make_status(1, False))
    await coordinator.async_refresh()

    mock_pixie_client.query_status.assert_not_awaited()


async def test_poll_runs_when_push_stale(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """query_status runs when any known device hasn't been seen recently."""
    coordinator = init_integration.runtime_data.coordinator
    # Age every known device past the freshness window.
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}
    mock_pixie_client.query_status.reset_mock()

    await coordinator.async_refresh()

    mock_pixie_client.query_status.assert_awaited()


async def test_poll_runs_when_any_known_device_is_stale(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A chatty subset must not suppress polls that refresh quiet devices."""
    import time as time_module

    coordinator = init_integration.runtime_data.coordinator
    mock_pixie_client.query_status.reset_mock()

    # Pretend address 2 hasn't been seen in ages (well past _PUSH_FRESH_SECS).
    coordinator._last_seen[2] = time_module.monotonic() - 3600

    # Address 1 is chatty — push just arrived.
    push_callback = mock_pixie_client.on_status_update.call_args.args[0]
    push_callback(_make_status(1, True))
    await coordinator.async_refresh()

    mock_pixie_client.query_status.assert_awaited()


async def test_command_grace_period_preserves_local_state(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Recently-commanded addresses aren't overwritten by stale poll results."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator.data[1] = _make_status(1, True)
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}

    # Query returns the *old* (off) state for address 1 — the device
    # hasn't had time to reflect the command yet.
    mock_pixie_client.query_status.return_value = {1: _make_status(1, False)}
    coordinator.mark_commanded(1)

    await coordinator.async_refresh()
    assert coordinator.data[1].is_on is True


async def test_disconnect_marks_entities_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """The disconnect callback flips last_update_success so entities go unavailable."""
    coordinator = init_integration.runtime_data.coordinator
    data_before = dict(coordinator.data)

    with patch.object(coordinator, "_try_reconnect"):
        mock_pixie_client.is_connected = False
        coordinator._on_disconnect()
        await hass.async_block_till_done()

    state = hass.states.get("light.pixie_switch_1")
    assert state is not None
    assert state.state == "unavailable"
    # Last-known data is preserved — a BLE glitch shouldn't erase history
    # for quiet devices that may miss the reconnect's login burst.
    assert coordinator.data == data_before
    assert coordinator.last_update_success is False


async def test_coordinator_login_error_raises_auth_failed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """LoginError during a poll → ConfigEntryAuthFailed → reauth starts."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}
    mock_pixie_client.query_status.side_effect = LoginError("session died")

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"].get("source") == "reauth" for f in flows)


async def test_coordinator_connection_error_marks_failure(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """ConnectionError during a poll increments the failure counter."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}
    mock_pixie_client.query_status.side_effect = ConnectionError("gone")

    with patch.object(coordinator, "_try_reconnect"):
        await coordinator.async_refresh()

    assert coordinator._consecutive_failures == 1
    assert coordinator.last_update_success is False


async def test_unreachable_issue_raised_after_threshold(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """After 5 consecutive failures a mesh_unreachable repair issue appears."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}
    mock_pixie_client.query_status.side_effect = ConnectionError("gone")

    with patch.object(coordinator, "_try_reconnect"):
        for _ in range(5):
            await coordinator.async_refresh()

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "mesh_unreachable") is not None


async def test_unreachable_issue_cleared_on_recovery(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
    mock_device_statuses: dict[int, DeviceStatus],
) -> None:
    """A successful poll after the issue was raised clears it."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}
    mock_pixie_client.query_status.side_effect = ConnectionError("gone")

    with patch.object(coordinator, "_try_reconnect"):
        for _ in range(5):
            await coordinator.async_refresh()

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "mesh_unreachable") is not None

    # Recover: next poll returns real data.
    mock_pixie_client.query_status.side_effect = None
    mock_pixie_client.query_status.return_value = mock_device_statuses
    await coordinator.async_refresh()

    assert issue_reg.async_get_issue(DOMAIN, "mesh_unreachable") is None


async def test_stale_device_pruned_from_registry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A device absent beyond _STALE_THRESHOLD is removed from the registry."""
    import time as time_module

    coordinator = init_integration.runtime_data.coordinator
    registry = dr.async_get(hass)
    identifier = (DOMAIN, f"{init_integration.entry_id}_2")
    assert registry.async_get_device(identifiers={identifier}) is not None

    # Simulate address 2 having disappeared from the mesh 25h ago. The
    # merge path is cumulative (``merged = dict(self.data)``), so we have
    # to evict it from the current data snapshot too — otherwise every
    # subsequent poll keeps it "active" and it never crosses the
    # stale-gate.
    now = time_module.monotonic()
    coordinator._last_seen[2] = now - (25 * 3600)
    # Force the poll: age every OTHER known address too.
    for addr in list(coordinator._known_addresses):
        if addr != 2:
            coordinator._last_seen[addr] = now - _PUSH_FRESH_SECS - 1
    coordinator.data.pop(2, None)
    mock_pixie_client.query_status.return_value = {1: _make_status(1, True)}

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert registry.async_get_device(identifiers={identifier}) is None


async def test_seed_last_seen_populates_from_registry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """After setup, _last_seen has entries for every non-mesh registry device."""
    coordinator = init_integration.runtime_data.coordinator
    # Both switch addresses from the initial poll should be stamped.
    assert 1 in coordinator._last_seen
    assert 2 in coordinator._last_seen


async def test_push_update_creates_data_when_none(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A push arriving before any data was set initialises self.data."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator.data = None  # simulate pre-first-refresh state

    push_callback = mock_pixie_client.on_status_update.call_args.args[0]
    push_callback(_make_status(7, True))
    await hass.async_block_till_done()

    assert coordinator.data is not None
    assert coordinator.data[7].is_on is True


async def test_poll_generic_exception_wraps_as_update_failed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A non-Login/Connection exception from query_status → UpdateFailed."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}
    mock_pixie_client.query_status.side_effect = RuntimeError("boom")

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator._consecutive_failures == 1


async def test_seed_last_seen_reads_registry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """seed_last_seen walks the device registry and stamps non-mesh addresses."""
    coordinator = init_integration.runtime_data.coordinator
    registry = dr.async_get(hass)
    entry_id = init_integration.entry_id

    # Add a device with a non-integer suffix — must be skipped without error.
    registry.async_get_or_create(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, f"{entry_id}_notanint")},
        name="Garbage suffix",
    )
    # The "mesh" suffix device is skipped by suffix == "mesh" check.
    registry.async_get_or_create(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, f"{entry_id}_mesh")},
        name="Mesh root",
    )

    coordinator._last_seen.clear()
    coordinator.seed_last_seen()

    # Existing per-device registry entries (addresses 1 & 2) get stamped.
    assert 1 in coordinator._last_seen
    assert 2 in coordinator._last_seen
    # The "mesh" identifier and the non-integer suffix must NOT leak in.
    assert "mesh" not in coordinator._last_seen
    assert "notanint" not in coordinator._last_seen


async def test_try_reconnect_success_swaps_clients(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A successful reconnect replaces client and bleak_client on the runtime."""
    from unittest.mock import AsyncMock as _AsyncMock

    coordinator = init_integration.runtime_data.coordinator
    runtime = init_integration.runtime_data

    new_client = MagicMock()
    new_client.is_connected = True
    new_client.on_status_update = MagicMock(return_value=lambda: None)
    new_client.set_disconnect_callback = MagicMock()
    new_bleak_client = MagicMock()

    with patch(
        "custom_components.sal_pixie._connect_and_login",
        _AsyncMock(return_value=(new_client, new_bleak_client)),
    ):
        await coordinator._try_reconnect()

    assert coordinator.client is new_client
    assert runtime.client is new_client
    assert runtime.bleak_client is new_bleak_client
    assert coordinator._disconnected is False
    new_client.set_disconnect_callback.assert_called_once_with(coordinator._on_disconnect)


async def test_try_reconnect_failure_leaves_state_alone(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """If _connect_and_login raises, the old client stays in place."""
    from unittest.mock import AsyncMock as _AsyncMock

    coordinator = init_integration.runtime_data.coordinator
    original_client = coordinator.client

    with patch(
        "custom_components.sal_pixie._connect_and_login",
        _AsyncMock(side_effect=ConnectionError("nope")),
    ):
        await coordinator._try_reconnect()

    # client reference didn't get swapped out.
    assert coordinator.client is original_client


async def test_try_reconnect_tolerates_stale_disconnect_errors(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Exceptions closing the old PixieClient / bleak_client don't abort reconnect."""
    from unittest.mock import AsyncMock as _AsyncMock

    coordinator = init_integration.runtime_data.coordinator
    runtime = init_integration.runtime_data

    # Both old-side closes raise — the reconnect must still succeed.
    runtime.client.disconnect = _AsyncMock(side_effect=RuntimeError("stale"))
    runtime.bleak_client.is_connected = True
    runtime.bleak_client.disconnect = _AsyncMock(side_effect=RuntimeError("stale"))

    new_client = MagicMock()
    new_client.is_connected = True
    new_client.on_status_update = MagicMock(return_value=lambda: None)
    new_client.set_disconnect_callback = MagicMock()

    with patch(
        "custom_components.sal_pixie._connect_and_login",
        _AsyncMock(return_value=(new_client, MagicMock())),
    ):
        await coordinator._try_reconnect()

    assert coordinator.client is new_client


async def test_reconnect_and_retry_runs_action_on_success(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """After a successful reconnect, the supplied action is awaited."""
    coordinator = init_integration.runtime_data.coordinator
    action = MagicMock()

    async def _action(client):
        action(client)

    # Stub _try_reconnect so it's a no-op but leaves the existing (connected)
    # client in place — mock_pixie_client.is_connected is True by default.
    async def _fake_reconnect():
        return None

    with patch.object(coordinator, "_try_reconnect", _fake_reconnect):
        await coordinator.reconnect_and_retry(_action)

    action.assert_called_once_with(coordinator.client)


async def test_reconnect_and_retry_raises_when_still_disconnected(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """If the client is still disconnected after a retry attempt, raise."""
    coordinator = init_integration.runtime_data.coordinator

    async def _action(client):  # pragma: no cover — shouldn't run
        raise AssertionError("action should not be invoked on failure")

    async def _fake_reconnect():
        return None

    mock_pixie_client.is_connected = False
    with patch.object(coordinator, "_try_reconnect", _fake_reconnect):
        with pytest.raises(ConnectionError):
            await coordinator.reconnect_and_retry(_action)


async def test_ping_fills_gap_for_missing_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Devices missing from the 0xDC burst get unicast-pinged and folded back."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}

    # 0xDC burst returns only address 1; address 2 is missing.
    mock_pixie_client.query_status.return_value = {1: _make_status(1, True)}
    mock_pixie_client.ping_device.return_value = _make_status(2, False)

    await coordinator.async_refresh()

    mock_pixie_client.ping_device.assert_awaited_with(2, timeout=pytest.approx(1.0))
    # Both addresses end up in data: 1 from the burst, 2 from the gap-fill ping.
    assert 1 in coordinator.data
    assert 2 in coordinator.data
    assert coordinator._miss_counts.get(2, 0) == 0


async def test_ping_timeout_accrues_miss_count(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """Missing-from-burst + ping-timeout increments the miss counter."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}

    mock_pixie_client.query_status.return_value = {1: _make_status(1, True)}
    mock_pixie_client.ping_device.return_value = None  # timeout

    await coordinator.async_refresh()

    assert coordinator._miss_counts[2] == 1
    # Below threshold: address 2 retains last-known data (not yet evicted).
    assert 2 in coordinator.data


async def test_device_dropped_after_threshold_misses(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """After _MISSES_BEFORE_OFFLINE consecutive ping failures, the device drops."""
    coordinator = init_integration.runtime_data.coordinator
    mock_pixie_client.query_status.return_value = {1: _make_status(1, True)}
    mock_pixie_client.ping_device.return_value = None

    for _ in range(_MISSES_BEFORE_OFFLINE):
        # Force the poll path every iteration.
        coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}
        await coordinator.async_refresh()

    assert coordinator._miss_counts[2] >= _MISSES_BEFORE_OFFLINE
    assert 2 not in coordinator.data


async def test_push_clears_miss_count(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A push update for an address resets its ping-miss counter."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator._miss_counts[2] = 2

    push_callback = mock_pixie_client.on_status_update.call_args.args[0]
    push_callback(_make_status(2, True))
    await hass.async_block_till_done()

    assert 2 not in coordinator._miss_counts


async def test_ping_skipped_for_recently_commanded(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """A freshly-commanded device absent from the burst is not ping-probed.

    The device's response is likely still propagating and would arrive as
    a push; pinging now both wastes airtime and could stack a 0xDA command
    on top of the ON/OFF command still being acknowledged.
    """
    coordinator = init_integration.runtime_data.coordinator
    coordinator._last_seen = {addr: 0 for addr in coordinator._known_addresses}
    coordinator.mark_commanded(2)

    mock_pixie_client.query_status.return_value = {1: _make_status(1, True)}

    await coordinator.async_refresh()

    # ping_device must NOT have been called with address 2.
    for call in mock_pixie_client.ping_device.await_args_list:
        assert call.args[0] != 2


async def test_coordinator_shutdown_unsubscribes(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_pixie_client: MagicMock,
) -> None:
    """async_shutdown unhooks the push subscriber."""
    coordinator = init_integration.runtime_data.coordinator
    unsubscribe = coordinator._unsubscribe
    coordinator._unsubscribe = MagicMock(wraps=unsubscribe)

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    coordinator._unsubscribe.assert_called()
