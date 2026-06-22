# Tactical Traps — Home Assistant Integration

A custom **Home Assistant integration** (HACS-installable) that controls **Tactical
Traps** Bluetooth locks / concealment cabinets natively — no add-on and no MQTT.
It uses Home Assistant's built-in Bluetooth stack, talks the lock's `F5` protocol
directly (login → status → `token XOR 0x35` toggle), and exposes each cabinet as a
standard `lock.` entity with an optional auto-relock for gravity-drop cabinets.

## Install via HACS

1. HACS → **⋮ → Custom repositories**.
2. Repository: `https://github.com/sam3gp8/ha-tactical-traps`, type: **Integration** → **Add**.
3. Find **Tactical Traps** in HACS, **Download**, and **restart Home Assistant**.
4. **Settings → Devices & Services**. If Home Assistant has already seen the lock over
   Bluetooth it appears as a discovered device — otherwise **+ Add Integration → Tactical Traps**.
5. Confirm/enter the lock's Bluetooth address and **PIN**.

Or use the one-click link (opens the dialog pre-filled):

[![Open your Home Assistant instance and open a repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sam3gp8&repository=ha-tactical-traps&category=integration)

Requires a Bluetooth adapter on the Home Assistant host or an **ESPHome Bluetooth
proxy** in range of the cabinet. Close the phone app while pairing (the lock allows
one connection at a time).

## Options & battery life

**Settings → Devices & Services → Tactical Traps → Configure**:

- **Proof-of-life check (hours)** — how often Home Assistant briefly wakes the lock
  to confirm it's alive and read its state. Default **12 h** (twice a day). Set **0**
  to never poll — the lock is then contacted **only when you send a lock/unlock
  command**, and its state in Home Assistant is the last known value between commands.
- **Auto-relock delay (seconds)** — after any unlock, automatically re-engage the lock
  after this many seconds (for gravity-drop cabinets). `0` disables it.

The integration **never holds the Bluetooth connection open** — every operation
connects, acts, and disconnects, so the lock can return to low-power advertising and
sleep. That, plus the infrequent (or disabled) polling, is what keeps the battery
from draining. Trade-off: if the lock is operated by its keypad or the phone app,
Home Assistant won't reflect it until the next proof-of-life check (or the next
command, if polling is off).

### Speeding up unlock/lock

Most of the time to open from cold is the BLE connection to a *sleeping* lock — the
direct cost of the battery savings above. To reduce latency without giving that up:

- **Keep connection warm after use (seconds)** — after a command, hold the connection
  open briefly so the **auto-relock** and any quick follow-up command skip the slow
  reconnect + login and are near-instant. It only costs battery during that short
  window. Great for gravity-drop cabinets (open → grab → relock). It does **not**
  speed up the first cold open (there's nothing to keep warm yet). `0` = off.
- **Put an [ESPHome Bluetooth proxy](https://esphome.io/projects/?type=bluetooth)
  near the cabinet.** This is usually the biggest real-world win for the *cold open*:
  connecting through a nearby proxy is far faster and more reliable than reaching the
  cabinet from the Home Assistant host's adapter across the house. It's battery-neutral
  for the lock.
- The command sequence itself is already trimmed to the minimum (login → status →
  toggle, no confirming re-read), so every action is as few Bluetooth round-trips as
  the protocol allows.

## Lost your PIN?

The lock's PIN ships on a small card that's easy to misplace. If you've lost yours,
recover it the safe way rather than trying to defeat the lock:

- **Contact Tactical Traps support** with your serial number and proof of purchase —
  they can help verified owners reset or recover the combination.
- **Check for a mechanical backup/override key** that shipped with the cabinet.
- **Look for a documented factory-reset** in your manual that lets you set a new PIN
  with physical access to the unit.
- If the PIN was never changed from the factory default, the app's defaults are
  `0000` and `1234`.

This integration deliberately does **not** include a PIN brute-forcer: it would be a
break-in tool for a firearm-security device usable against any such lock, not just
your own.

## Notes

- The protocol frame codec is unit-tested; the Bluetooth/Home Assistant glue should
  be validated on your own hardware.
- Independent interoperability project — **not affiliated with or endorsed by
  Tactical Traps**. Use it only on locks you own.

## Support

If this is useful, you can [**buy me a coffee**](https://buymeacoffee.com/sam3gp8) ☕

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-sam3gp8-ffdd00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/sam3gp8)

## License

[MIT](LICENSE).
