#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run through sudo.' >&2; exit 1; }
akimbo_uid=${1:?user id required}
[[ $akimbo_uid =~ ^[0-9]+$ && $akimbo_uid != 0 ]] || exit 1
akimbo_user=$(getent passwd "$akimbo_uid" | cut -d: -f1)
[[ -n $akimbo_user ]] || exit 1
getent group akimbo-uinput >/dev/null || groupadd --system akimbo-uinput
usermod -aG akimbo-uinput "$akimbo_user"
install -d -m 0755 /etc/udev/rules.d /etc/modules-load.d
printf '%s\n' 'KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="akimbo-uinput", MODE="0660", OPTIONS+="static_node=uinput"' > /etc/udev/rules.d/70-akimbo-uinput.rules
printf '%s\n' uinput > /etc/modules-load.d/akimbo-uinput.conf
modprobe uinput
udevadm control --reload-rules
udevadm trigger --subsystem-match=misc
# Grant access only to private subnets of currently attached supported interfaces.
# Rerun setup-network after attaching USB for the first time or changing networks.
if systemctl is-active --quiet firewalld; then
    install -d -m 0700 /var/lib/akimbo-display
    python3 - <<'PY'
import ipaddress, json, pathlib, subprocess
state = pathlib.Path('/var/lib/akimbo-display/firewall.json')
owned = json.loads(state.read_text()) if state.exists() else []
links = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show', 'up']))
for link in links:
    base = pathlib.Path('/sys/class/net') / link['ifname']
    if not (base / 'wireless').exists() and (base / 'device/driver').resolve().name != 'ipheth':
        continue
    zone = subprocess.run(['firewall-cmd', '--get-zone-of-interface=' + link['ifname']], text=True, capture_output=True).stdout.strip()
    if not zone or zone == 'no zone':
        zone = subprocess.check_output(['firewall-cmd', '--get-default-zone'], text=True).strip()
    for a in link.get('addr_info', []):
        if a.get('scope') != 'global': continue
        net = ipaddress.ip_network(f"{a['local']}/{a['prefixlen']}", strict=False)
        if not net.is_private: continue
        rule = f'rule family="ipv4" source address="{net}" port port="1701" protocol="tcp" accept'
        query = ['firewall-cmd', '--permanent', '--zone=' + zone, '--query-rich-rule=' + rule]
        existed = subprocess.run(query, capture_output=True).returncode == 0
        if not existed:
            subprocess.run(['firewall-cmd', '--permanent', '--zone=' + zone, '--add-rich-rule=' + rule], check=True)
            owned.append({'zone': zone, 'rule': rule})
            state.write_text(json.dumps(owned, indent=2))
        subprocess.run(['firewall-cmd', '--zone=' + zone, '--add-rich-rule=' + rule], check=True)
PY
fi
