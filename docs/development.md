# Development

## Files

- `dex.py`: standard-library Linux launcher, CLI validation, USB discovery, activation, viewing, panel timer and cleanup.
- `test_dex.py`: subprocess integration tests with fake ADB and scrcpy executables.
- `docs/operations.md`: dependency paths, user controls, recovery and runtime behaviour.
- `docs/power-management.md`: evidence behind the keep-active workaround and real-device acceptance checks.

There is no package installation or compilation step. Run `python3 dex.py --help` to inspect the CLI and `python3 -m unittest discover -s . -p 'test_dex.py' -v` for validation.

## Boundaries

If you run an installed copy of `dex.py` (for example `~/Applications/ScrcpyDex/dex.py`), edits here do not affect it until you copy the file over and relaunch.

Use argument lists for subprocesses and always select the intended serial. Own only processes started by this session. Preserve finite timeouts, process-group cleanup and the single-session lock. Cleanup signals each child's whole process group, even after the group leader has exited, so descendants scrcpy leaves behind are stopped too. Dependency discovery, the scrcpy version gate, `--doctor` and the locked-phone check are best-effort aids: they must never send input to the phone or change its settings. Both scrcpy children must use the chosen ADB executable. Do not replace panel blanking with Android sleep or power-key events: those can reproduce the original black DeX stream.

The launcher currently supports Linux (`fcntl`, POSIX signals and process groups). Keep the implementation standard-library only unless a dependency solves a demonstrated requirement. Upstream tools are external dependencies; do not copy their binaries into this project as part of routine changes.

## Automated coverage

The 19 tests cover default and explicit frame-rate options, viewer-only `--scrcpy-arg` passthrough, dynamic display selection, resize/fullscreen, missing, unauthorised and `no permissions` phones, libusb listings without a `usb:` field, ambiguous devices, wireless, mDNS and emulator entries, dependency discovery from `~/Applications` with the scrcpy-bundled adb, the scrcpy version gate, helper upload/activation failures, activator and keep-active failure, viewer exit, descendants left in a viewer's process group, duplicate launches, Ctrl+C, invalid arguments, periodic display-0 blanking, timer failure/disable, `--notick`, reset on exit, `--doctor`, `--reset`, the locked-phone warning and log pruning. Fake long-running children are checked for process leaks.

GitHub Actions (`.github/workflows/tests.yml`) runs the mock suite on Ubuntu with Python 3.10 and 3.14 on every push and pull request.

These tests verify orchestration rather than Android power semantics. Follow the real-phone checks in [power management](power-management.md#remaining-device-checks) when changing sleep, display or cleanup behaviour. Do not mark a device check complete based only on mock tests.
