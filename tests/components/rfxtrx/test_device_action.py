"""The tests for RFXCOM RFXtrx device actions."""
from typing import NamedTuple, Set, Tuple

import RFXtrx
import pytest
import voluptuous_serialize

import homeassistant.components.automation as automation
from homeassistant.components.rfxtrx import DOMAIN, device_action
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceRegistry
from homeassistant.setup import async_setup_component

from tests.common import (
    MockConfigEntry,
    assert_lists_same,
    async_get_device_automations,
    mock_device_registry,
    mock_registry,
)
from tests.components.rfxtrx.conftest import create_rfx_test_cfg


@pytest.fixture(name="device_reg")
def device_reg_fixture(hass):
    """Return an empty, loaded, registry."""
    return mock_device_registry(hass)


@pytest.fixture(name="entity_reg")
def entity_reg_fixture(hass):
    """Return an empty, loaded, registry."""
    return mock_registry(hass)


class DeviceTestData(NamedTuple):
    """Test data linked to a device."""

    code: str
    device_identifiers: Set[Tuple[str]]


DEVICE_LIGHTING_1 = DeviceTestData("0710002a45050170", {("rfxtrx", "10", "0", "E5")})

DEVICE_BLINDS_1 = DeviceTestData(
    "09190000009ba8010100", {("rfxtrx", "19", "0", "009ba8:1")}
)

DEVICE_TEMPHUM_1 = DeviceTestData(
    "0a52080705020095220269", {("rfxtrx", "52", "8", "05:02")}
)


@pytest.mark.parametrize("device", [DEVICE_LIGHTING_1, DEVICE_TEMPHUM_1])
async def test_device_test_data(rfxtrx, device: DeviceTestData):
    """Verify that our testing data remains correct."""
    pkt: RFXtrx.lowlevel.Packet = RFXtrx.lowlevel.parse(bytearray.fromhex(device.code))
    assert device.device_identifiers == {
        ("rfxtrx", f"{pkt.packettype:x}", f"{pkt.subtype:x}", pkt.id_string)
    }


async def setup_entry(hass, devices):
    """Construct a config setup."""
    entry_data = create_rfx_test_cfg(devices=devices)
    mock_entry = MockConfigEntry(domain="rfxtrx", unique_id=DOMAIN, data=entry_data)

    mock_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    await hass.async_start()


@pytest.mark.parametrize(
    "device,expected",
    [
        [DEVICE_LIGHTING_1, [{"type": "send_command"}]],
        [DEVICE_BLINDS_1, [{"type": "send_command"}]],
        [DEVICE_TEMPHUM_1, []],
    ],
)
async def test_get_actions(hass, device_reg: DeviceRegistry, device, expected):
    """Test we get the expected actions from a rfxtrx."""
    await setup_entry(hass, {device.code: {"signal_repetitions": 1}})

    device_entry = device_reg.async_get_device(device.device_identifiers, set())

    actions = await async_get_device_automations(hass, "action", device_entry.id)
    actions = [action for action in actions if action["domain"] == DOMAIN]

    expected_actions = [
        {"domain": DOMAIN, "device_id": device_entry.id, **action_type}
        for action_type in expected
    ]

    assert_lists_same(actions, expected_actions)


@pytest.mark.parametrize(
    "device,config,expected",
    [
        [DEVICE_LIGHTING_1, {"type": "send_command", "data": 1}, "0710000045050100"],
        [DEVICE_LIGHTING_1, {"type": "send_command", "data": 10}, "0710000045050a00"],
        [DEVICE_BLINDS_1, {"type": "send_command", "data": 10}, "09190000009ba8010a00"],
    ],
)
async def test_action(
    hass, device_reg: DeviceRegistry, rfxtrx: RFXtrx.Connect, device, config, expected
):
    """Test for actions."""

    await setup_entry(hass, {device.code: {"signal_repetitions": 1}})

    device_entry = device_reg.async_get_device(device.device_identifiers, set())

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "trigger": {
                        "platform": "event",
                        "event_type": "test_event",
                    },
                    "action": {
                        "domain": DOMAIN,
                        "device_id": device_entry.id,
                        **config,
                    },
                },
            ]
        },
    )

    hass.bus.async_fire("test_event")
    await hass.async_block_till_done()

    rfxtrx.transport.send.assert_called_once_with(bytearray.fromhex(expected))


@pytest.mark.parametrize(
    "device,expected",
    [
        [DEVICE_LIGHTING_1, RFXtrx.lowlevel.Lighting1.COMMANDS],
        [DEVICE_BLINDS_1, RFXtrx.lowlevel.RollerTrol.COMMANDS],
        [DEVICE_TEMPHUM_1, None],
    ],
)
async def test_capabilities(hass, device_reg: DeviceRegistry, device, expected):
    """Test getting capabilities."""
    await setup_entry(hass, {device.code: {"signal_repetitions": 1}})

    device_entry = device_reg.async_get_device(device.device_identifiers, set())

    capabilities = await device_action.async_get_action_capabilities(
        hass,
        {
            "domain": DOMAIN,
            "device_id": device_entry.id,
            "type": "send_command",
        },
    )

    assert capabilities and "extra_fields" in capabilities

    if expected:
        field = {
            "type": "select",
            "options": list((key, value) for key, value in expected.items()),
        }
    else:
        field = {"type": "integer"}

    assert voluptuous_serialize.convert(
        capabilities["extra_fields"], custom_serializer=cv.custom_serializer
    ) == [{"name": "data", "required": True, **field}]
