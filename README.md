# Akimbo Display

Use your iPad as an additional monitor for a Fedora XFCE/X11 laptop. Akimbo creates an extended desktop and streams it to Safari over the same Wi-Fi LAN or a supported USB Personal Hotspot connection. It includes named iPad profiles, touch input via Weylus, window dragging between monitors, taskbar placement, and desktop recovery.

For everyday use, setup instructions, the full command reference, and troubleshooting, see the [plain-text user manual](AKIMBO-DISPLAY-MANUAL.txt).

## Requirements

- Fedora with an XFCE **X11** session and Python 3.11 or newer. Development and live verification used Fedora 44 with AMD graphics; other graphics drivers are not verified.
- An unused HDMI/DP output that the driver allows Akimbo to activate without a connected display. No HDMI dummy plug was needed on the tested laptop. This version cannot use an output already occupied by an external monitor.
- An iPad with Safari and a reachable local network. Wi-Fi-only iPads use the Wi-Fi path; the USB path requires cellular Personal Hotspot support and an active Linux `ipheth` network interface.
- Internet access for installation and sudo access for Fedora dependencies, input permissions, and firewall setup. Local Wi-Fi streaming does not require internet access.

Wayland, audio streaming, and Safari's on-screen keyboard are not supported. Use the laptop keyboard or a physical keyboard.

## Install and use

Run these commands in a terminal inside your XFCE desktop. Run the installer as your normal user; it requests sudo when needed:

```sh
git clone https://github.com/sharpredux/akimbo.git
cd akimbo
python3 akimbo-display install
```

Log out and back in so the touch group takes effect, then open a terminal:

```sh
akimbo-display doctor
akimbo-display configure --model ipad-mini-7 --quality balanced --position below --resolution ''
akimbo-display start
akimbo-display url --show-code
```

Open the printed `http://LAPTOP-IP:1701` address in Safari and enter the access code. The browser selects `Monitor: AKIMBO-IPAD`. Drag a window's title bar down through the middle of the laptop's bottom edge; once it is on the iPad, maximize it there. The new desktop may initially be black/empty until a window is moved onto it. Panels with automatic output selection stay on the laptop while Akimbo runs.

Add the page to the Home Screen for a larger viewing area. Keep the laptop session unlocked for normal use. To finish, run `akimbo-display stop`; closing Safari does not stop the service. To apply new settings or reconnect after a network change, run `akimbo-display restart` and reload Safari.

If the firewall blocks the connection, or you have changed Wi-Fi networks or first connected USB, run `akimbo-display setup-network` and restart. The complete troubleshooting guide is in the [manual](AKIMBO-DISPLAY-MANUAL.txt).

`install --user-only` installs the command and service without system packages. The installed command is copied under `~/.local/share/akimbo-display/app`, so it works outside this directory and VS Code. The installer is repeatable and pins Weylus to `38a01a8f8e429500c7e9f67fc1c88ca37a4d1e93`; it builds bundled FFmpeg/x264 because Fedora codec availability varies. Initial builds need network access and can take a while. Dependencies remain installed on uninstall.

Builds use one CPU worker with a 1 GiB memory soft limit, 1.5 GiB hard limit, and 512 MiB swap cap; full-program LTO is disabled. This keeps compilation from exhausting a small laptop. Interrupted builds reuse completed files. Check progress with `systemctl --user status akimbo-build`; rerun install to resume after a failure.

The bundled FFmpeg configuration is narrowed to the H.264 encoders, MP4 muxer, and scaling/upload filters used by Weylus. The pinned upstream sources are retained; `scripts/ffmpeg-minimal.sh` replaces their broad FFmpeg build configuration.

To update an installed copy after pulling changes in this repository:

```sh
git pull --ff-only
python3 akimbo-display install --user-only
akimbo-display restart
```

The `--user-only` update reuses installed dependencies and Weylus. Run the full install again if dependencies or the backend need to be installed or updated.

## Models and placement

```sh
akimbo-display models list
akimbo-display models show ipad-mini-7
akimbo-display start --model ipad-mini-7 --orientation portrait --position left
akimbo-display start --quality performance --fps 60
akimbo-display configure --model custom --resolution 1600x1050
akimbo-display preview --position above
```

The default mini 7 presets in landscape are performance 1132×744, balanced 1510×992, and native 2266×1488. Even rounding makes dimensions compatible with H.264, with negligible aspect-ratio difference. Model data includes Apple source links. Presets scale the virtual desktop, not XFCE's global DPI. Native resolution makes UI smaller; balanced is the default. Portrait swaps dimensions. Browser chrome may leave borders; content uses aspect-preserving fitting and corresponding touch mapping. Landscape/portrait is chosen explicitly; rotating the iPad does not automatically rearrange the laptop.

`configure` persists options; `start` overrides them for one session. An explicit resolution wins over the model preset; `--resolution ''` clears it. Position applies to the bounding rectangle of all physical displays. Frame rate defaults to 30; 60 is a request, not a measured guarantee. Video performance, Safari compatibility, and Pencil behavior require testing with the actual iPad. Audio and Safari's on-screen keyboard are not supported by this backend; use the laptop keyboard or a physical iPad keyboard.

Use `restart` instead of `start` in the examples when a session is already running. A bare `restart` loads saved settings; it does not retain overrides from an earlier `start` command.

## Connection and privacy

USB requires a cellular iPad with Personal Hotspot and a trusted USB data connection. Accept Trust This Computer on the iPad. Linux must expose an `ipheth` network interface. A charging cable alone does not carry the web service. `--transport auto` chooses USB first, otherwise Wi-Fi. Internet access is not needed while streaming. Safari opens the **laptop's IP**, not `localhost` on the iPad.

Weylus serves HTTP and WebSocket on TCP 1701, bound to one selected interface. An access code is required but HTTP does **not** encrypt the desktop or code: use USB or a trusted private Wi-Fi network. No router forwarding is configured. The installer permits only currently connected USB/Wi-Fi private source subnets through firewalld. Run `akimbo-display setup-network` after first connecting USB or changing Wi-Fi subnets. Network fallback is selected on start; run `restart` when switching interfaces. The access code is stored mode 0600 and is not included in process arguments or printed URLs.

The dedicated `akimbo-uinput` group allows input synthesis across the host; only the installing user is added. Services run as that user. No login autostart is enabled.

## Recovery and limitations

```sh
akimbo-display status
akimbo-display stop
akimbo-display repair
journalctl --user -u akimbo-display -n 60 --no-pager
akimbo-display uninstall
akimbo-display uninstall --system
```

Layout recovery snapshots live in the private XDG runtime directory. Graceful stop, backend exit, and startup failure restore original positions and framebuffer dimensions. If physical monitors were disconnected/reconnected, recovery removes the virtual monitor but retains the snapshot instead of guessing a new layout; reconnect the original monitors and run repair. Uninstall preserves configuration, source/build artifacts, and shell backups. `--system` also removes the tool's udev/module and owned firewall rules; it retains Fedora packages.

XFCE's compositor is temporarily disabled while streaming because it clips drawing outside normal outputs. Window transparency and shadows may change for the duration of the session. The original compositor preference is restored on stop or service failure. A private persistent `recovery.json` also survives reboot: `repair` restores that preference without applying obsolete monitor positions to the new desktop session.

An unused HDMI/DP connector is required, but **no cable or dummy plug** is needed in it: Akimbo activates a software mode on the disconnected connector so X11 permits the mouse to enter the iPad region. GTK normally ignores disconnected outputs, so Akimbo starts XFCE's window manager with a narrowly scoped compatibility library that reports this active output as connected to that process. This lets title-bar drags, maximize, and tiling use both monitors. Panels set to Automatic are temporarily pinned to the laptop's eDP output and restored on stop; panels already assigned to an output are left alone. The normal window manager and original display layout are restored on stop or crash recovery. If all connectors are in use, this build cannot create a true extension without a virtual display driver or a spare connector. Rotated or scaled physical displays are rejected to preserve reversible restoration. X11, rather than Wayland, is required.

## Verification

```sh
python3 -m unittest discover -s tests -v
for script in scripts/*.sh; do bash -n "$script"; done
# Explicit live tests (briefly change the display, with automatic recovery):
python3 -m tests.live_layout
bash tests/live_session.sh
```

Live acceptance: drag and maximize a window on the iPad region, test touch at corners, verify USB and Wi-Fi, measure video responsiveness, then stop and compare the original layout. Check all four placements and recovery after a backend failure. Never claim a connected iPad test based only on unit tests.

Validated on the development laptop: 18 automated tests; a managed XFCE window moved into the virtual region and its expected pixels captured; the X11 pointer reached the virtual monitor center; a simulated title-bar drag moved a managed window fully into the iPad region; authenticated MP4/H.264 streaming with uinput initialization; rejected incorrect access code; immediate restart; restoration after forcibly killing the session supervisor. A connected-iPad screenshot exposed the pointer clipping in the earlier logical-only version; physical touch/Pencil behavior and USB tethering still require connected-device testing after this fix. The tested AMD driver reported no H.264 encode profile, so automatic selection used software encoding. A firewall `WARN: UNVERIFIED` means read-only verification was denied/timed out; the installer configures the rule with sudo, and `setup-network` can refresh it for a new connection.

## License and dependencies

The Akimbo controller and project source are distributed under the [MIT license](LICENSE). [Weylus](https://github.com/H-M-H/Weylus), FFmpeg, x264, and other dependencies are separate projects with their own licenses. The installer downloads/builds them locally; their source trees and compiled binaries are not included in this repository.
