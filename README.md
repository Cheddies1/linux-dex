# Surface DeX

Use a Linux laptop as a screen, keyboard and mouse for Samsung DeX over USB. A small Python launcher combines [ScrcpyDex](https://github.com/Aureliano021/ScrcpyDex) activation with [scrcpy](https://github.com/Genymobile/scrcpy), keeps the phone active with its panel dark, and cleans up when the desktop window closes.

Tested on a Surface Go running Linux Mint and an S24 Ultra running Android 17, using scrcpy 5.0.1. Fullscreen at 1800x1200 works; the 60 fps cap feels substantially smoother than 30. Teams and Outlook in the work profile work. The Fold 4 has not been tested.

## Setup

Requires Linux, Python 3 (standard library only), ADB, USB device permissions and scrcpy 5.0.1. No Python packages, .NET runtime or build step are required. Enable USB debugging on the phone and authorise the computer.

Keep the complete official scrcpy Linux release directory. The default paths on the Surface are:

- `~/Applications/scrcpy-linux-x86_64-v5.0.1/scrcpy`
- `~/Applications/ScrcpyDex/scrcpydex-server.jar`
- `~/Applications/ScrcpyDex/dex.py` - copy this project's launcher here.

Obtain the helper from ScrcpyDex; [dependency details](docs/operations.md#dependencies) identify the inspected revision and checksum. Dependencies are not bundled or downloaded by the launcher.

From the Surface, update the launcher from its development copy on deepthought:

```bash
scp eddie@deepthought:/home/eddie/projects/personal/surface-dex/dex.py ~/Applications/ScrcpyDex/dex.py
```

## Run

Connect the phone by USB and unlock it before starting:

```bash
python3 ~/Applications/ScrcpyDex/dex.py --resolution 1800x1200 --fullscreen --max-fps 60
```

Left Alt releases/captures the mouse. Alt+f toggles fullscreen. Close the outer window or press Ctrl+C in the launcher terminal to end the session. If DeX redirects audio, select your Bluetooth headphones again in its media output panel.

The phone panel is switched off at launch and re-blanked every 60 seconds. This is a repeating timer, including during phone use, rather than a minute measured from your last touch. Use `--phone-blank-interval 120` to change it or `--phone-blank-interval 0` to disable repeat blanking. Keeping Android active may delay automatic inactivity locking during the session.

The original keep-active and panel-restoration behaviour passed the wired test. The newer repeating blanking timer has automated coverage but still needs a real-phone test, including panel restoration on exit.

## Options and diagnostics

Run `python3 dex.py --help` for all options. Defaults are a 30 fps cap, windowed display, unchanged DeX resolution and a 60-second re-blank interval. `--serial SERIAL` selects a phone when multiple USB devices are connected; `--adb`, `--scrcpy` and `--jar` override dependency paths. The launcher selects USB devices only, even though wireless ADB was used during diagnosis.

Session logs and the single-session lock live in `~/.cache/surface-dex/`. See [operations and recovery](docs/operations.md) for setup details, troubleshooting and cleanup behaviour.

## Development

Run from this project directory:

```bash
python3 -m unittest discover -s . -p 'test_dex.py' -v
```

The ten tests use fake ADB/scrcpy processes and require no phone. They check launch options, failures, timer behaviour and process cleanup. They do not establish Samsung firmware compatibility or real display behaviour.

- [Implementation and contribution notes](docs/development.md)
- [Sleep diagnosis, evidence and remaining checks](docs/power-management.md)
