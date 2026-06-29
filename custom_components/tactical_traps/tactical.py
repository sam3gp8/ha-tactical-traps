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

try:  # const has no Home Assistant dependencies; literals are the fallback for
    from .const import NOTIFY_UUID, SERVICE_UUID, WRITE_UUID  # standalone tests
except ImportError:  # running tactical.py directly (codec self-test)
    SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
    WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
    NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"

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
        self._write_char = None
        self._notify_char = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    # ---- connection lifecycle ----
    async def _ensure_connected(self) -> None:
        if (
            self._client is not None
            and self._client.is_connected
            and self._write_char is not None
            and self._notify_char is not None
        ):
            return
        # imported lazily so the pure codec can be tested without HA installed
        from bleak_retry_connector import (
            BleakClientWithServiceCache,
            clear_cache,
            establish_connection,
        )
        from homeassistant.components import bluetooth

        def _fresh_device():
            dev = bluetooth.async_ble_device_from_address(
                self._hass, self.address, connectable=True
            )
            if dev is None:
                raise TacticalError(
                    "lock not found by any Bluetooth adapter or proxy — is it in "
                    "range and powered, and is the phone app closed?"
                )
            return dev

        self._authed = False
        self._client = await establish_connection(
            BleakClientWithServiceCache, _fresh_device(), self.address,
            disconnected_callback=self._on_disconnect,
        )
        write, notify = self._resolve_chars()
        if write is None or notify is None:
            # The cached GATT table is stale/empty (FFF2/FFF1 don't resolve).
            # Force a fresh discovery and try once more.
            for _clear in (self._client.clear_cache, lambda: clear_cache(self.address)):
                try:
                    await _clear()
                except Exception:  # noqa: BLE001 - best effort
                    pass
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = await establish_connection(
                BleakClientWithServiceCache, _fresh_device(), self.address,
                disconnected_callback=self._on_disconnect,
            )
            write, notify = self._resolve_chars()
        if write is None or notify is None:
            await self.disconnect()
            raise TacticalError(
                "lock GATT characteristics (FFF2/FFF1) not found even after a fresh "
                "service discovery — power-cycle the lock and/or move it closer to "
                "the adapter or a Bluetooth proxy"
            )
        self._write_char, self._notify_char = write, notify
        await self._client.start_notify(self._notify_char, self._on_notify)

    def _resolve_chars(self):
        """Find the write + notify characteristics. Try the known FFF2/FFF1 UUIDs
        first, then auto-detect from the service table (preferring the FFF0 vendor
        service) so a slightly different layout still works."""
        svcs = self._client.services
        write = svcs.get_characteristic(WRITE_UUID)
        notify = svcs.get_characteristic(NOTIFY_UUID)
        if write is not None and notify is not None:
            return write, notify

        def scan(restrict_to_vendor_service: bool):
            w, n = write, notify
            for ch in svcs.characteristics.values():
                if restrict_to_vendor_service and (
                    (ch.service_uuid or "").lower() != SERVICE_UUID.lower()
                ):
                    continue
                props = ch.properties
                if w is None and ("write" in props or "write-without-response" in props):
                    w = ch
                if n is None and "notify" in props:
                    n = ch
            return w, n

        write, notify = scan(True)
        if write is None or notify is None:
            write, notify = scan(False)
        return write, notify

    def _on_disconnect(self, _client) -> None:
        self._authed = False
        self._write_char = None
        self._notify_char = None

    def _on_notify(self, _char, data: bytearray) -> None:
        self._queue.put_nowait(bytes(data))

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        self._authed = False
        self._write_char = None
        self._notify_char = None
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - best effort
                pass

    # ---- framed exchange ----
    async def _exchange(self, frame: bytes, expect_cmd: int, timeout: float = 4.0):
        while not self._queue.empty():           # drop stale notifications
            self._queue.get_nowait()
        # write to the resolved characteristic object (not a UUID lookup)
        await self._client.write_gatt_char(self._write_char, frame, response=True)
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
        """Bring the bolt to `target`; idempotent. Returns the resulting state.

        An accepted toggle (reply dir 0x10) means the bolt actuated, so we report
        the target state immediately instead of waiting and re-reading status —
        that saves a settle delay and a full round-trip on every lock/unlock.
        """
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
