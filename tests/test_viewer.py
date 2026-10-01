import json
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from akimbo_display import cli


@unittest.skipUnless(shutil.which('node'), 'JavaScript runtime unavailable')
class ViewerTests(unittest.TestCase):
    def viewer_script(self, fps=30):
        fake_upstream = '''
class Settings { send_server_config() {} }
function frame_rate_scale_inv(x) { return 100 * Math.pow(x, 2 / 3); }
'''
        with patch.object(cli, 'backend', return_value='fake'), \
             patch.object(cli, 'run', return_value=SimpleNamespace(stdout=fake_upstream)):
            return cli.viewer_script(cli.DEFAULTS | {'fps': fps})

    def run_javascript(self, environment, assertions, script=None):
        result = subprocess.run(['node'], input=environment + (script or self.viewer_script()) + assertions,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_standard_fullscreen_prompt_waits_for_video_and_handles_retry(self):
        environment = '''
let load, requests = 0, exits = 0, legacyRequests = 0;
const localStorage = {getItem() {return '{}';}, setItem() {}};
function element(tag) {
  return {
    tag, style: {}, children: [], listeners: {}, hidden: false, textContent: '',
    appendChild(child) {this.children.push(child);},
    addEventListener(name, fn) {this.listeners[name] = fn;},
    setAttribute() {}
  };
}
const docEvents = {};
const body = element('body');
body.requestFullscreen = function(options) {
  requests++;
  if (this.rejectFullscreen) return Promise.reject(new Error('blocked'));
  if (!options || options.navigationUI !== 'hide') throw Error('Navigation UI was not hidden');
  document.fullscreenElement = body;
  if (docEvents.fullscreenchange) docEvents.fullscreenchange();
  return Promise.resolve();
};
const video = element('video');
video.readyState = 0;
video.webkitDisplayingFullscreen = false;
video.webkitEnterFullscreen = function() {legacyRequests++;};
const settingsButton = element('button');
const document = {
  body, fullscreenEnabled: true, fullscreenElement: null,
  createElement: element,
  getElementById(id) {
    if (id === 'video') return video;
    if (id === 'fullscreen') return settingsButton;
    return null;
  },
  addEventListener(name, fn) {docEvents[name] = fn;},
  exitFullscreen() {
    exits++;
    this.fullscreenElement = null;
    if (docEvents.fullscreenchange) docEvents.fullscreenchange();
    return Promise.resolve();
  }
};
const window = {addEventListener(name, fn) {if (name === 'load') load = fn;}};
'''
        assertions = '''
(async () => {
  load();
  const prompt = body.children[0], button = prompt.children[0], status = prompt.children[1];
  if (!prompt.hidden) throw Error('Fullscreen prompt appeared before video was ready');
  video.listeners.loadeddata();
  if (prompt.hidden || button.textContent !== 'Enter Fullscreen') throw Error('Fullscreen prompt did not appear');
  const event = {preventDefault() {}, stopPropagation() {}};
  await button.listeners.click(event);
  if (requests !== 1 || legacyRequests) throw Error('Standard fullscreen was not preferred');
  if (!prompt.hidden || settingsButton.textContent !== 'Exit Fullscreen') throw Error('Fullscreen UI did not update');
  await settingsButton.onclick(event);
  if (exits !== 1 || prompt.hidden) throw Error('Fullscreen did not exit through settings');
  body.rejectFullscreen = true;
  await button.listeners.click(event);
  if (button.textContent !== 'Try Fullscreen Again' || status.hidden || !status.textContent.includes('blocked'))
    throw Error('Rejected fullscreen did not offer a retry');
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
        self.run_javascript(environment, assertions)

    def test_legacy_video_fullscreen_fallback(self):
        environment = '''
let load, legacyRequests = 0;
const localStorage = {getItem() {return '{}';}, setItem() {}};
function element(tag) {
  return {
    tag, style: {}, children: [], listeners: {}, hidden: false, textContent: '',
    appendChild(child) {this.children.push(child);},
    addEventListener(name, fn) {this.listeners[name] = fn;},
    setAttribute() {}
  };
}
const body = element('body');
const video = element('video');
video.readyState = 2;
video.webkitDisplayingFullscreen = false;
video.webkitEnterFullscreen = function() {
  legacyRequests++;
  video.webkitDisplayingFullscreen = true;
  video.listeners.webkitbeginfullscreen();
};
const document = {
  body, fullscreenElement: null,
  createElement: element,
  getElementById(id) {return id === 'video' ? video : null;},
  addEventListener() {}
};
const window = {addEventListener(name, fn) {if (name === 'load') load = fn;}};
'''
        assertions = '''
(async () => {
  load();
  const prompt = body.children[0], button = prompt.children[0];
  await button.listeners.click({preventDefault() {}, stopPropagation() {}});
  if (legacyRequests !== 1 || !prompt.hidden) throw Error('Legacy video fullscreen was not entered');
  video.webkitDisplayingFullscreen = false;
  video.listeners.webkitendfullscreen();
  if (prompt.hidden) throw Error('Prompt did not return after legacy fullscreen exit');
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
        self.run_javascript(environment, assertions)

    def test_unsupported_browser_explains_fullscreen_limit(self):
        environment = '''
let load;
const localStorage = {getItem() {return '{}';}, setItem() {}};
function element(tag) {
  return {
    tag, style: {}, children: [], listeners: {}, hidden: false, textContent: '',
    appendChild(child) {this.children.push(child);},
    addEventListener(name, fn) {this.listeners[name] = fn;},
    setAttribute() {}
  };
}
const body = element('body');
const video = element('video');
video.readyState = 2;
const document = {
  body, fullscreenElement: null,
  createElement: element,
  getElementById(id) {return id === 'video' ? video : null;},
  addEventListener() {}
};
const window = {addEventListener(name, fn) {if (name === 'load') load = fn;}};
'''
        assertions = '''
load();
const prompt = body.children[0], button = prompt.children[0], status = prompt.children[1];
if (prompt.hidden || !button.hidden || status.hidden || !status.textContent.includes('unavailable'))
  throw Error('Unsupported-browser explanation was not shown');
'''
        self.run_javascript(environment, assertions)
