# Gehaeuse fuer das Moonraker-LCD-Statusdisplay
#   - LCD 2004 mit I2C-Adapter (PCF8574)
#   - Drehgeber HW-040 / KY-040 rechts neben dem Display
#   - Arduino Nano im Gehaeuse, USB-Kabel nach unten
#   - Halter fuer 3030-Nutprofil (M5 + Nutenstein), Display nach oben geneigt
#
# Ausfuehren in FreeCAD (Makro oder Python-Konsole):
#   exec(open("/pfad/zu/cad/lcd_gehaeuse.py").read())
# oder ohne Oberflaeche:
#   /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd cad/lcd_gehaeuse.py
#
# Koordinaten des Gehaeuses: x nach rechts, y nach hinten, z nach oben.
# y = 0 ist die Innenseite der Front, x = 0 / z = 0 die Innenseiten links / unten.
# Alle Masse in mm. Die mit "MESSEN" markierten Werte am eigenen Teil pruefen.

import math
import os

import FreeCAD as App
import Part
from FreeCAD import Placement, Rotation
from FreeCAD import Vector as V

# ------------------------------------------------------------------ Parameter
WALL = 2.4            # Seitenwaende
FRONT = 2.4           # Frontplatte
LID = 2.4             # Deckelplatte
LIP = 7.0             # Steg des Deckels, der ins Gehaeuse greift
FIT = 0.2             # Spiel zwischen Deckelsteg und Gehaeuse
CORNER = 3.0          # Radius der Aussenkanten

# LCD 2004
PCB_W, PCB_H, PCB_T = 98.0, 60.0, 1.6
HOLE_DX, HOLE_DZ = 93.0, 55.0          # Lochabstand der Befestigungsloecher
BEZEL_W, BEZEL_H = 97.0, 40.0
BEZEL_T = 10.0        # Hoehe des schwarzen Rahmens ueber der Platine (gemessen) = Hoehe der Dome
DOME_D = 7.5          # Dome fuer die Displayplatine
INSERT_D = 4.0        # Loch fuer Gewindeeinsatz M3 (z.B. M3 x 5,7, Aussen-D 4,6)
INSERT_DEPTH = 6.5    # Lochtiefe (Einsatzlaenge + 0,8)
VA_W, VA_H = 76.0, 25.2                # sichtbare Flaeche
WIN_MARGIN = 0.8      # Fenster etwas groesser als die sichtbare Flaeche
WIN_CHAMFER = 1.6     # Fase aussen am Fenster
BACKPACK = (41.5, 19.0, 12.0)          # I2C-Adapter inkl. Poti (B x H x Tiefe)
I2C_SPACE = 20.0      # Platz links fuer die Stifte des I2C-Adapters mit Dupont-Steckern

# Innenraum
GAP = 2.0             # Abstand Displayplatine - rechtes Fach
RIGHT_W = 36.0        # rechtes Fach (Drehgeber, Nano)
IN_H = 64.0
IN_D = 32.0

# Drehgeber HW-040 / KY-040
ENC_Z = 42.0          # Hoehe der Achse ueber dem Innenboden
ENC_HOLE = 7.4        # Hals 7 mm (gemessen) + Spiel
ENC_BOARD = (19.0, 26.0)               # Platine B x H (gemessen), Stifte (gewinkelt) unten
ENC_TOP = 10.0        # Achse bis Oberkante der Platine
ENC_BODY = (12.0, 6.5)                 # Drehgebergehaeuse Kante, Hoehe ueber der Platine (gemessen)
ENC_FIT = 0.2         # Spiel zwischen Drehgebergehaeuse und Rahmen
ENC_COLLAR = (1.5, 2.0)                # Rahmen um das Gehaeuse (Breite, Hoehe) = Verdrehschutz,
                                       # unten offen fuer den Dupont-Stecker
PLUG = (13.0, 6.5, 21.0)               # Dupont-Stecker auf der Vorderseite der Platine (B, Hoehe, Laenge ab Platinenende+5)
PLUG_RELIEF = 0.5     # Freiraum in der Front unter dem Stecker
CLAMP_DX = 14.0       # Dome fuer den Klemmbuegel links/rechts der Achse
CLAMP_GAP = 0.5       # Dome etwas kuerzer, damit der Buegel sicher auf die Platine drueckt
CLAMP_T = 4.0         # Dicke des Buegels
CLAMP_H = 22.0        # Hoehe des Buegels
CLAMP_POCKET = (15.0, 17.0, 2.0)       # Freiraum fuer die Loetstellen des Drehgebers

# Arduino Nano (steht hochkant, Bauteilseite nach rechts, USB unten)
NANO_L, NANO_W = 43.2, 18.6
NANO_Z0 = 2.0         # Unterkante der Platine ueber dem Innenboden
NANO_CLEAR = 10.0     # Platz auf der Bauteilseite (ICSP-Stifte)
USB_HOLE = (14.0, 12.0)                # Durchbruch im Boden fuer den Mini-USB-Stecker
# laut Foto: USB-Buchse buendig mit der Platinenkante, ca. 4,5 mm hoch;
# Stiftleisten (Stiftseite) beginnen 2,3 mm ueber der USB-Kante und enden 0,8 mm vor der oberen Kante
USB_H = 4.5
HEADER_GAP = (2.3, 0.8)                # freier Rand unten (USB-Ende) / oben
NANO_GRIP = (1.5, 0.5)                 # wie weit die Schienen unten / oben die Platine fassen

# Halter fuer 3030-Profil
TILT = 20.0           # Neigung des Displays nach oben (Grad)
PROFILE = 30.0
SLOT_KEY = 7.6        # Fuehrungssteg fuer die 8-mm-Nut
GAP_TOP = 10.0        # Abstand Profil - Deckel an der Oberkante des Profils
ARM_UP, ARM_DOWN = 10.0, 45.0          # Anlage am Deckel ueber / unter der Profiloberkante
BR_W = 60.0
ANCHOR_Z = 54.0       # Hoehe (Gehaeuse-z) auf Hoehe der Profiloberkante
M5_SPACING = 30.0
# Gedruckter Dreh-Nutenstein (statt Hammermutter): durch den Schlitz stecken, 90 Grad drehen.
# Die M5-Schraube schneidet ihr Gewinde selbst. MESSEN am Profil:
SLOT_OPEN = 8.2       # Schlitzbreite
SLOT_LIP = 2.2        # Dicke der Nutstege
SLOT_INNER = 16.5     # Breite der Nut hinter den Stegen
TNUT_W = 7.4          # schmale Seite (passt durch den Schlitz)
TNUT_T = 4.0          # Dicke
M5_CORE = 4.2         # Kernloch M5
M3_PILOT = 2.5        # Kernloch fuer M3-Schrauben (selbstschneidend in PLA/PETG)
M3_CLEAR = 3.4

EXPORT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None

# ------------------------------------------------------------------ abgeleitet
IN_W = I2C_SPACE + PCB_W + GAP + RIGHT_W
PCB_X = I2C_SPACE
PCB_Z = (IN_H - PCB_H) / 2
LCD_CX = PCB_X + PCB_W / 2
LCD_CZ = PCB_Z + PCB_H / 2
ENC_X = PCB_X + PCB_W + GAP + RIGHT_W / 2
NANO_X = IN_W - NANO_CLEAR - PCB_T      # linke Seite (Stiftseite) der Nano-Platine
NANO_Y = IN_D - NANO_W                  # Nano liegt am Deckel an
NANO_YC = NANO_Y + NANO_W / 2
NANO_Z1 = NANO_Z0 + NANO_L
USB_X = NANO_X + PCB_T + 2.0
SCREW_Y = IN_D - LIP / 2
SCREW_Z = (15.0, 49.0)
BR_X0 = LCD_CX - BR_W / 2
BR_SCREW_Z = (ANCHOR_Z, ANCHOR_Z - 35.0)


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def cyl(r, p, d, h):
    return Part.makeCylinder(r, h, p, d)


def fuse(shapes):
    result = shapes[0]
    for s in shapes[1:]:
        result = result.fuse(s)
    return result.removeSplitter()


def round_y_edges(shape, r):
    edges = []
    for e in shape.Edges:
        if len(e.Vertexes) == 2:
            d = e.Vertexes[1].Point - e.Vertexes[0].Point
            if abs(d.y) > 0.99 * d.Length:
                edges.append(e)
    return shape.makeFillet(r, edges)


def rect_wire(cx, y, cz, w, h):
    pts = [V(cx - w / 2, y, cz - h / 2), V(cx + w / 2, y, cz - h / 2),
           V(cx + w / 2, y, cz + h / 2), V(cx - w / 2, y, cz + h / 2)]
    return Part.makePolygon(pts + [pts[0]])


def holes():
    x0 = LCD_CX - HOLE_DX / 2
    z0 = LCD_CZ - HOLE_DZ / 2
    return [(x0, z0), (x0 + HOLE_DX, z0), (x0, z0 + HOLE_DZ), (x0 + HOLE_DX, z0 + HOLE_DZ)]


def clamp_x():
    return (ENC_X - CLAMP_DX, ENC_X + CLAMP_DX)


def enc_board_back():
    """y der Rueckseite der Drehgeberplatine (Gehaeuse liegt an der Front an)."""
    return ENC_BODY[1] + PCB_T


def plug_z():
    """z-Bereich des Dupont-Steckers: von unterhalb der Platine bis knapp unter den Rahmen."""
    bottom = ENC_Z + ENC_TOP - ENC_BOARD[1]
    top = min(bottom + 5.0, ENC_Z - ENC_BODY[0] / 2 - ENC_FIT - 0.5)
    return top - PLUG[2], top


# ------------------------------------------------------------------ Klemmbuegel
# Drueckt die Platine des Drehgebers von hinten gegen die Front,
# 2x M3x8 in Gewindeeinsaetze der Dome.
def make_clamp():
    y0 = enc_board_back()
    half = CLAMP_DX + DOME_D / 2
    bar = box(ENC_X - half, ENC_X + half, y0, y0 + CLAMP_T, ENC_Z - CLAMP_H / 2, ENC_Z + CLAMP_H / 2)
    pw, ph, pd = CLAMP_POCKET
    bar = bar.cut(box(ENC_X - pw / 2, ENC_X + pw / 2, y0 - 1, y0 + pd, ENC_Z - ph / 2, ENC_Z + ph / 2))
    for x in clamp_x():
        bar = bar.cut(cyl(M3_CLEAR / 2, V(x, y0 - 1, ENC_Z), V(0, 1, 0), CLAMP_T + 2))
    return bar.removeSplitter()


# ------------------------------------------------------------------ Gehaeuse
def make_shell():
    outer = round_y_edges(box(-WALL, IN_W + WALL, -FRONT, IN_D, -WALL, IN_H + WALL), CORNER)
    shell = outer.cut(box(0, IN_W, 0, IN_D + 1, 0, IN_H))
    # Dome fuer die Displayplatine
    domes = [cyl(DOME_D / 2, V(x, -0.5, z), V(0, 1, 0), BEZEL_T + 0.5) for x, z in holes()]
    # Dome fuer den Klemmbuegel des Drehgebers
    clamp_h = enc_board_back() - CLAMP_GAP
    domes += [cyl(DOME_D / 2, V(x, -0.5, ENC_Z), V(0, 1, 0), clamp_h + 0.5) for x in clamp_x()]
    # U-Rahmen um das Drehgebergehaeuse (oben, links, rechts)
    i = ENC_BODY[0] / 2 + ENC_FIT
    o = i + ENC_COLLAR[0]
    ch = ENC_COLLAR[1]
    domes += [box(ENC_X - o, ENC_X + o, -0.5, ch, ENC_Z + i, ENC_Z + o),
              box(ENC_X - o, ENC_X - i, -0.5, ch, ENC_Z - i, ENC_Z + o),
              box(ENC_X + i, ENC_X + o, -0.5, ch, ENC_Z - i, ENC_Z + o)]
    shell = fuse([shell] + domes)
    cuts = [cyl(INSERT_D / 2, V(x, BEZEL_T - INSERT_DEPTH, z), V(0, 1, 0), INSERT_DEPTH + 0.1)
            for x, z in holes()]
    cuts += [cyl(INSERT_D / 2, V(x, clamp_h - INSERT_DEPTH, ENC_Z), V(0, 1, 0), INSERT_DEPTH + 0.1)
             for x in clamp_x()]
    # Displayfenster mit Fase
    ww, wh = VA_W + 2 * WIN_MARGIN, VA_H + 2 * WIN_MARGIN
    window = Part.makeLoft([
        rect_wire(LCD_CX, -FRONT - 0.01, LCD_CZ, ww + 2 * WIN_CHAMFER + 0.02, wh + 2 * WIN_CHAMFER + 0.02),
        rect_wire(LCD_CX, -FRONT + WIN_CHAMFER, LCD_CZ, ww, wh)], True)
    cuts.append(window)
    cuts.append(box(LCD_CX - ww / 2, LCD_CX + ww / 2, -FRONT + WIN_CHAMFER - 0.01, 0.5,
                    LCD_CZ - wh / 2, LCD_CZ + wh / 2))
    # Drehgeber: Loch fuer den Hals, Freiraum fuer den Dupont-Stecker
    cuts.append(cyl(ENC_HOLE / 2, V(ENC_X, -FRONT - 1, ENC_Z), V(0, 1, 0), FRONT + 2))
    z0, z1 = plug_z()
    cuts.append(box(ENC_X - PLUG[0] / 2 - 0.5, ENC_X + PLUG[0] / 2 + 0.5, -PLUG_RELIEF, 0.01, z0 - 0.5, z1 + 0.5))
    # Schrauben Deckel (seitlich)
    for z in SCREW_Z:
        cuts.append(cyl(M3_CLEAR / 2, V(-WALL - 1, SCREW_Y, z), V(1, 0, 0), WALL + 2))
        cuts.append(cyl(M3_CLEAR / 2, V(IN_W - 1, SCREW_Y, z), V(1, 0, 0), WALL + 2))
    # USB-Stecker des Nano
    cuts.append(box(USB_X - USB_HOLE[0] / 2, USB_X + USB_HOLE[0] / 2,
                    NANO_YC - USB_HOLE[1] / 2, NANO_YC + USB_HOLE[1] / 2, -WALL - 1, 0.5))
    for c in cuts:
        shell = shell.cut(c)
    return shell.removeSplitter()


# ------------------------------------------------------------------ Deckel
def notch(x0, x1, y_front, y_back, z0, z1):
    """Aussparung in einer Nano-Schiene. Die Seite zum vorderen Schienenende ist
    um 45 Grad abgeschraegt, damit es beim Druck (Deckel liegt aussen unten) keinen
    Ueberhang gibt."""
    pts = [V(x0, y_back, z0), V(x0, y_front, z0), V(x1, y_front - (x1 - x0), z0), V(x1, y_back, z0)]
    return Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(0, 0, z1 - z0))


def make_lid():
    plate = round_y_edges(box(-WALL, IN_W + WALL, IN_D, IN_D + LID, -WALL, IN_H + WALL), CORNER)
    lip = box(FIT, IN_W - FIT, IN_D - LIP, IN_D + 0.5, FIT, IN_H - FIT).cut(
        box(FIT + 1.6, IN_W - FIT - 1.6, IN_D - LIP - 1, IN_D + 1, FIT + 1.6, IN_H - FIT - 1.6))
    parts = [plate, lip]
    for z in SCREW_Z:
        parts.append(box(FIT, 5.0, IN_D - LIP, IN_D + 0.5, z - 3.5, z + 3.5))
        parts.append(box(IN_W - 5.0, IN_W - FIT, IN_D - LIP, IN_D + 0.5, z - 3.5, z + 3.5))
    # Fuehrungsschienen fuer den Nano (Platine wird von vorne eingeschoben)
    rx0, rx1 = NANO_X - 2.0, NANO_X + PCB_T + 2.0
    gx0, gx1 = NANO_X - 0.2, NANO_X + PCB_T + 0.2
    # unten: Stiftseite ueber die ganze Laenge (die Leisten beginnen erst 2,3 mm hoeher),
    # Bauteilseite nur hinter der USB-Buchse - sie sitzt buendig an der Kante und
    # muss beim Einschieben an der Schiene vorbei
    bottom = box(rx0, rx1, NANO_Y, IN_D + 0.5, 0.3, NANO_Z0 + NANO_GRIP[0])
    bottom = bottom.cut(box(gx0, gx1, NANO_Y - 1, IN_D + 1, NANO_Z0, 10))
    bottom = bottom.cut(box(NANO_X + PCB_T - 0.3, rx1 + 1, NANO_Y - 1, NANO_YC + 5.5, 0, 10))
    # oben: fasst die Platine nur 0,5 mm, weil die Stiftleisten bis 0,8 mm an die Kante reichen
    top = box(rx0, rx1, NANO_Y, IN_D + 0.5, NANO_Z1 - NANO_GRIP[1], NANO_Z1 + 2.5)
    top = top.cut(box(gx0, gx1, NANO_Y - 1, IN_D + 1, NANO_Z1 - 3.0, NANO_Z1 + 0.3))
    parts += [bottom, top]
    lid = fuse(parts)
    # Freiraum im Steg fuer USB-Buchse und ICSP-Stifte des Nano
    lid = lid.cut(box(NANO_X + PCB_T - 0.3, IN_W, NANO_YC - 5.0, NANO_YC + 5.0, -1, NANO_Z0 + 10))
    lid = lid.cut(box(NANO_X + PCB_T + 0.2, IN_W, NANO_YC - 3.0, NANO_YC + 4.0, NANO_Z1 - 11, NANO_Z1 - 1))
    for z in SCREW_Z:
        lid = lid.cut(cyl(M3_PILOT / 2, V(-1, SCREW_Y, z), V(1, 0, 0), 6.0))
        lid = lid.cut(cyl(M3_PILOT / 2, V(IN_W + 1, SCREW_Y, z), V(-1, 0, 0), 6.0))
    for z in BR_SCREW_Z:
        lid = lid.cut(cyl(M3_CLEAR / 2, V(LCD_CX, IN_D - 1, z), V(0, 1, 0), LID + 2))
    return lid.removeSplitter()


# ------------------------------------------------------------------ Halter
# Welt: X wie Gehaeuse, Y zum Profil hin, Z oben. Profilflaeche bei Y = 0,
# Profil bei Y = 0..30, Z = 0..30. Das Gehaeuse liegt bei Y < 0.
def bracket_points():
    a = math.radians(TILT)
    ay, az = -5.0 - GAP_TOP, PROFILE
    dy, dz = -math.sin(a), -math.cos(a)      # am Deckel entlang nach unten
    top = (ay - ARM_UP * dy, az - ARM_UP * dz)
    bot = (ay + ARM_DOWN * dy, az + ARM_DOWN * dz)
    return (ay, az), top, bot


def case_to_world():
    (ay, az), _, _ = bracket_points()
    rot = Rotation(V(1, 0, 0), -TILT)
    p = rot.multVec(V(0, IN_D + LID, ANCHOR_Z))
    return Placement(V(0, ay - p.y, az - p.z), rot)


def make_bracket_world():
    _, top, bot = bracket_points()
    pts = [V(BR_X0, 0, 0), V(BR_X0, 0, PROFILE), V(BR_X0, top[0], top[1]),
           V(BR_X0, bot[0], bot[1]), V(BR_X0, 0, 0)]
    br = Part.Face(Part.makePolygon(pts)).extrude(V(BR_W, 0, 0))
    br = br.fuse(box(BR_X0, BR_X0 + BR_W, 0, 2.0, PROFILE / 2 - SLOT_KEY / 2, PROFILE / 2 + SLOT_KEY / 2))
    for x in (LCD_CX - M5_SPACING / 2, LCD_CX + M5_SPACING / 2):
        br = br.cut(cyl(2.75, V(x, 3.0, PROFILE / 2), V(0, -1, 0), 10.0))
        br = br.cut(cyl(5.0, V(x, -5.0, PROFILE / 2), V(0, -1, 0), 60.0))   # Schraubenkopf + Inbus
    return br.removeSplitter()


def to_case(shape):
    return shape.transformGeometry(case_to_world().inverse().toMatrix())


def to_world(shape):
    return shape.transformGeometry(case_to_world().toMatrix())


def make_bracket():
    # Gewindeeinsaetze von der Anlageflaeche zum Deckel her einschmelzen
    br = to_case(make_bracket_world())
    for z in BR_SCREW_Z:
        br = br.cut(cyl(INSERT_D / 2, V(LCD_CX, IN_D + LID - 0.1, z), V(0, 1, 0), INSERT_DEPTH + 0.1))
    return br


def make_tnut():
    """Dreh-Nutenstein, flach auf dem Druckbett. Lange Seite quer zur Nut nach dem Drehen.
    Zwei diagonale Ecken sind auf den Drehkreis gerundet (drehen nur in eine Richtung),
    die beiden eckigen stossen nach 90 Grad an die Nutwand (Anschlag)."""
    r = SLOT_INNER / 2 - 0.5                 # Drehkreis, passt in die Nut
    length = 2 * math.sqrt(max((SLOT_INNER / 2 + 0.3) ** 2 - (TNUT_W / 2) ** 2, r * r))
    head = box(-length / 2, length / 2, -TNUT_W / 2, TNUT_W / 2, 0, TNUT_T)
    keep = cyl(r, V(0, 0, -1), V(0, 0, 1), TNUT_T + 2)
    # eckig: +x/+y und -x/-y. Mit der Rille zum Schraubenkopf dreht der Stein beim
    # Festziehen (rechtsrum vom Kopf aus) frei in die Querlage und schlaegt dort an.
    keep = keep.fuse(box(0, length, 0, TNUT_W, -1, TNUT_T + 1))
    keep = keep.fuse(box(-length, 0, -TNUT_W, 0, -1, TNUT_T + 1))
    nut = head.common(keep)
    nut = nut.cut(cyl(M5_CORE / 2, V(0, 0, -1), V(0, 0, 1), TNUT_T + 2))
    # Markierung: Rille auf der Seite zum Schraubenkopf
    nut = nut.cut(box(M5_CORE / 2 + 1.0, length / 2 - 1.5, -0.4, 0.4, TNUT_T - 0.5, TNUT_T + 1))
    return nut.removeSplitter()


def make_profile():
    p = box(-30, IN_W + 30, 0, PROFILE, 0, PROFILE)
    c = PROFILE / 2
    for slot in (box(-31, IN_W + 31, -1, 9, c - 4.1, c + 4.1), box(-31, IN_W + 31, PROFILE - 9, PROFILE + 1, c - 4.1, c + 4.1),
                 box(-31, IN_W + 31, c - 4.1, c + 4.1, -1, 9), box(-31, IN_W + 31, c - 4.1, c + 4.1, PROFILE - 9, PROFILE + 1)):
        p = p.cut(slot)
    return to_case(p)


# ------------------------------------------------------------------ Bauteile (nur zur Kontrolle)
def make_dummies():
    d = {}
    d["LCD_Platine"] = box(PCB_X, PCB_X + PCB_W, BEZEL_T, BEZEL_T + PCB_T, PCB_Z, PCB_Z + PCB_H)
    d["LCD_Rahmen"] = box(LCD_CX - BEZEL_W / 2, LCD_CX + BEZEL_W / 2, 0, BEZEL_T, LCD_CZ - BEZEL_H / 2, LCD_CZ + BEZEL_H / 2)
    bw, bh, bt = BACKPACK
    y0 = BEZEL_T + PCB_T
    bz1 = PCB_Z + PCB_H - 1.0
    d["I2C_Adapter"] = box(PCB_X + 4, PCB_X + 4 + bw, y0, y0 + bt, bz1 - bh, bz1)
    d["I2C_Stecker"] = box(2.0, PCB_X + 4, y0 + 2, y0 + 8, bz1 - bh / 2 - 6, bz1 - bh / 2 + 6)
    ex = ENC_X
    bw, bd = ENC_BODY
    f = 0.0                              # Vorderseite des Drehgebergehaeuses
    d["Drehgeber"] = fuse([
        box(ex - bw / 2, ex + bw / 2, f, f + bd, ENC_Z - bw / 2, ENC_Z + bw / 2),
        cyl(3.5, V(ex, f, ENC_Z), V(0, -1, 0), 7.0),
        cyl(3.0, V(ex, f - 7, ENC_Z), V(0, -1, 0), 13.0)])
    w, h = ENC_BOARD
    pb = f + bd
    d["Drehgeber_Platine"] = box(ex - w / 2, ex + w / 2, pb, pb + PCB_T, ENC_Z + ENC_TOP - h, ENC_Z + ENC_TOP)
    z0, z1 = plug_z()                    # Stecker liegt auf der Vorderseite, so hoch wie das Gehaeuse
    d["Drehgeber_Stecker"] = box(ex - PLUG[0] / 2, ex + PLUG[0] / 2, pb - PLUG[1], pb, z0, z1)
    d["Nano"] = box(NANO_X, NANO_X + PCB_T, NANO_Y, IN_D, NANO_Z0, NANO_Z1)
    d.update(nano_parts())
    return d


def nano_parts(dy=0.0):
    """Nano mit Buchse, ICSP, Stiftleisten und Steckern, um dy in y verschoben."""
    zh0, zh1 = NANO_Z0 + HEADER_GAP[0], NANO_Z1 - HEADER_GAP[1]
    p = {
        "Nano_USB": box(NANO_X + PCB_T, NANO_X + PCB_T + USB_H, NANO_YC - 3.9, NANO_YC + 3.9, NANO_Z0 - 0.3, NANO_Z0 + 9),
        "Nano_ICSP": box(NANO_X + PCB_T, NANO_X + PCB_T + 8.5, NANO_YC - 2.6, NANO_YC + 2.6, NANO_Z1 - 9.5, NANO_Z1 - 1.5),
        "Nano_Leisten": fuse([box(NANO_X - 2.5, NANO_X, yc - 1.27, yc + 1.27, zh0, zh1)
                              for yc in (NANO_Y + 1.4, IN_D - 1.4)]),
        "Nano_Stecker": fuse([box(NANO_X - 21.5, NANO_X - 2.5, yc - 1.27, yc + 1.27, zh0, zh1)
                              for yc in (NANO_Y + 1.4, IN_D - 1.4)]),
    }
    if dy:
        for s in p.values():
            s.translate(V(0, dy, 0))
    return p


COLORS = {
    "Gehaeuse": (0.20, 0.22, 0.25), "Deckel": (0.30, 0.32, 0.36), "Halter": (0.85, 0.45, 0.10),
    "Klemmbuegel": (0.85, 0.45, 0.10),
    "Profil_3030": (0.75, 0.75, 0.78), "LCD_Platine": (0.10, 0.50, 0.15), "LCD_Rahmen": (0.05, 0.05, 0.05),
    "I2C_Adapter": (0.10, 0.25, 0.70), "I2C_Stecker": (0.10, 0.10, 0.10), "Drehgeber": (0.60, 0.60, 0.62),
    "Drehgeber_Platine": (0.10, 0.25, 0.70), "Drehgeber_Stecker": (0.10, 0.10, 0.10),
    "Nano": (0.10, 0.25, 0.70), "Nano_USB": (0.80, 0.80, 0.82), "Nano_ICSP": (0.10, 0.10, 0.10),
    "Nano_Leisten": (0.10, 0.10, 0.10),
    "Nano_Stecker": (0.10, 0.10, 0.10),
}


def collisions(parts, dummies):
    found = []
    items = list(parts.items()) + list(dummies.items())
    for i, (na, a) in enumerate(items):
        for nb, b in items[i + 1:]:
            if {na, nb} in ({"Halter", "Profil_3030"},):
                continue
            if not a.BoundBox.intersect(b.BoundBox):
                continue
            v = a.common(b).Volume
            if v > 0.05:
                found.append((na, nb, round(v, 2)))
    return found


def print_oriented(name, shape):
    s = shape.copy()
    if name == "Gehaeuse":
        s.rotate(V(0, 0, 0), V(1, 0, 0), 90)     # Front auf das Druckbett
    elif name in ("Deckel", "Klemmbuegel"):
        s.rotate(V(0, 0, 0), V(1, 0, 0), -90)    # Aussenseite auf das Druckbett
    elif name == "Halter":
        s = to_world(shape)
        s.rotate(V(0, 0, 0), V(0, 1, 0), -90)    # Seitenflaeche auf das Druckbett
    bb = s.BoundBox
    s.translate(V(-bb.XMin, -bb.YMin, -bb.ZMin))
    return s


def build(export=True):
    name = "LCD_Gehaeuse"
    if name in App.listDocuments():
        App.closeDocument(name)
    doc = App.newDocument(name)
    parts = {"Gehaeuse": make_shell(), "Deckel": make_lid(), "Halter": make_bracket(),
             "Klemmbuegel": make_clamp()}
    dummies = make_dummies()
    dummies_view = dict(dummies, Profil_3030=make_profile())
    pl = case_to_world()
    objs = {}
    for n, s in list(parts.items()) + list(dummies_view.items()):
        o = doc.addObject("Part::Feature", n)
        o.Shape = s
        o.Placement = pl
        objs[n] = o
        if App.GuiUp:
            o.ViewObject.ShapeColor = COLORS.get(n, (0.5, 0.5, 0.5))
    doc.recompute()
    report = {"aussen": (round(IN_W + 2 * WALL, 1), round(IN_D + FRONT + LID, 1), round(IN_H + 2 * WALL, 1)),
              "kollisionen": collisions(parts, dummies),
              "volumen_cm3": {n: round(s.Volume / 1000, 1) for n, s in parts.items()},
              "solid_ok": {n: (len(s.Solids), s.isValid()) for n, s in parts.items()}}
    if export and EXPORT_DIR:
        import Import
        import MeshPart
        doc.saveAs(os.path.join(EXPORT_DIR, "lcd_gehaeuse.FCStd"))
        Import.export([objs[n] for n in parts], os.path.join(EXPORT_DIR, "lcd_gehaeuse.step"))
        Import.export(list(objs.values()), os.path.join(EXPORT_DIR, "lcd_gehaeuse_mit_bauteilen.step"))
        for n, s in parts.items():
            p = print_oriented(n, s)
            p.exportStep(os.path.join(EXPORT_DIR, n.lower() + ".step"))
            mesh = MeshPart.meshFromShape(Shape=p, LinearDeflection=0.02, AngularDeflection=0.1, Relative=False)
            mesh.write(os.path.join(EXPORT_DIR, n.lower() + ".stl"))
        # Nutenstein (2x drucken), liegt schon flach
        nut = make_tnut()
        bb = nut.BoundBox
        nut.translate(V(-bb.XMin, -bb.YMin, -bb.ZMin))
        nut.exportStep(os.path.join(EXPORT_DIR, "nutenstein.step"))
        MeshPart.meshFromShape(Shape=nut, LinearDeflection=0.01, AngularDeflection=0.1,
                               Relative=False).write(os.path.join(EXPORT_DIR, "nutenstein.stl"))
    return doc, report


if __name__ in ("__main__", "builtins") or not App.GuiUp:
    _doc, _report = build(export=True)
    print(_report)
