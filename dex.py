#!/usr/bin/env python3
"""Start Samsung DeX over USB using the existing ScrcpyDex helper and scrcpy."""
import argparse
import fcntl
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time


REMOTE = '/data/local/tmp/scrcpydex-server.jar'
SERVER = f'CLASSPATH={REMOTE} app_process /data/local/tmp com.scrcpydex.server.Server'
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
MIN_SCRCPY = (5, 0, 1)
HELPER_URL = 'https://github.com/Aureliano021/ScrcpyDex'
HELPER_SHA256 = 'c57d704ab4116fc43e0370d746455c6c80170391f17082561d80cc926ab0c15c'
KEEP_LOGS = 20
STATE_HELP = {
    'unauthorized': 'unlock it and accept the USB debugging prompt',
    'authorizing': 'unlock it and accept the USB debugging prompt',
    'offline': 'reconnect the cable, then unlock the phone',
    'no permissions': ('this user cannot open the USB device; install Android udev rules '
                       '(for example android-sdk-platform-tools-common), check plugdev membership, then reconnect'),
}


class Interrupted(Exception):
    def __init__(self, signum, frame):
        self.signum = signum


def interrupt(signum, frame):
    raise Interrupted(signum, frame)


def group_alive(process):
    process.poll()  # Reap the leader so its zombie does not count as alive.
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    return True


def stop(process):
    """Stop a child's whole process group, including descendants left after the leader exits."""
    if process is None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + 3
        while group_alive(process) and time.monotonic() < deadline:
            time.sleep(0.05)
        if not group_alive(process):
            break
    process.wait(timeout=0.1)


def executable(value):
    found = shutil.which(os.path.expanduser(str(value)))
    if not found:
        raise RuntimeError(f'Executable not found: {value}')
    return str(Path(found).resolve())


def version(text, prefix):
    match = re.search(prefix + r'(\d+)\.(\d+)(?:\.(\d+))?', text)
    return tuple(int(part or 0) for part in match.groups()) if match else None


def runnable(path):
    return path.is_file() and os.access(path, os.X_OK)


def find_scrcpy(value):
    if value:
        return executable(value)
    bundles = sorted(Path.home().glob('Applications/scrcpy-*/scrcpy'),
                     key=lambda path: version(path.parent.name, 'v') or (0,), reverse=True)
    for candidate in [path for path in bundles if runnable(path)] + [shutil.which('scrcpy')]:
        if candidate:
            return str(Path(candidate).resolve())
    raise RuntimeError('scrcpy not found. Extract the official scrcpy release into ~/Applications '
                       'or pass --scrcpy PATH.')


def find_adb(value, scrcpy):
    if value:
        return executable(value)
    found = shutil.which('adb')
    if found:
        return str(Path(found).resolve())
    if scrcpy and runnable(Path(scrcpy).with_name('adb')):
        return str(Path(scrcpy).with_name('adb'))
    raise RuntimeError('adb not found. Install Android platform tools, keep the adb that ships with scrcpy, '
                       'or pass --adb PATH.')


def find_jar(value):
    candidates = ([Path(value).expanduser()] if value else
                  [Path(__file__).resolve().with_name('scrcpydex-server.jar'),
                   Path.home() / 'Applications' / 'ScrcpyDex' / 'scrcpydex-server.jar'])
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(f'DeX helper not found in {", ".join(map(str, candidates))}. '
                       f'Download scrcpydex-server.jar from {HELPER_URL} or pass --jar PATH.')


def scrcpy_version(scrcpy):
    result = subprocess.run([scrcpy, '--version'], capture_output=True, text=True, timeout=10)
    return version(result.stdout, 'scrcpy ')


def check_scrcpy(scrcpy):
    found = scrcpy_version(scrcpy)
    if found is None:
        print(f'Warning: could not read the version of {scrcpy}; {dotted(MIN_SCRCPY)} or newer is required.',
              file=sys.stderr)
    elif found < MIN_SCRCPY:
        raise RuntimeError(f'{scrcpy} is scrcpy {dotted(found)}; {dotted(MIN_SCRCPY)} or newer is required '
                           '(older releases lack --keep-active). Pass --scrcpy PATH.')
    return found


def dotted(parts):
    return '.'.join(map(str, parts))


def cache_dir():
    base = os.environ.get('XDG_CACHE_HOME', '')
    return (Path(base) if os.path.isabs(base) else Path.home() / '.cache') / 'linux-dex'


def prune_logs(cache, keep):
    logs = sorted(cache.glob('session-*.log'))
    for old in logs[:max(0, len(logs) - keep)]:
        try:
            old.unlink()
        except OSError:
            pass


def devices(adb):
    """Return (serial, state, usb) for each transport listed by adb devices -l."""
    result = subprocess.run([adb, 'devices', '-l'], check=True,
                            capture_output=True, text=True, timeout=20)
    rows, listing = [], False
    for line in result.stdout.splitlines():
        if line.startswith('List of devices'):
            listing = True
            continue
        fields = line.split()
        if not listing or len(fields) < 2 or line.startswith('*'):
            continue
        serial = fields[0]
        state = 'no permissions' if fields[1:3] == ['no', 'permissions'] else fields[1]
        # The libusb backend omits the usb: field, so treat any non-network, non-emulator serial as USB.
        usb = any(field.startswith('usb:') for field in fields[2:]) or not (
            ':' in serial or '._tcp' in serial or serial.startswith('emulator-'))
        rows.append((serial, state, usb))
    return rows


def device(adb, serial):
    usb = [row for row in devices(adb) if row[2] and (not serial or row[0] == serial)]
    if not usb:
        raise RuntimeError('No matching USB phone. Connect and unlock it, then authorise USB debugging.')
    if len(usb) != 1:
        raise RuntimeError('Multiple USB phones connected; use --serial SERIAL.')
    found, state, _ = usb[0]
    if state != 'device':
        raise RuntimeError(f'Phone {found} is {state}: {STATE_HELP.get(state, "unlock it and authorise USB debugging")}.')
    return found


def phone_looks_locked(adb, serial):
    """Best-effort check for an asleep or locked phone; None when the state cannot be read."""
    try:
        power, window = (subprocess.run([adb, '-s', serial, 'shell', 'dumpsys', *service], capture_output=True,
                                        text=True, errors='replace', timeout=10).stdout
                         for service in (['power'], ['window', 'policy']))
    except (OSError, subprocess.SubprocessError):
        return None
    awake = re.search(r'mWakefulness=(\w+)', power)
    keyguard = re.search(r'KeyguardServiceDelegate\s.*?showing=(true|false)', window, re.DOTALL)
    if (awake and awake.group(1) != 'Awake') or (keyguard and keyguard.group(1) == 'true'):
        return True
    return False if awake or keyguard else None


def reset(adb, serial):
    """Undo a crashed session: restore the handset panel and ask the helper to end DeX."""
    status = 0
    for name, command in (('Phone panel reset', ['cmd', 'display', 'power-reset', '0']),
                          ('DeX disconnect', [SERVER + ' disconnect'])):
        try:
            subprocess.run([adb, '-s', serial, 'shell', *command], check=True, timeout=10,
                           capture_output=True)
            print(f'{name}: done')
        except (OSError, subprocess.SubprocessError) as exc:
            print(f'{name} failed: {exc}', file=sys.stderr)
            status = 1
    return status


def doctor(args):
    """Report what the launcher would use, without starting DeX. Returns 1 if anything blocks a launch."""
    problems = 0

    def report(label, text, problem=False):
        nonlocal problems
        problems += problem
        print(f'{label + ":":<9}{"PROBLEM: " if problem else ""}{text}')

    scrcpy = adb = None
    try:
        scrcpy = find_scrcpy(args.scrcpy)
        found = scrcpy_version(scrcpy)
        if found is None:
            report('scrcpy', f'{scrcpy} (version unreadable)', True)
        else:
            report('scrcpy', f'{scrcpy} ({dotted(found)})', found < MIN_SCRCPY)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        report('scrcpy', exc, True)
    try:
        adb = find_adb(args.adb, scrcpy)
        result = subprocess.run([adb, 'version'], capture_output=True, text=True, timeout=10)
        report('adb', f'{adb} ({(result.stdout.splitlines() or ["version unknown"])[0]})')
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        report('adb', exc, True)
    try:
        jar = find_jar(args.jar)
        digest = hashlib.sha256(jar.read_bytes()).hexdigest()
        known = 'matches the inspected revision' if digest == HELPER_SHA256 else 'differs from the inspected revision'
        report('helper', f'{jar} ({jar.stat().st_size} bytes, SHA-256 {known})')
    except (RuntimeError, OSError) as exc:
        report('helper', exc, True)
    cache = cache_dir()
    try:
        cache.mkdir(parents=True, exist_ok=True)
        with (cache / 'session.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                report('cache', f'{cache} (no launcher running)')
            except BlockingIOError:
                report('cache', f'{cache} (a launcher is running)')
    except OSError as exc:
        report('cache', exc, True)
    if adb:
        try:
            for serial, state, usb in devices(adb):
                print(f'{"device:":<9}{serial} {state} ({"USB" if usb else "not USB, ignored"})')
            serial = device(adb, args.serial)
            locked = phone_looks_locked(adb, serial)
            report('phone', f'{serial} ready' + {True: ', but it looks asleep or locked; unlock it before launch',
                                                 False: ', awake and unlocked', None: ''}[locked])
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            report('phone', exc, True)
    return 1 if problems else 0


def session(args, adb, scrcpy, jar, serial, log_path, log):
    activator = viewer = keeper = None
    panel_override = False
    status = 1
    previous = {sig: signal.signal(sig, interrupt) for sig in SIGNALS}
    try:
        subprocess.run([adb, '-s', serial, 'push', str(jar), REMOTE], check=True, timeout=15)
        activator = subprocess.Popen([adb, '-s', serial, 'shell', SERVER + ' activate'],
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + args.timeout
        while True:
            if activator.poll() is not None:
                raise RuntimeError('DeX activator exited before creating a display.')
            output = log_path.read_text(errors='replace')
            match = re.search(r'^DEX_ACTIVATED_DISPLAY_ID=([1-9][0-9]*)\r?\n', output, re.MULTILINE)
            if match:
                display_id = match.group(1)
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f'DeX activation timed out after {args.timeout:g} seconds.')
            time.sleep(0.1)
        print(f'DeX display {display_id}. Left Alt releases/captures the mouse.', flush=True)
        if args.resolution:
            subprocess.run([adb, '-s', serial, 'shell', 'wm', 'size', args.resolution,
                            '-d', display_id], check=True, timeout=10)
            print(f'Requested DeX resolution: {args.resolution}', flush=True)
        print('If Bluetooth audio stops, select the headphones in DeX media output.', flush=True)
        scrcpy_env = dict(os.environ, ADB=adb)
        keeper = subprocess.Popen([
            scrcpy, f'--serial={serial}', '--display-id=0',
            '--no-video', '--no-audio', '--no-window', '--no-clipboard-autosync',
            '--keep-active', '--turn-screen-off',
        ], stdout=log, stderr=subprocess.STDOUT, env=scrcpy_env, start_new_session=True)
        print('Phone keep-active session started with the handset screen off. Stops when DeX closes.', flush=True)
        viewer = subprocess.Popen([
            scrcpy, f'--serial={serial}', f'--display-id={display_id}',
            '--video-codec=h264', '--max-size=0' if args.resolution else '--max-size=1920', f'--max-fps={args.max_fps}',
            '--mouse=uhid', '--keyboard=uhid', '--no-audio', '--window-title=Samsung DeX',
        ] + (['--fullscreen'] if args.fullscreen else []) + args.scrcpy_arg, env=scrcpy_env, start_new_session=True)
        blank_interval = args.phone_blank_interval
        next_blank = time.monotonic() + blank_interval
        if blank_interval:
            print(f'Phone panel re-blanks every {blank_interval:g}s, including during touch use.', flush=True)
        while viewer.poll() is None:
            if keeper.poll() is not None:
                raise RuntimeError(f'Phone keep-active session exited with status {keeper.returncode}.')
            if activator.poll() is not None:
                raise RuntimeError('DeX activator stopped while scrcpy was running.')
            if blank_interval and time.monotonic() >= next_blank:
                # Display-only override: never send POWER/SLEEP, which can blank DeX too.
                panel_override = True
                try:
                    subprocess.run([adb, '-s', serial, 'shell', 'cmd', 'display', 'power-off', '0'],
                                   check=True, timeout=5, stdout=log, stderr=subprocess.STDOUT)
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f'Warning: phone re-blank failed; timer disabled: {exc}. See {log_path}', file=sys.stderr)
                    blank_interval = 0
                next_blank = time.monotonic() + blank_interval
            time.sleep(0.1)
        if viewer.returncode != 0:
            raise RuntimeError(f'scrcpy exited with status {viewer.returncode}.')
        status = 0
    except Interrupted as exc:
        print('\nStopping DeX...', flush=True)
        status = 128 + exc.signum
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        print(log_path.read_text(errors='replace')[-6000:], file=sys.stderr)
    finally:
        for sig in SIGNALS:
            signal.signal(sig, signal.SIG_IGN)
        try:
            # Stop only processes belonging to this session. Never kill the ADB server.
            for name, process in (('scrcpy viewer', viewer), ('phone keep-active session', keeper)):
                try:
                    stop(process)
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f'Warning: could not stop {name}: {exc}', file=sys.stderr)
                    status = status or 1
            if panel_override:
                try:
                    # Clear DisplayManager's override as well as scrcpy's panel power mode.
                    subprocess.run([adb, '-s', serial, 'shell', 'cmd', 'display', 'power-reset', '0'],
                                   check=True, timeout=5, stdout=log, stderr=subprocess.STDOUT)
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f'Warning: phone panel reset failed: {exc}. Run adb -s {serial} shell cmd display power-reset 0',
                          file=sys.stderr)
                    status = status or 1
            if activator is not None:
                try:
                    subprocess.run([adb, '-s', serial, 'shell', SERVER + ' disconnect'],
                                   check=True, timeout=5, stdout=log, stderr=subprocess.STDOUT)
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f'Warning: DeX disconnect failed: {exc}. See {log_path}', file=sys.stderr)
                    status = status or 1
                finally:
                    try:
                        stop(activator)
                    except (OSError, subprocess.SubprocessError) as exc:
                        print(f'Warning: could not stop activator: {exc}', file=sys.stderr)
                        status = status or 1
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--doctor', action='store_true',
                      help='Report the dependencies, phone and lock the launcher would use, then exit')
    mode.add_argument('--reset', action='store_true',
                      help='Restore the phone panel and end DeX after a crashed session, then exit')
    parser.add_argument('--serial', help='USB phone serial (required if more than one is connected)')
    parser.add_argument('--adb', help='adb executable (default: adb on PATH, then the adb beside scrcpy)')
    parser.add_argument('--scrcpy', help='scrcpy executable (default: newest ~/Applications/scrcpy-*/scrcpy, '
                                         'then scrcpy on PATH)')
    parser.add_argument('--jar', help='ScrcpyDex helper (default: scrcpydex-server.jar beside dex.py, '
                                      'then ~/Applications/ScrcpyDex/)')
    parser.add_argument('--timeout', type=float, default=30, help='Activation timeout in seconds (default: 30)')
    parser.add_argument('--resolution', help='DeX virtual display size, e.g. 1800x1200')
    parser.add_argument('--fullscreen', action='store_true', help='Start scrcpy in fullscreen mode')
    parser.add_argument('--max-fps', type=int, default=30, help='Video frame-rate cap (default: 30; try 60)')
    parser.add_argument('--phone-blank-interval', type=float, default=60,
                        help='Re-blank handset every N seconds, even during touch use (default: 60; 0 disables)')
    parser.add_argument('--scrcpy-arg', action='append', default=[], metavar='ARG',
                        help='Extra option for the DeX viewer only; repeat as needed, '
                             'e.g. --scrcpy-arg=--render-driver=opengl')
    args = parser.parse_args()
    if not math.isfinite(args.phone_blank_interval) or args.phone_blank_interval < 0:
        parser.error('--phone-blank-interval must be a finite non-negative number')
    if args.max_fps <= 0:
        parser.error('--max-fps must be a positive integer')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be a finite positive number')
    if args.resolution:
        dimensions = re.fullmatch(r'([0-9]{3,4})x([0-9]{3,4})', args.resolution)
        if not dimensions or not (640 <= int(dimensions[1]) <= 7680 and 480 <= int(dimensions[2]) <= 4320):
            parser.error('--resolution must be WIDTHxHEIGHT, from 640x480 to 7680x4320')
    if args.doctor:
        return doctor(args)
    try:
        if args.reset:
            try:
                scrcpy = find_scrcpy(args.scrcpy)
            except RuntimeError:
                scrcpy = None
            adb = find_adb(args.adb, scrcpy)
        else:
            scrcpy = find_scrcpy(args.scrcpy)
            adb, jar = find_adb(args.adb, scrcpy), find_jar(args.jar)
            found = check_scrcpy(scrcpy)
        cache = cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        with (cache / 'session.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another DeX launcher is already running.') from None
            serial = device(adb, args.serial)
            if args.reset:
                return reset(adb, serial)
            print(f'adb: {adb}\nscrcpy {dotted(found) if found else "(version unknown)"}: {scrcpy}\n'
                  f'Helper: {jar}', flush=True)
            if phone_looks_locked(adb, serial):
                print('Warning: the phone looks asleep or locked. Unlock it now or the DeX window may stay black.',
                      file=sys.stderr, flush=True)
            prune_logs(cache, KEEP_LOGS - 1)
            prefix = time.strftime('session-%Y%m%d-%H%M%S-')
            with tempfile.NamedTemporaryFile(mode='ab', prefix=prefix, suffix='.log', dir=cache, delete=False) as log:
                log_path = Path(log.name)
                print(f'Phone: {serial}\nSession log: {log_path}', flush=True)
                return session(args, adb, scrcpy, jar, serial, log_path, log)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
