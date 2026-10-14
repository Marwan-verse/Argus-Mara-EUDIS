"""Local startup boundaries, process isolation and native mode selection."""
import os
import sys
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk

from argus import soc_launcher as launcher
from desktop_soc import login_screen


class LocalStartupTests(unittest.TestCase):
    def test_command_output_handles_utf8_and_unexpected_bytes_on_windows(self):
        result = launcher.run_command([
            sys.executable, '-c',
            'import os; os.write(1, bytes([0xe2, 0x86, 0x92])); os.write(2, bytes([0x81]))',
        ])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '\u2192')
        self.assertEqual(result.stderr, '\ufffd')

    def test_credentials_created_once_and_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            target = launcher.prepare_credentials(Path(directory))
            original = target.read_text()
            self.assertEqual(len(original.splitlines()), 3)
            for line in original.splitlines():
                self.assertGreaterEqual(len(line.split('=', 1)[1]), 14)
            launcher.prepare_credentials(Path(directory))
            self.assertEqual(target.read_text(), original)

    def test_ready_stack_uses_verified_https_and_existing_compose(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(launcher, 'ROOT', Path(directory)), \
                patch.object(launcher, 'docker_path', return_value='docker'), \
                patch.object(launcher, 'run_command', return_value=Mock(returncode=0)) as run, \
                patch.object(launcher, 'SOCClient') as client:
            client.return_value.request.return_value = {'ready': True}
            url, ca_file = launcher.start_local(Mock(), threading.Event())
            self.assertEqual(url, launcher.LOCAL_URL)
            client.assert_called_once_with(url, ca_file=ca_file)
            client.return_value.request.assert_called_once_with('GET', '/healthz')
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn(['up', '-d', '--build', 'relay', 'https'], [cmd[-5:] for cmd in commands])
            self.assertIn(['run', '--rm', 'seed'], [cmd[-3:] for cmd in commands])
            self.assertFalse(any('desktop' in cmd for cmd in commands))
            self.assertTrue(Path(directory, 'data/soc-local/demo.env').is_file())

    def test_failed_container_start_never_seeds_or_checks_health(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(launcher, 'ROOT', Path(directory)), \
                patch.object(launcher, 'docker_path', return_value='docker'), \
                patch.object(launcher, 'run_command', side_effect=[Mock(returncode=0), Mock(returncode=1)]) as run, \
                patch.object(launcher, 'SOCClient') as client:
            with self.assertRaisesRegex(launcher.StartupError, 'Container startup failed'):
                launcher.start_local(Mock(), threading.Event())
            self.assertEqual(run.call_count, 2)
            client.assert_not_called()

    def test_stopped_engine_starts_desktop_before_compose(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(launcher, 'ROOT', Path(directory)), \
                patch.object(launcher, 'docker_path', return_value='docker'), \
                patch.object(launcher, 'run_command', side_effect=[Mock(returncode=1)] + [Mock(returncode=0)] * 5) as run, \
                patch.object(launcher, 'SOCClient') as client:
            client.return_value.request.return_value = {'ready': True}
            launcher.start_local(Mock(), threading.Event())
            self.assertEqual(run.call_args_list[1].args[0], ['docker', 'desktop', 'start', '--detach'])

    def test_cancelled_start_never_invokes_docker(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch.object(launcher, 'docker_path', return_value='docker'), \
                patch.object(launcher, 'run_command') as run:
            with self.assertRaisesRegex(launcher.StartupError, 'cancelled'):
                launcher.start_local(Mock(), cancelled)
            run.assert_not_called()

    def test_second_client_has_ca_and_cannot_launch_more_clients(self):
        with patch.object(launcher.subprocess, 'Popen') as popen:
            launcher.open_second_client(launcher.LOCAL_URL, 'public-ca.crt')
        args, options = popen.call_args
        self.assertIn('--soc-client', args[0])
        self.assertEqual(options['env']['ARGUS_SOC_CA_FILE'], 'public-ca.crt')
        self.assertFalse(any('PASSWORD' in str(value) for value in args[0]))


class StartupScreenTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f'Native display unavailable: {error}')
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)

    def tearDown(self):
        if self.root.winfo_exists():
            self.root.tk.call(self.root.protocol('WM_DELETE_WINDOW'))
        self.assertEqual(self.errors, [])

    def button(self, text):
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ctk.CTkButton) and text in child.cget('text'):
                    return child
                found = walk(child)
                if found:
                    return found
        return walk(self.root)

    def pump_until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.02)
        self.assertTrue(predicate())

    def test_offline_does_not_start_docker_or_authenticate(self):
        offline = Mock()
        with patch.object(launcher, 'start_local') as start, patch('desktop_soc.SOCClient') as client:
            login_screen(self.root, '', Mock(), on_offline=offline, local_launcher=True)
            self.button('Continue offline').invoke()
            offline.assert_called_once()
            start.assert_not_called()
            client.assert_not_called()

    def test_local_launch_opens_one_extra_window_and_requires_login(self):
        logged_in = Mock()
        with patch.object(launcher, 'start_local', return_value=(launcher.LOCAL_URL, 'public-ca.crt')), \
                patch.object(launcher, 'open_second_client') as second:
            login_screen(self.root, '', logged_in, on_offline=Mock(), local_launcher=True)
            button = self.button('Start local server')
            button.invoke()
            button.invoke()
            self.pump_until(lambda: second.called)
            second.assert_called_once_with(launcher.LOCAL_URL, 'public-ca.crt')
            logged_in.assert_not_called()
            self.assertEqual(button.winfo_manager(), '')

    def test_failed_start_allows_retry_and_offline_without_extra_window(self):
        with patch.object(launcher, 'start_local', side_effect=launcher.StartupError('Install Docker')), \
                patch.object(launcher, 'open_second_client') as second:
            login_screen(self.root, '', Mock(), on_offline=Mock(), local_launcher=True)
            self.button('Start local server').invoke()
            self.pump_until(lambda: self.button('Continue offline').cget('state') == 'normal')
            second.assert_not_called()

    def test_strict_child_screen_has_no_offline_or_local_launcher(self):
        login_screen(self.root, launcher.LOCAL_URL, Mock())
        self.assertIsNone(self.button('Continue offline'))
        self.assertIsNone(self.button('Start local server'))


if __name__ == '__main__':
    unittest.main()
