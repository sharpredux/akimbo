#!/usr/bin/env bash
set -euo pipefail
akimbo_uid=${1:?user id required}
if [[ $(id -u) != 0 ]]; then
    exec sudo bash "$0" "$akimbo_uid"
fi
akimbo_user=$(getent passwd "$akimbo_uid" | cut -d: -f1)
[[ -n $akimbo_user && $akimbo_uid != 0 ]] || exit 1
python3 - <<'PY'
import json, pathlib, subprocess
state = pathlib.Path('/var/lib/akimbo-display/firewall.json')
if state.exists():
    for entry in json.loads(state.read_text()):
        for permanent in ([], ['--permanent']):
            subprocess.run(['firewall-cmd', *permanent, '--zone=' + entry['zone'], '--remove-rich-rule=' + entry['rule']], check=True)
    state.unlink()
for name in ('/etc/udev/rules.d/70-akimbo-uinput.rules', '/etc/modules-load.d/akimbo-uinput.conf'):
    pathlib.Path(name).unlink(missing_ok=True)
PY
gpasswd -d "$akimbo_user" akimbo-uinput || true
udevadm control --reload-rules
udevadm trigger --subsystem-match=misc
echo 'Akimbo system rules removed. Installed Fedora packages and user data were retained.'
