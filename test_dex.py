"""Exercise launcher lifecycle without a phone or an ADB server."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


FAKE = r'''#!/usr/bin/env python3
import json, os, signal, sys, time
from pathlib import Path
mode = os.environ.get('CASE', 'ok')
args = sys.argv[1:]
def event(kind):
    with open(os.environ['EVENTS'], 'a') as f:
        f.write(json.dumps([kind, args, os.getpid()]) + '\n')
def stop(signum, frame):
    event('stopped')
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
if Path(sys.argv[0]).name == 'adb':
    if args == ['devices', '-l']:
        print('List of devices attached')
        if mode != 'none':
            state = 'unauthorized' if mode == 'unauthorized' else 'device'
            print('PHONE ' + state + ' usb:1-1 product:test model:test')
        if mode == 'multiple':
            print('PHONE2 device usb:1-2 product:test model:test')
        print('192.0.2.1:5555 device product:test model:test')
    elif 'push' in args:
        event('push')
        sys.exit(1 if mode == 'push-fail' else 0)
    elif args[2:5] == ['shell', 'wm', 'size']:
        event('resize')
        sys.exit(1 if mode == 'resize-fail' else 0)
    elif args[2:5] == ['shell', 'cmd', 'display']:
        event(args[5])
        sys.exit(1 if mode == 'blank-fail' and args[5] == 'power-off' else 0)
    elif args[-1].endswith(' disconnect'):
        event('disconnect')
    elif args[-1].endswith(' activate'):
        event('activate')
        if mode == 'early-exit':
            print('activation failed', flush=True)
            sys.exit(1)
        if mode not in ('timeout', 'zero'):
            print('DEX_ACTIVATED_DISPLAY_ID=17', flush=True)
        elif mode == 'zero':
            print('DEX_ACTIVATED_DISPLAY_ID=0', flush=True)
        if mode == 'activator-dies':
            time.sleep(0.5)
            sys.exit(1)
        while True:
            time.sleep(0.1)
    else:
        sys.exit(2)
else:
    if os.environ.get('ADB') != str(Path(sys.argv[0]).with_name('adb')):
        sys.exit(9)
    if '--keep-active' in args:
        event('keeper')
        if mode == 'keeper-fail':
            sys.exit(8)
        if mode == 'keeper-dies':
            time.sleep(0.4)
            sys.exit(8)
        while True:
            time.sleep(0.1)
    event('viewer')
    if mode in ('hold', 'activator-dies', 'keeper-fail', 'keeper-dies'):
        while True:
            time.sleep(0.1)
    time.sleep(0.5 if mode in ('blank-watch', 'blank-fail') else 0.2)
    sys.exit(7 if mode == 'viewer-fail' else 0)
'''


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('adb', 'scrcpy'):
            path = self.root / name
            path.write_text(FAKE)
            path.chmod(0o755)
        (self.root / 'helper.jar').touch()
        self.events = self.root / 'events'
        self.env = dict(os.environ, HOME=str(self.root), EVENTS=str(self.events))
        self.command = [sys.executable, str(Path(__file__).with_name('dex.py')),
                        '--adb', str(self.root / 'adb'), '--scrcpy', str(self.root / 'scrcpy'),
                        '--jar', str(self.root / 'helper.jar'), '--timeout', '0.9']

    def read_events(self):
        return [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []

    def run_case(self, case, extra=()):
        result = subprocess.run(self.command + list(extra), env=dict(self.env, CASE=case),
                                capture_output=True, text=True, timeout=12)
        for kind, args, pid in self.read_events():
            if kind in ('activate', 'viewer', 'keeper'):
                with self.assertRaises(ProcessLookupError, msg=f'leaked {kind}: {pid}'):
                    os.kill(pid, 0)
        return result, [e[0] for e in self.read_events()]

    def test_success_dynamic_id_and_options(self):
        result, kinds = self.run_case('ok')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('disconnect', kinds)
        args = next(e[1] for e in self.read_events() if e[0] == 'viewer')
        for option in ('--display-id=17', '--serial=PHONE', '--no-audio', '--mouse=uhid', '--max-fps=30'):
            self.assertIn(option, args)
        self.assertNotIn('--stay-awake', args)
        keeper = next(e[1] for e in self.read_events() if e[0] == 'keeper')
        for option in ('--serial=PHONE', '--display-id=0', '--no-video', '--no-audio',
                       '--no-window', '--no-clipboard-autosync', '--keep-active', '--turn-screen-off'):
            self.assertIn(option, keeper)
        self.assertEqual(kinds.count('keeper'), 1)

    def test_preflight_and_push_failure(self):
        for case in ('none', 'unauthorized', 'multiple', 'push-fail'):
            with self.subTest(case=case):
                self.events.write_text('')
                result, kinds = self.run_case(case)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('activate', kinds)
                self.assertNotIn('disconnect', kinds)

    def test_activation_and_viewer_failures_cleanup(self):
        for case in ('timeout', 'zero', 'early-exit', 'viewer-fail', 'activator-dies', 'keeper-fail', 'keeper-dies'):
            with self.subTest(case=case):
                self.events.write_text('')
                result, kinds = self.run_case(case)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('disconnect', kinds)
                if case in ('timeout', 'zero', 'early-exit'):
                    self.assertNotIn('viewer', kinds)
                    self.assertNotIn('keeper', kinds)
                if case.startswith('keeper-'):
                    self.assertIn('Phone keep-active session exited with status 8', result.stderr)

    def test_serial_is_exact(self):
        result, kinds = self.run_case('ok', ['--serial', 'PHON'])
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('push', kinds)

    def test_resolution_fullscreen_and_resize_failure(self):
        extra = ['--resolution', '1800x1200', '--fullscreen', '--max-fps', '60']
        result, kinds = self.run_case('ok', extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        resize = next(e[1] for e in self.read_events() if e[0] == 'resize')
        self.assertEqual(resize, ['-s', 'PHONE', 'shell', 'wm', 'size', '1800x1200', '-d', '17'])
        viewer = next(e[1] for e in self.read_events() if e[0] == 'viewer')
        self.assertIn('--fullscreen', viewer)
        self.assertIn('--max-size=0', viewer)
        self.assertIn('--max-fps=60', viewer)
        self.assertLess(kinds.index('resize'), kinds.index('viewer'))
        self.events.write_text('')
        result, kinds = self.run_case('resize-fail', extra)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('viewer', kinds)
        self.assertIn('disconnect', kinds)

    def test_invalid_resolution(self):
        for size in ('0x0', '1800x0', '1800x1200;reboot', '9999x9999'):
            with self.subTest(size=size):
                result, kinds = self.run_case('ok', ['--resolution', size])
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('push', kinds)

    def test_periodic_panel_blank_and_reset(self):
        result, kinds = self.run_case('blank-watch', ['--phone-blank-interval', '0.1'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(kinds.count('power-off'), 2)
        self.assertEqual(kinds.count('power-reset'), 1)
        self.assertLess(kinds.index('power-off'), kinds.index('power-reset'))
        self.assertLess(kinds.index('power-reset'), kinds.index('disconnect'))
        for kind, args, pid in self.read_events():
            if kind in ('power-off', 'power-reset'):
                self.assertEqual(args, ['-s', 'PHONE', 'shell', 'cmd', 'display', kind, '0'])

    def test_panel_blank_disabled_or_failed(self):
        result, kinds = self.run_case('blank-watch', ['--phone-blank-interval', '0'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('power-off', kinds)
        self.assertNotIn('power-reset', kinds)
        self.events.write_text('')
        result, kinds = self.run_case('blank-fail', ['--phone-blank-interval', '0.1'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(kinds.count('power-off'), 1)
        self.assertIn('timer disabled', result.stderr)
        self.assertIn('power-reset', kinds)

    def test_invalid_panel_blank_interval(self):
        for interval in ('-1', 'nan', 'inf'):
            with self.subTest(interval=interval):
                result, kinds = self.run_case('ok', ['--phone-blank-interval', interval])
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('push', kinds)

    def test_interrupt_and_duplicate(self):
        proc = subprocess.Popen(self.command + ['--phone-blank-interval', '0.1'], env=dict(self.env, CASE='hold'),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while 'power-off' not in [e[0] for e in self.read_events()]:
                if proc.poll() is not None or time.monotonic() > deadline:
                    self.fail('launcher did not start viewer and blank timer')
                time.sleep(0.05)
            second = subprocess.run(self.command, env=self.env, capture_output=True, timeout=3)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual([e[0] for e in self.read_events()].count('activate'), 1)
            proc.send_signal(signal.SIGINT)
            proc.communicate(timeout=10)
            self.assertIn('disconnect', [e[0] for e in self.read_events()])
            self.assertIn('power-reset', [e[0] for e in self.read_events()])
            for kind, args, pid in self.read_events():
                if kind in ('activate', 'viewer', 'keeper'):
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == '__main__':
    unittest.main()
