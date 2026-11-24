import copy

from moonraker_lcd import simulator
from moonraker_lcd.config import Config
from moonraker_lcd.i18n import Translator
from moonraker_lcd.printer import Printer
from moonraker_lcd.ui import UI

#: 24.11.2026 14:00 Ortszeit
import datetime

WALL = datetime.datetime(2026, 11, 24, 14, 0).timestamp()


def make_printer(config=None, objects=None):
    config = config or Config()
    printer = Printer(config, Translator(config.display.language))
    printer.hostname = "drucker"
    printer.set_online(True)
    printer.set_klippy("ready")
    printer.update_objects(copy.deepcopy(simulator.base_objects()))
    printer.update_objects(objects or {})
    return printer


def printing_printer(config=None, progress=0.42):
    printer = make_printer(config, simulator.printing(progress))
    printer.set_metadata(simulator.FILENAME, simulator.METADATA)
    return printer


def make_ui(printer, config=None, cols=20, rows=4):
    config = config or Config()
    calls = []
    ui = UI(config, printer, Translator(config.display.language), on_action=calls.append)
    ui.resize(cols, rows)
    return ui, calls
