"""Local startup boundaries, process isolation and native mode selection."""
import gc
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
from argus.collab_client import ClientError
from desktop_soc import login_screen

SAVED = {'url': 'https://soc.example.invalid', 'token': 'synthetic-token-' + 'x' * 27,
         'username': 'marwan', 'ca_file': None}


class LocalStartupTests(unittest.TestCase):
    def test_fresh_demo_has_full_igor_and_restricted_bob_with_local_short_password(self):
        import contextlib
        import io
        from argus.collab_server import main
        from argus.collab_store import Store
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'accounts.sqlite3'
            environment = {'ARGUS_SOC_DB': str(path), 'ARGUS_SOC_ORIGIN': 'https://localhost:8443',
                           'ARGUS_SOC_LOCAL_DEMO': '1', 'ARGUS_DEMO_MYKHAILO_PASSWORD': 'synthetic-mykhailo',
                           'ARGUS_DEMO_IGOR_PASSWORD': 'synthetic-igor', 'ARGUS_DEMO_BOB_PASSWORD': 'xyz',
                           'ARGUS_DEMO_ADMIN_PASSWORD': 'synthetic-admin-password'}
            with patch.dict(os.environ, environment), patch.object(sys, 'argv', ['soc', '--seed-demo']), \
                    contextlib.redirect_stdout(io.StringIO()):
                main()
            store = Store(path)
            try:
                igor = store.user(store.credential('igor')['id'])
                bob = store.user(store.credential('bob')['id'])
                self.assertEqual(igor['groups'], ['intelligence', 'user'])
                self.assertEqual(bob['groups'], ['user'])
                self.assertTrue(store.verify(store.credential('bob')['password_hash'], 'xyz'))
                self.assertFalse(igor['admin'] or bob['admin'])
            finally:
                store.close()

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
            self.assertEqual(len(original.splitlines()), 4)
            for line in original.splitlines():
                self.assertGreaterEqual(len(line.split('=', 1)[1]), 14)
            launcher.prepare_credentials(Path(directory))
            self.assertEqual(target.read_text(), original)

    def test_existing_credentials_gain_only_missing_demo_passwords(self):
        old_lines = ['ARGUS_DEMO_MARWAN_PASSWORD=old-marwan-secret-1', 'ARGUS_DEMO_IGOR_PASSWORD=old-igor-secret-22',
                     'ARGUS_DEMO_ADMIN_PASSWORD=old-admin-secret-333']
        for ending in ('\n', ''):  # Also a hand-made file without a final line break.
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory, 'demo.env')
                target.write_text('\n'.join(old_lines) + ending)
                launcher.prepare_credentials(Path(directory))
                lines = target.read_text().splitlines()
                self.assertEqual(lines[:3], old_lines)
                self.assertEqual([line.split('=', 1)[0] for line in lines[3:]],
                                 ['ARGUS_DEMO_MYKHAILO_PASSWORD', 'ARGUS_DEMO_BOB_PASSWORD'])
                self.assertGreaterEqual(len(lines[3].split('=', 1)[1]), 14)
                updated = target.read_text()
                launcher.prepare_credentials(Path(directory))
                self.assertEqual(target.read_text(), updated)

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
        # Collect earlier tests' Tk objects here, on the main thread. If a background
        # sign-in job collects them instead, a Font.__del__ waits forever on its
        # destroyed interpreter.
        gc.collect()
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

    def widgets(self, kind):
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, kind):
                    yield child
                yield from walk(child)
        return list(walk(self.root))

    def pump_until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.02)
        self.assertTrue(predicate())

    def sign_in_with_box(self, ticked):
        logged_in = Mock()
        with patch('desktop_soc.soc_session.load', return_value=None), \
                patch('desktop_soc.soc_session.save', return_value=True) as save, \
                patch('desktop_soc.soc_session.forget') as forget, \
                patch('desktop_soc.SOCClient') as client:
            login_screen(self.root, SAVED['url'], logged_in, remember=True)
            self.pump_until(lambda: self.button('Sign in').cget('state') == 'normal')
            url, username, password = self.widgets(ctk.CTkEntry)
            username.insert(0, 'marwan')
            password.insert(0, 'synthetic-password-42')
            if not ticked:
                self.widgets(ctk.CTkCheckBox)[0].deselect()
            self.button('Sign in').invoke()
            self.pump_until(lambda: logged_in.called)
        client.return_value.login.assert_called_once_with('marwan', 'synthetic-password-42')
        return client.return_value, save, forget

    def test_saved_sign_in_opens_the_app_without_a_password(self):
        logged_in = Mock()
        with patch('desktop_soc.soc_session.load', return_value=SAVED), patch('desktop_soc.SOCClient') as client:
            login_screen(self.root, '', logged_in, remember=True)
            self.pump_until(lambda: logged_in.called)
        client.assert_called_once_with(SAVED['url'], allow_loopback_http=False, ca_file=None)
        client.return_value.resume.assert_called_once_with(SAVED['token'])
        client.return_value.login.assert_not_called()
        self.assertIs(logged_in.call_args.args[0], client.return_value)
        self.assertIs(client.return_value.remember, True)

    def test_expired_saved_sign_in_is_forgotten_and_asks_for_the_password(self):
        logged_in = Mock()
        with patch('desktop_soc.soc_session.load', return_value=SAVED), \
                patch('desktop_soc.soc_session.forget') as forget, patch('desktop_soc.SOCClient') as client:
            client.return_value.resume.side_effect = ClientError('Sign in required', 401)
            login_screen(self.root, '', logged_in, remember=True)
            self.pump_until(lambda: forget.called and self.button('Sign in').cget('state') == 'normal')
        logged_in.assert_not_called()
        url, username, password = self.widgets(ctk.CTkEntry)
        self.assertEqual((url.get(), username.get(), password.get()), (SAVED['url'], 'marwan', ''))

    def test_ticked_box_saves_the_sign_in(self):
        client, save, forget = self.sign_in_with_box(ticked=True)
        save.assert_called_once_with(client)
        forget.assert_not_called()
        self.assertIs(client.remember, True)

    def test_unticked_box_forgets_any_saved_sign_in(self):
        client, save, forget = self.sign_in_with_box(ticked=False)
        save.assert_not_called()
        forget.assert_called_once()

    def test_create_account_requests_approval_and_checks_the_repeat(self):
        with patch('desktop_soc.SOCClient') as client:
            login_screen(self.root, SAVED['url'], Mock())
            self.button('Create account').invoke()
            self.root.update()
            username, secret, repeat = self.widgets(ctk.CTkEntry)[3:]
            self.assertEqual(username.get(), '')
            username.insert(0, 'newcomer')
            secret.insert(0, 'synthetic-password-42')
            repeat.insert(0, 'synthetic-password-43')
            self.button('Request account').invoke()
            self.root.update()
            client.return_value.signup.assert_not_called()
            self.assertEqual((secret.get(), repeat.get()), ('', ''))
            secret.insert(0, 'synthetic-password-42')
            repeat.insert(0, 'synthetic-password-42')
            self.button('Request account').invoke()
            self.pump_until(lambda: 'requested' in self.status_text())
        client.return_value.signup.assert_called_once_with('newcomer', 'synthetic-password-42')
        self.assertEqual(self.widgets(ctk.CTkEntry)[1].get(), 'newcomer')
        self.assertIn('administrator approves', self.status_text())

    def status_text(self):
        return ' '.join(label.cget('text') for label in self.widgets(ctk.CTkLabel))

    def test_second_demo_window_never_uses_a_saved_sign_in(self):
        with patch('desktop_soc.soc_session.load', return_value=SAVED) as load:
            login_screen(self.root, launcher.LOCAL_URL, Mock())
            self.root.update()
        load.assert_not_called()
        self.assertEqual(self.widgets(ctk.CTkCheckBox), [])

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
