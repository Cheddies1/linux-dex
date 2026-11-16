# Power management: evidence and decisions

## Tested configuration and result

Tests on 2026-11-15 and 2026-11-16 used an S24 Ultra (SM-S928B), Android 17 / SDK 37 / One UI 90000, scrcpy 5.0.1 and a Surface Go running Linux Mint. The exact Mint release was not recorded. Surface decoding used OpenGL and VA-API. A Galaxy Z Fold4 was added on 2026-11-16; see below.

Wired DeX worked at 1800x1200 fullscreen with Teams and Outlook in the work profile. Eddie reported substantially smoother interaction after raising the cap from 30 to 60 fps; delivered frame rate was not measured. The separate handset keep-active session kept a YouTube stream visible beyond the previous 60-second handset timeout during an approximately two-minute test. The physical panel stayed dark but touchpad input remained available. Closing the viewer restored the handset panel.

On 2026-11-16 the launcher at commit `3fb9a6a` ran on the Surface with no path flags. It found scrcpy 5.0.1 in `~/Applications`, adb at `/usr/lib/android-sdk/platform-tools/adb` and the helper in `~/Applications/ScrcpyDex/`, whose SHA-256 matched the inspected revision. `--doctor` listed the phone as USB, ignored a wireless connection to the same phone and reported it awake and unlocked. A session at 1800x1200 fullscreen and 60 fps then ran normally.

A later session the same day, run without `--resolution`, still streamed at 1800x1200. With a third session running, `wm size -d` on the ScrcpyDex display (unique ID `wifi:desktop:00:11:22:33:44:55`, physical 1920x1080) reported `Override size: 1800x1200` and `Override density: 160` against a physical density of 320. The launcher never sets density, so the density override comes from DeX or the helper. The size override persisting is kept as intended behaviour for a laptop that always uses the same size. With the Xreal One glasses then connected (display type `EXTERNAL`, unique ID `local:4626964578939494661`, 1920x1080), `wm size -d` reported no size override, so the ScrcpyDex size did not carry over to them. The glasses also showed `Override density: 160` against a physical density of 100, which supports DeX itself setting density.

### Galaxy Z Fold4

On 2026-11-16 a Galaxy Z Fold4 (SM-F936B), Android 16 / SDK 36 / One UI 80000, ran DeX through the launcher on the same Surface. The first session, without `--resolution`, used the DeX default of 1920x1080; a later session with `--resolution 1800x1200` worked, and `wm size -d` then reported that override, with `Override density: 160` against a physical 320, as on the S24 Ultra. The Fold's ScrcpyDex display reported unique ID `wifi:00:11:22:33:44:55`, which differs from the S24 Ultra's `wifi:desktop:00:11:22:33:44:55`; each phone keeps its own size. The lock-state check read `mWakefulness=Awake` and `KeyguardServiceDelegate` / `showing=false`, and the firmware advertises `cmd display power-off` and `power-reset`.

The Fold has two built-in displays, both in display group 0: display 0 (904x2316, the cover screen while closed) and display 1 (1812x2176, the inner screen). The launcher's keep-active session and blanking timer target display 0 only. Both were OFF with the phone closed during the session. With the Fold4 unfolded during a session, the inner screen was usable and DeX kept streaming without interruption. The next 60-second tick blanked the inner screen too, so `cmd display power-off 0` affects whichever panel is active; folding and reopening woke it again. This is kept as intended behaviour. `--notick` was added the same day for sessions where the phone screen should stay on, for example while charging; it has mock coverage only. During the Fold4 session the scrcpy capture display was in display group 2 with the DeX display; during the S24 Ultra session the same day it was in group 0. The launcher behaves the same on both.

The periodic re-blank timer has automated coverage, and on 2026-11-16 the Fold4 confirmed on a real phone that a tick blanks the active panel while DeX keeps streaming. Panel restoration after the timer has fired is not yet confirmed: the earlier successful restoration used scrcpy alone, before the extra DisplayManager override was added.

## Why charging stay-awake failed

The first attempted fix used `--stay-awake`. Paired power dumps showed USB power, `stay_on_while_plugged_in=7`, but effective `mStayOn=false`. The work profile enforced `mMaximumScreenOffTimeoutFromDeviceAdmin=900000`. AOSP disables charging stay-on when an administrator maximum is enforced. Eddie confirmed the policy origin and raised it internally; this launcher does not change it.

The primary power group's timeout was 60000 ms and its activity timestamp did not advance with DeX input. The secondary group's activity timestamp advanced and its timeout was 600000 ms. The black viewer coincided with primary-group sleep, even while the secondary group remained awake. Increasing handset timeout would delay the failure without addressing this coupling.

## Isolating the capture path

With Xreal One glasses connected, YouTube continued on physical DeX after the handset slept under the same work-profile policy. Wireless scrcpy then mirrored that same display. At handset timeout, the glasses kept playing while the Surface viewer went black and remained open.

Read-only dumps captured handset display 0 OFF in group 0, Xreal display 18 ON in group 2, and scrcpy's intermediate capture display 19 OFF in group 0. The capture display mirrored display 18, had `mFlags=16`, `FLAG_PRIVATE`, `mStopped=false` and `mCurrentLayerStack=-1`. Keyguard reported `showing=false` and `inputRestricted=false`. These display IDs describe one session only.

The strongest explanation is that the intermediate capture display shares the handset's sleeping power group, even while its external source display remains active. This reproduces without ScrcpyDex activation, so the loopback DeX helper alone does not explain it. Raw device dumps were kept outside the project in temporary files; they are not required to run or test the launcher and should not be published with it.

## Chosen workaround

Scrcpy's [virtual-display blanking issue](https://github.com/Genymobile/scrcpy/issues/6787) led to `--keep-active`. The [v5.0.1 controller](https://github.com/Genymobile/scrcpy/blob/v5.0.1/server/src/main/java/com/genymobile/scrcpy/control/Controller.java) reports user activity every four seconds to the source display when mirroring. Putting that flag only on the DeX viewer targets DeX rather than the primary group containing the capture display.

The launcher therefore runs a second stock scrcpy session targeting display 0, with `--no-video --no-audio --no-window --no-clipboard-autosync --keep-active --turn-screen-off`. It separates Android wakefulness from physical panel illumination. Waking the handset manually can leave the panel lit while keep-active continues, which motivated the repeating blanking timer.

[Shinonome](https://github.com/wonderhoy-labs/shinonome#keeping-the-desktop-alive-with-the-screen-off) independently documents a similar Android 17 issue on a Pixel: virtual-display group flags were overridden, and waking the primary group while forcing the physical panel off worked. That supports this approach but does not establish identical Samsung internals. No custom scrcpy server patch is used.

Synthetic activity may delay automatic inactivity locking throughout the session. The panel-off action is not a lock. The timer is periodic, not an idle detector, and may interrupt active handset use. These are deliberate properties of the current workaround.

## Remaining device checks

- On the S24 Ultra, wake the handset during a wired session with the default timer; verify it re-blanks within 60 seconds while DeX continues playing. The Fold4 passed this on 2026-11-16.
- Close the viewer after the timer has fired; verify the phone panel restores and DeX ends.
- Check normal handset inactivity timeout after exit and longer DeX use beyond the short acceptance test.
- Exercise disconnect/reconnect and the documented display-reset recovery if automatic cleanup cannot reach the phone.
- Run a session with `--notick`; verify the phone screen stays on throughout, DeX keeps streaming, and normal screen timeout returns after exit.
- Check pointer-setting persistence when needed.
- Start with the phone locked and with it asleep; verify the launcher warns. The awake and unlocked case gave no warning on 2026-11-16.
- Run `--reset` after a forced crash (kill the launcher with SIGKILL); verify the panel restores and DeX ends.

Update this record only from observed results. Firmware updates may change the helper's Samsung APIs, display grouping or shell power commands.
