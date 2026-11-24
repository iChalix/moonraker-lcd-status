"""Den echten Arduino-Sketch fuer den PC uebersetzen und steuern."""

import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKETCH = os.path.join(
    os.path.dirname(os.path.dirname(HERE)), "arduino", "MoonrakerLcdStatus", "MoonrakerLcdStatus.ino"
)


def compiler():
    return shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")


def build(directory, cols=20, rows=4):
    """Sketch uebersetzen; fuer andere Groessen mit angepassten #defines."""
    with open(SKETCH, encoding="utf-8") as handle:
        source = handle.read()
    source = source.replace("#define LCD_COLS 20", "#define LCD_COLS %d" % cols)
    source = source.replace("#define LCD_ROWS 4", "#define LCD_ROWS %d" % rows)
    path = os.path.join(directory, "sketch_%dx%d.inc" % (cols, rows))
    with open(path, "w", encoding="utf-8") as handle:
        # die Arduino-IDE bindet Arduino.h von selbst ein
        handle.write("#include <Arduino.h>\n" + source)
    binary = os.path.join(directory, "sketch_%dx%d" % (cols, rows))
    subprocess.run(
        [compiler(), "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-function", "-I", HERE,
         "-DSKETCH=\"%s\"" % path, os.path.join(HERE, "host.cpp"), "-o", binary],
        check=True,
    )
    return binary


class Screen:
    def __init__(self, rows, light, on, cgram, errors, overflow):
        self.rows, self.light, self.on = rows, light, on
        self.cgram, self.errors, self.overflow = cgram, errors, overflow

    @property
    def text(self):
        table = {0xDF: "°", 0xE1: "ä", 0xEF: "ö", 0xF5: "ü", 0xE2: "ß"}
        glyphs = "▏▍▋▉█░ÄÜ"
        return [
            "".join(glyphs[c] if c < 8 else table.get(c, chr(c)) for c in row) for row in self.rows
        ]


class Arduino:
    """Laufender Sketch mit LCD-Modell."""

    def __init__(self, binary):
        self.process = subprocess.Popen(
            [binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1
        )
        self.port = self.process.stdout.readline().strip()

    def command(self, text):
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def show(self):
        self.command("SHOW")
        parts = self.process.stdout.readline().split()
        rows = [bytes.fromhex(part) for part in parts[:-5]]
        light, on, cgram, errors, overflow = (int(part) for part in parts[-5:])
        return Screen(rows, bool(light), bool(on), cgram, errors, overflow)

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)
        self.process.stdout.close()


def temporary_directory():
    return tempfile.TemporaryDirectory()
