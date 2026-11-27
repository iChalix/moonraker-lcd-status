"""Druckerzustand aus Moonraker: Rohobjekte sammeln und auswerten."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass

from .config import Config
from .screen import clean

#: Immer benoetigte Klipper-Objekte und die Felder daraus
BASE_OBJECTS = {
    "webhooks": ["state", "state_message"],
    "print_stats": ["state", "filename", "total_duration", "print_duration", "filament_used", "message", "info"],
    "virtual_sdcard": ["progress", "file_position"],
    "display_status": ["progress", "message"],
    "pause_resume": ["is_paused"],
    "idle_timeout": ["state"],
    "toolhead": ["extruder"],
    "gcode_move": ["gcode_position", "speed_factor", "extrude_factor"],
    "fan": ["speed"],
    # nur fuer max_temp der Heizer (Grenze beim Einstellen im Menue)
    "configfile": ["settings"],
}
HEATER_FIELDS = ["temperature", "target"]
HEATER_PREFIXES = ("heater_generic ", "temperature_fan ")
SENSOR_PREFIXES = ("temperature_sensor ",)


class Phase(enum.Enum):
    OFFLINE = "offline"            # Moonraker nicht erreichbar
    DISCONNECTED = "disconnected"  # Klipper laeuft nicht
    STARTUP = "startup"
    ERROR = "error"                # Klipper-Fehler (Konfiguration, MCU)
    SHUTDOWN = "shutdown"          # Klipper hat abgeschaltet (Not-Aus)
    STANDBY = "standby"
    BUSY = "busy"
    PRINTING = "printing"
    PAUSED = "paused"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    PRINT_ERROR = "print_error"

    @property
    def ready(self) -> bool:
        """Klipper nimmt Befehle an."""
        return self not in (
            Phase.OFFLINE, Phase.DISCONNECTED, Phase.STARTUP, Phase.ERROR, Phase.SHUTDOWN,
        )

    @property
    def active(self) -> bool:
        """Ein Druck laeuft oder pausiert."""
        return self in (Phase.PRINTING, Phase.PAUSED)

    @property
    def fault(self) -> bool:
        return self in (Phase.ERROR, Phase.SHUTDOWN)


@dataclass(frozen=True)
class Heater:
    object: str
    name: str
    kind: str  # extruder | bed | heater | sensor
    temperature: float
    target: float

    @property
    def heating(self) -> bool:
        return self.target > 0


def is_extruder(name: str) -> bool:
    return name.startswith("extruder") and name[len("extruder"):].isdigit() or name == "extruder"


def number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class Printer:
    """Haelt den Zustand und beantwortet die Fragen der Anzeige."""

    def __init__(self, config: Config, translate) -> None:
        self._config = config
        self._t = translate
        self.objects: dict = {}
        self.metadata: dict = {}
        self.metadata_for = ""
        self.online = False
        self.klippy_state = ""
        self.klippy_message = ""
        self.hostname = ""
        self.addresses: list = []
        self.cpu_temp = None
        self.cpu_load = None
        self.memory_load = None

    # ----------------------------------------------------------- Eingang

    def set_online(self, online: bool) -> None:
        self.online = online
        if not online:
            self.klippy_state = ""
            self.klippy_message = ""
            self.objects = {}
            self.cpu_load = self.cpu_temp = self.memory_load = None

    def set_klippy(self, state: str, message: str = "") -> None:
        self.klippy_state = (state or "").lower()
        self.klippy_message = message or ""

    def reset_objects(self) -> None:
        self.objects = {}

    def update_objects(self, status: dict) -> None:
        for name, values in status.items():
            if isinstance(values, dict):
                self.objects.setdefault(name, {}).update(values)

    def set_metadata(self, filename: str, metadata: dict) -> None:
        self.metadata_for = filename
        self.metadata = metadata if isinstance(metadata, dict) else {}

    def update_proc_stats(self, stats: dict) -> None:
        if stats.get("cpu_temp") is not None:
            self.cpu_temp = number(stats["cpu_temp"])
        usage = stats.get("system_cpu_usage")
        if isinstance(usage, dict) and "cpu" in usage:
            self.cpu_load = number(usage["cpu"])
        memory = stats.get("system_memory")
        if isinstance(memory, dict) and number(memory.get("total")) > 0:
            self.memory_load = 100.0 * number(memory.get("used")) / number(memory["total"])

    def update_system_info(self, info: dict) -> None:
        """Ergebnis von ``machine.system_info``: IPv4-Adressen einsammeln."""
        network = info.get("system_info", info).get("network", {}) if isinstance(info, dict) else {}
        found = []
        for name in sorted(network):
            for entry in network[name].get("ip_addresses", []):
                if entry.get("family") == "ipv4" and not entry.get("is_link_local"):
                    found.append(entry.get("address", ""))
        self.addresses = [address for address in found if address]

    def subscription(self, available) -> dict:
        """Aus allen Objekten des Druckers die fuer die Anzeige noetigen."""
        available = list(available)
        wanted = {name: fields for name, fields in BASE_OBJECTS.items() if name in available}
        for name in available:
            if name in self._config.hidden:
                continue
            if name == "heater_bed" or is_extruder(name) or name.startswith(HEATER_PREFIXES):
                wanted[name] = HEATER_FIELDS
            elif name.startswith(SENSOR_PREFIXES):
                wanted[name] = ["temperature"]
        return wanted

    # ----------------------------------------------------------- Auswertung

    def get(self, name: str, field: str, default=None):
        value = self.objects.get(name, {}).get(field)
        return default if value is None else value

    @property
    def phase(self) -> Phase:
        if not self.online:
            return Phase.OFFLINE
        state = self.klippy_state
        if state == "ready":
            # webhooks meldet einen Shutdown auch, wenn die Nachricht verloren ging
            state = str(self.get("webhooks", "state", "ready")).lower()
        if state == "shutdown":
            return Phase.SHUTDOWN
        if state == "error":
            return Phase.ERROR
        if state == "startup":
            return Phase.STARTUP
        if state != "ready":
            return Phase.DISCONNECTED
        job = str(self.get("print_stats", "state", "standby")).lower()
        if job == "printing" and self.get("pause_resume", "is_paused", False):
            return Phase.PAUSED
        if job in ("printing", "paused", "complete", "cancelled"):
            phase = Phase(job)
        elif job == "error":
            phase = Phase.PRINT_ERROR
        else:
            phase = Phase.STANDBY
        if phase is Phase.STANDBY and self.get("idle_timeout", "state") == "Printing":
            return Phase.BUSY
        return phase

    @property
    def fault_message(self) -> str:
        message = self.klippy_message or self.get("webhooks", "state_message", "")
        return clean(message)

    @property
    def message(self) -> str:
        """M117-Text, bei einem Druckfehler dessen Meldung."""
        if self.phase is Phase.PRINT_ERROR:
            text = clean(self.get("print_stats", "message", ""))
            if text:
                return text
        return clean(self.get("display_status", "message", ""))

    @property
    def filename(self) -> str:
        return str(self.get("print_stats", "filename", ""))

    @property
    def job_name(self) -> str:
        name = self.filename.rsplit("/", 1)[-1]
        base, dot, extension = name.rpartition(".")
        if dot and extension.lower() in ("gcode", "gco", "g", "ufp"):
            name = base
        return clean(name)

    @property
    def _meta(self) -> dict:
        return self.metadata if self.metadata_for and self.metadata_for == self.filename else {}

    @property
    def progress(self) -> float:
        if self.phase is Phase.COMPLETE:
            return 1.0
        source = self._config.progress.source
        value = None
        if source == "display":
            value = self.get("display_status", "progress")
        elif source == "auto":
            start = number(self._meta.get("gcode_start_byte"), -1)
            end = number(self._meta.get("gcode_end_byte"), -1)
            position = self.get("virtual_sdcard", "file_position")
            if 0 <= start < end and position is not None:
                value = (number(position) - start) / (end - start)
        if value is None:
            value = self.get("virtual_sdcard", "progress", 0.0)
        return min(max(number(value), 0.0), 1.0)

    @property
    def elapsed(self) -> float:
        return number(self.get("print_stats", "print_duration"))

    @property
    def total_elapsed(self) -> float:
        return number(self.get("print_stats", "total_duration"))

    @property
    def remaining(self):
        """Restzeit in Sekunden oder ``None``, solange sie nicht schaetzbar ist."""
        done, elapsed = self.progress, self.elapsed
        estimated = number(self._meta.get("estimated_time"))
        by_slicer = max(estimated - elapsed, 0.0) if estimated > 0 else None
        by_file = elapsed * (1 - done) / done if done >= 0.01 and elapsed >= 30 else None
        mode = self._config.progress.eta
        if mode == "slicer":
            return by_slicer
        if mode == "file":
            return by_file
        if by_slicer is None or by_file is None:
            return by_slicer if by_file is None else by_file
        # am Anfang dem Slicer, am Ende der tatsaechlichen Geschwindigkeit trauen
        return by_slicer * (1 - done) + by_file * done

    def eta(self, now: float = None):
        """Uhrzeit (Unixzeit) des Druckendes; waehrend einer Pause unbekannt."""
        remaining = self.remaining
        if remaining is None or self.phase is not Phase.PRINTING:
            return None
        return (time.time() if now is None else now) + remaining

    @property
    def layers(self):
        """``(aktuell, gesamt)`` oder ``None``."""
        info = self.get("print_stats", "info", {})
        info = info if isinstance(info, dict) else {}
        total = info.get("total_layer")
        current = info.get("current_layer")
        meta = self._meta
        height = number(meta.get("layer_height"))
        first = number(meta.get("first_layer_height"), height) or height
        if total is None:
            total = meta.get("layer_count")
        if total is None and height > 0 and number(meta.get("object_height")) > 0:
            total = round((number(meta["object_height"]) - first) / height) + 1
        if current is None and height > 0 and total is not None:
            z = self.z
            if z is None:
                return None
            current = round((z - first) / height) + 1
            current = max(0, current) if self.elapsed > 0 else 0
        if current is None or total is None:
            return None
        total = int(number(total))
        return (min(int(number(current)), total), total) if total > 0 else None

    @property
    def z(self):
        position = self.get("gcode_move", "gcode_position")
        if isinstance(position, (list, tuple)) and len(position) >= 3:
            return number(position[2])
        return None

    @property
    def fan(self):
        speed = self.get("fan", "speed")
        return None if speed is None else number(speed)

    @property
    def speed_factor(self) -> float:
        return number(self.get("gcode_move", "speed_factor"), 1.0)

    @property
    def flow_factor(self) -> float:
        return number(self.get("gcode_move", "extrude_factor"), 1.0)

    @property
    def filament_used(self) -> float:
        """Verbrauchtes Filament in Metern."""
        return number(self.get("print_stats", "filament_used")) / 1000.0

    # ----------------------------------------------------------- Temperaturen

    def _name(self, name: str) -> str:
        if name in self._config.names:
            return self._config.names[name]
        if name == "heater_bed":
            return self._t("bed")
        if is_extruder(name):
            multiple = sum(1 for other in self.objects if is_extruder(other)) > 1
            index = name[len("extruder"):] or "0"
            return "%s %s" % (self._t("hotend"), index) if multiple else self._t("hotend")
        short = name.split(" ", 1)[-1].replace("_", " ").strip()
        return short[:1].upper() + short[1:]

    def _heater(self, name: str, kind: str):
        values = self.objects[name]
        if values.get("temperature") is None:
            return None
        return Heater(
            name, self._name(name), kind, number(values["temperature"]), number(values.get("target"))
        )

    @property
    def heaters(self) -> list:
        """Alle Temperaturen: Extruder, Bett, weitere Heizer, Sensoren."""
        groups = {"extruder": [], "bed": [], "heater": [], "sensor": []}
        for name in sorted(self.objects):
            if is_extruder(name):
                kind = "extruder"
            elif name == "heater_bed":
                kind = "bed"
            elif name.startswith(HEATER_PREFIXES):
                kind = "heater"
            elif name.startswith(SENSOR_PREFIXES):
                kind = "sensor"
            else:
                continue
            heater = self._heater(name, kind)
            if heater is not None:
                groups[kind].append(heater)
        return [heater for group in groups.values() for heater in group]

    @property
    def extruder(self):
        """Der gerade aktive Extruder."""
        extruders = [h for h in self.heaters if h.kind == "extruder"]
        active = self.get("toolhead", "extruder", "")
        for heater in extruders:
            if heater.object == active:
                return heater
        return extruders[0] if extruders else None

    def max_temp(self, name: str) -> float:
        """``max_temp`` aus Klippers Konfiguration, sonst 300."""
        settings = self.get("configfile", "settings", {}) or {}
        value = number((settings.get(name) or {}).get("max_temp"), 0.0)
        return value if value > 0 else 300.0

    @property
    def bed(self):
        for heater in self.heaters:
            if heater.kind == "bed":
                return heater
        return None

    @property
    def display_name(self) -> str:
        return self._config.display.name or self.hostname or "Klipper"
