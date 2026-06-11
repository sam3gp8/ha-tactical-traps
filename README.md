# Tactical Traps — Home Assistant Integration

A custom **Home Assistant integration** (HACS-installable) that controls **Tactical
Traps** Bluetooth locks / concealment cabinets natively — no add-on and no MQTT.
It uses Home Assistant's built-in Bluetooth stack, talks the lock's `F5` protocol
directly (login → status → `token XOR 0x35` toggle), and exposes each cabinet as a
standard `lock.` entity with an optional auto-relock for gravity-drop cabinets.

> Prefer the **add-on** (its own UI, BLE console, Brutus/Listen/Calibrate tools)?
> That lives at <https://github.com/sam3gp8/ha-tactical-traps>. This repository is
> the lighter, native **integration** for everyday use.

## Install via HACS

1. HACS → **⋮ → Custom repositories**.
2. Repository: `https://github.com/sam3gp8/tactical-traps`, type: **Integration** → **Add**.
3. Find **Tactical Traps** in HACS, **Download**, and **restart Home Assistant**.
4. **Settings → Devices & Services**. If Home Assistant has already seen the lock over
   Bluetooth it appears as a discovered device — otherwise **+ Add Integration → Tactical Traps**.
5. Confirm/enter the lock's Bluetooth address and **PIN**.

Requires a Bluetooth adapter on the Home Assistant host or an **ESPHome Bluetooth
proxy** in range of the cabinet. Close the phone app while pairing (the lock allows
one connection at a time).

## Options

**Settings → Devices & Services → Tactical Traps → Configure**:

- **Status poll interval** — how often the lock state is read (default 30 s).
- **Auto-relock delay** — after any unlock, automatically re-engage the lock after
  this many seconds. Set it for gravity-drop cabinets where the lock is the only
  thing holding the door. `0` disables it.

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
