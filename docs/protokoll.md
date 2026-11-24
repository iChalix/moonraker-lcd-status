# Serielles Protokoll (Version 1)

57600 Baud, 8N1. Eine Nachricht ist eine Zeile:

```
<Nutzlast>*<Prüfsumme>\n
```

Die Prüfsumme ist das XOR aller Bytes der Nutzlast als zwei Hex-Ziffern. Die
Nutzlast enthält keine Zeichen unter 0x20. Eine Zeile ist höchstens 39 Byte lang.

## Dienst → Arduino

| Nutzlast | Bedeutung |
|---|---|
| `?` | Kennung anfragen, Antwort `IMLS …` statt Quittung |
| `L<Zeile><Text>` | Displayzeile 0–3 setzen; kürzerer Text wird mit Leerzeichen gefüllt |
| `G<n><16 Hex>` | eigenes Zeichen 0–7, je Pixelzeile ein Byte |
| `B0` / `B1` | Beleuchtung |
| `C` | alles löschen |
| `Z` | LCD neu initialisieren und alles neu schreiben |
| `P` | Lebenszeichen |

Text sind HD44780-Codes. Die eigenen Zeichen 0–7 stehen auf 0x80–0x87, weil
Steuerzeichen nicht erlaubt sind.

Jeder Befehl wird quittiert, der Dienst wartet darauf:

| Antwort | Bedeutung |
|---|---|
| `K` | verarbeitet |
| `NC` | Prüfsumme falsch |
| `NF` | Format falsch oder Zeile zu lang |
| `NU` | Befehl unbekannt oder ungültig |

## Arduino → Dienst

| Nutzlast | Bedeutung |
|---|---|
| `IMLS <Protokoll> <Sketch> <Spalten> <Zeilen> <I2C>` | Kennung, beim Start und auf `?`; I2C `00` = kein LCD gefunden |
| `R<n>` | Drehgeber um n Rastungen, negativ = gegen den Uhrzeigersinn |
| `S` | kurz gedrückt |
| `H` | lang gedrückt (0,8 s) |

## Regeln

- Vor der Kennung sendet der Dienst ausschließlich `?`. Kommt keine, schließt er
  den Port und versucht es erst nach `wrong_device_delay` wieder.
- Kommt 30 s lang keine gültige Nachricht, schaltet der Arduino Display und
  Beleuchtung aus; die nächste gültige schaltet sie wieder ein.
- `?`, `L` und `P` bleiben in allen Protokollversionen gleich. Damit kann der
  Dienst auch auf einem alten Sketch „Sketch veraltet“ anzeigen.
