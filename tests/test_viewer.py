import json
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from akimbo_display import cli


@unittest.skipUnless(shutil.which('node'), 'JavaScript runtime unavailable')
class ViewerTests(unittest.TestCase):
    def test_config_waits_for_named_monitor_and_preserves_fps(self):
        fake_upstream = '''
class Settings {
  constructor() { this.capturable_select = select; }
  send_server_config() { sent.push(this.capturable_select.value); }
}
function frame_rate_scale_inv(x) { return 100 * Math.pow(x, 2 / 3); }
'''
        with patch.object(cli, 'backend', return_value='fake'), patch.object(cli, 'run', return_value=SimpleNamespace(stdout=fake_upstream)):
            script = cli.viewer_script(cli.DEFAULTS | {'fps': 60})
        environment = '''
let saved = '{}', sent = [], load, changed, fps = {value:0, dispatchEvent() {}};
const localStorage = {getItem() {return saved;}, setItem(k,v) {saved=v;}};
const select = {options:[], value:'', selectedOptions:[], dispatchEvent() {new Settings().send_server_config();}};
const window = {addEventListener(event, fn) {load=fn;}};
const document = {getElementById(id) {return id === 'window' ? select : fps;}};
class MutationObserver {constructor(fn) {changed=fn;} observe() {}}
class Event {constructor(name) {this.name=name;}}
'''
        assertions = '''
new Settings().send_server_config();
select.selectedOptions = [{textContent:'Desktop'}];
new Settings().send_server_config();
if (sent.length) throw Error('Captured full desktop before monitor selection');
load();
const target = {textContent:'Monitor: AKIMBO-IPAD', value:'1'};
select.options = [{textContent:'Desktop', value:'0'}, target];
select.selectedOptions = [target];
changed();
if (sent.length !== 1 || sent[0] !== '1') throw Error('Virtual monitor was not selected');
if (Math.abs(Math.pow(fps.value / 100, 1.5) - 60) > 0.001) throw Error('Incorrect FPS slider conversion');
const stored = JSON.parse(saved);
if (!stored.uinput_support || stored.stretch || stored.frame_rate !== '60') throw Error('Incorrect viewer defaults');
'''
        result = subprocess.run(['node'], input=environment + script + assertions, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
