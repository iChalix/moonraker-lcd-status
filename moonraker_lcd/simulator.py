"""Vorgetaeuschter Drucker, um Display und Drehgeber ohne Klipper zu testen."""

from __future__ import annotations

import asyncio
import time

from .service import Service, run_tasks

FILENAME = "Benchy_0.2mm_PLA_BLV_1h12m.gcode"
METADATA = {
    "estimated_time": 4320, "layer_height": 0.2, "first_layer_height": 0.2, "object_height": 40.0,
    "gcode_start_byte": 0, "gcode_end_byte": 1000000, "layer_count": 200,
}


def base_objects() -> dict:
    return {
        "webhooks": {"state": "ready", "state_message": "Printer is ready"},
        "print_stats": {"state": "standby", "filename": "", "total_duration": 0, "print_duration": 0,
                        "filament_used": 0, "message": "", "info": {"total_layer": None, "current_layer": None}},
        "virtual_sdcard": {"progress": 0.0, "file_position": 0},
        "display_status": {"progress": 0.0, "message": None},
        "pause_resume": {"is_paused": False},
        "idle_timeout": {"state": "Idle"},
        "toolhead": {"extruder": "extruder"},
        "gcode_move": {"gcode_position": [0, 0, 0, 0], "speed_factor": 1.0, "extrude_factor": 1.0},
        "fan": {"speed": 0.0},
        "extruder": {"temperature": 24.1, "target": 0.0},
        "heater_bed": {"temperature": 22.4, "target": 0.0},
        "heater_generic chamber": {"temperature": 25.0, "target": 0.0},
        "temperature_sensor raspberry_pi": {"temperature": 48.3},
    }


def printing(progress: float) -> dict:
    """Objekte eines laufenden Drucks bei ``progress`` (0..1)."""
    layer = max(1, int(progress * 200))
    return {
        "print_stats": {"state": "printing", "filename": FILENAME, "print_duration": 4320 * progress,
                        "total_duration": 4320 * progress + 240, "filament_used": 4200 * progress,
                        "info": {"total_layer": 200, "current_layer": layer}},
        "virtual_sdcard": {"progress": progress, "file_position": int(progress * 1000000)},
        "display_status": {"progress": progress, "message": None},
        "idle_timeout": {"state": "Printing"},
        "gcode_move": {"gcode_position": [100, 100, layer * 0.2, 0], "speed_factor": 1.0, "extrude_factor": 0.98},
        "fan": {"speed": 0.8},
        "extruder": {"temperature": 234.8, "target": 235.0},
        "heater_bed": {"temperature": 59.9, "target": 60.0},
    }


class SimulatedClient:
    """Ersetzt den Moonraker-Client; Menuebefehle wirken auf den Scheindrucker."""

    def __init__(self, printer, on_change) -> None:
        self.printer = printer
        self._on_change = on_change
        self.calls: list = []
        self.phase = "idle"
        self.progress = 0.0

    def prepare(self) -> None:
        self.printer.hostname = "simulator"
        self.printer.addresses = ["192.0.2.10"]
        self.printer.set_klippy("ready")
        self.printer.set_online(True)
        self.printer.set_klippy("ready")
        self.printer.update_objects(base_objects())
        self.printer.update_proc_stats(
            {"cpu_temp": 51.5, "system_cpu_usage": {"cpu": 12.0},
             "system_memory": {"total": 1000, "used": 380}}
        )

    async def run(self) -> None:
        self.prepare()
        self._on_change()
        started = time.monotonic()
        while True:
            await asyncio.sleep(0.5)
            if self.phase == "idle" and time.monotonic() - started > 8:
                self.phase = "printing"
                self.printer.set_metadata(FILENAME, METADATA)
            if self.phase == "printing":
                self.progress += 0.004
                self.printer.update_objects(printing(min(self.progress, 1.0)))
                if self.progress >= 1.0:
                    self.phase = "complete"
                    self.printer.update_objects({"print_stats": {"state": "complete"}})
            self._on_change()

    async def call(self, method: str, params=None, timeout: float = None):
        self.calls.append((method, params))
        if method == "printer.print.pause":
            self.phase = "paused"
            self.printer.update_objects({"print_stats": {"state": "paused"}})
        elif method == "printer.print.resume":
            self.phase = "printing"
        elif method == "printer.print.cancel":
            self.phase = "cancelled"
            self.printer.update_objects({"print_stats": {"state": "cancelled"}})
        self._on_change()
        return "ok"


def simulated_service(config) -> Service:
    service = Service.__new__(Service)
    service._setup(config)
    service.client = SimulatedClient(service.printer, service.display.wake)
    return service


async def preview(config, cols: int, rows: int, show, seconds: float = 0.0) -> None:
    """Simulation im Terminal statt auf dem LCD."""
    service = simulated_service(config)
    service.ui.resize(cols, rows)
    service.client.prepare()
    service.client.progress = 0.4
    end = time.monotonic() + seconds if seconds > 0 else None

    async def draw():
        while end is None or time.monotonic() < end:
            show(service.ui.render(time.monotonic(), time.time()))
            await asyncio.sleep(config.display.refresh_interval)

    await run_tasks([service.client.run(), draw()])
