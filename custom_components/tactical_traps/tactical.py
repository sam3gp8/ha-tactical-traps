"""Tactical Traps F5 protocol: frame codec + async BLE client.

The pure codec functions (build/parse and the toggle derivation) are unit-tested
without Home Assistant. The BLE client uses Home Assistant's Bluetooth stack via
bleak-retry-connector.

Frame:  F5 | CMD | DIR | LEN | 5F | CHK | <payload>
        CHK = (sum of every other byte) & 0xFF
Reply DIR: 0x10 = accepted/OK, 0x11 = refused, 0x26 = not-authenticated.
Toggle payload is bound to the per-connection session token (last byte of the
0x60 status reply): payload = token XOR 0x35 (confirmed on real hardware).
"""
from __future__ import annotations

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

# Opcodes
CMD_LOGIN = 0x0F
CMD_STATUS = 0x60
CMD_TOGGLE = 0x61
CMD_KEEPALIVE = 0x75
CMD_LOGOUT = 0x6F

DIR_WRITE = 0x00
DIR_OK = 0x10
DIR_REFUSED = 0x11
DIR_NOAUTH = 0x26

TOGGLE_XOR = 0x35  # payload = session_token XOR 0x35

STATE_LOCKED = 0x00
STATE_UNLOCKED = 0x01


class TacticalError(Exception):
    """Recoverable problem talking to the lock."""


# --------------------------------------------------------------------------- #
# Pure codec (no Bluetooth / no Home Assistant) — unit-tested
# --------------------------------------------------------------------------- #
def build(cmd: int, payload: bytes = b"", direction: int = DIR_WRITE) -> bytes:
    payload = bytes(payload)
    head = bytes([0xF5, cmd & 0xFF, direction & 0xFF, len(payload) & 0xFF, 0x5F])
    chk = (sum(head) + sum(payload)) & 0xFF
    return head + bytes([chk]) + payload


def parse(frame: bytes):
    """Return (cmd, direction, payload, ok) or None if not a valid F5 frame."""
    frame = bytes(frame)
    if len(frame) < 6 or frame[0] != 0xF5:
        return None
    cmd = frame[1]
    direction = frame[2]
    length = frame[3]
    payload = frame[6:6 + length]
    return cmd, direction, payload, (direction == DIR_OK)


def login_frame(pin: str) -> bytes:
    return build(CMD_LOGIN, str(pin).encode("ascii"))


def status_frame() -> bytes:
    return build(CMD_STATUS)


def toggle_frame(session_token: int) -> bytes:
    return build(CMD_TOGGLE, bytes([(session_token ^ TOGGLE_XOR) & 0xFF]))


def state_name(state: int | None) -> str:
    if state == STATE_LOCKED:
        return "locked"
    if state == STATE_UNLOCKED:
        return "unlocked"
    return "unknown"


# --------------------------------------------------------------------------- #
# Async BLE client (Home Assistant Bluetooth)
# --------------------------------------------------------------------------- #
class TacticalBLEClient:
    """One connection's worth of talking to a lock. Not thread-safe; the
    coordinator serialises all access with an asyncio.Lock."""

    def __init__(self, hass, address: str, pin: str):
        self._hass = hass
        self.address = address.upper()
        self.pin = pin
        self._client = None
        self._authed = False
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    # ---- connection lifecycle ----
    async def _ensure_connected(self) -> None:
        if self._client is not None and self._client.is_connected:
            return
        # imported lazily so the pure codec can be tested without HA installed
        from bleak_retry_connector import (
            BleakClientWithServiceCache,
            establish_connection,
        )
        from homeassistant.components import bluetooth

        from .const import NOTIFY_UUID

        device = bluetooth.async_ble_device_from_address(
            self._hass, self.address, connectable=True
        )
        if device is None:
            raise TacticalError(
                "lock not found by any Bluetooth adapter or proxy — is it in range "
                "and powered, and is the phone app closed?"
            )
        self._authed = False
        self._client = await establish_connection(
            BleakClientWithServiceCache, device, self.address,
            disconnected_callback=self._on_disconnect,
        )
        await self._client.start_notify(NOTIFY_UUID, self._on_notify)

    def _on_disconnect(self, _client) -> None:
        self._authed = False

    def _on_notify(self, _char, data: bytearray) -> None:
        self._queue.put_nowait(bytes(data))

    async def disconnect(self) -> None:
        client, self._client, self._authed = self._client, None, False
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - best effort
                pass

    # ---- framed exchange ----
    async def _exchange(self, frame: bytes, expect_cmd: int, timeout: float = 4.0):
        from .const import WRITE_UUID

        while not self._queue.empty():           # drop stale notifications
            self._queue.get_nowait()
        await self._client.write_gatt_char(WRITE_UUID, frame, response=True)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                data = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            parsed = parse(data)
            if parsed and parsed[0] == expect_cmd:
                return parsed

    async def _login_if_needed(self) -> None:
        await self._ensure_connected()
        if self._authed:
            return
        res = await self._exchange(login_frame(self.pin), CMD_LOGIN)
        if res is None:
            raise TacticalError("no reply to login — lock busy (close the phone app) or out of range")
        _cmd, direction, _payload, ok = res
        if not ok:
            raise TacticalError("login rejected — check the PIN")
        self._authed = True

    async def read_state(self) -> int:
        """Login if needed and return STATE_LOCKED / STATE_UNLOCKED."""
        await self._login_if_needed()
        res = await self._exchange(status_frame(), CMD_STATUS)
        if res is None:
            raise TacticalError("no status reply from lock")
        _cmd, _dir, payload, _ok = res
        if not payload:
            raise TacticalError("empty status reply")
        return payload[0]

    async def ensure(self, target: int) -> int:
        """Bring the bolt to `target`; idempotent. Returns the resulting state."""
        await self._login_if_needed()
        res = await self._exchange(status_frame(), CMD_STATUS)
        if res is None or not res[2]:
            raise TacticalError("could not read lock status")
        payload = res[2]
        state, token = payload[0], payload[-1]
        if state == target:
            return state
        res = await self._exchange(toggle_frame(token), CMD_TOGGLE)
        if res is None:
            raise TacticalError("no reply to toggle")
        if res[1] != DIR_OK:
            raise TacticalError(
                f"lock refused the toggle (0x{res[1]:02X}) for session token "
                f"0x{token:02X}"
            )
        await asyncio.sleep(0.4)
        res = await self._exchange(status_frame(), CMD_STATUS)
        if res and res[2]:
            return res[2][0]
        return target

    async def validate(self) -> bool:
        """Connect + login only, for the config flow. Disconnects afterwards."""
        try:
            await self._login_if_needed()
            return True
        finally:
            await self.disconnect()


# --------------------------------------------------------------------------- #
# Self-test (pure codec only)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    assert login_frame("1679").hex(" ") == "f5 0f 00 04 5f 3e 31 36 37 39", login_frame("1679").hex(" ")
    assert status_frame().hex(" ") == "f5 60 00 00 5f b4", status_frame().hex(" ")
    # confirmed pairs: token 0x68 -> 0x5D, token 0xF4 -> 0xC1
    assert toggle_frame(0x68)[-1] == 0x5D
    assert toggle_frame(0xF4)[-1] == 0xC1
    # parse round-trips an accepted status reply
    s = bytes([0xF5, 0x60, 0x10, 0x09, 0x5F, 0x00, 0x00, 0x01, 0x15, 0x99, 0x00, 0x02, 0x83, 0x5B, 0xF4])
    cmd, direction, payload, ok = parse(s)
    assert cmd == CMD_STATUS and ok and payload[0] == STATE_LOCKED and payload[-1] == 0xF4
    print("tactical codec self-test OK:", toggle_frame(0xF4).hex(" "))
