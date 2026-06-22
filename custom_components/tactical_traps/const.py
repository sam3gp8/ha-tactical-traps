"""Constants for the Tactical Traps integration."""
from __future__ import annotations

DOMAIN = "tactical_traps"
PLATFORMS = ["lock"]

# Config / option keys
CONF_ADDRESS = "address"
CONF_PIN = "pin"
CONF_POLL_HOURS = "poll_interval_hours"
CONF_AUTO_RELOCK = "auto_relock_seconds"
CONF_KEEP_ALIVE = "keep_alive_seconds"

# Battery-friendly defaults: check for "proof of life" twice a day, and never
# hold the BLE connection open between operations. 0 hours = only talk to the
# lock when a lock/unlock command is sent (no background polling at all).
DEFAULT_POLL_HOURS = 12
DEFAULT_AUTO_RELOCK = 0          # seconds; 0 = disabled
# Keep the connection (and login session) alive this long after an operation so
# follow-up commands and auto-relock are instant. 0 = disconnect immediately
# (max battery). A short window costs little battery but removes the reconnect
# cost from back-to-back actions.
DEFAULT_KEEP_ALIVE = 0           # seconds

# GATT (standard for the FFF0 Tactical Traps locks; auto-used on connect)
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
