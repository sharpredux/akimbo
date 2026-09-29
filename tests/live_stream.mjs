// Explicit integration test against a running local Akimbo session (Node 22+).
// No input events are injected and the access code is never printed.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';

const runtime = process.env.XDG_RUNTIME_DIR || `/run/user/${process.getuid()}`;
const state = JSON.parse(fs.readFileSync(path.join(runtime, 'akimbo-display/state.json')));
const config = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config');
const code = fs.readFileSync(path.join(config, 'akimbo-display/access-code'), 'utf8').trim();
const base = `http://${state.network.address}:1701`;
const denied = await fetch(`${base}/ws?access_code=wrong-test-code`);
assert.equal(denied.status, 401, 'Incorrect access codes must be rejected');
const html = await fetch(`${base}/?access_code=${encodeURIComponent(code)}`);
assert.equal(html.status, 200);
assert.match(await html.text(), /id="video"/);

await new Promise((resolve, reject) => {
  const ws = new WebSocket(`${base.replace('http:', 'ws:')}/ws?access_code=${encodeURIComponent(code)}`);
  ws.binaryType = 'arraybuffer';
  let frames = 0, bytes = 0, hasHeader = false, configured = false, done = false;
  const timeout = setTimeout(() => finish(new Error('Timed out waiting for encoded video')), 15000);
  function finish(error) {
    if (done) return;
    done = true;
    clearTimeout(timeout);
    ws.close();
    if (error) reject(error);
    else {
      console.log(`Authenticated monitor stream: ${frames} binary messages, ${bytes} bytes, MP4 header verified; touch device initialized.`);
      resolve();
    }
  }
  ws.onopen = () => ws.send(JSON.stringify('GetCapturableList'));
  ws.onerror = () => finish(new Error('WebSocket failed'));
  ws.onclose = () => { if (!done) finish(new Error('Stream closed early')); };
  ws.onmessage = ({data}) => {
    try {
      if (typeof data === 'string') {
        const message = JSON.parse(data);
        if (message.CapturableList) {
          const index = message.CapturableList.indexOf('Monitor: AKIMBO-IPAD');
          assert.notEqual(index, -1, 'Named iPad monitor must be capturable');
          ws.send(JSON.stringify({Config: {
            uinput_support: true, capturable_id: index, capture_cursor: true,
            max_width: state.geometry.w, max_height: state.geometry.h,
            client_name: 'Akimbo smoke test', frame_rate: 30,
          }}));
        }
        if (message === 'ConfigOk') configured = true;
        if (message.Error || message.ConfigError) finish(new Error(message.Error || message.ConfigError));
      } else {
        const buffer = Buffer.from(data);
        frames++;
        bytes += buffer.length;
        hasHeader ||= buffer.includes(Buffer.from('ftyp'));
        if (frames >= 8 && configured && hasHeader) finish();
      }
    } catch (error) { finish(error); }
  };
});
