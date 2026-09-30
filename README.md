# Akimbo Display

Use an iPad as an extra monitor for Fedora XFCE/X11. Akimbo streams the
extended desktop to Safari over Wi-Fi or USB Personal Hotspot.

## Requirements

- Fedora XFCE running an X11 session
- Python 3.11 or newer
- Safari on an iPad connected to the same private network
- An unused HDMI or DisplayPort output supported by the graphics driver
- Internet and `sudo` access for the first installation

## Install

```sh
git clone https://github.com/sharpredux/akimbo.git
cd akimbo
python3 akimbo-display install
```

Log out and back in after installation.

## Use

```sh
akimbo-display doctor
akimbo-display start
```

`start` prints the Safari address and access code. Open the address on the
iPad, enter the code, and drag a window onto the extended display.

Stop and restore the desktop:

```sh
akimbo-display stop
```

After changing Wi-Fi networks or connecting USB for the first time:

```sh
akimbo-display setup-network
akimbo-display restart
```

## Common settings

Save defaults:

```sh
akimbo-display configure --model ipad-mini-7 --quality balanced --position below
```

Apply settings to one session:

```sh
akimbo-display restart --orientation portrait --position right
akimbo-display restart --quality performance --fps 30
akimbo-display restart --transport wifi
akimbo-display restart --model custom --resolution 1600x1050
```

List supported iPad models:

```sh
akimbo-display models list
```

Run `akimbo-display COMMAND --help` for all options.

## Update

```sh
cd akimbo
git pull --ff-only
python3 akimbo-display install --user-only
akimbo-display restart
```

## Troubleshooting

```sh
akimbo-display doctor
akimbo-display status
journalctl --user -u akimbo-display -n 60 --no-pager
akimbo-display repair
```

- Use the complete printed address, including `http://` and `:1701`.
- Keep the laptop and iPad on the same private network.
- Run `setup-network` after the network subnet changes.
- Use `repair` only when Akimbo is stopped and the desktop was not restored.

## Limits

- X11 is required; Wayland is not supported.
- Audio and Safari's on-screen keyboard are not supported.
- USB requires a cellular iPad with Personal Hotspot and a trusted data cable.
- Streaming uses unencrypted HTTP. Use USB or trusted private Wi-Fi.

See [AKIMBO-DISPLAY-MANUAL.txt](AKIMBO-DISPLAY-MANUAL.txt) for complete setup,
options, recovery, security, and uninstall instructions.
