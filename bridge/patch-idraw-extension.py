#!/usr/bin/env python3
"""
Patch the UUNA TEK / iDraw Inkscape extension so it can connect to a plotter
exposed over the network (our socat virtual serial port), not just a local USB
DrawCore.

Why this is needed
------------------
The extension finds the plotter by scanning local USB devices for the DrawCore's
CH340 chip (VID:PID 1A86:7523 / 1A86:8040) in `listDRAWCOREports()`. A virtual
serial port (e.g. ~/.idraw-tty from socat) has no USB descriptor, so it is never
found — even if you type its exact path. The connect path
`find_named_drawcore_then_testPort()` only iterates that USB list.

This patch adds a short-circuit at the top of that function: if the given port is
an existing device path, open it directly with the extension's own `testPort()`
(which still verifies it really is a DrawCore via the `v\r` handshake).

Idempotent and safe: it only changes behaviour when you type a real path that
responds as a DrawCore; normal USB / nickname usage is unaffected. Re-run after
any extension update (updates overwrite the file). A .orig-backup is kept.
"""
import glob
import os
import sys

MARKER = "Wireless-bridge support"

ANCHOR = """    if port_name is not None:
        name_upper = port_name.upper()
"""

INSERT = """    if port_name is not None:
        # Wireless-bridge support: if an explicit device path is given (e.g. a
        # socat virtual serial port linked to a remote DrawCore over the network),
        # open it directly. USB enumeration (listDRAWCOREports) only finds local
        # CH340 devices by VID/PID and will never report such a virtual port.
        import os
        if os.path.exists(port_name):
            direct_port = testPort(port_name)
            if direct_port is not None:
                return direct_port

        name_upper = port_name.upper()
"""

EXT_DIR = os.path.expanduser(
    "~/Library/Application Support/org.inkscape.Inkscape/"
    "config/inkscape/extensions"
)


def main():
    targets = glob.glob(
        os.path.join(EXT_DIR, "**", "drawcore_plotink", "drawcore_serial.py"),
        recursive=True,
    )
    if not targets:
        sys.exit(f"drawcore_serial.py not found under {EXT_DIR}")

    for path in targets:
        src = open(path, encoding="utf-8").read()
        if MARKER in src:
            print(f"already patched: {path}")
            continue
        if ANCHOR not in src:
            print(f"WARNING anchor not found, skipped (check manually): {path}")
            continue
        open(path + ".orig-backup", "w", encoding="utf-8").write(src)
        open(path, "w", encoding="utf-8").write(src.replace(ANCHOR, INSERT, 1))
        print(f"patched: {path}  (backup at {path}.orig-backup)")


if __name__ == "__main__":
    main()
