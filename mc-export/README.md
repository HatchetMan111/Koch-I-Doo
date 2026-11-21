# Koch-I-Doo → Monsieur Cuisine Smart

Ein **Experiment/Zusatzmodul** – Koch-I-Doo selbst bleibt unverändert
(TM5/TM6). Wer ein **Monsieur Cuisine Smart (MC3.0)** hat, kann seine
Koch-I-Doo-Rezepte mit einem Klick als Datei exportieren und mit dem
Open-Source-Tool **smart-recipe** ins eigene MC-Konto laden.

> Nicht offiziell, nicht mit Lidl/Monsieur Cuisine verbunden. Es werden
> **Entwürfe** erzeugt – Zutaten, Mengen, Temperaturen, Zeiten und Allergene
> immer prüfen, bevor gekocht wird.

## So geht's

1. In Koch-I-Doo ein Rezept öffnen → **„⤓ Monsieur Cuisine"** → es wird eine
   `…-mc.json` heruntergeladen.
2. Einmalig am PC:
   ```bash
   npm install -g github:gerkensm/smart-recipe
   smart-recipe login-browser --device mc --save
   ```
3. Rezept hochladen:
   ```bash
   smart-recipe create-file rezept-mc.json --device mc --always-upload
   ```
   Nach dem Upload die Draft-URL öffnen, prüfen, korrigieren, kochen.

## Was die Datei enthält

`recipe-input.json` im Schema von smart-recipe (Monsieur Cuisine Smart):
Titel, Beschreibung, Zutatengruppen, Schritte mit TM-Badges als MC-Modi
(Manual Cooking rechts/links/heizend, Teigkneten, Turbo), Zeiten in Minuten,
Portionen.

## Grenzen

- Nur **MC Smart / MC3.0**, nicht MC Connect / MC2.0.
- Aus Koch-I-Doo-Badges abgeleitet; MC-Geräte können andere Modi/Tests haben.
- Bei fehlendem `mc-export/` in der Installation gibt es einen klaren Fehler
  (die App läuft normal weiter).
