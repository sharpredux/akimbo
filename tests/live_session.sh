#!/usr/bin/env bash
# Explicit integration test; changes the desktop briefly and always stops it.
set -euo pipefail
cd "$(dirname "$0")/.."
if systemctl --user is-active --quiet akimbo-display.service; then
    echo 'An Akimbo session is already active; stop it before running this test.' >&2
    exit 1
fi
trap 'akimbo-display stop' EXIT
akimbo-display start
python3 - <<'PY'
from akimbo_display.cli import state_read
from tests.x11_probe import probe, probe_pointer, probe_drag
probe(state_read()['geometry'])
probe_pointer(state_read()['geometry'])
probe_drag(state_read()['geometry'])
PY
node tests/live_stream.mjs
akimbo-display stop
# Verify recovery when the session supervisor is abruptly killed.
akimbo-display start
systemctl --user kill --kill-whom=main --signal=SIGKILL akimbo-display.service
python3 - <<'PY'
import time
from akimbo_display.cli import state_read, service_active
for _ in range(100):
    if not service_active() and state_read() is None:
        print('SIGKILL recovery restored the layout and cleared recovery state.')
        break
    time.sleep(0.1)
else:
    raise SystemExit('Crash recovery did not complete in time.')
PY
