"""Statusanzeige fuer Klipper-Drucker auf einem Text-LCD am Arduino.

Der Dienst liest den Druckerzustand ueber Moonraker, baut daraus fertige
Displayzeilen und schickt sie seriell an den Arduino. Der meldet den
Drehgeber zurueck; Seiten, Menue und Sprache liegen vollstaendig hier.
"""

__version__ = "1.6.0"

import os
import subprocess


def describe() -> str:
    """Version, in einem Git-Klon zusaetzlich der genaue Stand.

    Beispiel: ``1.2.0 (v1.2.0-3-g1983b41)``. Ohne Git (oder ausserhalb eines
    Klons) kommt nur die Versionsnummer zurueck.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=os.path.dirname(here),
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return __version__
    stand = result.stdout.strip()
    if result.returncode != 0 or not stand:
        return __version__
    return "%s (%s)" % (__version__, stand)


__all__ = ["__version__", "describe"]
