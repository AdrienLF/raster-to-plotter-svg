# Wireless Inkscape → plotter bridge

Drive the iDraw H A3 from Inkscape + the UUNA TEK extension on the Mac **without
moving the USB cable**. The plotter stays plugged into the Pi (`pi-atelier`); the
Mac gets a virtual serial port that is really the Pi's `/dev/ttyACM0`, tunneled
over Tailscale with `socat` on both ends.

```
Inkscape + uunatek  →  ~/.idraw-tty (socat PTY on Mac)  →  TCP 4000 / Tailscale
                                                         →  socat on Pi
                                                         →  /dev/ttyACM0  →  iDraw
```

It is a raw byte passthrough, so all DrawCore/Grbl traffic (`v`, `$B`, `?`, `$H`,
motion + `ok` replies) works exactly as over USB.

There are **two** parts to making this work: the network bridge (below) **and** a
small patch to the Inkscape extension (see "Extension patch" — without it the
extension refuses the virtual port).

---

## Pi side (`pi-atelier`)

`socat` is already installed. Install the service:

```sh
sudo cp idraw-serial.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now idraw-serial
systemctl is-active idraw-serial          # -> active
sudo ss -tlnp | grep 4000                 # listening on the Tailscale IP
```

If the Pi's Tailscale IP changes, update the `ExecStart` line in the service file
and `sudo systemctl restart idraw-serial`.

> Buster note: this Pi runs Raspbian 10 (Buster), whose apt repos are archived, so
> `ser2net` can't be installed from apt. We use `socat` instead, which is already
> present. No apt changes needed.

## Mac side

```sh
brew install socat
cp com.idraw.bridge.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.idraw.bridge.plist
launchctl list | grep idraw      # second column 0 = running
ls -l ~/.idraw-tty               # symlink to a /dev/ttys* device
```

The LaunchAgent calls the `socat` binary directly (not `idraw-bridge.sh`) because
macOS blocks launchd from executing scripts inside `~/Documents` (a TCC-protected
folder). `idraw-bridge.sh` is kept for running the bridge manually from a
terminal. If `socat` is not at `/opt/homebrew/bin/socat`, edit the path in the
plist. After editing the plist, restart the agent:
`launchctl kickstart -k gui/$(id -u)/com.idraw.bridge`

The bridge keeps one persistent connection to the Pi, so the DrawCore is reset
once (when the bridge starts) and then stays booted and responsive — which is
exactly what the extension expects (it opens with DTR/RTS deasserted and queries
the version rather than waiting for a reset banner).

## Extension patch (required)

The UUNA TEK / iDraw extension finds the plotter by scanning **local USB** for the
DrawCore's CH340 chip (`VID:PID 1A86:7523 / 1A86:8040`). A virtual serial port has
no USB descriptor, so the extension never considers it — even if you type its
exact path — and fails with **"Failed to connect to iDraw2 …"**.

`patch-idraw-extension.py` adds a one-block short-circuit to the extension's
`find_named_drawcore_then_testPort()`: if you give an existing device path, it
opens it directly via the extension's own `testPort()` (which still verifies a
real DrawCore via the `v\r` handshake). Safe and idempotent — normal USB/nickname
use is unaffected.

```sh
python3 patch-idraw-extension.py     # re-run after any extension update
```

Patched file (a `.orig-backup` is kept next to it):
`~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/idraw_deps/drawcore_plotink/drawcore_serial.py`

Then in **Inkscape → UUNA TEK extension → Setup tab**: choose "use a specified
port" (not "first available") and set the serial port to:

```
/Users/adrien/.idraw-tty
```

## Verify end to end

1. Pi: `systemctl is-active idraw-serial` -> active; port 4000 listening.
2. Mac: `ls -l ~/.idraw-tty` shows the symlink; `launchctl list | grep idraw`.
3. Handshake smoke test (no Inkscape) — opens in raw mode like pyserial and runs
   the same `v`/`?` queries the extension uses:
   ```sh
   python3 -c "import os,time,select,tty; fd=os.open(os.path.expanduser('~/.idraw-tty'),os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK); tty.setraw(fd); time.sleep(0.3); os.write(fd,b'v\r'); time.sleep(0.4); r,_,_=select.select([fd],[],[],2); print('v ->', (os.read(fd,128) if r else b''))"
   ```
   Expect `b'DrawCore V2.12...'`. Proves the whole path end to end.
4. Inkscape: with the extension patched and the port set to `~/.idraw-tty`, run a
   homing/jog command — the machine should move.
5. Plot a small test SVG and confirm geometry, pen up/down, and return-home.

> Raw mode matters in the smoke test: a cooked-mode open echoes the board's
> replies back to it, causing an `error:2`/`ok` loop. pyserial (and the extension)
> open raw, so this only affects hand-written test clients.

## Shared serial port

While the bridge LaunchAgent is running, its persistent connection holds
`/dev/ttyACM0` open on the Pi, so the Flask web UI (`../web/server.py`) cannot use
the plotter at the same time. To switch to the web UI, stop the bridge
(`launchctl unload ~/Library/LaunchAgents/com.idraw.bridge.plist`) or stop the Pi
service (`sudo systemctl stop idraw-serial`).
