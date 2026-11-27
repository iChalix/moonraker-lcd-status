"""Bedienlogik: Seiten, Menue, Rueckfragen, Hinweise, Beleuchtung.

Reine Zustandslogik ohne Ein-/Ausgabe: :meth:`UI.render` liefert Zeilen,
:meth:`UI.rotate`, :meth:`UI.click` und :meth:`UI.long_press` verarbeiten den
Drehgeber. Ausgefuehrt wird ueber den ``on_action``-Rueckruf.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import pages, screen
from .config import Config
from .printer import Phase

BACK = "back"
MAIN = "main"
#: Homing-Untermenue: (Text, G-Code)
HOMING = (
    ("home_all", "G28"), ("home_xy", "G28 X Y"), ("home_x", "G28 X"), ("home_y", "G28 Y"),
    ("home_z", "G28 Z"),
)
#: Schrittweiten beim Einstellen einer Achsposition (mm)
MOVE_STEPS = (0.1, 1.0, 10.0)
#: waehlbares Tempo beim Bewegen (mm/min); der Wert aus der Konfiguration kommt dazu
#: Schrittweiten beim Z-Offset (mm)
Z_STEPS = (0.005, 0.01, 0.025, 0.05, 0.1)
#: groesster Z-Offset, der sich einstellen laesst (mm)
Z_LIMIT = 2.0
#: Prozent je Rastung beim Einstellen eines Luefters
FAN_STEP = 10
MOVE_SPEEDS = (50, 100, 200, 300, 500, 1000, 1500, 2000, 3000, 4000, 5000, 6000, 8000, 10000)


@dataclass(frozen=True)
class Action:
    """Was der Dienst ausfuehren soll."""

    kind: str  # rpc | gcode | power | refresh | back | submenu | edit | jog | step | speed | filament | ftemp | fan | zoffset | zstep
    label: str
    method: str = ""
    payload: str = ""
    confirm: bool = False
    when: str = "always"


def allowed(action: Action, phase: Phase) -> bool:
    """Passt der Menuepunkt zum Zustand? Wird auch beim Ausfuehren geprueft."""
    when = action.when
    if when == "fault":
        return phase.fault
    if action.kind in ("gcode", "edit", "jog") and not phase.ready:
        return False
    if when == "ready":
        return phase.ready
    if when == "always":
        return phase is not Phase.OFFLINE
    if when == "printing":
        return phase is Phase.PRINTING
    if when == "paused":
        return phase is Phase.PAUSED
    if when == "active":
        return phase.active
    # idle: Klipper bereit und kein Druck - "busy" zaehlt nicht als Leerlauf
    return phase.ready and not phase.active and phase is not Phase.BUSY


class UI:
    def __init__(self, config: Config, printer, translate, on_action=None) -> None:
        self._config = config
        self._printer = printer
        self._t = translate
        self._on_action = on_action or (lambda action: None)
        self.cols = 20
        self.rows = 4
        self._page = 0
        self._page_since = 0.0
        self._last_input = 0.0
        self._menu = None      # Liste der Actions oder None
        self._menu_id = MAIN
        self._stack = []       # (Menue, Cursor) der uebergeordneten Menues
        self._cursor = 0
        self._edit = None      # [Action, Wert] beim Einstellen einer Temperatur
        self._jog = None       # [Action, Ist, Ziel] beim Einstellen einer Achsposition
        self._move_step = 1    # Index in MOVE_STEPS, 1 mm
        self._step_edit = None  # Index beim Einstellen der Schrittweite
        menu = config.menu
        self._speeds = {"x": menu.move_speed_x, "y": menu.move_speed_y, "z": menu.move_speed_z}
        self._speed_edit = None  # [Achse, Tempo] beim Einstellen des Tempos
        self._ftemp = menu.filament_temperature or next(
            (p.extruder for p in menu.preheats if p.extruder), 200)
        self._ftemp_edit = None  # Temperatur beim Einstellen fuer Laden/Entladen
        self._fan_edit = None  # [Action, Prozent] beim Einstellen eines Luefters
        self._z_step = 1         # Index in Z_STEPS, 0.01 mm
        self._z_step_edit = None  # Index beim Einstellen der Schrittweite
        self._z_edit = None      # [Ist, Ziel] beim Einstellen des Z-Offsets
        self._question = None  # Action, die auf Ja/Nein wartet
        self._answer = False
        self._notice = None    # (Text, Ablaufzeit)
        self._phase = None
        self._phase_since = 0.0

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows

    # ------------------------------------------------------------ Eingaben

    def _input(self, now: float) -> bool:
        """``False``, wenn die Eingabe nur das dunkle Display geweckt hat."""
        was_dark = not self.backlight(now)
        self._last_input = now
        return not was_dark

    def rotate(self, steps: int, now: float) -> None:
        if not steps or not self._input(now):
            return
        if self._question is not None:
            # im Uhrzeigersinn zum Ja, zurueck zum Nein
            self._answer = steps > 0
        elif self._jog is not None:
            self._adjust_jog(steps)
        elif self._step_edit is not None:
            self._step_edit = min(max(self._step_edit + steps, 0), len(MOVE_STEPS) - 1)
        elif self._fan_edit is not None:
            self._fan_edit[1] = min(max(self._fan_edit[1] + steps * FAN_STEP, 0), 100)
        elif self._z_edit is not None:
            target = round(self._z_edit[1] + steps * Z_STEPS[self._z_step], 3)
            self._z_edit[1] = min(max(target, -Z_LIMIT), Z_LIMIT)
        elif self._z_step_edit is not None:
            self._z_step_edit = min(max(self._z_step_edit + steps, 0), len(Z_STEPS) - 1)
        elif self._ftemp_edit is not None:
            low, high = self._ftemp_limits()
            self._ftemp_edit = min(max(self._ftemp_edit + steps * self._config.menu.temperature_step, low), high)
        elif self._speed_edit is not None:
            axis, speed = self._speed_edit
            values = self._speed_values(axis)
            index = min(max(values.index(speed) + steps, 0), len(values) - 1)
            self._speed_edit[1] = values[index]
        elif self._edit is not None:
            step = self._config.menu.temperature_step
            top = int(self._printer.max_temp(self._edit[0].payload))
            self._edit[1] = min(max(self._edit[1] + steps * step, 0), top)
        elif self._menu is not None:
            self._cursor = min(max(self._cursor + steps, 0), len(self._menu) - 1)
        else:
            count = len(pages.page_list(self._context(now, 0.0)))
            self._page = (self._page + steps) % count
            self._page_since = now

    def click(self, now: float) -> None:
        if not self._input(now):
            return
        if self._notice is not None:
            self._notice = None
            return
        if self._question is not None:
            action, answer = self._question, self._answer
            self._question = None
            if answer:
                self._execute(action, now)
            else:
                self._close_menu()
            return
        if self._jog is not None:
            self._finish_jog(now)
            return
        if self._step_edit is not None:
            self._move_step, self._step_edit = self._step_edit, None
            return
        if self._speed_edit is not None:
            axis, speed = self._speed_edit
            self._speeds[axis], self._speed_edit = speed, None
            return
        if self._ftemp_edit is not None:
            self._ftemp, self._ftemp_edit = self._ftemp_edit, None
            return
        if self._fan_edit is not None:
            self._finish_fan(now)
            return
        if self._z_edit is not None:
            self._finish_z(now)
            return
        if self._z_step_edit is not None:
            self._z_step, self._z_step_edit = self._z_step_edit, None
            return
        if self._edit is not None:
            self._finish_edit(now)
            return
        if self._menu is None:
            self._open_menu()
            return
        action = self._menu[self._cursor]
        if action.kind == BACK:
            self._leave_menu()
        elif action.kind == "submenu":
            self._enter_menu(action.payload)
        elif action.kind == "edit":
            self._start_edit(action)
        elif action.kind == "jog":
            self._start_jog(action, now)
        elif action.kind == "step":
            self._step_edit = self._move_step
        elif action.kind == "speed":
            self._speed_edit = [action.payload, self._speeds[action.payload]]
        elif action.kind == "zoffset":
            offset = round(self._printer.z_offset, 3)
            self._z_edit = [offset, offset]
        elif action.kind == "zstep":
            self._z_step_edit = self._z_step
        elif action.kind == "fan":
            self._fan_edit = [action, self._fan_percent(action.payload)]
        elif action.kind == "ftemp":
            low, high = self._ftemp_limits()
            self._ftemp_edit = min(max(self._ftemp, low), high)
        elif action.kind == "filament":
            self._execute(Action("gcode", action.label, payload=self._filament_script(action.payload),
                                 when="idle"), now)
        elif action.confirm:
            self._question, self._answer = action, False
        else:
            self._execute(action, now)

    def long_press(self, now: float) -> None:
        """Ein Schritt zurueck, auf den Seiten: zur ersten Seite."""
        if not self._input(now):
            return
        if self._notice is not None:
            self._notice = None
        elif self._question is not None:
            self._question = None
        elif self._edit is not None:
            self._edit = None
        elif any(edit is not None for edit in self._value_edits()):
            self._jog = self._step_edit = self._speed_edit = self._ftemp_edit = self._fan_edit = None
            self._z_edit = self._z_step_edit = None
        elif self._menu is not None:
            self._leave_menu()
        else:
            self._page = 0

    def notice(self, text: str, now: float, seconds: float = 4.0) -> None:
        self._notice = (text, now + seconds)
        self._last_input = now

    # ------------------------------------------------------------ Menue

    def actions(self, menu_id: str = MAIN) -> list:
        """Alle gerade passenden Menuepunkte."""
        if menu_id == "home":
            candidates = [Action(BACK, self._t("back"))] + [
                Action("gcode", self._t(key), payload=gcode, when="idle") for key, gcode in HOMING
            ]
            return [action for action in candidates if self._allowed(action)]
        if menu_id == "move":
            candidates = [Action(BACK, self._t("back"))] + [
                Action("jog", self._t("axis_" + axis), payload=axis, when="idle") for axis in "xyz"
            ] + [Action("step", self._t("step"), when="idle")] + [
                Action("speed", "%s %s" % (self._t("speed"), axis.upper()), payload=axis, when="idle")
                for axis in "xyz"
            ] + [Action("gcode", self._t("motors_off"), payload="M84", when="idle")]
            return [action for action in candidates if self._allowed(action)]
        if menu_id == "zoffset":
            probe = self._printer.z_uses_probe
            candidates = [
                Action(BACK, self._t("back")),
                Action("zoffset", self._t("z_offset"), when="ready"),
                Action("zstep", self._t("step"), when="ready"),
                Action("gcode", self._t("reset"), payload=self._z_script("Z=0"), when="ready"),
                Action("gcode", self._t("save"), confirm=True, when="idle", payload="%s\nSAVE_CONFIG" % (
                    "Z_OFFSET_APPLY_PROBE" if probe else "Z_OFFSET_APPLY_ENDSTOP")),
            ]
            return [action for action in candidates if self._allowed(action)]
        if menu_id == "fans":
            candidates = [Action(BACK, self._t("back"))] + [
                Action("fan", name, payload=obj, when="ready") for obj, name, _ in self._printer.fans
            ]
            return [action for action in candidates if self._allowed(action)]
        if menu_id == "filament":
            candidates = [
                Action(BACK, self._t("back")),
                Action("filament", self._t("load"), payload="load", when="idle"),
                Action("filament", self._t("unload"), payload="unload", when="idle"),
                Action("ftemp", self._t("temperature"), when="idle"),
            ]
            return [action for action in candidates if self._allowed(action)]
        if menu_id == "heat":
            return [action for action in self._heat_actions() if self._allowed(action)]
        t, menu = self._t, self._config.menu
        candidates = [Action(BACK, t("back"))]
        if menu.pause:
            candidates.append(Action("rpc", t("pause"), "printer.print.pause", when="printing"))
            candidates.append(Action("rpc", t("resume"), "printer.print.resume", when="paused"))
        if menu.cancel:
            candidates.append(
                Action("rpc", t("cancel"), "printer.print.cancel", confirm=True, when="active")
            )
        if menu.firmware_restart:
            candidates.append(
                Action("rpc", t("firmware_restart"), "printer.firmware_restart", confirm=True, when="fault")
            )
        if menu.homing:
            candidates.append(Action("submenu", t("home"), payload="home", when="idle"))
        if menu.move:
            candidates.append(Action("submenu", t("move"), payload="move", when="idle"))
        if menu.heating and (self._printer.extruder or self._printer.bed):
            candidates.append(Action("submenu", t("heat"), payload="heat", when="ready"))
        if menu.z_offset:
            candidates.append(Action("submenu", t("z_offset"), payload="zoffset", when="ready"))
        if menu.fans and self._printer.fans:
            candidates.append(Action("submenu", t("fan"), payload="fans", when="ready"))
        if menu.filament and self._printer.extruder:
            candidates.append(Action("submenu", t("filament"), payload="filament", when="idle"))
        for item in menu.items:
            candidates.append(
                Action(
                    "gcode" if item.gcode else "power", item.label,
                    payload=item.gcode or item.power_device, confirm=item.confirm, when=item.when,
                )
            )
        candidates.append(Action("refresh", t("refresh"), when="display"))
        if menu.reboot:
            candidates.append(Action("rpc", t("reboot"), "machine.reboot", confirm=True, when="host"))
        if menu.shutdown:
            candidates.append(
                Action("rpc", t("shutdown_host"), "machine.shutdown", confirm=True, when="host")
            )
        return [action for action in candidates if self._allowed(action)]

    def _heat_actions(self) -> list:
        """Vorgaben und Abkuehlen nur ohne Druck, Zieltemperaturen auch waehrend."""
        t, printer = self._t, self._printer
        extruder, bed = printer.extruder, printer.bed
        actions = [Action(BACK, t("back"))]
        for preset in self._config.menu.preheats:
            lines, parts = [], []
            if preset.extruder and extruder:
                lines.append(_set_target(extruder.object, preset.extruder))
                parts.append("%d°" % preset.extruder)
            if preset.bed and bed:
                lines.append(_set_target(bed.object, preset.bed))
                parts.append("%d°" % preset.bed)
            if lines:
                label = "%s %s" % (preset.label, "/".join(parts))
                actions.append(Action("gcode", label, payload="\n".join(lines), when="idle"))
        for heater in (extruder, bed):
            if heater:
                actions.append(Action("edit", heater.name, payload=heater.object, when="ready"))
        actions.append(Action("gcode", t("cooldown"), payload="TURN_OFF_HEATERS", when="idle"))
        return actions

    def _allowed(self, action: Action) -> bool:
        if action.kind == BACK or action.when == "display":
            return True
        phase = self._printer.phase
        if action.when == "host":
            # nie waehrend eines Drucks oder solange sich etwas bewegt
            return phase is not Phase.OFFLINE and not phase.active and phase is not Phase.BUSY
        return allowed(action, phase)

    def _open_menu(self) -> None:
        if not self._config.menu.enabled:
            return
        self._menu_id, self._stack = MAIN, []
        self._menu = self.actions()
        self._cursor = 0

    def _close_menu(self) -> None:
        self._menu, self._menu_id, self._stack = None, MAIN, []
        self._edit = self._jog = self._step_edit = self._speed_edit = self._ftemp_edit = self._fan_edit = None
        self._z_edit = self._z_step_edit = None

    def _enter_menu(self, menu_id: str) -> None:
        self._stack.append((self._menu_id, self._cursor))
        self._menu_id = menu_id
        self._menu = self.actions(menu_id)
        self._cursor = 0

    def _leave_menu(self) -> None:
        """Eine Ebene zurueck; im Hauptmenue schliessen."""
        if not self._stack:
            self._close_menu()
            return
        self._menu_id, cursor = self._stack.pop()
        self._menu = self.actions(self._menu_id)
        self._cursor = min(cursor, len(self._menu) - 1)

    def _refresh_menu(self) -> None:
        """Menue an den neuen Zustand anpassen; der Cursor bleibt auf demselben
        Eintrag. Ist der verschwunden, steht er auf "Zurueck" - nie auf einem
        Befehl, den der Benutzer nicht ausgewaehlt hat."""
        if self._edit is not None and not self._allowed(self._edit[0]):
            self._edit = None
        if self._jog is not None and not self._allowed(self._jog[0]):
            self._jog = None
        if self._fan_edit is not None and not self._allowed(self._fan_edit[0]):
            self._fan_edit = None
        if self._z_edit is not None and not self._printer.phase.ready:
            self._z_edit = None
        if self._menu is None:
            return
        selected = self._menu[self._cursor]
        self._menu = self.actions(self._menu_id)
        self._cursor = self._menu.index(selected) if selected in self._menu else 0

    def _execute(self, action: Action, now: float) -> None:
        self._close_menu()
        # zwischen Anzeige und Druck auf den Knopf kann sich der Zustand aendern
        if not self._allowed(action):
            self.notice(self._t("not_now"), now)
            return
        self._on_action(action)

    def _heater(self, name: str):
        for heater in self._printer.heaters:
            if heater.object == name:
                return heater
        return None

    def _start_jog(self, action: Action, now: float) -> None:
        if not self._printer.homed(action.payload):
            self.notice(self._t("home_first"), now, 2.0)
            return
        position = self._printer.position(action.payload)
        self._jog = [action, position, position]

    def _adjust_jog(self, steps: int) -> None:
        """Zielposition aendern, innerhalb der Grenzen; bewegt wird erst beim Klick."""
        action, _, target = self._jog
        axis = action.payload
        low, high = self._printer.axis_limits(axis)
        if axis == "z":
            low = max(low, 0.0)  # nie unter Z=0 ins Bett
        target = round(target + steps * MOVE_STEPS[self._move_step], 3)
        if high > low:
            target = min(max(target, low), high)
        self._jog[2] = target

    def _finish_jog(self, now: float) -> None:
        """Zur Zielposition fahren; die Achsauswahl bleibt offen."""
        action, position, target = self._jog
        self._jog = None
        delta = round(target - position, 3)
        if not delta:
            return
        if not self._allowed(action):
            self.notice(self._t("not_now"), now)
            return
        axis = action.payload
        speed = self._speeds[axis]
        script = "SAVE_GCODE_STATE NAME=lcd_move\nG91\nG1 %s%s F%d\nRESTORE_GCODE_STATE NAME=lcd_move" % (
            axis.upper(), _number(delta), speed)
        self._on_action(Action("gcode", action.label, payload=script, when="idle"))

    def _value_edits(self) -> tuple:
        return (self._jog, self._step_edit, self._speed_edit, self._ftemp_edit, self._fan_edit,
                self._z_edit, self._z_step_edit)

    def _z_script(self, change: str) -> str:
        """SET_GCODE_OFFSET; nach dem Homing faehrt der Kopf sofort mit (MOVE=1)."""
        move = " MOVE=1" if self._printer.homed("z") else ""
        return "SET_GCODE_OFFSET %s%s" % (change, move)

    def _finish_z(self, now: float) -> None:
        """Z-Offset um die Differenz verstellen; das Menue bleibt offen."""
        current, target = self._z_edit
        self._z_edit = None
        delta = round(target - current, 3)
        if not delta:
            return
        if not self._printer.phase.ready:
            self.notice(self._t("not_now"), now)
            return
        payload = self._z_script("Z_ADJUST=%s" % _number(delta))
        self._on_action(Action("gcode", self._t("z_offset"), payload=payload, when="ready"))

    def _fan_percent(self, name: str) -> int:
        for obj, _, speed in self._printer.fans:
            if obj == name:
                return int(round(speed * 100))
        return 0

    def _finish_fan(self, now: float) -> None:
        """Drehzahl senden; das Luefter-Menue bleibt offen."""
        action, percent = self._fan_edit
        self._fan_edit = None
        if not self._allowed(action):
            self.notice(self._t("not_now"), now)
            return
        if action.payload == "fan":
            script = "M106 S%d" % int(percent * 255 / 100 + 0.5) if percent else "M107"
        else:
            script = "SET_FAN_SPEED FAN=%s SPEED=%s" % (action.payload.split(" ", 1)[1], _number(percent / 100))
        self._on_action(Action("gcode", action.label, payload=script, when="ready"))

    def _ftemp_limits(self) -> tuple:
        """Laden/Entladen: nicht unter min_extrude_temp, nicht ueber max_temp."""
        extruder = self._printer.extruder
        name = extruder.object if extruder else "extruder"
        return int(self._printer.setting(name, "min_extrude_temp", 170.0)), int(self._printer.max_temp(name))

    def _filament_script(self, kind: str) -> str:
        """Aufheizen und warten, dann Makro oder eingebauter Ablauf."""
        heat = "M109 S%d" % self._ftemp
        macro = "LOAD_FILAMENT" if kind == "load" else "UNLOAD_FILAMENT"
        if macro in self._printer.macros:
            return "\n".join((heat, macro))
        menu, extruder = self._config.menu, self._printer.extruder
        chunk = self._printer.setting(extruder.object if extruder else "extruder", "max_extrude_only_distance", 50.0)
        lines = ["SAVE_GCODE_STATE NAME=lcd_filament", heat, "M83"]
        if kind == "load":
            lines += _extrude(menu.filament_load_length, menu.filament_fast_speed, chunk)
            lines += _extrude(menu.filament_purge_length, menu.filament_slow_speed, chunk)
        else:
            # Spitze kurz anschmelzen, dann zurueckziehen
            lines += _extrude(5.0, menu.filament_slow_speed, chunk)
            lines += _extrude(-menu.filament_unload_length, menu.filament_fast_speed, chunk)
        lines.append("RESTORE_GCODE_STATE NAME=lcd_filament")
        return "\n".join(lines)

    def _speed_values(self, axis: str) -> list:
        return sorted(set(MOVE_SPEEDS) | {self._speeds[axis], self._speed_edit[1]})

    def _start_edit(self, action: Action) -> None:
        heater = self._heater(action.payload)
        value = heater.target if heater else 0
        if not value:
            # Startwert: erste Vorgabe fuer diesen Heizer
            kind = "bed" if action.payload == "heater_bed" else "extruder"
            values = [getattr(p, kind) for p in self._config.menu.preheats if getattr(p, kind)]
            value = values[0] if values else 0
        self._edit = [action, int(round(value))]

    def _finish_edit(self, now: float) -> None:
        """Zieltemperatur senden; das Heizen-Menue bleibt offen."""
        action, value = self._edit
        self._edit = None
        if not self._allowed(action):
            self.notice(self._t("not_now"), now)
            return
        self._on_action(Action("gcode", action.label, payload=_set_target(action.payload, value), when="ready"))

    # ------------------------------------------------------------ Zeitablauf

    def _context(self, now: float, wall: float) -> pages.PageContext:
        return pages.PageContext(
            self._printer, self._config, self._t, self.cols, self.rows, now, wall
        )

    def _tick(self, now: float, count: int) -> None:
        phase = self._printer.phase
        if phase is not self._phase:
            # Zwischen Leerlauf und "arbeitet" wechselt Klipper staendig (Homing,
            # Makros) - nur echte Wechsel springen auf die erste Seite zurueck.
            calm = (Phase.STANDBY, Phase.BUSY)
            if self._phase is not None and not (phase in calm and self._phase in calm):
                self._page = 0
                self._page_since = now
            self._phase = phase
            self._phase_since = now
            self._refresh_menu()
        if self._notice is not None and now >= self._notice[1]:
            self._notice = None
        display = self._config.display
        idle_for = now - self._last_input
        if self._menu is not None and idle_for >= self._config.menu.timeout:
            self._close_menu()
            self._question = None
        if self._menu is None and self._question is None:
            if display.auto_rotate > 0 and idle_for >= display.auto_rotate:
                if now - self._page_since >= display.auto_rotate:
                    self._page = (self._page + 1) % count
                    self._page_since = now
            elif display.auto_rotate <= 0 and display.page_timeout > 0 and idle_for >= display.page_timeout:
                self._page = 0
        self._page %= count

    def backlight(self, now: float) -> bool:
        timeout = self._config.display.backlight_timeout * 60.0
        if timeout <= 0:
            return True
        phase = self._printer.phase
        if phase.active or phase.fault or phase is Phase.BUSY:
            return True
        if any(heater.heating for heater in self._printer.heaters):
            return True
        return now - max(self._last_input, self._phase_since) < timeout

    # ------------------------------------------------------------ Ausgabe

    def render(self, now: float, wall: float) -> list:
        ctx = self._context(now, wall)
        page_list = pages.page_list(ctx)
        self._tick(now, len(page_list))
        if self._notice is not None:
            return self._render_notice(ctx)
        if self._question is not None:
            return self._render_question(ctx)
        if self._edit is not None:
            return self._render_edit(ctx)
        if self._jog is not None:
            return self._render_jog(ctx)
        if self._step_edit is not None:
            return self._render_step(ctx)
        if self._speed_edit is not None:
            return self._render_speed(ctx)
        if self._ftemp_edit is not None:
            value = screen.spread(self._t("temperature"), "%d°" % self._ftemp_edit, self.cols)
            return self._render_value(ctx, value)
        if self._fan_edit is not None:
            action, percent = self._fan_edit
            return self._render_value(ctx, screen.spread(action.label, "%d%%" % percent, self.cols))
        if self._z_edit is not None:
            return self._render_z(ctx)
        if self._z_step_edit is not None:
            value = screen.spread(self._t("step"), "%s mm" % _number(Z_STEPS[self._z_step_edit]), self.cols)
            return self._render_value(ctx, value)
        if self._menu is not None:
            return self._render_menu(ctx)
        return page_list[self._page]()

    def _render_notice(self, ctx) -> list:
        lines = screen.wrap(self._notice[0], self.cols)[: self.rows]
        top = (self.rows - len(lines)) // 2
        return ctx.finish([""] * top + [screen.center(line, self.cols) for line in lines])

    def _render_question(self, ctx) -> list:
        yes, no = self._t("yes"), self._t("no")
        choice = ("  %s  >%s" if self._answer else " >%s   %s") % (no, yes)
        lines = [screen.ticker(self._question.label, self.cols, ctx.now)]
        if self.rows >= 4:
            lines += [self._t("sure"), ""]
        return ctx.finish(lines + [choice])

    def _degrees(self, value: float) -> str:
        return "%d°" % round(value) if value > 0 else self._t("off")

    def _render_edit(self, ctx) -> list:
        action, value = self._edit
        heater = self._heater(action.payload)
        current = "%.0f°" % heater.temperature if heater else "-"
        target = screen.spread(self._t("target"), self._degrees(value), self.cols)
        if self.rows < 4:
            return ctx.finish([screen.spread(action.label, current, self.cols), target])
        return ctx.finish([
            screen.fit(action.label, self.cols),
            screen.spread(self._t("current"), current, self.cols),
            target,
            screen.center(self._t("edit_hint"), self.cols),
        ])

    def _render_jog(self, ctx) -> list:
        action, position, target = self._jog
        goal = screen.spread(self._t("target"), "%.1f mm" % target, self.cols)
        if self.rows < 4:
            return ctx.finish([screen.spread(action.label, "%.1f" % position, self.cols), goal])
        step = "%s %s" % (self._t("step"), _number(MOVE_STEPS[self._move_step]))
        return ctx.finish([
            screen.spread(action.label, step, self.cols),
            screen.spread(self._t("current"), "%.1f mm" % position, self.cols),
            goal,
            screen.center(self._t("edit_hint"), self.cols),
        ])

    def _render_step(self, ctx) -> list:
        value = screen.spread(self._t("step"), "%s mm" % _number(MOVE_STEPS[self._step_edit]), self.cols)
        if self.rows < 4:
            return ctx.finish([value, screen.center(self._t("edit_hint"), self.cols)])
        return ctx.finish(["", value, "", screen.center(self._t("edit_hint"), self.cols)])

    def _speed_text(self, speed: int) -> str:
        return "%d mm/min" % speed if self.cols >= 20 else "%d" % speed

    def _render_speed(self, ctx) -> list:
        axis, speed = self._speed_edit
        value = screen.spread("%s %s" % (self._t("speed"), axis.upper()), self._speed_text(speed), self.cols)
        return self._render_value(ctx, value)

    def _render_z(self, ctx) -> list:
        current, target = self._z_edit
        goal = screen.spread(self._t("target"), _signed(target) + " mm", self.cols)
        if self.rows < 4:
            return ctx.finish([screen.spread(self._t("z_offset"), _signed(current), self.cols), goal])
        return ctx.finish([
            screen.fit(self._t("z_offset"), self.cols),
            screen.spread(self._t("current"), _signed(current) + " mm", self.cols),
            goal,
            screen.center(self._t("edit_hint"), self.cols),
        ])

    def _render_value(self, ctx, value: str) -> list:
        """Einzelner Wert beim Einstellen, mit Hinweis."""
        if self.rows < 4:
            return ctx.finish([value, screen.center(self._t("edit_hint"), self.cols)])
        return ctx.finish(["", value, "", screen.center(self._t("edit_hint"), self.cols)])

    def _label(self, action: Action) -> str:
        """Menuetext; bei Temperaturen mit dem aktuellen Ziel."""
        if action.kind == "edit":
            heater = self._heater(action.payload)
            return "%s: %s" % (action.label, self._degrees(heater.target if heater else 0))
        if action.kind == "jog":
            axis = action.payload
            value = "%.1f" % self._printer.position(axis) if self._printer.homed(axis) else "?"
            return "%s: %s" % (action.label, value)
        if action.kind == "step":
            return "%s: %s mm" % (action.label, _number(MOVE_STEPS[self._move_step]))
        if action.kind == "speed":
            return "%s: %d" % (action.label, self._speeds[action.payload])
        if action.kind == "ftemp":
            return "%s: %d°" % (action.label, self._ftemp)
        if action.kind == "fan":
            return "%s: %d%%" % (action.label, self._fan_percent(action.payload))
        if action.kind == "zoffset":
            return "%s: %s" % (action.label, _signed(self._printer.z_offset))
        if action.kind == "zstep":
            return "%s: %s mm" % (action.label, _number(Z_STEPS[self._z_step]))
        if action.kind == "submenu":
            return action.label + " >"
        return action.label

    def _render_menu(self, ctx) -> list:
        # den Cursor moeglichst in der Mitte halten
        top = min(max(self._cursor - 1, 0), max(len(self._menu) - self.rows, 0))
        if self._cursor >= top + self.rows:
            top = self._cursor - self.rows + 1
        lines = []
        for index, action in enumerate(self._menu[top : top + self.rows], start=top):
            marker = ">" if index == self._cursor else " "
            width = self.cols - 1
            text = self._label(action)
            lines.append(marker + (
                screen.ticker(text, width, ctx.now) if index == self._cursor else screen.fit(text, width)
            ))
        return ctx.finish(lines)


def _set_target(heater: str, value: int) -> str:
    return "SET_HEATER_TEMPERATURE HEATER=%s TARGET=%d" % (heater, value)


def _number(value: float) -> str:
    """1.0 -> "1", 0.10 -> "0.1", -2.5 -> "-2.5"."""
    return ("%.3f" % value).rstrip("0").rstrip(".")


def _extrude(length: float, speed: int, chunk: float) -> list:
    """Extruderfahrt in Stuecke bis ``chunk`` (Klippers max_extrude_only_distance)."""
    lines, rest, sign = [], round(abs(length), 3), -1 if length < 0 else 1
    while rest > 0:
        part = min(rest, chunk)
        lines.append("G1 E%s F%d" % (_number(sign * part), speed))
        rest = round(rest - part, 3)
    return lines


def _signed(value: float) -> str:
    """Offset mit Vorzeichen, ohne "-0.000"."""
    return "%+.3f" % (round(value, 3) + 0.0)
