# Linux DeX

Use a Linux laptop as a screen, keyboard and mouse for Samsung DeX over USB. A small Python launcher combines [ScrcpyDex](https://github.com/Aureliano021/ScrcpyDex) activation with [scrcpy](https://github.com/Genymobile/scrcpy), keeps the phone active with its panel dark, and cleans up when the desktop window closes.

Tested on a Surface Go running Linux Mint with an S24 Ultra running Android 17 and a Galaxy Z Fold4 running Android 16, using scrcpy 5.0.1. Fullscreen at 1800x1200 works, with 60fps. Other device combinations are untested.

## Setup

Requires Linux, Python 3 (standard library only), ADB, USB device permissions and scrcpy 5.0.1 or newer. No Python packages, .NET runtime or build step are required. Enable USB debugging on the phone and authorise the computer.

The launcher finds its dependencies without flags if they are in the usual places:

- scrcpy: the newest complete official release extracted as `~/Applications/scrcpy-*/`, then `scrcpy` on `PATH`. Distribution packages are often too old; the launcher refuses anything older than 5.0.1.
- adb: `adb` on `PATH`, then the `adb` that ships inside the scrcpy release.
- Helper: `scrcpydex-server.jar` next to `dex.py`, then `~/Applications/ScrcpyDex/scrcpydex-server.jar`.

Use `--scrcpy`, `--adb` and `--jar` to point elsewhere. Obtain the helper from [ScrcpyDex](https://github.com/Aureliano021/ScrcpyDex); [dependency details](docs/operations.md#dependencies) identify the inspected revision and checksum. Dependencies are not bundled or downloaded by the launcher.

The launcher is the single file `dex.py`. Clone this repository and run it in place, or copy it somewhere convenient such as `~/Applications/ScrcpyDex/dex.py`. The examples below assume that location.

Check the setup before the first launch. `--doctor` shows which adb, scrcpy and helper it would use, the scrcpy version, the helper checksum, every ADB device it sees, and whether the phone is ready. It exits non-zero if anything would block a launch:

```bash
python3 ~/Applications/ScrcpyDex/dex.py --doctor
```

## Run

Connect the phone by USB and unlock it before starting. The launcher warns if the phone looks asleep or locked, because DeX then shows a black window:

```bash
python3 ~/Applications/ScrcpyDex/dex.py --resolution 1800x1200 --fullscreen --max-fps 60
```

Left Alt releases/captures the mouse. Alt+f toggles fullscreen. Close the outer window or press Ctrl+C in the launcher terminal to end the session. If DeX redirects audio, select your Bluetooth headphones again in its media output panel.

The phone panel is switched off at launch and re-blanked every 60 seconds. This is a repeating timer, including during phone use, rather than a minute measured from your last touch. Use `--phone-blank-interval 120` to change it or `--phone-blank-interval 0` to disable repeat blanking. Use `--notick` to leave the phone screen alone entirely, for example while it is charging: it is neither switched off at launch nor re-blanked. Keeping Android active may delay automatic inactivity locking during the session.

The original keep-active and panel-restoration behaviour passed the wired test. The newer repeating blanking timer, `--doctor`, `--reset`, the locked-phone warning and dependency discovery have automated coverage but still need a real-phone test.

If a session crashes and leaves the phone in DeX or with its panel dark, reconnect it and run `python3 ~/Applications/ScrcpyDex/dex.py --reset`.

## Options and diagnostics

Run `python3 dex.py --help` for all options. Defaults are a 30 fps cap, windowed display, no resolution change and a 60-second re-blank interval. A size set with `--resolution` sticks: the phone reapplies it to later sessions until it is reset, so you only need the flag once ([details](docs/operations.md#launch-and-controls)). `--serial SERIAL` selects a phone when multiple USB devices are connected; `--adb`, `--scrcpy` and `--jar` override dependency discovery. `--scrcpy-arg` passes an extra option to the DeX viewer only and can be repeated, for example `--scrcpy-arg=--render-driver=opengl`; use the `=` form. The launcher selects USB devices only, even though wireless ADB was used during diagnosis.

Session logs and the single-session lock live in `~/.cache/linux-dex/` (or `$XDG_CACHE_HOME/linux-dex/`). The newest 20 logs are kept. See [operations and recovery](docs/operations.md) for setup details, troubleshooting and cleanup behaviour.

## Development

Run from this project directory:

```bash
python3 -m unittest discover -s . -p 'test_dex.py' -v
```

The 19 tests use fake ADB/scrcpy processes and require no phone. They check launch options, dependency discovery, device states, failures, timer behaviour, diagnostics, recovery and process cleanup. GitHub Actions runs them on every push. They do not establish Samsung firmware compatibility or real display behaviour.

- [Implementation and contribution notes](docs/development.md)
- [Sleep diagnosis, evidence and remaining checks](docs/power-management.md)

## Licence

MIT; see [LICENSE](LICENSE). scrcpy and ScrcpyDex are separate projects under their own licences and are not included here.
