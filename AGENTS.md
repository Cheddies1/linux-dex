# Linux DeX workspace

This project owns the Linux USB launcher for Samsung DeX. Read `README.md` and the relevant document in `docs/` before changing behaviour. If `LOCAL.md` exists, read it for the owner's machine-specific development and deployment setup; it is gitignored and must stay out of commits.

The stack is Python 3 standard library, ADB, official scrcpy 5.0.1 and the external ScrcpyDex helper. The launcher runs on the Linux machine the phone is plugged into. No build or Python dependency installation is needed.

Run tests from the project root: `python3 -m unittest discover -s . -p 'test_dex.py' -v`. See `docs/development.md` for code boundaries. Keep changes scoped, use British English and plain ASCII hyphens, and do not add AI attribution to commits.

Preserve USB serial selection, bounded subprocesses, session-owned process cleanup, the single-session lock and shared ADB server. Phone sleep and panel-off are different: never substitute a sleep/power key for display-only blanking. No policy-setting changes or automatic unlocking are implemented.

Update the owning docs when commands, defaults, recovery or device evidence change. Keep mock-test results separate from real-phone validation. Do not bundle device dumps, credentials or dependency binaries. Do not invent a licence or configure a remote without Eddie's instruction.
