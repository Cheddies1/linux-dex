#!/usr/bin/env python3
"""Start Samsung DeX over USB using the existing ScrcpyDex helper and scrcpy."""
import argparse
import fcntl
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


class Interrupted(Exception):
    def __init__(self, signum, frame):
        self.signum = signum


def interrupt(signum, frame):
    raise Interrupted(signum, frame)


def stop(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
    except ProcessLookupError:
        process.wait(timeout=3)


def executable(value):
    found = shutil.which(os.path.expanduser(str(value)))
    if not found:
        raise RuntimeError(f'Executable not found: {value}')
    return str(Path(found).resolve())


def device(adb, serial):
    result = subprocess.run([adb, 'devices', '-l'], check=True,
                            capture_output=True, text=True, timeout=10)
    rows = [line.split() for line in result.stdout.splitlines()]
    usb = [row for row in rows if len(row) >= 2 and any(s.startswith('usb:') for s in row[2:])]
    if serial:
        usb = [row for row in usb if row[0] == serial]
    if not usb:
        raise RuntimeError('No matching USB phone. Connect and unlock it, then authorise USB debugging.')
    if len(usb) != 1:
        raise RuntimeError('Multiple USB phones connected; use --serial SERIAL.')
    if usb[0][1] != 'device':
        raise RuntimeError(f'Phone is {usb[0][1]}; unlock it and authorise USB debugging.')
    return usb[0][0]


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
        ] + (['--fullscreen'] if args.fullscreen else []), env=scrcpy_env, start_new_session=True)
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
    parser.add_argument('--serial', help='USB phone serial (required if more than one is connected)')
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--scrcpy', default='~/Applications/scrcpy-linux-x86_64-v5.0.1/scrcpy')
    parser.add_argument('--jar', default='~/Applications/ScrcpyDex/scrcpydex-server.jar')
    parser.add_argument('--timeout', type=float, default=30, help='Activation timeout in seconds (default: 30)')
    parser.add_argument('--resolution', help='DeX virtual display size, e.g. 1800x1200 for Surface Go')
    parser.add_argument('--fullscreen', action='store_true', help='Start scrcpy in fullscreen mode')
    parser.add_argument('--max-fps', type=int, default=30, help='Video frame-rate cap (default: 30; try 60)')
    parser.add_argument('--phone-blank-interval', type=float, default=60,
                        help='Re-blank handset every N seconds, even during touch use (default: 60; 0 disables)')
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
    try:
        adb, scrcpy = executable(args.adb), executable(args.scrcpy)
        jar = Path(args.jar).expanduser().resolve()
        if not jar.is_file():
            raise RuntimeError(f'DeX helper not found: {jar}')
        cache = Path.home() / '.cache' / 'surface-dex'
        cache.mkdir(parents=True, exist_ok=True)
        with (cache / 'session.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another DeX launcher is already running.') from None
            serial = device(adb, args.serial)
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
