# OpenSC3

English · [Русский](README.ru.md)

**OpenSC3** is an open Linux control panel for the **fifine AmpliGame SC3** USB audio mixer (USB `3142:0c33`,
MVsilicon BP1048B2). FIFINE ships no Linux software for the SC3; on Linux it works as a plain USB audio device,
and everything else — gains, the built-in voice EQ and effects, the voice changer, the auto-tune key — sits
behind a vendor HID interface that the kernel does not bind. OpenSC3 talks to it directly.

**Status: pre-alpha**, developed and tested on one machine (CachyOS, KDE Plasma 6 Wayland, PipeWire).
Only firmware **V22** is supported.

## What it does

- **A window that looks like the mixer** (Qt/QML), seen from above. It mirrors the physical faders in real time,
  shows which of the six voices and which ELECTRIC (auto-tune) key is on, guesses the hardware MUTE keys, and shows
  input/output levels from PipeWire. A tray icon shows mute and connection state.
- **Microphone mute** from the window or tray (PipeWire, the same as the mute in KDE's volume applet).
- **Mic trim** — a software gain on top of the physical Mic fader, written into the SC3 (affects what the PC
  receives, not your headphones). Off by default: enable "Allow writing to SC3" in the window's settings.
- **CLI** `sc3`: setup check, readable status, full dump, live/off-air check, and experimental writes with dry
  run by default (`sc3 set`, `sc3 profile`, `sc3 undo`).
- **Stream-aware:** while OBS is streaming or recording, OpenSC3 does not talk to the mixer's control channel at
  all (OBS is asked over obs-websocket, read-only).

What the SC3 cannot do from a PC with its factory firmware: its buttons send nothing to the computer (so they
can't trigger PC actions), and the Headphone / Line Out faders, MIC MONITOR, 48V and RGB are not visible to software.

## Safety first

The protocol has commands that reflash the device or wedge its control channel. OpenSC3 verifies the interface
descriptor and the firmware build before the first request, never issues HID Feature requests, never touches the
USB configuration, and polls no faster than once per 0.5 s (tested for 15 minutes on the device). Writing is
limited to a small whitelist (mic trim, voice EQ, noise gate), one frame at a time, each read back and rolled back
on mismatch, logged, and undoable with `sc3 undo`; every write is lost on power-off (unplug USB for a full reset).
A test scans the source for anything outside these rules. Details: [docs/WRITE.md](docs/WRITE.md),
[docs/GOTCHAS.md](docs/GOTCHAS.md), [docs/RESEARCH.md](docs/RESEARCH.md) (Russian).

## Install

Requirements: Python ≥ 3.11, `libusb`, `pyside6` + `qt6-declarative` for the window, PipeWire with `wpctl` and
`pw-record`; optional `python-websockets` (OBS status), `python-pyudev`, `python-evdev`.

```sh
git clone https://github.com/highscrren-dotcom/OpenSC3.git && cd OpenSC3
sudo install -m 644 udev/70-fifine-sc3.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger --action=change --attr-match=idVendor=3142 --attr-match=idProduct=0c33
python3 -m opensc3 doctor      # checks the setup, sends nothing to the device
python3 -m opensc3 install     # menu entry and tray icons for your user (no sudo); --autostart to start in tray
```

The udev rule grants the logged-in user (`uaccess`) access to the SC3 only — no `input` group. An Arch package
draft is in [packaging/arch](packaging/arch) (not in the AUR yet).

## Use

```sh
python3 -m opensc3.app         # the window and tray (or "OpenSC3" in the app menu after install)
python3 -m opensc3 status      # readable state, ~20 read requests
python3 -m opensc3 live        # is OBS streaming or recording?
python3 -m opensc3 set mic.trim 3            # dry run: shows the frames, sends nothing
python3 -m opensc3 set mic.trim 3 --write    # writes (off-air only), then: python3 -m opensc3 undo --write
```

Installed as a package, the same commands are `sc3 …` and `opensc3` (the window).

## Credits

Built on public work: [dank0i/sc3](https://github.com/dank0i/sc3) (ACP protocol, firmware analysis),
[wopln/FIFINE-SC3-RGB-Plus](https://github.com/wopln/FIFINE-SC3-RGB-Plus) (firmware identification, bootloader
protocol), [Austrum-lab/fifine-am8](https://github.com/Austrum-lab/fifine-am8) (the same protocol on the AM8 under
Linux), and the public MVsilicon BP10 SDK ([leadercxn/bp1048_sdk_v0.1.12](https://github.com/leadercxn/bp1048_sdk_v0.1.12)).

## Disclaimer

OpenSC3 is an unofficial project, not affiliated with or endorsed by FIFINE or MVsilicon. "FIFINE" and "AmpliGame"
are trademarks of their respective owners; "SC3" only names the compatible model. No vendor firmware or data is
included. Use at your own risk.

License: [MIT](LICENSE).
