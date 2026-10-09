# OpenSC3

English · [Русский](README.ru.md)

**OpenSC3** is an open Linux control panel for the **fifine AmpliGame SC3** USB audio mixer (USB `3142:0c33`,
MVsilicon BP1048B2). FIFINE ships no software for the SC3 at all; on Linux it works as a plain USB audio device,
and everything else — mute state, gains, the built-in EQ and voice effects, the auto-tune key — sits behind a
vendor HID interface that the kernel does not bind. This project talks to it directly.

**Status: pre-alpha.** Mostly read-only: the CLI can check the setup, print a readable status and dump every
readable block and effect node; the window (Qt) shows the mixer's state, levels and microphone mute. Writing to
the mixer (mic trim, voice EQ, noise gate) exists behind a whitelist and a dry run by default — `sc3 … --write`
is experimental, see [docs/WRITE.md](docs/WRITE.md) (Russian). Plans — [docs/PLAN.md](docs/PLAN.md) (Russian).

## Safety first

The protocol has commands that reflash the device or wedge its control channel. This project sends **only**
whitelisted read frames, verifies the interface descriptor and the firmware build before the first one, never
issues HID Feature requests, never touches the USB configuration, and has a test that scans its own source for
dangerous calls. Details: [docs/GOTCHAS.md](docs/GOTCHAS.md), [docs/RESEARCH.md](docs/RESEARCH.md) (Russian).
Only firmware **V22** is supported.

## Quick start

Requirements: Python ≥ 3.11, `libusb` (system), `pyside6` for the window, optional `python-evdev` for buttons.

```sh
sudo install -m 644 udev/70-fifine-sc3.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger --action=change --attr-match=idVendor=3142 --attr-match=idProduct=0c33
python3 -m opensc3 doctor      # checks the setup, sends nothing to the device
python3 -m opensc3 status      # ~20 read requests
python3 -m opensc3 dump -o dump.json
python3 -m opensc3.app         # the window and tray
```

Installed as a package, the same commands are `sc3 doctor|status|dump` and `opensc3` (the window).

The udev rule grants the logged-in user (`uaccess`) access to the SC3 only — no `input` group.

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
