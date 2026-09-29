import unittest
from unittest.mock import patch
from akimbo_display import cli

LAYOUT = '''Screen 0: minimum 320 x 200, current 3840 x 1080, maximum 16384 x 16384
eDP connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 309mm x 173mm
HDMI-A-0 connected 1920x1080+0+0 (normal left inverted right x axis y axis) 708mm x 398mm
DP-0 disconnected (normal left inverted right x axis y axis)
'''


class GeometryTests(unittest.TestCase):
    def test_mini_profiles_and_orientation(self):
        for preset, expected in [('performance', (1132, 744)), ('balanced', (1510, 992)), ('native', (2266, 1488))]:
            cfg = cli.DEFAULTS | {'quality': preset}
            self.assertEqual(cli.dimensions(cfg), expected)
            self.assertEqual(cli.dimensions(cfg | {'orientation': 'portrait'}), expected[::-1])

    def test_models_are_encoder_compatible(self):
        for model in cli.MODELS:
            for quality in ('performance', 'balanced', 'native'):
                w, h = cli.dimensions(cli.DEFAULTS | dict(model=model, quality=quality))
                self.assertEqual((w % 2, h % 2), (0, 0))

    def test_invalid_custom_and_unknown_models(self):
        for extra in ({'model': 'typo'}, {'model': 'custom'}, {'resolution': 'bad'}, {'resolution': '1133x744'}, {'resolution': '10000x10000'}):
            with self.assertRaises(cli.Error): cli.dimensions(cli.DEFAULTS | extra)

    def test_positions_preserve_physical_relative_layout(self):
        layout = cli.parse_layout(LAYOUT)
        for position in ('below', 'above', 'left', 'right'):
            plan = cli.geometry(layout, 1510, 992, position)
            a, b = plan['outputs']
            self.assertEqual(a['x'] - b['x'], 1920)
            self.assertEqual(a['y'], b['y'])
            for output in [*plan['outputs'], plan]:
                self.assertGreaterEqual(output['x'], 0)
                self.assertGreaterEqual(output['y'], 0)
                self.assertLessEqual(output['x'] + output['w'], plan['width'])
                self.assertLessEqual(output['y'] + output['h'], plan['height'])
        self.assertEqual(layout['outputs'][0]['y'], 0)

    def test_below_layout(self):
        plan = cli.geometry(cli.parse_layout(LAYOUT), 1510, 992, 'below')
        self.assertEqual((plan['x'], plan['y'], plan['width'], plan['height']), (1165, 1080, 3840, 2072))

    def test_unused_connector_and_mode_cover_capture(self):
        self.assertEqual(cli.unused_output(LAYOUT), 'DP-0')
        with self.assertRaisesRegex(cli.Error, 'No unused display connector'):
            cli.unused_output(LAYOUT.replace('DP-0 disconnected', 'DP-0 connected'))
        name, args = cli.mode_line(1510, 992)
        self.assertEqual(name, 'AKIMBO-1512x992-30')
        self.assertEqual(args[0], name)
        self.assertEqual(len(args), 12)

    def test_limit_checked_before_mutation(self):
        layout = cli.parse_layout(LAYOUT) | {'max_height': 1500}
        with self.assertRaises(cli.Error): cli.geometry(layout, 1510, 992, 'below')

    def test_rotated_output_is_rejected(self):
        with self.assertRaises(cli.Error): cli.parse_layout(LAYOUT.replace('(normal left', 'left (normal left', 1))

    def test_restore_orders_output_movement_before_shrink(self):
        old = cli.parse_layout(LAYOUT)
        calls = []
        def fake(*args):
            calls.append(args)
            if args == ('--current',): return LAYOUT
            if args == ('--listmonitors',): return 'AKIMBO-IPAD'
            return ''
        with patch.object(cli, 'xrandr', side_effect=fake):
            cli.restore({'original': old})
        self.assertIn(('--delmonitor', cli.MONITOR), calls)
        self.assertEqual(calls[-1], ('--fb', '3840x1080'))
        self.assertEqual(calls[-2], ('--output', 'eDP', '--pos', '1920x0', '--output', 'HDMI-A-0', '--pos', '0x0'))

    def test_hotplug_does_not_restore_missing_output(self):
        calls = []
        def fake(*args):
            calls.append(args)
            if args == ('--current',): return '\n'.join(LAYOUT.splitlines()[:2])
            return 'AKIMBO-IPAD'
        with patch.object(cli, 'xrandr', side_effect=fake):
            with self.assertRaises(cli.Error): cli.restore({'original': cli.parse_layout(LAYOUT)})
        self.assertFalse(any('--output' in c for c in calls))


if __name__ == '__main__': unittest.main()
