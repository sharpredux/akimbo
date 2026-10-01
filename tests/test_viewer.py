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
let saved = '{"stretch":false}', sent = [], load, changed, fps = {value:0, dispatchEvent() {}};
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
if (!stored.uinput_support || !stored.stretch || stored.frame_rate !== '60') throw Error('Incorrect viewer defaults');
'''
        result = subprocess.run(['node'], input=environment + script + assertions, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_standard_fullscreen_uses_sidebar_and_hides_while_active(self):
        environment = '''
let load, requests = 0, exits = 0, legacyRequests = 0;
const localStorage = {getItem() {return '{}';}, setItem() {}};
function element(tag) {
  return {
    tag, style: {}, children: [], listeners: {}, hidden: false, textContent: '',
    appendChild(child) {child.parentElement = this; this.children.push(child);},
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
const settingsSection = element('section');
const settingsButton = element('button');
settingsSection.appendChild(settingsButton);
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
  const status = settingsSection.children[1];
  if (body.children.length) throw Error('Fullscreen control was added over the video');
  if (!settingsButton.disabled || settingsButton.textContent !== 'Waiting for Video')
    throw Error('Sidebar button did not wait for video');
  video.listeners.loadeddata();
  if (settingsButton.disabled || settingsButton.textContent !== 'Enter Fullscreen')
    throw Error('Sidebar button did not become available');
  const event = {preventDefault() {}, stopPropagation() {}};
  await settingsButton.onclick(event);
  if (requests !== 1 || legacyRequests) throw Error('Standard fullscreen was not preferred');
  if (!settingsButton.hidden || settingsButton.style.display !== 'none')
    throw Error('Sidebar button remained visible in fullscreen');
  await document.exitFullscreen();
  if (exits !== 1 || settingsButton.hidden || settingsButton.style.display !== 'block' ||
      settingsButton.textContent !== 'Enter Fullscreen')
    throw Error('Sidebar button did not return after native fullscreen exit');
  body.rejectFullscreen = true;
  await settingsButton.onclick(event);
  if (settingsButton.textContent !== 'Try Fullscreen Again' || status.hidden || !status.textContent.includes('blocked'))
    throw Error('Rejected fullscreen did not offer a sidebar retry');
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
    appendChild(child) {child.parentElement = this; this.children.push(child);},
    addEventListener(name, fn) {this.listeners[name] = fn;},
    setAttribute() {}
  };
}
const body = element('body');
const videoSection = element('section');
const enableVideo = element('input');
enableVideo.closest = function(selector) {return selector === 'section' ? videoSection : null;};
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
  getElementById(id) {
    if (id === 'video') return video;
    if (id === 'enable_video') return enableVideo;
    return null;
  },
  addEventListener() {}
};
const window = {addEventListener(name, fn) {if (name === 'load') load = fn;}};
'''
        assertions = '''
(async () => {
  load();
  const button = videoSection.children[0];
  if (!button || button.id !== 'fullscreen') throw Error('Legacy sidebar button was not restored');
  if (body.children.length) throw Error('Legacy control was added over the video');
  await button.onclick({preventDefault() {}, stopPropagation() {}});
  if (legacyRequests !== 1 || !button.hidden || button.style.display !== 'none')
    throw Error('Legacy video fullscreen was not entered');
  video.webkitDisplayingFullscreen = false;
  video.listeners.webkitendfullscreen();
  if (button.hidden || button.style.display !== 'block' || button.textContent !== 'Enter Fullscreen')
    throw Error('Sidebar button did not return after legacy fullscreen exit');
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
    appendChild(child) {child.parentElement = this; this.children.push(child);},
    addEventListener(name, fn) {this.listeners[name] = fn;},
    setAttribute() {}
  };
}
const body = element('body');
const videoSection = element('section');
const enableVideo = element('input');
enableVideo.closest = function(selector) {return selector === 'section' ? videoSection : null;};
const video = element('video');
video.readyState = 2;
const document = {
  body, fullscreenElement: null,
  createElement: element,
  getElementById(id) {
    if (id === 'video') return video;
    if (id === 'enable_video') return enableVideo;
    return null;
  },
  addEventListener() {}
};
const window = {addEventListener(name, fn) {if (name === 'load') load = fn;}};
'''
        assertions = '''
load();
const button = videoSection.children[0], status = videoSection.children[1];
if (!button.disabled || button.textContent !== 'Fullscreen Unavailable' ||
    status.hidden || status.style.display !== 'block' ||
    !status.textContent.includes('unavailable') || body.children.length)
  throw Error('Unsupported-browser explanation was not kept in the sidebar');
'''
        self.run_javascript(environment, assertions)
