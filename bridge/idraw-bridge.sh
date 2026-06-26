#!/bin/sh
# Mac side of the iDraw wireless bridge.
#
# Creates a virtual serial port at ~/.idraw-tty that is really the Pi's
# /dev/ttyACM0, tunneled over Tailscale. Point the uunatek Inkscape extension's
# serial port at the path printed below.
#
# Requires: brew install socat
# Run manually for testing, or let the LaunchAgent (com.idraw.bridge.plist) run
# it automatically.

PI_HOST=100.92.241.24   # pi-atelier Tailscale IP
PI_PORT=4000
LINK="$HOME/.idraw-tty"

echo "Bridging $LINK  ->  tcp:$PI_HOST:$PI_PORT"
echo "Set the uunatek extension's serial port to: $LINK"

# Keep the Tailscale UDP path warm so latency spikes don't cause serial timeouts.
ping -i 10 -q "$PI_HOST" > /dev/null 2>&1 &

# Persistent connection: the DrawCore resets once when this starts, then stays
# booted and responsive (which is what the UUNA TEK extension expects — it opens
# with DTR/RTS off and queries the version rather than waiting for a reset banner).
exec socat -d -d \
  pty,raw,echo=0,link="$LINK" \
  tcp:"$PI_HOST":"$PI_PORT",nodelay,keepalive
