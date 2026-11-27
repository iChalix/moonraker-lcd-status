"""Konfiguration (INI-Format, ohne Fremdabhaengigkeiten)."""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field

from .i18n import LANGUAGES
from .screen import CHARSETS

#: Suchreihenfolge, wenn kein --config angegeben wird
DEFAULT_CONFIG_PATHS = (
    "~/printer_data/config/moonraker-lcd.conf",
    "~/klipper_config/moonraker-lcd.conf",
    "/etc/moonraker-lcd/moonraker-lcd.conf",
    "./moonraker-lcd.conf",
)

PAGES = ("status", "temperatures", "print", "system")
PROGRESS_SOURCES = ("auto", "display", "sdcard")
ETA_SOURCES = ("auto", "slicer", "file")
WHEN = ("always", "idle", "printing", "paused", "active")


class ConfigError(ValueError):
    """Fehlerhafte oder unvollstaendige Konfiguration."""


@dataclass
class MoonrakerConfig:
    url: str = "ws://127.0.0.1:7125/websocket"
    api_key: str = ""
    connect_timeout: float = 10.0
    reconnect_min: float = 1.0
    reconnect_max: float = 15.0


@dataclass
class SerialConfig:
    port: str = ""
    baudrate: int = 57600
    #: so lange auf die Kennung des Arduino warten (Reset + Bootloader)
    handshake_timeout: float = 8.0
    #: Pause nach einem Geraet ohne Kennung - vermutlich der falsche Port
    wrong_device_delay: float = 60.0


@dataclass
class DisplayConfig:
    language: str = "de"
    charset: str = "a00"
    #: Name im Leerlauf; leer = Hostname laut Moonraker
    name: str = ""
    pages: tuple = PAGES
    #: Sekunden je Seite beim automatischen Wechsel, 0 = aus
    auto_rotate: float = 0.0
    #: nach so vielen Sekunden auf die erste Seite zurueck, 0 = aus
    page_timeout: float = 60.0
    #: Beleuchtung im Leerlauf nach so vielen Minuten aus, 0 = immer an
    backlight_timeout: float = 0.0
    refresh_interval: float = 0.25
    #: LCD regelmaessig neu initialisieren (Stoerungen), Sekunden, 0 = aus
    reinit_interval: float = 300.0
    clock_12h: bool = False


@dataclass
class EncoderConfig:
    enabled: bool = True
    reverse: bool = False


@dataclass
class ProgressConfig:
    source: str = "auto"
    eta: str = "auto"


@dataclass
class MenuItemConfig:
    """Eigener Menuepunkt aus ``[menu_item NAME]``."""

    label: str
    gcode: str = ""
    power_device: str = ""
    confirm: bool = False
    when: str = "idle"


@dataclass
class PreheatConfig:
    """Vorheiz-Vorgabe aus ``[preheat NAME]``; 0 = Heizer nicht anfassen."""

    label: str
    extruder: int = 0
    bed: int = 0


#: gilt, solange kein ``[preheat ...]`` konfiguriert ist
DEFAULT_PREHEATS = (PreheatConfig("PLA", 200, 60), PreheatConfig("PETG", 240, 80), PreheatConfig("ABS", 250, 100))


@dataclass
class MenuConfig:
    enabled: bool = True
    timeout: float = 20.0
    pause: bool = True
    cancel: bool = True
    firmware_restart: bool = True
    homing: bool = True
    #: Untermenue "Achsen bewegen" und das Tempo je Achse (mm/min, im Menue aenderbar)
    move: bool = True
    move_speed_x: int = 3000
    move_speed_y: int = 3000
    move_speed_z: int = 200
    heating: bool = True
    #: Untermenue Luefter: Bauteilluefter und [fan_generic], auch waehrend des Drucks
    fans: bool = True
    #: Untermenue Filament: LOAD_FILAMENT/UNLOAD_FILAMENT, wenn es die Makros gibt,
    #: sonst eingebauter Ablauf mit diesen Laengen (mm) und Tempi (mm/min)
    filament: bool = True
    filament_temperature: int = 0  # 0 = erste Vorheiz-Vorgabe
    filament_load_length: float = 50.0
    filament_purge_length: float = 30.0
    filament_unload_length: float = 60.0
    filament_fast_speed: int = 1200
    filament_slow_speed: int = 300
    #: Schrittweite beim Einstellen einer Zieltemperatur (Grad je Rastung)
    temperature_step: int = 5
    reboot: bool = False
    shutdown: bool = False
    items: list = field(default_factory=list)
    preheats: list = field(default_factory=lambda: list(DEFAULT_PREHEATS))


@dataclass
class Config:
    moonraker: MoonrakerConfig = field(default_factory=MoonrakerConfig)
    serial: SerialConfig = field(default_factory=SerialConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    encoder: EncoderConfig = field(default_factory=EncoderConfig)
    progress: ProgressConfig = field(default_factory=ProgressConfig)
    menu: MenuConfig = field(default_factory=MenuConfig)
    #: Klipper-Objekt -> Anzeigename
    names: dict = field(default_factory=dict)
    #: Klipper-Objekte, die nicht angezeigt werden
    hidden: tuple = ()
    log_level: str = "info"
    source: str = "<defaults>"

    def warnings(self) -> list:
        notes = []
        if not self.serial.port:
            notes.append("[serial] port ist nicht gesetzt - es wird nichts angezeigt.")
        elif "/by-id/usb-1a86_" in self.serial.port:
            notes.append(
                "CH340-Adapter haben keine Seriennummer: Steckt ein zweiter am selben "
                "Rechner, ist der by-id-Name nicht eindeutig - dann /dev/serial/by-path/ nutzen."
            )
        return notes

    def describe(self) -> str:
        lines = [
            "Konfiguration: %s" % self.source,
            "  Moonraker : %s" % self.moonraker.url,
            "  Serial    : %s @ %d Baud" % (self.serial.port or "<nicht gesetzt>", self.serial.baudrate),
            "  Sprache   : %s (Zeichensatz %s)" % (self.display.language, self.display.charset),
            "  Seiten    : %s" % ", ".join(self.display.pages),
            "  Drehgeber : %s" % ("ja" if self.encoder.enabled else "nein"),
        ]
        if self.menu.heating and self.menu.preheats:
            lines.append("  Vorheizen : %s" % ", ".join(
                "%s %d/%d" % (p.label, p.extruder, p.bed) for p in self.menu.preheats))
        for item in self.menu.items:
            lines.append("  Menuepunkt: %s (%s)" % (item.label, item.when))
        for note in self.warnings():
            lines.append("  Hinweis   : %s" % note)
        return "\n".join(lines)


def find_config(explicit: str = "") -> str:
    if explicit:
        path = os.path.abspath(os.path.expanduser(explicit))
        if not os.path.isfile(path):
            raise ConfigError("Konfigurationsdatei nicht gefunden: %s" % path)
        return path
    for candidate in DEFAULT_CONFIG_PATHS:
        path = os.path.abspath(os.path.expanduser(candidate))
        if os.path.isfile(path):
            return path
    return ""


def normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise ConfigError("[moonraker] url darf nicht leer sein")
    if url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    elif url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif not url.startswith(("ws://", "wss://")):
        url = "ws://" + url
    if "/websocket" not in url:
        url = url.rstrip("/") + "/websocket"
    return url


def _choice(value: str, allowed, where: str) -> str:
    value = value.strip().lower()
    if value not in allowed:
        raise ConfigError("%s: %r unbekannt (erlaubt: %s)" % (where, value, ", ".join(allowed)))
    return value


def _list(value: str) -> list:
    return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]


_SECTIONS = {
    "moonraker": {"url", "api_key", "api_key_file", "connect_timeout", "reconnect_min", "reconnect_max"},
    "serial": {"port", "baudrate", "handshake_timeout", "wrong_device_delay"},
    "display": {
        "language", "charset", "name", "pages", "auto_rotate", "page_timeout", "backlight_timeout",
        "refresh_interval", "reinit_interval", "clock_12h", "hide",
    },
    "encoder": {"enabled", "reverse"},
    "progress": {"source", "eta"},
    "menu": {
        "enabled", "timeout", "pause", "cancel", "firmware_restart", "homing", "move",
        "move_speed_x", "move_speed_y", "move_speed_z", "heating", "fans", "filament", "filament_temperature",
        "filament_load_length", "filament_purge_length", "filament_unload_length", "filament_fast_speed",
        "filament_slow_speed", "temperature_step", "reboot", "shutdown",
    },
    "logging": {"level"},
}
_ITEM_KEYS = {"label", "gcode", "power_device", "confirm", "when"}
_PREHEAT_KEYS = {"label", "extruder", "bed"}


def load(path: str = "") -> Config:
    """Konfiguration laden; ohne Datei gelten die Standardwerte."""
    cfg = Config()
    resolved = find_config(path)
    if not resolved:
        return cfg
    # interpolation=None: "%" in G-Code und API-Schluesseln ist nichts Besonderes
    parser = configparser.ConfigParser(
        inline_comment_prefixes=("#",), delimiters=("=",), interpolation=None
    )
    parser.optionxform = str
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            parser.read_file(handle)
        _apply(cfg, parser)
    except ConfigError:
        raise
    except (OSError, configparser.Error, ValueError) as exc:
        raise ConfigError("Konfiguration %s: %s" % (resolved, exc)) from exc
    cfg.source = resolved
    validate(cfg)
    return cfg


def _check_keys(parser) -> None:
    for section in parser.sections():
        if section == "names":
            continue
        if section.startswith("menu_item"):
            allowed = _ITEM_KEYS
        elif section.startswith("preheat"):
            allowed = _PREHEAT_KEYS
        elif section in _SECTIONS:
            allowed = _SECTIONS[section]
        else:
            raise ConfigError("unbekannter Abschnitt [%s]" % section)
        unknown = sorted(set(parser[section]) - allowed)
        if unknown:
            raise ConfigError("[%s]: unbekannt: %s" % (section, ", ".join(unknown)))


def _apply(cfg: Config, parser) -> None:
    _check_keys(parser)

    sec = parser["moonraker"] if parser.has_section("moonraker") else None
    if sec is not None:
        m = cfg.moonraker
        m.url = normalize_url(sec.get("url", m.url))
        m.api_key = sec.get("api_key", "").strip()
        key_file = sec.get("api_key_file", "").strip()
        if key_file and not m.api_key:
            expanded = os.path.expanduser(key_file)
            try:
                with open(expanded, "r", encoding="utf-8") as handle:
                    m.api_key = handle.read().strip()
            except OSError as exc:
                raise ConfigError("api_key_file %s nicht lesbar: %s" % (expanded, exc)) from exc
        m.connect_timeout = sec.getfloat("connect_timeout", m.connect_timeout)
        m.reconnect_min = sec.getfloat("reconnect_min", m.reconnect_min)
        m.reconnect_max = sec.getfloat("reconnect_max", m.reconnect_max)

    if parser.has_section("serial"):
        sec, s = parser["serial"], cfg.serial
        s.port = os.path.expanduser(sec.get("port", "").strip())
        s.baudrate = sec.getint("baudrate", s.baudrate)
        s.handshake_timeout = sec.getfloat("handshake_timeout", s.handshake_timeout)
        s.wrong_device_delay = sec.getfloat("wrong_device_delay", s.wrong_device_delay)

    if parser.has_section("display"):
        sec, d = parser["display"], cfg.display
        d.language = _choice(sec.get("language", d.language), LANGUAGES, "[display] language")
        d.charset = _choice(sec.get("charset", d.charset), tuple(CHARSETS), "[display] charset")
        d.name = sec.get("name", "").strip()
        if "pages" in sec:
            d.pages = tuple(_choice(p, PAGES, "[display] pages") for p in _list(sec["pages"]))
        d.auto_rotate = sec.getfloat("auto_rotate", d.auto_rotate)
        d.page_timeout = sec.getfloat("page_timeout", d.page_timeout)
        d.backlight_timeout = sec.getfloat("backlight_timeout", d.backlight_timeout)
        d.refresh_interval = sec.getfloat("refresh_interval", d.refresh_interval)
        d.reinit_interval = sec.getfloat("reinit_interval", d.reinit_interval)
        d.clock_12h = sec.getboolean("clock_12h", d.clock_12h)
        cfg.hidden = tuple(_list(sec.get("hide", "")))

    if parser.has_section("encoder"):
        sec, e = parser["encoder"], cfg.encoder
        e.enabled = sec.getboolean("enabled", e.enabled)
        e.reverse = sec.getboolean("reverse", e.reverse)

    if parser.has_section("progress"):
        sec, p = parser["progress"], cfg.progress
        p.source = _choice(sec.get("source", p.source), PROGRESS_SOURCES, "[progress] source")
        p.eta = _choice(sec.get("eta", p.eta), ETA_SOURCES, "[progress] eta")

    if parser.has_section("menu"):
        sec, n = parser["menu"], cfg.menu
        n.timeout = sec.getfloat("timeout", n.timeout)
        n.temperature_step = sec.getint("temperature_step", n.temperature_step)
        for key in ("move_speed_x", "move_speed_y", "move_speed_z", "filament_temperature",
                    "filament_fast_speed", "filament_slow_speed"):
            setattr(n, key, sec.getint(key, getattr(n, key)))
        for key in ("filament_load_length", "filament_purge_length", "filament_unload_length"):
            setattr(n, key, sec.getfloat(key, getattr(n, key)))
        for key in ("enabled", "pause", "cancel", "firmware_restart", "homing", "move", "heating", "fans",
                    "filament", "reboot", "shutdown"):
            setattr(n, key, sec.getboolean(key, getattr(n, key)))

    preheats = []
    for section in parser.sections():
        if section.startswith("menu_item"):
            cfg.menu.items.append(_menu_item(section, parser[section]))
        elif section.startswith("preheat"):
            preheats.append(_preheat(section, parser[section]))
    if preheats:
        cfg.menu.preheats = preheats

    if parser.has_section("names"):
        cfg.names = {key.strip(): value.strip() for key, value in parser["names"].items()}

    if parser.has_section("logging"):
        cfg.log_level = _choice(
            parser["logging"].get("level", cfg.log_level),
            ("debug", "info", "warning", "error"),
            "[logging] level",
        )


def _menu_item(section: str, sec) -> MenuItemConfig:
    default_label = section[len("menu_item"):].strip()
    label = sec.get("label", default_label).strip()
    if not label:
        raise ConfigError("[%s]: 'label' fehlt" % section)
    item = MenuItemConfig(
        label=label,
        gcode="\n".join(line.strip() for line in sec.get("gcode", "").splitlines() if line.strip()),
        power_device=sec.get("power_device", "").strip(),
        confirm=sec.getboolean("confirm", False),
        when=_choice(sec.get("when", "idle"), WHEN, "[%s] when" % section),
    )
    if bool(item.gcode) == bool(item.power_device):
        raise ConfigError("[%s]: genau eines von 'gcode' und 'power_device' angeben" % section)
    return item


def _preheat(section: str, sec) -> PreheatConfig:
    label = sec.get("label", section[len("preheat"):]).strip()
    if not label:
        raise ConfigError("[%s]: 'label' fehlt" % section)
    preheat = PreheatConfig(label, sec.getint("extruder", 0), sec.getint("bed", 0))
    if preheat.extruder < 0 or preheat.bed < 0:
        raise ConfigError("[%s]: Temperaturen duerfen nicht negativ sein" % section)
    if not (preheat.extruder or preheat.bed):
        raise ConfigError("[%s]: 'extruder' oder 'bed' angeben" % section)
    return preheat


def validate(cfg: Config) -> None:
    if not cfg.display.pages:
        raise ConfigError("[display] pages: mindestens eine Seite noetig")
    if cfg.display.refresh_interval < 0.1:
        raise ConfigError("[display] refresh_interval muss mindestens 0.1 sein")
    for name, value in (
        ("auto_rotate", cfg.display.auto_rotate),
        ("page_timeout", cfg.display.page_timeout),
        ("backlight_timeout", cfg.display.backlight_timeout),
        ("reinit_interval", cfg.display.reinit_interval),
    ):
        if value < 0:
            raise ConfigError("[display] %s darf nicht negativ sein" % name)
    if cfg.menu.timeout <= 0:
        raise ConfigError("[menu] timeout muss > 0 sein")
    for axis in "xyz":
        if getattr(cfg.menu, "move_speed_" + axis) <= 0:
            raise ConfigError("[menu] move_speed_%s muss > 0 sein (mm/min)" % axis)
    menu = cfg.menu
    if menu.filament_temperature < 0 or menu.filament_purge_length < 0:
        raise ConfigError("[menu] filament_temperature/filament_purge_length duerfen nicht negativ sein")
    if menu.filament_load_length <= 0 or menu.filament_unload_length <= 0:
        raise ConfigError("[menu] filament_load_length/filament_unload_length muessen > 0 sein")
    if menu.filament_fast_speed <= 0 or menu.filament_slow_speed <= 0:
        raise ConfigError("[menu] filament_fast_speed/filament_slow_speed muessen > 0 sein (mm/min)")
    if not 1 <= cfg.menu.temperature_step <= 50:
        raise ConfigError("[menu] temperature_step muss zwischen 1 und 50 liegen")
    if cfg.serial.baudrate <= 0:
        raise ConfigError("[serial] baudrate muss > 0 sein")
    if cfg.moonraker.reconnect_min <= 0 or cfg.moonraker.connect_timeout <= 0:
        raise ConfigError("[moonraker] Zeiten muessen > 0 sein")
