# 🍳 Kochido – Schritt für Schritt kochen ohne Abo

Lokaler **Cookidoo-Ersatz** für den Thermomix (**TM5 & TM6**): Rezepte im
Cookidoo-artigen **Guided-Cooking-Modus** kochen – Vollbild-Schritt für Schritt,
Einwiegen-Chips, Timer mit Pieps, Temperatur-/Stufen-/Linkslauf-Badges –
komplett ohne Abo und Cloud, auf deinem eigenen Proxmox-Server.

## Einzeiler-Installation (auf dem Proxmox-Host als root)

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/Kochido/main/install/kochido.sh)"
```

Der Installer:

- erstellt einen **unprivilegierten LXC** (Debian 12, Default: 2 vCPU / 1 GB RAM / 4 GB,
  `onboot: 1`, `nesting: 1`), ID wählbar per `--id`, sonst nächste freie ab 200
- installiert Python/FastAPI + die fertig gebaute React/Vite-SPA (kein Node im Container)
- richtet `kochido.service` ein (**`Restart=always`**, `After=network-online.target`)
- legt 3 **Demo-Rezepte** an (beim allerersten Start)
- verifiziert selbst: Service läuft, API antwortet (`/api/health`), Web-UI 200,
  Erreichbarkeit vom Host – und gibt die finale URL aus

### Optionen

```text
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/Kochido/main/install/kochido.sh)" -- OPTIONEN
```

| Option | Default | Bedeutung |
|---|---|---|
| `--id ID` | nächste freie ab 200 | Container-ID |
| `--port PORT` | `8090` | Web-UI-Port im Container |
| `--ip CIDR` / `--gateway GW` | DHCP | feste IP (empfohlen: DHCP-Reservierung) |
| `--memory MB` / `--rootfs GB` | `1024` / `4` | Ressourcen |
| `--sshkey PFAD\|URL` | – | SSH-Key-Login als root |
| `--update` | – | App im bestehenden CT aktualisieren (Rezepte bleiben) |
| `--uninstall` | – | CT stoppen + löschen (mit Rückfrage) |
| `--status` | – | Status: Service, Version, URL, Rezeptzahl |
| `--debug` | – | vollständiges `bash -x`-Trace |

## Was ist Kochido?

- **🍳 Guided Cooking wie Cookidoo:** Vollbild-Kochmodus mit großem
  Schritt-Text, Zutaten-Chips zum Abhaken, Timer-Ring mit Pieps am Ende,
  Badges für ⏱ Zeit · 🌡 Temperatur (37 °C … 120 °C, Varoma) · 🌀 Stufe
  (Sanft, ½–10, Turbo) · ↺ Linkslauf · 🥖 Teigmodus. Bedienung per Touch
  (Swipe), Tastatur (←/→/Leertaste) oder Buttons; Bildschirm bleibt an
  (Wake Lock).
- **⤓ Rezept-Import in Sekunden:**
  - **Chefkoch-URL** einfügen → die App liest die schema.org-Daten und
    erkennt TM-Anweisungen („3 Min./100°C/Stufe 2“) automatisch als
    strukturierte Badges – Zutaten werden den Schritten zugeordnet
  - **Freitext** einfügen (WhatsApp, PDF, Website) → Zutaten- und
    Schritt-Blöcke werden heuristisch erkannt
  - **Cookidoo-Rezepte:** cookidump-Export (`data.json`, Einzel-JSON oder
    gespeicherte HTML-Seite) hochladen/einfügen; auch „Created Recipes“
    im cookidoo-uploader-Schema werden samt TM-Parametern übernommen
- **✎ Editor:** Schritte mit Zeit/Temperatur/Stufe/Linkslauf/Teigmodus
  pflegen, Einwiegen-Chips und Tipps pro Schritt, Zutaten-Tabelle
- **🍽 Portions-Skalierung** mit Bruch-Formatierung (½, ¾ …)
- **Suche, Tags, Favoriten** – und alles läuft **lokal** (FastAPI + SQLite)

## Nach der Installation

1. `http://<CT-IP>:8090` öffnen (Handy/Tablett im gleichen Netz)
2. **⤓ Importieren** → Chefkoch-Rezept-URL einfügen → Vorschau prüfen → speichern
3. Eigene Cookidoo-Sammlung einmalig importieren (siehe unten) → **Abo kündigen**
4. **🍳 Kochen starten** – der Rest ist wie bei Cookidoo, nur ohne Abo

### Cookidoo-Rezepte einmalig übernehmen

Die App liest **keine** Cookidoo-Konten live (das Abo soll ja weg) – die
bestehende Sammlung wird einmalig per [cookidump](https://github.com/auino/cookidump)
geholt:

```bash
git clone https://github.com/auino/cookidump && cd cookidump
pip install -r requirements.txt
python cookidump.py ./chromedriver ~/cookidump-dump --separate-json
# → im Browser bei Cookidoo anmelden, Filter setzen, Dump laufen lassen
```

Dann in Kochido: **⤓ Importieren → Tab „Cookidoo / cookidump“** →
`data.json` (alle Rezepte auf einmal) oder eine einzelne Rezept-JSON/HTML
hochladen → Vorschau prüfen → **„Alle importieren“**.

## Datensicherung

Alle Rezepte liegen im Container unter `/opt/kochido/data`
(`kochido.db` + `images/`). Kopie auf den Host:

```bash
pct exec <CT-ID> -- tar -C /opt/kochido -cf - data | tar -xf - -C ~/kochido-backup
```

## Update / Deinstall

```bash
# Update (App neu von GitHub, Rezept-Datenbank bleibt unberührt)
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/Kochido/main/install/kochido.sh)" -- --update

# Status
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/Kochido/main/install/kochido.sh)" -- --status

# Deinstall (Container + Rezepte löschen)
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/Kochido/main/install/kochido.sh)" -- --uninstall
```

## Tech-Stack

| Schicht | Technik |
|---|---|
| Backend | Python / FastAPI + SQLite (WAL), Port 8090, bindet `0.0.0.0` |
| Frontend | React 18 + Vite (SPA, `dist/` committed – kein Node im CT) |
| Import | schema.org/Recipe (JSON-LD), Freitext-Heuristik, cookidump JSON/HTML, Cookidoo-Custom-Recipe-Schema |
| Betrieb | systemd `kochido.service` (`Restart=always`), LXC unprivileged, `onboot: 1` |

Tests: `pytest` (68 Fälle für Parser, Import-Wege und API) –
`python3 -m pytest tests/`

## Repo-Struktur

```
Kochido/
├── backend/            # FastAPI-App + Importer (main.py, db.py, importers/)
│   └── seed/            # 3 Demo-Rezepte (nur bei leerer DB)
├── frontend/           # React/Vite-Quellcode
│   └── dist/            # Produktions-Build (committed, wird im CT ausgeliefert)
├── install/kochido.sh  # Proxmox-Installer (Community-Scripts-Stil)
├── kochido.service     # systemd-Unit (Referenz; Installer schreibt sie im CT)
├── tests/              # pytest-Suite (Parser, Importer, API)
└── harness/            # Mock-Tests für den Installer (ohne echten Proxmox-Host)
```

## Hinweise / Legalität

Kochido speichert und rendert Rezepte **nur lokal für den privaten Gebrauch**.
Cookidoo-/Chefkoch-Inhalte sind urheberrechtlich geschützt – Dumps bitte nur
aus dem eigenen Abo ziehen und nicht teilen. Die Parameter-Erkennung ist
heuristisch: Nach dem Import im Editor prüfen (TM-Badges sind frei editierbar).

---

*Teil der HatchetMan111 Proxmox-Installer-Sammlung – im Stil der
[Proxmox VE Community Scripts](https://community-scripts.github.io/ProxmoxVE/).*
