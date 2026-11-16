# Development

## Files

- `dex.py`: standard-library Linux launcher, CLI validation, USB discovery, activation, viewing, panel timer and cleanup.
- `test_dex.py`: subprocess integration tests with fake ADB and scrcpy executables.
- `docs/operations.md`: dependency paths, user controls, recovery and runtime behaviour.
- `docs/power-management.md`: evidence behind the keep-active workaround and real-device acceptance checks.

There is no package installation or compilation step. Run `python3 dex.py --help` to inspect the CLI and `python3 -m unittest discover -s . -p 'test_dex.py' -v` for validation.

## Boundaries

The development copy is `~/projects/personal/surface-dex` on deepthought. The deployed copy is `~/Applications/ScrcpyDex/dex.py` on the Surface. Edits here do not change the running Surface copy until it is copied and relaunched. The project moved out of the deepthought infrastructure repository on 2026-11-16.

Use argument lists for subprocesses and always select the intended serial. Own only processes started by this session. Preserve finite timeouts, process-group cleanup and the single-session lock. Both scrcpy children must use the chosen ADB executable. Do not replace panel blanking with Android sleep or power-key events: those can reproduce the original black DeX stream.

The launcher currently supports Linux (`fcntl`, POSIX signals and process groups). Keep the implementation standard-library only unless a dependency solves a demonstrated requirement. Upstream tools are external dependencies; do not copy their binaries into this project as part of routine changes.

## Automated coverage

The ten tests cover default and explicit frame-rate options, dynamic display selection, resize/fullscreen, missing or unauthorised phones, ambiguous devices, helper upload/activation failures, activator and keep-active failure, viewer exit, duplicate launches, Ctrl+C, invalid arguments, periodic display-0 blanking, timer failure/disable and reset on exit. Fake long-running children are checked for process leaks.

These tests verify orchestration rather than Android power semantics. Follow the real-phone checks in [power management](power-management.md#remaining-device-checks) when changing sleep, display or cleanup behaviour. Do not mark a device check complete based only on mock tests.
