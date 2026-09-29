"""Explicit live smoke test: add one monitor briefly, with a recovery watchdog."""
import json
import os
import subprocess
import sys
from akimbo_display import cli
from tests.x11_probe import probe, probe_pointer

cli.session()
if cli.service_active() or cli.state_read():
    raise SystemExit('Stop or repair Akimbo before running the live layout test.')
original = cli.layout_snapshot()
plan = cli.geometry(original, *cli.dimensions(cli.DEFAULTS), 'below')
virtual_output = cli.unused_output(cli.xrandr('--current'))
state = dict(original=original, geometry=plan, virtual_output=virtual_output, phase='testing',
             boot_id=cli.boot_id(),
             environment={k: os.environ[k] for k in ('DISPLAY', 'XAUTHORITY', 'XDG_SESSION_TYPE') if k in os.environ})
cli.save_state(state)
# A separate process restores the layout even if this test process is interrupted.
watchdog = subprocess.Popen([sys.executable, '-c',
    'import time; time.sleep(15); from akimbo_display.cli import repair; repair()'],
    start_new_session=True)
try:
    cli.apply_layout(plan, cli.DEFAULTS, virtual_output)
    print(cli.xrandr('--listactivemonitors'))
    print(json.dumps(cli.parse_layout(cli.xrandr('--current')), indent=2))
    probe(plan)
    probe_pointer(plan)
finally:
    cli.restore(state)
    cli.clear_state()
    watchdog.terminate()
    watchdog.wait()
assert cli.parse_layout(cli.xrandr('--current')) == {k:v for k,v in original.items() if k != 'compositing'}
assert cli.mode_line(plan['w'], plan['h'])[0] not in cli.xrandr('--current')
print('Live virtual monitor created and original layout restored exactly.')
