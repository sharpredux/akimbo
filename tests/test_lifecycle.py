"""Failure-path tests that must not touch the real X server or user's files."""
import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from akimbo_display import cli
from tests.test_cli import LAYOUT


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name) / 'runtime'
        self.cfgdir = Path(self.tmp.name) / 'config'
        for name, path in [('RUNTIME', self.runtime), ('CONFIG', self.cfgdir)]:
            p = patch.object(cli, name, path); p.start(); self.addCleanup(p.stop)
        p = patch.object(cli, 'firewall_check'); p.start(); self.addCleanup(p.stop)
        cli.write_json(self.runtime / 'request.json', {'config': cli.DEFAULTS, 'environment': {}})
        cli.atomic(self.cfgdir / 'access-code', 'test-only-code')

    def test_partial_display_failure_restores_and_clears_snapshot(self):
        original = cli.parse_layout(LAYOUT)
        with patch.object(cli, 'session'), patch.object(cli, 'backend'), \
             patch.object(cli.os, 'access', return_value=True), \
             patch.object(cli, 'choose_network', return_value={'address': '127.0.0.1'}), \
             patch.object(cli.socket, 'socket'), patch.object(cli, 'encoder', return_value='software'), \
             patch.object(cli, 'layout_snapshot', return_value=original), \
             patch.object(cli, 'xrandr', return_value=LAYOUT), \
             patch.object(cli, 'build_xfce_shim', return_value=Path('/tmp/test-shim.so')), \
             patch.object(cli, 'panel_outputs', return_value={}), \
             patch.object(cli, 'apply_layout', side_effect=cli.Error('monitor failed')), \
             patch.object(cli, 'restore') as restore:
            with self.assertRaisesRegex(cli.Error, 'monitor failed'): cli.serve()
        self.assertEqual(restore.call_count, 1)
        self.assertEqual(restore.call_args.args[0]['original'], original)
        self.assertIsNone(cli.state_read())

    def test_recovery_failure_keeps_snapshot(self):
        with patch.object(cli, 'session'), patch.object(cli, 'backend'), \
             patch.object(cli.os, 'access', return_value=True), \
             patch.object(cli, 'choose_network', return_value={'address': '127.0.0.1'}), \
             patch.object(cli.socket, 'socket'), patch.object(cli, 'encoder', return_value='software'), \
             patch.object(cli, 'layout_snapshot', return_value=cli.parse_layout(LAYOUT)), \
             patch.object(cli, 'xrandr', return_value=LAYOUT), \
             patch.object(cli, 'build_xfce_shim', return_value=Path('/tmp/test-shim.so')), \
             patch.object(cli, 'panel_outputs', return_value={}), \
             patch.object(cli, 'apply_layout', side_effect=cli.Error('monitor failed')), \
             patch.object(cli, 'restore', side_effect=cli.Error('hotplug')):
            with self.assertRaisesRegex(cli.Error, 'hotplug'): cli.serve()
        self.assertIsNotNone(cli.state_read())

    def test_port_conflict_does_not_touch_layout(self):
        sock = Mock()
        sock.__enter__ = Mock(return_value=sock)
        sock.__exit__ = Mock(return_value=False)
        sock.bind.side_effect = OSError('address in use')
        with patch.object(cli, 'session'), patch.object(cli, 'backend'), \
             patch.object(cli.os, 'access', return_value=True), \
             patch.object(cli, 'choose_network', return_value={'address': '127.0.0.1'}), \
             patch.object(cli.socket, 'socket', return_value=sock), \
             patch.object(cli, 'layout_snapshot') as snapshot:
            with self.assertRaisesRegex(cli.Error, 'Cannot bind'): cli.serve()
        snapshot.assert_not_called()
        self.assertIsNone(cli.state_read())

    def test_private_config_permissions(self):
        cli.save_config(cli.DEFAULTS)
        self.assertEqual((self.cfgdir / 'config.toml').stat().st_mode & 0o777, 0o600)
        self.assertEqual(cli.config(), cli.DEFAULTS)

    def test_reboot_recovers_compositor_without_old_display_auth(self):
        state = {'boot_id': 'previous-boot', 'original': {'compositing': 'true'}}
        with patch.object(cli, 'boot_id', return_value='current-boot'), \
             patch.object(cli, '_restore_layout') as layout, patch.object(cli, 'run') as run:
            cli.restore(state)
        layout.assert_not_called()
        self.assertEqual(run.call_args.args[0][-2:], ['-s', 'true'])

    def test_persistent_snapshot_survives_runtime_cleanup(self):
        state = {'boot_id': 'test', 'original': {}}
        cli.save_state(state)
        (self.runtime / 'state.json').unlink()
        self.assertEqual(cli.state_read(), state)
        cli.clear_state()
        self.assertIsNone(cli.state_read())

    def test_install_interrupt_is_explained_without_traceback(self):
        output = io.StringIO()
        with patch('sys.argv', ['akimbo-display', 'install']), \
             patch.object(cli, 'install', side_effect=KeyboardInterrupt), \
             contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as result: cli.main()
        self.assertEqual(result.exception.code, 130)
        self.assertIn('Completed installation/build files were preserved', output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())

    def test_start_prints_safari_url_and_access_code(self):
        state = {
            'phase': 'running',
            'geometry': {'w': 1510, 'h': 992},
            'encoder': 'software',
            'network': {'address': '192.0.2.10', 'transport': 'wifi'},
        }
        output = io.StringIO()
        with patch.object(cli, 'session'), patch.object(cli, 'backend'), \
             patch.object(cli, 'service_active', side_effect=[False, True]), \
             patch.object(cli, 'state_read', side_effect=[None, state, state]), \
             patch.object(cli, 'run'), contextlib.redirect_stdout(output):
            cli.start(SimpleNamespace())
        self.assertIn('Safari: http://192.0.2.10:1701', output.getvalue())
        self.assertIn('Access code: test-only-code', output.getvalue())


if __name__ == '__main__': unittest.main()
