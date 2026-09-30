"""Akimbo's standard-library-only display/session controller."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "akimbo-display"
DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "akimbo-display"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "akimbo-display"
MONITOR = "AKIMBO-IPAD"
SERVICE = "akimbo-display.service"
DEFAULTS = dict(model="ipad-mini-7", orientation="landscape", quality="balanced",
                position="below", transport="auto", resolution="", fps=30, encoder="auto")
MODELS = json.loads((Path(__file__).parent / "models.json").read_text())


class Error(Exception):
    pass


def run(args, check=True, **kwargs):
    kwargs.setdefault("timeout", 20)
    try:
        result = subprocess.run([str(a) for a in args], text=True, capture_output=True, **kwargs)
    except subprocess.TimeoutExpired:
        raise Error(f"{args[0]} timed out after {kwargs['timeout']} seconds.") from None
    if check and result.returncode:
        raise Error(f"{args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def atomic(path, text):
    private_dir(path.parent)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(text)
    os.replace(temp, path)


def write_json(path, value):
    atomic(path, json.dumps(value, indent=2) + "\n")


def config():
    path = CONFIG / "config.toml"
    return DEFAULTS | (tomllib.loads(path.read_text()) if path.exists() else {})


def save_config(cfg):
    atomic(CONFIG / "config.toml", "\n".join(f"{k} = {json.dumps(v)}" for k, v in cfg.items()) + "\n")


def options(args):
    cfg = config()
    for key in DEFAULTS:
        val = getattr(args, key, None)
        if val is not None:
            cfg[key] = val
    dimensions(cfg)
    for key, allowed in dict(position=("above", "below", "left", "right"),
                             orientation=("portrait", "landscape"),
                             quality=("performance", "balanced", "native"),
                             transport=("auto", "usb", "wifi"),
                             encoder=("auto", "software", "vaapi")).items():
        if cfg[key] not in allowed:
            raise Error(f"Invalid {key}: {cfg[key]}")
    if not 1 <= cfg["fps"] <= 60:
        raise Error("FPS must be between 1 and 60.")
    return cfg


def dimensions(cfg):
    model = cfg["model"]
    if model != "custom" and model not in MODELS:
        raise Error(f"Unknown model {model!r}; use 'models list' or --model custom.")
    if cfg["resolution"]:
        match = re.fullmatch(r"(\d+)x(\d+)", cfg["resolution"])
        if not match:
            raise Error("Resolution must be WIDTHxHEIGHT, for example 1510x992.")
        w, h = map(int, match.groups())
    elif model == "custom":
        raise Error("The custom model requires --resolution WIDTHxHEIGHT.")
    else:
        scale = {"performance": 0.5, "balanced": 2 / 3, "native": 1}.get(cfg["quality"])
        if scale is None:
            raise Error("Unknown quality preset.")
        w, h = (int(v * scale) // 2 * 2 for v in MODELS[model]["native"])
    if min(w, h) < 320 or max(w, h) > 8192 or w % 2 or h % 2:
        raise Error("Dimensions must be even and between 320 and 8192 for H.264.")
    w, h = max(w, h), min(w, h)
    return (h, w) if cfg["orientation"] == "portrait" else (w, h)


def xrandr(*args):
    binary = shutil.which("xrandr") or str(DATA / "bin/xrandr")
    return run([binary, *args]).stdout


def unused_output(text):
    for line in text.splitlines():
        match = re.match(r"^(\S+) disconnected \(", line)
        if match:
            return match[1]
    raise Error("No unused display connector is available. A RandR monitor without a real output clips the mouse; disconnect an unused HDMI/DP output or use a virtual display driver.")


def mode_line(width, height):
    # GTF uses 8-pixel horizontal granularity. A slightly wider CRTC backs
    # the exact-sized capture monitor without changing its iPad resolution.
    mode_width = (width + 7) // 8 * 8
    result = run(["gtf", str(mode_width), str(height), "30"]).stdout
    match = re.search(r'^\s*Modeline\s+(.+)$', result, re.M)
    if not match:
        raise Error("gtf did not return an X11 modeline.")
    values = shlex.split(match[1])
    name = f"AKIMBO-{mode_width}x{height}-30"
    return name, [name, *values[1:]]


def parse_layout(text):
    header = re.search(r"current (\d+) x (\d+), maximum (\d+) x (\d+)", text)
    if not header:
        raise Error("Cannot read X11 framebuffer geometry.")
    outputs = []
    for line in text.splitlines():
        match = re.match(r"(\S+) connected (primary )?(\d+)x(\d+)\+(\d+)\+(\d+) (.*)", line)
        if match:
            name, primary, w, h, x, y, rest = match.groups()
            # The reversible layout implementation deliberately rejects transforms/rotation.
            if not rest.startswith("(normal "):
                raise Error("Rotated/reflected physical outputs are not supported yet.")
            outputs.append(dict(name=name, primary=bool(primary), w=int(w), h=int(h), x=int(x), y=int(y)))
    if not outputs:
        raise Error("No active physical X11 outputs found.")
    return dict(width=int(header[1]), height=int(header[2]),
                max_width=int(header[3]), max_height=int(header[4]), outputs=outputs)


def geometry(layout, width, height, position):
    outputs = [dict(o) for o in layout["outputs"]]
    left = min(o["x"] for o in outputs)
    top = min(o["y"] for o in outputs)
    right = max(o["x"] + o["w"] for o in outputs)
    bottom = max(o["y"] + o["h"] for o in outputs)
    x = (left + right - width) // 2
    y = (top + bottom - height) // 2
    if position == "below": y = bottom
    elif position == "above": y = top - height
    elif position == "left": x = left - width
    elif position == "right": x = right
    dx, dy = max(0, -x), max(0, -y)
    for o in outputs:
        o["x"] += dx
        o["y"] += dy
    x, y = x + dx, y + dy
    mode_width = (width + 7) // 8 * 8
    fw, fh = max(right + dx, x + mode_width, layout["width"] + dx), max(bottom + dy, y + height, layout["height"] + dy)
    if fw > layout["max_width"] or fh > layout["max_height"]:
        raise Error("Requested layout exceeds the X11 framebuffer limit.")
    return dict(x=x, y=y, w=width, h=height, width=fw, height=fh, outputs=outputs)


def choose_network(transport):
    links = json.loads(run(["ip", "-j", "-4", "address", "show", "up"]).stdout)
    candidates = []
    for link in links:
        name = link["ifname"]
        if name == "lo": continue
        base = Path("/sys/class/net") / name
        driver = (base / "device/driver").resolve().name
        kind = "usb" if driver == "ipheth" else "wifi" if (base / "wireless").exists() else None
        if kind is None or transport not in ("auto", kind): continue
        for address in link.get("addr_info", []):
            if address.get("scope") == "global" and ipaddress.ip_address(address["local"]).is_private:
                candidates.append(dict(interface=name, address=address["local"], transport=kind,
                                       subnet=str(ipaddress.ip_network(f'{address["local"]}/{address["prefixlen"]}', strict=False))))
    if not candidates:
        raise Error(f"No usable {transport} link. Enable USB Personal Hotspot and Trust This Computer, or connect Wi-Fi.")
    return sorted(candidates, key=lambda c: (c["transport"] != "usb", c["interface"]))[0]


def session():
    if os.environ.get("XDG_SESSION_TYPE") != "x11" or not os.environ.get("DISPLAY"):
        raise Error("Run this from a terminal inside your XFCE X11 session.")


def layout_snapshot():
    layout = parse_layout(xrandr("--current"))
    verbose = xrandr("--verbose")
    for transform in re.findall(r"Transform:\s+([^\n]+)\n\s+([^\n]+)\n\s+([^\n]+)", verbose):
        nums = [float(v) for row in transform for v in row.split()]
        if nums != [1., 0., 0., 0., 1., 0., 0., 0., 1.]:
            raise Error("Scaled/transformed physical outputs require a custom layout; refusing to change them.")
    if MONITOR in xrandr("--listmonitors"):
        raise Error("An AKIMBO-IPAD monitor already exists; run repair first.")
    layout["compositing"] = run(["xfconf-query", "-c", "xfwm4", "-p", "/general/use_compositing"]).stdout.strip()
    return layout


def panel_numbers():
    result = run(["xfconf-query", "-c", "xfce4-panel", "-p", "/panels"], check=False)
    if result.returncode:
        return []
    return re.findall(r"(?m)^\s*(\d+)\s*$", result.stdout)


def panel_value(prop, value_type):
    result = run(["xfconf-query", "-c", "xfce4-panel", "-p", prop], check=False)
    if result.returncode:
        return None
    value = result.stdout.strip()
    try:
        return int(value) if value_type == "int" else value
    except ValueError:
        return None


def panel_settings(target):
    """Return only the reversible XFCE panel changes needed by a session."""
    settings = {}
    for number in panel_numbers():
        base = f"/panels/panel-{number}"
        output_prop = base + "/output-name"
        output = panel_value(output_prop, "string")
        if output in (None, "Automatic"):
            settings[output_prop] = dict(type="string", original=output, session=target)

        # XFCE's animated hide uses the full X11 framebuffer edge. When the
        # iPad is below the laptop, that animation moves the panel through the
        # iPad instead of just beyond the laptop edge.
        speed_prop = base + "/popdown-speed"
        speed = panel_value(speed_prop, "int")
        if speed != 0:
            settings[speed_prop] = dict(type="int", original=speed, session=0)

        # XFCE raises an always-visible panel when fullscreen video loses focus
        # to the other monitor. Intelligent hiding has the same problem because
        # it follows only the focused window. Always-hide avoids both cases.
        behavior_prop = base + "/autohide-behavior"
        behavior = panel_value(behavior_prop, "int")
        settings[behavior_prop] = dict(type="int", original=behavior, temporary=0, session=2)
    return settings


def set_panel_value(prop, value, value_type, create=False):
    args = ["xfconf-query", "-c", "xfce4-panel", "-p", prop]
    if create:
        args += ["-n", "-t", value_type]
    run([*args, "-s", str(value)])


def prepare_panels(state):
    """Pin panels and make hidden panels visible before XFWM is replaced."""
    for prop, setting in state.get("panel_settings", {}).items():
        if prop.endswith("/output-name"):
            set_panel_value(prop, setting["session"], setting["type"], setting["original"] is None)
        elif prop.endswith("/autohide-behavior") and setting["original"] not in (None, 0):
            set_panel_value(prop, setting["temporary"], setting["type"])


def hide_panels(state):
    """Hide panels after replacement XFWM has adopted their visible windows."""
    for prop, setting in state.get("panel_settings", {}).items():
        if prop.endswith(("/popdown-speed", "/autohide-behavior")):
            set_panel_value(prop, setting["session"], setting["type"], setting["original"] is None)


def restore_panels(state):
    for prop, setting in state.get("panel_settings", {}).items():
        current = panel_value(prop, setting["type"])
        # Respect a change made by the user while the iPad was running.
        expected = (setting["session"],)
        if state.get("phase") == "starting" and "temporary" in setting:
            expected += (setting["temporary"],)
        if current not in expected:
            continue
        if setting["original"] is None:
            run(["xfconf-query", "-c", "xfce4-panel", "-p", prop, "-r"])
        else:
            set_panel_value(prop, setting["original"], setting["type"])

    # Recovery snapshots written by releases before panel_settings existed.
    target = state.get("panel_target")
    for prop, previous in state.get("panel_outputs", {}).items():
        if previous not in (None, "Automatic"):
            continue
        current = run(["xfconf-query", "-c", "xfce4-panel", "-p", prop], check=False)
        if current.returncode or current.stdout.strip() != target:
            continue
        args = ["xfconf-query", "-c", "xfce4-panel", "-p", prop]
        run([*args, "-r"] if previous is None else [*args, "-s", previous])


def build_xfce_shim():
    source = ROOT / "scripts/xfce-virtual-output.c"
    target = DATA / "bin/xfce-virtual-output.so"
    if target.exists() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return target
    private_dir(target.parent)
    temp = target.with_suffix(".so.tmp")
    try:
        run(["gcc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-o", temp,
             source, "-ldl", "-lXrandr"], timeout=30)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def replace_xfwm(state, shim=None):
    unit = f'akimbo-xfwm-{("virtual" if shim else "normal")}-{secrets.token_hex(4)}'
    args = ["systemd-run", "--user", "--unit", unit, "--collect",
            "--property=PartOf=graphical-session.target"]
    for key in ("DISPLAY", "XAUTHORITY"):
        value = os.environ.get(key)
        if value:
            args.append(f"--setenv={key}={value}")
    if shim:
        args += [f"--setenv=AKIMBO_VIRTUAL_OUTPUT={state['virtual_output']}",
                 f"--setenv=LD_PRELOAD={shim}"]
    args += [shutil.which("xfwm4") or "xfwm4", "--replace"]
    if shim:
        args.append("--compositor=off")
    run(args)


def wait_desktop_geometry(plan):
    expected = (plan["width"], plan["height"])
    for _ in range(40):
        value = run(["xprop", "-root", "_NET_DESKTOP_GEOMETRY"], check=False)
        match = re.search(r"=\s*(\d+),\s*(\d+)", value.stdout)
        if match and tuple(map(int, match.groups())) == expected:
            return
        time.sleep(0.1)
    raise Error("XFCE did not recognize the iPad monitor; display layout will be restored.")


def apply_layout(plan, cfg, output):
    # XFWM's compositor clips repainting to physical outputs. Disabling it for
    # this session makes the unbacked RandR region render into the root image.
    run(["xfconf-query", "-c", "xfwm4", "-p", "/general/use_compositing", "-s", "false"])
    # Expand first so moving outputs cannot exceed the current framebuffer.
    xrandr("--fb", f'{plan["width"]}x{plan["height"]}')
    args = []
    for o in plan["outputs"]:
        args += ["--output", o["name"], "--pos", f'{o["x"]}x{o["y"]}']
    xrandr(*args, "--fb", f'{plan["width"]}x{plan["height"]}')
    mode_name, modeline = mode_line(plan["w"], plan["h"])
    xrandr("--newmode", *modeline)
    xrandr("--addmode", output, mode_name)
    xrandr("--output", output, "--mode", mode_name, "--pos", f'{plan["x"]}x{plan["y"]}',
           "--fb", f'{plan["width"]}x{plan["height"]}')
    model = MODELS.get(cfg["model"])
    if model:
        native = sorted(model["native"], reverse=cfg["orientation"] == "landscape")
        mmw, mmh = (round(p / model["ppi"] * 25.4) for p in native)
    else:
        mmw, mmh = (round(plan[k] / 96 * 25.4) for k in ("w", "h"))
    rect = f'{plan["w"]}/{mmw}x{plan["h"]}/{mmh}+{plan["x"]}+{plan["y"]}'
    xrandr("--setmonitor", MONITOR, rect, output)
    time.sleep(1)
    actual = parse_layout(xrandr("--current"))
    if (actual["width"], actual["height"]) != (plan["width"], plan["height"]) or MONITOR not in xrandr("--listactivemonitors"):
        raise Error("XFCE/Xorg did not retain the virtual monitor. Original layout will be restored.")


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def restore(state):
    same_boot = state.get("boot_id", boot_id()) == boot_id()
    try:
        # A reboot creates a fresh X server; leave its physical layout alone.
        if same_boot:
            _restore_layout(state)
    finally:
        try:
            restore_panels(state)
        finally:
            try:
                if same_boot and state.get("wm_shim_started"):
                    replace_xfwm(state)
            finally:
                original = state["original"].get("compositing")
                if original in ("true", "false"):
                    run(["xfconf-query", "-c", "xfwm4", "-p", "/general/use_compositing", "-s", original])


def _restore_layout(state):
    os.environ.update(state.get("environment", {}))
    current = parse_layout(xrandr("--current"))
    original = state["original"]
    if MONITOR in xrandr("--listmonitors"):
        xrandr("--delmonitor", MONITOR)
    output = state.get("virtual_output")
    if output:
        mode_name, _ = mode_line(state["geometry"]["w"], state["geometry"]["h"])
        if mode_name in xrandr("--current"):
            xrandr("--output", output, "--off")
            binary = shutil.which("xrandr") or str(DATA / "bin/xrandr")
            run([binary, "--delmode", output, mode_name], check=False)
            run([binary, "--rmmode", mode_name], check=False)
    # Do not re-enable unplugged screens or overwrite an unrelated new topology.
    if {o["name"] for o in current["outputs"]} != {o["name"] for o in original["outputs"]}:
        raise Error("Physical display connections changed. Virtual monitor removed; recovery snapshot retained. Restore connections and run repair.")
    args = []
    for o in original["outputs"]:
        args += ["--output", o["name"], "--pos", f'{o["x"]}x{o["y"]}']
    xrandr(*args)
    xrandr("--fb", f'{original["width"]}x{original["height"]}')


def state_read():
    for path in (RUNTIME / "state.json", CONFIG / "recovery.json"):
        if path.exists(): return json.loads(path.read_text())
    return None


def save_state(state):
    # The persistent copy restores compositor preferences after a hard reboot.
    write_json(CONFIG / "recovery.json", state)
    write_json(RUNTIME / "state.json", state)


def clear_state():
    (RUNTIME / "state.json").unlink(missing_ok=True)
    (CONFIG / "recovery.json").unlink(missing_ok=True)


def service_active():
    return run(["systemctl", "--user", "is-active", "--quiet", SERVICE], check=False).returncode == 0


def firewall_check(net):
    if run(["systemctl", "is-active", "--quiet", "firewalld"], check=False).returncode:
        return "firewalld inactive; check any other host firewall manually"
    if not shutil.which("busctl"):
        return "UNVERIFIED: run setup-network to install the firewall rule"
    prefix = ["busctl", "--system", "--allow-interactive-authorization=no", "--timeout=3", "call",
              "org.fedoraproject.FirewallD1", "/org/fedoraproject/FirewallD1"]
    iface = "org.fedoraproject.FirewallD1.zone"
    try:
        result = run([*prefix, iface, "getZoneOfInterface", "s", net["interface"]], check=False, timeout=4)
        if result.returncode: return "UNVERIFIED: firewalld requires administrator access; use setup-network"
        zone = json.loads(result.stdout.strip().split(" ", 1)[1])
        if not zone:
            result = run([*prefix, "org.fedoraproject.FirewallD1", "getDefaultZone"], check=False, timeout=4)
            if result.returncode: return "UNVERIFIED: cannot query the default firewall zone"
            zone = json.loads(result.stdout.strip().split(" ", 1)[1])
    except (Error, ValueError, IndexError):
        return "UNVERIFIED: firewall query unavailable; use setup-network"
    rule = f'rule family="ipv4" source address="{net["subnet"]}" port port="1701" protocol="tcp" accept'
    for method, sig, values in (("queryRichRule", "ss", [zone, rule]), ("queryPort", "sss", [zone, "1701", "tcp"])):
        try:
            result = run([*prefix, iface, method, sig, *values], check=False, timeout=4)
        except Error:
            return "UNVERIFIED: firewall query unavailable; use setup-network"
        if result.returncode:
            return "UNVERIFIED: firewalld requires administrator access; use setup-network"
        if result.stdout.strip() == "b true":
            return f'{zone}: port 1701 permitted for {net["subnet"]}'
    raise Error("Firewall rule missing for this network. Run 'akimbo-display setup-network' with the iPad connected.")


def backend():
    executable = DATA / "bin/weylus"
    if not executable.exists():
        raise Error("Weylus is not installed. Run 'akimbo-display install' in your laptop terminal.")
    return executable


def encoder(cfg):
    if cfg["encoder"] == "software": return "software"
    if shutil.which("vainfo"):
        try:
            result = run(["vainfo", "--display", "drm", "--device", "/dev/dri/renderD128"], check=False, timeout=5)
        except Error:
            result = None
        if result is not None and result.returncode == 0 and re.search(r"VAProfileH264\w*\s*:\s*VAEntrypointEncSlice", result.stdout + result.stderr):
            return "vaapi"
    if cfg["encoder"] == "vaapi":
        raise Error("H.264 VAAPI encoding unavailable; use --encoder software or auto.")
    return "software"


def viewer_script(cfg):
    # Upstream's override hook keeps its player/input implementation intact.
    script = run([backend(), "--print-lib-js"]).stdout
    defaults = dict(frame_rate=str(cfg["fps"]), uinput_support=True, capture_cursor=True,
                    enable_touch=True, enable_mouse=True, enable_stylus=True, stretch=False,
                    enable_video=True, energysaving=False, scale_video="1")
    prelude = f'''// Seed settings before upstream initializes its controls.
try {{
  const stored = JSON.parse(localStorage.getItem('settings') || '{{}}');
  localStorage.setItem('settings', JSON.stringify(Object.assign(stored, {json.dumps(defaults)})));
}} catch (error) {{ console.warn('Cannot persist Akimbo viewer defaults', error); }}
'''
    return prelude + script + f'''\n// Akimbo saved viewer defaults. Do not select the full desktop by accident.
const akimboSendConfig = Settings.prototype.send_server_config;
Settings.prototype.send_server_config = function() {{
  const option = this.capturable_select.selectedOptions[0];
  if (!option || option.textContent !== 'Monitor: AKIMBO-IPAD') return;
  return akimboSendConfig.call(this);
}};
window.addEventListener('load', () => {{
  const select = document.getElementById('window');
  if (!select) return;
  let applied = false;
  const apply = () => {{
    const item = Array.from(select.options).find(o => o.textContent === 'Monitor: AKIMBO-IPAD');
    if (!item || applied) return;
    applied = true;
    select.value = item.value;
    const fps = document.getElementById('frame_rate');
    if (fps) {{ fps.value = frame_rate_scale_inv({cfg['fps']}); fps.dispatchEvent(new Event('input')); }}
    select.dispatchEvent(new Event('change'));
  }};
  new MutationObserver(apply).observe(select, {{childList:true}});
  apply();
}});\n'''


def serve():
    private_dir(RUNTIME)
    with (RUNTIME / "session.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if state_read(): raise Error("Recovery state exists; run repair before starting.")
        request = json.loads((RUNTIME / "request.json").read_text())
        cfg = request["config"]
        os.environ.update(request["environment"])
        session()
        executable = backend()
        if not os.access("/dev/uinput", os.W_OK):
            raise Error("Touch permission missing. Run install, then log out and back in.")
        net = choose_network(cfg["transport"])
        firewall_check(net)
        # Catch an occupied port before changing the user's display arrangement.
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try: probe.bind((net["address"], 1701))
            except OSError as exc: raise Error(f"Cannot bind {net['address']}:1701: {exc}")
        original = layout_snapshot()
        plan = geometry(original, *dimensions(cfg), cfg["position"])
        virtual_output = unused_output(xrandr("--current"))
        shim = build_xfce_shim()
        laptop_output = next((o["name"] for o in original["outputs"] if o["name"].startswith("eDP")), None)
        physical_primary = next((o["name"] for o in original["outputs"] if o["primary"]), None)
        panel_target = laptop_output or physical_primary or original["outputs"][0]["name"]
        selected_encoder = encoder(cfg)
        state = dict(original=original, geometry=plan, virtual_output=virtual_output, config=cfg, network=net,
                     encoder=selected_encoder, environment=request["environment"], phase="starting", boot_id=boot_id(),
                     panel_settings=panel_settings(panel_target), panel_target=panel_target, wm_shim_started=False)
        save_state(state)
        process = None
        stopping = False
        def stop_signal(*_):
            nonlocal stopping
            stopping = True
        signal.signal(signal.SIGTERM, stop_signal)
        signal.signal(signal.SIGINT, stop_signal)
        try:
            # Pin panels before the framebuffer changes. Existing hidden panels
            # are shown so replacement XFWM adopts them at their real position.
            prepare_panels(state)
            apply_layout(plan, cfg, virtual_output)
            state["wm_shim_started"] = True
            save_state(state)
            replace_xfwm(state, shim)
            # Hide only after replacement XFWM is in control. Otherwise it can
            # relocate XFCE's far-offscreen hidden windows to the top-left.
            hide_panels(state)
            wait_desktop_geometry(plan)
            atomic(RUNTIME / "viewer.js", viewer_script(cfg))
            # Avoid placing the access code in argv, the URL, or the journal.
            code = (CONFIG / "access-code").read_text().strip()
            isolated = RUNTIME / "backend-config/weylus"
            atomic(isolated / "weylus.toml", '\n'.join([
                f'access_code = {json.dumps(code)}', f'bind_address = {json.dumps(net["address"])}',
                'web_port = 1701', 'try_vaapi = ' + str(selected_encoder == "vaapi").lower(),
                'no_gui = true', 'auto_start = true', 'wayland_support = false']) + '\n')
            env = os.environ | {"XDG_CONFIG_HOME": str(isolated.parent), "WEYLUS_VAAPI_DEVICE": "/dev/dri/renderD128"}
            process = subprocess.Popen([str(executable), "--no-gui", "--bind-address", net["address"],
                                        "--custom-lib-js", str(RUNTIME / "viewer.js")], env=env)
            deadline = time.monotonic() + 15
            while not stopping and time.monotonic() < deadline:
                if process.poll() is not None: raise Error("Weylus exited; inspect journalctl --user -u akimbo-display.")
                try:
                    with socket.create_connection((net["address"], 1701), timeout=0.3): break
                except OSError: time.sleep(0.2)
            else:
                raise Error("Weylus did not become ready.")
            state["phase"] = "running"
            save_state(state)
            while not stopping:
                if process.poll() is not None: raise Error("Weylus stopped unexpectedly.")
                time.sleep(1)
                actual = parse_layout(xrandr("--current"))
                if actual["outputs"] != plan["outputs"] or (actual["width"], actual["height"]) != (plan["width"], plan["height"]):
                    raise Error("Display layout changed during streaming; stopping for recovery.")
        finally:
            if process and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            restore(state)
            clear_state()


def start(args):
    session()
    if service_active(): raise Error("Already running. Use restart to apply settings or switch networks.")
    if state_read(): raise Error("Recovery snapshot exists. Run repair first.")
    cfg = options(args)
    backend()
    env = {k: os.environ[k] for k in ("DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE") if k in os.environ}
    write_json(RUNTIME / "request.json", dict(config=cfg, environment=env))
    run(["systemctl", "--user", "reset-failed", SERVICE], check=False)
    run(["systemctl", "--user", "start", SERVICE])
    for _ in range(100):
        state = state_read()
        if state and state["phase"] == "running":
            print(f'{state["geometry"]["w"]}x{state["geometry"]["h"]} {cfg["position"]}; {state["encoder"]}; {state["network"]["transport"]}')
            show_url(True)
            return
        if not service_active():
            raise Error("Start failed. See: journalctl --user -u akimbo-display -n 40 --no-pager")
        time.sleep(0.2)
    run(["systemctl", "--user", "stop", SERVICE], check=False)
    raise Error("Startup timed out; server stopped and layout recovery attempted.")


def stop():
    run(["systemctl", "--user", "stop", SERVICE], check=False)
    if state_read(): repair()
    print("Stopped; display layout restored.")


def repair():
    if service_active(): raise Error("Stop the running session before repair.")
    private_dir(RUNTIME)
    with (RUNTIME / "session.lock").open("w") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise Error("Session is still shutting down; retry repair shortly.")
        state = state_read()
        if state:
            restore(state)
            clear_state()
        print("Recovery complete." if state else "No recovery snapshot exists.")


def show_url(show_code):
    state = state_read()
    if state and state["phase"] == "running" and service_active():
        print(f'Safari: http://{state["network"]["address"]}:1701')
    else: print("Not running. Use akimbo-display start.")
    if show_code:
        path = CONFIG / "access-code"
        if path.exists(): print("Access code: " + path.read_text().strip())


def doctor():
    checks = []
    for name, check in [
        ("X11 session", session), ("Display layout", lambda: parse_layout(xrandr("--current"))),
        ("Network", lambda: choose_network(config()["transport"])), ("Weylus", backend),
    ]:
        try: value = check(); checks.append((name, True, value))
        except (Error, OSError) as exc: checks.append((name, False, str(exc)))
    checks.append(("Touch permission", os.access("/dev/uinput", os.W_OK), "/dev/uinput"))
    checks.append(("User service", (CONFIG.parent / "systemd/user" / SERVICE).exists(), SERVICE))
    try:
        checks.append(("Firewall", True, firewall_check(choose_network(config()["transport"]))))
    except (Error, OSError) as exc:
        checks.append(("Firewall", False, str(exc)))
    for name, ok, detail in checks:
        label = "WARN" if str(detail).startswith("UNVERIFIED") else "OK" if ok else "MISSING"
        print(f'{label}: {name}: {detail if detail is not None else "ready"}')
    print("Encoder: " + encoder(config()))
    return 0 if all(ok for _, ok, _ in checks) else 1


def install_user():
    private_dir(DATA)
    target = DATA / "app"
    if ROOT != target:
        target.mkdir(exist_ok=True)
        shutil.copytree(ROOT / "akimbo_display", target / "akimbo_display", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "scripts", target / "scripts", dirs_exist_ok=True)
        shutil.copy2(ROOT / "akimbo-display", target / "akimbo-display")
    entry = target / "akimbo-display"
    entry.chmod(0o755)
    bindir = HOME / ".local/bin"
    bindir.mkdir(parents=True, exist_ok=True)
    link = bindir / "akimbo-display"
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() != entry.resolve():
            raise Error(f"Refusing to replace unrelated executable: {link}")
        link.unlink()
    link.symlink_to(entry)
    if not (CONFIG / "config.toml").exists(): save_config(DEFAULTS)
    if not (CONFIG / "access-code").exists(): atomic(CONFIG / "access-code", secrets.token_urlsafe(24) + "\n")
    unit = CONFIG.parent / "systemd/user" / SERVICE
    # Absolute executable, no dependence on terminal PATH or working directory.
    atomic(unit, f'''[Unit]
Description=Akimbo iPad extended display
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart="{entry}" _serve
ExecStopPost="{entry}" _recover
KillMode=mixed
TimeoutStopSec=15
Restart=no
UMask=0077
''')
    for shellfile in (HOME / ".bashrc", HOME / ".bash_profile"):
        original = shellfile.read_text() if shellfile.exists() else ""
        marker = "# Akimbo terminal command"
        if marker not in original:
            # Backup before a narrowly marked shell startup addition.
            if shellfile.exists(): shutil.copy2(shellfile, shellfile.with_name(shellfile.name + ".akimbo-backup"))
            with shellfile.open("a") as stream:
                stream.write('\n# Akimbo terminal command\ncase ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac\n# End Akimbo terminal command\n')
    run(["systemctl", "--user", "daemon-reload"])
    print(f"Installed {link}. Open a new terminal to use akimbo-display.")


def install(args):
    if os.getuid() == 0: raise Error("Run install as your normal user; it invokes sudo only for system setup.")
    install_user()
    if args.user_only: return
    # The user runs this in a real terminal so sudo can request their password.
    subprocess.run(["bash", str(ROOT / "scripts/install-system.sh"), str(os.getuid()), str(DATA)], check=True)
    print("Installation complete. Log out and back in for touch permissions, then run doctor.")


def uninstall(args):
    stop()
    if args.system:
        subprocess.run(["bash", str(ROOT / "scripts/uninstall-system.sh"), str(os.getuid())], check=True)
    link = HOME / ".local/bin/akimbo-display"
    if link.is_symlink() and link.resolve() == DATA / "app/akimbo-display": link.unlink()
    (CONFIG.parent / "systemd/user" / SERVICE).unlink(missing_ok=True)
    for shellfile in (HOME / ".bashrc", HOME / ".bash_profile"):
        if shellfile.exists():
            text = shellfile.read_text()
            text = re.sub(r"\n# Akimbo terminal command\n.*?\n# End Akimbo terminal command\n", "\n", text, flags=re.S)
            shellfile.write_text(text)
    run(["systemctl", "--user", "daemon-reload"])
    print(f"Command and service removed. Configuration and build files retained at {CONFIG} and {DATA}.")


def add_options(parser):
    parser.add_argument("--model")
    for key, choices in dict(orientation=["landscape", "portrait"], quality=["performance", "balanced", "native"],
                             position=["below", "above", "left", "right"], transport=["auto", "usb", "wifi"],
                             encoder=["auto", "software", "vaapi"]).items():
        parser.add_argument("--" + key, choices=choices)
    parser.add_argument("--resolution", help="Even WIDTHxHEIGHT; orientation determines ordering. Empty string resets override.")
    parser.add_argument("--fps", type=int)


def main():
    parser = argparse.ArgumentParser(description="Extend Fedora XFCE/X11 to iPad Safari over a private USB or Wi-Fi link.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "restart", "configure", "preview"):
        add_options(sub.add_parser(name))
    for name in ("stop", "status", "doctor", "repair", "setup-network", "_serve", "_recover"):
        sub.add_parser(name)
    p = sub.add_parser("url"); p.add_argument("--show-code", action="store_true")
    p = sub.add_parser("install"); p.add_argument("--user-only", action="store_true")
    p = sub.add_parser("uninstall"); p.add_argument("--system", action="store_true")
    p = sub.add_parser("models"); p.add_argument("action", choices=["list", "show"]); p.add_argument("model", nargs="?")
    args = parser.parse_args()
    try:
        if args.command == "models":
            if args.action == "list":
                for key, m in MODELS.items(): print(f'{key:22} {m["name"]} ({m["native"][0]}x{m["native"][1]})')
                print("custom                 Supply --resolution WIDTHxHEIGHT")
            else:
                if args.model not in MODELS: raise Error("Choose a model from 'models list'.")
                print(json.dumps(MODELS[args.model], indent=2))
                for quality in ("performance", "balanced", "native"):
                    print(quality, dimensions(DEFAULTS | dict(model=args.model, quality=quality)))
        elif args.command == "configure":
            cfg = options(args); save_config(cfg); print(json.dumps(cfg, indent=2))
        elif args.command == "preview":
            cfg = options(args)
            print(json.dumps(geometry(parse_layout(xrandr("--current")), *dimensions(cfg), cfg["position"]), indent=2))
        elif args.command == "install": install(args)
        elif args.command == "setup-network":
            subprocess.run(["sudo", "bash", str(ROOT / "scripts/setup-root.sh"), str(os.getuid())], check=True)
        elif args.command == "uninstall": uninstall(args)
        elif args.command == "start": start(args)
        elif args.command == "restart": stop(); start(args)
        elif args.command == "stop": stop()
        elif args.command == "repair": repair()
        elif args.command == "url": show_url(args.show_code)
        elif args.command == "status":
            state = state_read()
            print(json.dumps({"active": service_active(), "session": {k:v for k,v in (state or {}).items() if k not in ("environment", "original")}}, indent=2))
        elif args.command == "doctor": sys.exit(doctor())
        elif args.command == "_serve": serve()
        elif args.command == "_recover": repair()
    except KeyboardInterrupt:
        print("\nInterrupted. Completed installation/build files were preserved.", file=sys.stderr)
        if args.command == "install":
            print("Check 'systemctl --user status akimbo-build' before restarting install; a managed build may still be running.", file=sys.stderr)
        elif args.command in ("start", "restart"):
            print("Check 'akimbo-display status'; use 'akimbo-display stop' to restore the desktop.", file=sys.stderr)
        sys.exit(130)
    except (Error, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"akimbo-display: {exc}", file=sys.stderr)
        sys.exit(1)
