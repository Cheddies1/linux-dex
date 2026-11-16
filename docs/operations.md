# Operations and recovery

## Dependencies

Python 3 and ADB must be available on the Linux client. Linux Mint's `android-sdk-platform-tools-common` supplies Android USB rules. The original APT ADB worked over USB but lacked `adb pair`; the Surface subsequently used Google's standalone Platform Tools at `~/Applications/platform-tools/adb` for wireless diagnosis. Use `--adb ~/Applications/platform-tools/adb` to select it explicitly. The launcher passes that executable to both scrcpy processes through `ADB`.

The tested scrcpy release is [5.0.1](https://github.com/Genymobile/scrcpy/releases/tag/v5.0.1). Extract its complete Linux x86_64 release into `~/Applications/`; the executable needs the accompanying server and release files. Changing versions needs a fresh device test, especially keep-active and panel cleanup.

The [ScrcpyDex helper inspected during setup](https://github.com/Aureliano021/ScrcpyDex/blob/fd3b53c1379352fd71d0b9216b2f375bf2d72427/server/scrcpydex-server.jar) is 13,291 bytes, from revision `fd3b53c1379352fd71d0b9216b2f375bf2d72427`, with SHA-256 `c57d704ab4116fc43e0370d746455c6c80170391f17082561d80cc926ab0c15c`. Eddie's working download originally came from the moving main branch; its checksum has not been checked on the Surface. Retain the working copy. Neither dependency is vendored here, and upstream licences govern their use and redistribution.

```bash
sha256sum ~/Applications/ScrcpyDex/scrcpydex-server.jar
```

## Launch and controls

Unlock the handset before launch. Starting locked produced a blank viewer until Eddie woke and unlocked the phone. Automatic unlocking is not implemented.

The Surface's tested display size is 1800x1200 (3:2). `--resolution 1800x1200` applies `wm size WIDTHxHEIGHT -d DISPLAY_ID` to the detected DeX display and removes scrcpy's capture size cap. It does not resize the handset display or change density. Without this option, DeX keeps its own resolution and capture is capped at 1920 pixels on the longest side. Window decorations can still introduce bars outside fullscreen.

The keyboard and mouse use UHID. Left Alt toggles capture. Reduce pointer and wheel speed in Samsung Settings -> General management -> Mouse if movement is too fast; Eddie also disabled Enhance pointer precision. Persistence across fresh sessions is not yet confirmed.

Audio forwarding is disabled. DeX activation can nevertheless select its own media output; reselect Bluetooth headphones in DeX. Teams/Outlook content worked, but microphone/camera forwarding and other protected content have not been validated. The protected-buffer warning did not block the tested apps.

## Process lifecycle

The launcher locks `~/.cache/linux-dex/session.lock`, selects one authorised USB phone, pushes the helper and starts its `activate` mode. It reads `DEX_ACTIVATED_DISPLAY_ID` from the activation log; display IDs must never be hard-coded. It optionally resizes that display, starts a headless scrcpy keep-active session targeting display 0, and starts the DeX viewer.

The keep-active session has no video, audio, window or clipboard autosync. It supplies `--keep-active --turn-screen-off`. The viewer uses H.264, UHID input and the chosen frame-rate cap. The loop monitors both scrcpy and activation processes. Closing the viewer or interrupting the launcher stops its own processes, resets any timer-applied display override and requests DeX disconnect. It never kills the shared ADB server.

The repeating panel timer uses `cmd display power-off 0`; cleanup uses `cmd display power-reset 0`. These commands are advertised by the tested S24 Ultra firmware. It never sends a sleep/power key. Timer failures warn and disable repeat blanking while leaving DeX running. Reset failures print a recovery command and return an error. Disconnection or an uncatchable launcher termination can prevent cleanup.

## Troubleshooting

Logs are printed at launch and saved as `~/.cache/linux-dex/session-*.log`. They contain activation and keep-active output, periodic display command output and disconnect results. Viewer output remains in the terminal. Logs may contain device identifiers; inspect before sharing. Launchers before 2026-11-16 used `~/.cache/surface-dex/`; it is no longer read and can be deleted once its logs are no longer needed.

If no USB phone is found, check the cable, USB debugging authorisation and `adb devices -l`. The launcher requires an authorised `device` entry with USB transport metadata. If several phones are connected, use `--serial SERIAL`. Close existing manual helper and keep-active sessions before launching; the launcher lock only covers other copies of this launcher.

If the phone stays in DeX after a crash, run the following with only the intended phone connected, or add `-s SERIAL` after `adb`:

```bash
adb shell 'CLASSPATH=/data/local/tmp/scrcpydex-server.jar app_process /data/local/tmp com.scrcpydex.server.Server disconnect'
```

If the timer's display override remains after a failed cleanup, reconnect and run:

```bash
adb -s SERIAL shell cmd display power-reset 0
```

If repeating blanking affects the stream, disable it with `--phone-blank-interval 0` and retain the established keep-active path while collecting evidence.

For wireless diagnosis, use a recent ADB. `unknown command pair` means the client is too old; repeated `already connected` with an `offline` device is not a working connection. Pairing is per computer. The pairing-dialog port differs from the connection port shown on the main Wireless debugging screen. Ports and display IDs change between sessions. Wireless use is outside this launcher's USB selection logic.
