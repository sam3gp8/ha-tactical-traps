"""Constants for the Tactical Traps integration."""
from __future__ import annotations

DOMAIN = "tactical_traps"
PLATFORMS = ["lock"]

# Config / option keys
CONF_ADDRESS = "address"
CONF_PIN = "pin"
CONF_POLL_INTERVAL = "poll_interval"
CONF_AUTO_RELOCK = "auto_relock_seconds"

DEFAULT_POLL_INTERVAL = 30      # seconds
DEFAULT_AUTO_RELOCK = 0         # seconds; 0 = disabled

# GATT (standard for the FFF0 Tactical Traps locks; auto-used on connect)
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
