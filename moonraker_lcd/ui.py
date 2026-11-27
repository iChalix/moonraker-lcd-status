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


@dataclass(frozen=True)
class Action:
    """Was der Dienst ausfuehren soll."""

    kind: str  # rpc | gcode | power | refresh | back | submenu | edit
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
    if action.kind in ("gcode", "edit") and not phase.ready:
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
        if menu.heating and (self._printer.extruder or self._printer.bed):
            candidates.append(Action("submenu", t("heat"), payload="heat", when="ready"))
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
        self._menu, self._menu_id, self._stack, self._edit = None, MAIN, [], None

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

    def _label(self, action: Action) -> str:
        """Menuetext; bei Temperaturen mit dem aktuellen Ziel."""
        if action.kind == "edit":
            heater = self._heater(action.payload)
            return "%s: %s" % (action.label, self._degrees(heater.target if heater else 0))
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
