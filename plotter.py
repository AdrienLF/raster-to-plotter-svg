import serial
import time


class Plotter:
    """
    Uunatek iDraw H A3 — Grbl 1.1h DrawCore V2.12

    Coordinate system after init():
        Top-left:     X=0,   Y=420
        Top-right:    X=297, Y=420
        Bottom-left:  X=0,   Y=0
        Bottom-right: X=297, Y=0

    Z axis:  Z=0 = pen UP,  Z=5 = pen DOWN  (never use negative Z)
    Speed:   50–2500 mm/min
    """

    PORT = "/dev/ttyACM0"
    BAUD = 115200
    WIDTH = 297   # mm (X axis)
    HEIGHT = 420  # mm (Y axis)

    def __init__(self, port: str = PORT, home: bool = True):
        self.ser = serial.Serial(port, self.BAUD, timeout=10)
        time.sleep(2)
        self.ser.read(self.ser.in_waiting)
        self._send("$X")
        if home:
            self.home()
        self._send("G21")          # mm
        self._send("G90")          # absolute
        self._send("G92 X0 Y420")  # remap: Y=420=top, Y=0=bottom
        self.pen_up()

    def _send(self, cmd: str, timeout: float = 60) -> None:
        self.ser.write((cmd + "\n").encode())
        start = time.time()
        while time.time() - start < timeout:
            line = self.ser.readline().decode().strip()
            if line.lower() == "ok":
                return
            if "ALARM" in line or "error" in line:
                raise RuntimeError(f"Grbl error for {cmd!r}: {line}")

    def home(self) -> None:
        """Run homing cycle (uses physical limit switches, ~5–8s)."""
        self.ser.write(b"$H\n")
        start = time.time()
        while time.time() - start < 30:
            line = self.ser.readline().decode().strip()
            if line.lower() == "ok":
                return
            if "ALARM" in line or "error" in line:
                raise RuntimeError(f"Homing failed: {line}")
        raise TimeoutError("Homing timed out")

    def pen_up(self) -> None:
        self._send("G00 Z0")

    def pen_down(self) -> None:
        self._send("G00 Z5")

    def move(self, x: float, y: float, speed: int = 2000) -> None:
        """Rapid move with pen up."""
        self._send(f"G00 X{x:.3f} Y{y:.3f}")

    def draw(self, x: float, y: float, speed: int = 1500) -> None:
        """Draw to position at given speed (pen must already be down)."""
        self._send(f"G01 X{x:.3f} Y{y:.3f} F{speed}")

    def go_home(self) -> None:
        self.pen_up()
        self._send("G00 X0 Y420")

    def close(self) -> None:
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.go_home()
        self.close()


if __name__ == "__main__":
    # Example: draw a small square near top-left
    with Plotter() as p:
        p.move(20, 400)
        p.pen_down()
        p.draw(70, 400)
        p.draw(70, 350)
        p.draw(20, 350)
        p.draw(20, 400)
        p.pen_up()
