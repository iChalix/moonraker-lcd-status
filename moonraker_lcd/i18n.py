"""Texte der Anzeige. Fehlt ein Text in einer Sprache, gilt der englische."""

from __future__ import annotations

TEXTS = {
    "de": {
        "standby": "bereit", "busy": "arbeitet", "printing": "druckt", "paused": "Pause",
        "complete": "Fertig", "cancelled": "Abgebrochen", "error": "FEHLER",
        "offline": "kein Moonraker", "startup": "Klipper startet", "shutdown": "Klipper-Stopp",
        "disconnected": "Klipper fehlt", "print_error": "Druckfehler",
        "hotend": "Hotend", "bed": "Bett", "layer": "S", "eta": "Ende", "remaining": "Rest",
        "elapsed": "Dauer", "height": "Höhe", "speed": "Tempo", "fan": "Lüfter", "flow": "Fluss",
        "filament": "Filament", "print": "Druck", "system": "System", "temperatures": "Temperaturen",
        "no_job": "kein Druck aktiv", "load": "Last", "memory": "RAM",
        "back": "Zurück", "pause": "Pause", "resume": "Fortsetzen", "cancel": "Abbrechen",
        "firmware_restart": "Firmware-Neustart", "reboot": "Pi neu starten",
        "shutdown_host": "Pi herunterfahren", "refresh": "Anzeige auffrischen",
        "yes": "Ja", "no": "Nein", "sure": "Sicher?", "sent": "gesendet", "failed": "Fehlgeschlagen",
        "not_now": "Jetzt nicht möglich", "sketch_old": "Sketch veraltet", "sketch_flash": "bitte neu flashen",
        "service_old": "Dienst veraltet", "bye": "Anzeige beendet",
        "days": "Mo Di Mi Do Fr Sa So",
    },
    "en": {
        "standby": "ready", "busy": "busy", "printing": "printing", "paused": "paused",
        "complete": "Done", "cancelled": "Cancelled", "error": "ERROR",
        "offline": "no Moonraker", "startup": "Klipper starting", "shutdown": "Klipper halted",
        "disconnected": "no Klipper", "print_error": "Print error",
        "hotend": "Hotend", "bed": "Bed", "layer": "L", "eta": "ETA", "remaining": "Left",
        "elapsed": "Elapsed", "height": "Height", "speed": "Speed", "fan": "Fan", "flow": "Flow",
        "filament": "Filament", "print": "Print", "system": "System", "temperatures": "Temperatures",
        "no_job": "no print active", "load": "Load", "memory": "RAM",
        "back": "Back", "pause": "Pause", "resume": "Resume", "cancel": "Cancel print",
        "firmware_restart": "Firmware restart", "reboot": "Reboot host",
        "shutdown_host": "Shut down host", "refresh": "Refresh display",
        "yes": "Yes", "no": "No", "sure": "Sure?", "sent": "sent", "failed": "Failed",
        "not_now": "Not possible now", "sketch_old": "Sketch outdated", "sketch_flash": "please reflash",
        "service_old": "Service outdated", "bye": "Display stopped",
        "days": "Mon Tue Wed Thu Fri Sat Sun",
    },
}

LANGUAGES = tuple(TEXTS)


class Translator:
    def __init__(self, language: str) -> None:
        self.language = language
        self._texts = TEXTS[language]

    def __call__(self, key: str) -> str:
        return self._texts.get(key, TEXTS["en"][key])

    def weekday(self, index: int) -> str:
        return self("days").split()[index]

    def date(self, when) -> str:
        """``Di 24.11.`` bzw. ``Tue 24 Nov`` ohne Abhaengigkeit von der Locale."""
        if self.language == "de":
            return "%s %02d.%02d." % (self.weekday(when.weekday()), when.day, when.month)
        months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
        return "%s %d %s" % (self.weekday(when.weekday()), when.day, months[when.month - 1])
