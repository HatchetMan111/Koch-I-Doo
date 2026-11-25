#!/usr/bin/env bash
# =============================================================================
# Kochido-Installer-Harness: testet install/kochido.sh ohne echten Proxmox-Host.
# Mocks: pct/pveam/curl/openssl (harness/bin), Root-Modus via unshare -rm.
# Jede Assertion prüft wörtliche Installer-Ausgaben bzw. pct-Mock-Logs.
# =============================================================================
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
INSTALLER="$ROOT/install/kochido.sh"
FAKEBIN="$HERE/bin"
WORK="$(mktemp -d /tmp/kochido-harness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
FAILED_CASES=()

ok_case()   { PASS=$((PASS + 1)); echo "  ✔ $1"; }
fail_case() { FAIL=$((FAIL + 1)); FAILED_CASES+=("$1"); echo "  ✘ $1"; echo "      $2"; }

# Führt den Installer in einer sauberen Env aus (Phils Profil exportiert
# eine grep-Funktion → env -i, Grube 15).
run_installer() {
    local state="$1"; shift
    # unshare -rm simuliert root; wenn das im Sandbox/CI nicht erlaubt ist,
    # fällt HARNESS_AS_ROOT=0 auf plain env zurück (mit Harness-Escape KOCHIDO_HARNESS_NONROOT)
    if [[ "${HARNESS_AS_ROOT:-1}" == "1" ]] && unshare -rm true 2>/dev/null; then
        unshare -rm env -i \
            PATH="$FAKEBIN:/usr/bin:/bin" \
            HOME=/root TERM=dumb \
            HARNESS_STATE="$state" \
            KOCHIDO_PASSWORD=harness-password \
            bash "$INSTALLER" "$@" 2>&1
    else
        env -i \
            PATH="$FAKEBIN:/usr/bin:/bin" \
            HOME=/root TERM=dumb \
            HARNESS_STATE="$state" \
            KOCHIDO_PASSWORD=harness-password \
            KOCHIDO_HARNESS_NONROOT=1 \
            bash "$INSTALLER" "$@" 2>&1
    fi
}

new_state() {
    local name="$1"
    local st="$WORK/$name"
    mkdir -p "$st"
    # pveam available liefert (nach Download-Pfad) ein Debian-13-Template
    # (mit Storage-Präfix, wie pveam es ausgibt)
    printf 'local-lvm:vztmpl/debian-13-standard_13.0-1_amd64.tar.zst\n' > "$st/pveam_avail"
    echo "$st"
}

assert_log() {
    local state="$1" pattern="$2" label="$3"
    if grep -qF -- "$pattern" "$state/pct.log" 2>/dev/null; then
        ok_case "$label"
    else
        fail_case "$label" "Erwartet in pct.log: '$pattern'"$( [[ -f "$state/pct.log" ]] && echo " — pct.log: $(head -c 600 "$state/pct.log")" )
    fi
}

assert_not_log() {
    local state="$1" pattern="$2" label="$3"
    if grep -qF -- "$pattern" "$state/pct.log" 2>/dev/null; then
        fail_case "$label" "Darf nicht in pct.log stehen: '$pattern'"
    else
        ok_case "$label"
    fi
}

assert_out() {
    local out="$1" pattern="$2" label="$3"
    if printf '%s' "$out" | grep -qF -- "$pattern"; then
        ok_case "$label"
    else
        fail_case "$label" "Erwartet in Ausgabe: '$pattern' — Ausgabe: $(printf '%s' "$out" | head -c 500)"
    fi
}

assert_not_out() {
    local out="$1" pattern="$2" label="$3"
    if printf '%s' "$out" | grep -qF -- "$pattern"; then
        fail_case "$label" "Sollte NICHT vorkommen: '$pattern' — Ausgabe: $(printf '%s' "$out" | head -c 400)"
    else
        ok_case "$label"
    fi
}

echo "━━━ Kochido-Installer-Harness ━━━"

# ── 1) Syntax: Host-Script + Inner-Script ──────────────────────────────────
echo "— Struktur"
if bash -n "$INSTALLER" 2>/dev/null; then
    ok_case "bash -n install/kochido.sh"
else
    fail_case "bash -n install/kochido.sh" "Syntaxfehler"
fi

TMP_INNER="$WORK/inner-extract"
mkdir -p "$TMP_INNER"
# Inner-Script aus dem quoter Heredoc extrahieren und syntaxprüfen
awk '/<<.INNEREOF./{f=1;next} /^INNEREOF$/{f=0} f' "$INSTALLER" > "$TMP_INNER/setup-inner.sh"
if bash -n "$TMP_INNER/setup-inner.sh" 2>/dev/null; then
    ok_case "bash -n Inner-Setup-Script (heredoc extrahiert)"
else
    fail_case "bash -n Inner-Setup-Script" "Syntaxfehler im INNEREOF-Block"
fi
INNER_OK=1
for pat in "python3-venv" "python3 -m venv /opt/kochido/venv" "/opt/kochido/app.new" \
           "mv -T /opt/kochido/app.link /opt/kochido/app" "ln -sfn" \
           "frontend/dist/index.html" "Restart=always" "After=network-online.target" \
           "KOCHIDO_DATA=/opt/kochido/data" "api/health" "dhclient-enter-hooks" \
           "systemctl enable kochido" "systemctl restart kochido" "--upgrade -r" \
           ".kochido-installed" "User=kochido" "NoNewPrivileges=true" \
           "ProtectSystem=strict" "ReadWritePaths=/opt/kochido/data" \
           "Environment=KOCHIDO_TZ" "sha256sum -c" "useradd -r" \
           "umask 022" "a+rX" 'chmod 755 /opt/kochido'; do
    if ! grep -qF -- "$pat" "$TMP_INNER/setup-inner.sh"; then
        fail_case "Inner-Script enthält '$pat'" "Strukturprüfung fehlgeschlagen"
        INNER_OK=0
    fi
done
[[ $INNER_OK == 1 ]] && ok_case "Inner-Script-Struktur (venv, systemd gehärtet, Marker, Symlink-Swap, Health-Check, DNS-Hook)"

# Inner-Script darf keine Host-Expansion enthalten (quoted heredoc)
if grep -n '$(HOST_DNS' "$INSTALLER" | grep -q INNEREOF; then
    fail_case "INNEREOF quoting" "Host-Variable im quoted Heredoc"
else
    ok_case "INNEREOF bleibt quoted (keine Host-Expansion)"
fi

# ── 2) Standard-Installation (Root via unshare) ────────────────────────────
echo "— Install-Flow"
ST=$(new_state install)
OUT=$(run_installer "$ST")
assert_out "$OUT" "Nächste freie CT-ID: 200" "Install: nächste freie ID ab 200 ermittelt"
assert_log "$ST" "--hostname kochido" "Install: pct create mit hostname kochido"
assert_log "$ST" "--unprivileged 1" "Install: unprivilegierter CT"
assert_log "$ST" "--onboot 1" "Install: onboot 1 (Reboot-sicher)"
assert_log "$ST" "--features nesting=1" "Install: nesting=1"
assert_log "$ST" "--memory 1024" "Install: 1024 MB RAM (Default)"
assert_log "$ST" "--rootfs local-lvm:4" "Install: 4 GB Disk (Default)"
assert_log "$ST" "firewall=0" "Install: net0 firewall=0 (Port im CT offen)"
assert_log "$ST" "create 200 local-lvm:vztmpl/debian-13-standard" "Install: pct create mit aufgelöstem Template (Storage:vztmpl/name)"
if [[ -f "$ST/inner-run" ]]; then ok_case "Install: Inner-Setup wurde ausgeführt (pct exec)"; else fail_case "Install: Inner-Setup" "inner-run-Marker fehlt"; fi
assert_out "$OUT" "http://10.0.0.77:8090" "Install: Summary mit finaler URL"
assert_out "$OUT" "🔑 Root-PW:   harness-password" "Install: generiertes Passwort wird angezeigt"
assert_out "$OUT" "API antwortet (HTTP 200" "Install: Verifikation API 200"
assert_out "$OUT" "Vom Host erreichbar: http://10.0.0.77:8090" "Install: Host-Erreichbarkeit geprüft"

# ── 3) --id / --port respektiert ───────────────────────────────────────────
ST=$(new_state install_id)
OUT=$(run_installer "$ST" --id 210 --port 8099)
assert_log "$ST" "create 210" "Install --id 210: CT-ID übernommen"
assert_out "$OUT" "http://10.0.0.77:8099" "Install --port 8099: Port übernommen"

# ── 4) Validierung / Fehlerpfade ───────────────────────────────────────────
echo "— Fehlerpfade"
ST=$(new_state badport)
OUT=$(run_installer "$ST" --port 99999)
assert_out "$OUT" "Ungültiger Port" "Fehler: ungültiger Port abgelehnt"

ST=$(new_state unkopt)
OUT=$(run_installer "$ST" --gibtsnicht)
assert_out "$OUT" "Unbekannte Option: --gibtsnicht" "Fehler: unbekannte Option abgelehnt"

ST=$(new_state root)
# Root-Check-Test: OHNE Harness-Escape (env ohne KOCHIDO_HARNESS_NONROOT)
OUT=$(env -i PATH="$FAKEBIN:/usr/bin:/bin" HOME=/root TERM=dumb \
      HARNESS_STATE="$ST" bash "$INSTALLER" 2>&1)
assert_out "$OUT" "Bitte als root ausführen" "Fehler: Root-Check (ohne Harness-Escape)"

# ── 5) Existierender Container ─────────────────────────────────────────────
ST=$(new_state existing)
cat > "$ST/ct_list" <<'LST'
100 running alpine
200 running kochido
201 running test
LST
OUT=$(run_installer "$ST")
assert_out "$OUT" "bereits installiert" "Existierender CT: Hinweis statt Abbruch"
assert_out "$OUT" "Update durch" "Existierender CT: Plain-Installer wechselt automatisch in den Update-Pfad"
if [[ -f "$ST/inner-run" ]]; then ok_case "Existierender CT: Inner-Setup (Update) läuft"; else fail_case "Existierender CT: Update" "inner-run fehlt"; fi
assert_not_log "$ST" "create 200" "Existierender CT: kein zweites pct create"

# ── 6) Update (inkl. gestoppter CT) ────────────────────────────────────────
echo "— Update-Flow"
ST=$(new_state update)
cat > "$ST/ct_list" <<'LST'
200 stopped kochido
LST
OUT=$(run_installer "$ST" --update)
assert_log "$ST" "start 200" "Update: gestoppten CT selbst starten (Grube 10)"
if [[ -f "$ST/inner-run" ]]; then ok_case "Update: Inner-Setup erneut ausgeführt"; else fail_case "Update: Inner-Setup" "inner-run-Marker fehlt"; fi
assert_out "$OUT" "Rezept-Datenbank (/opt/kochido/data) blieb unberührt" "Update: Datenbestand wird geschont"

# ── 7) Status ──────────────────────────────────────────────────────────────
echo "— Status"
ST=$(new_state status_run)
cat > "$ST/ct_list" <<'LST'
200 running kochido
LST
OUT=$(run_installer "$ST" --status)
assert_out "$OUT" "Service:   kochido läuft (Port 8090)" "Status (läuft): Service-Zeile"

ST=$(new_state status_stop)
cat > "$ST/ct_list" <<'LST'
200 stopped kochido
LST
OUT=$(run_installer "$ST" --status)
assert_out "$OUT" "nicht gestartet" "Status (gestoppt): Warnung statt Fake-Grün"
assert_out "$OUT" "pct start 200" "Status (gestoppt): Start-Hinweis"

# bash -c "$(...)" --status → $0-Fallback (Grube 8)
ST=$(new_state status_z0)
OUT=$(cd /tmp && env -i PATH="$FAKEBIN:/usr/bin:/bin" HOME=/root TERM=dumb \
        HARNESS_STATE="$ST" KOCHIDO_HARNESS_NONROOT=1 KOCHIDO_PASSWORD=harness-password \
        bash -c "$(cat "$INSTALLER")" --status 2>&1)
assert_out "$OUT" "Status Kochido" "\$0-Fallback: bash -c SCRIPT --status erkennt Option"

# bash -c "$(...)" -- --status → "--" ist $0 und darf NICHT als unbekannte Option durchgehen
ST=$(new_state status_dashdash)
OUT=$(cd /tmp && env -i PATH="$FAKEBIN:/usr/bin:/bin" HOME=/root TERM=dumb \
        HARNESS_STATE="$ST" KOCHIDO_HARNESS_NONROOT=1 KOCHIDO_PASSWORD=harness-password \
        bash -c "$(cat "$INSTALLER")" -- --status 2>&1)
assert_out "$OUT" "Status Kochido" "bash -c SCRIPT -- --status: doppeltes -- wird übersprungen"
assert_not_out "$OUT" "Unbekannte Option" "bash -c SCRIPT -- --status: kein '--'-Fehler"

# ── 8) Uninstall ───────────────────────────────────────────────────────────
echo "— Uninstall"
ST=$(new_state rm_yes)
cat > "$ST/ct_list" <<'LST'
200 running kochido
LST
OUT=$(run_installer "$ST" --uninstall --yes </dev/null)
assert_log "$ST" "destroy 200 --purge" "Uninstall --yes: CT gelöscht"

ST=$(new_state rm_no)
cat > "$ST/ct_list" <<'LST'
200 running kochido
LST
OUT=$(run_installer "$ST" --uninstall </dev/null)
assert_out "$OUT" "Keine Bestätigung erhalten" "Uninstall ohne --yes: nicht-interaktiv → Abbruch"
assert_not_log "$ST" "destroy 200 --purge" "Uninstall ohne --yes: CT NICHT gelöscht"

# --force ohne --yes: nichts gelöscht
ST=$(new_state force_no)
cat > "$ST/ct_list" <<'LST'
200 running kochido
LST
OUT=$(run_installer "$ST" --force </dev/null)
assert_out "$OUT" "Keine Bestätigung erhalten" "--force ohne --yes: Rückfrage erzwungen"

# ── 9) Verifikations-Fehlerpfade ───────────────────────────────────────────
echo "— Verifikation"
ST=$(new_state http_fail)
echo "000" > "$ST/curl_code"
OUT=$(run_installer "$ST")
assert_out "$OUT" "API antwortet nicht" "Verifikation: HTTP 000 → Diagnose + Abbruch"

ST=$(new_state svc_fail)
echo "failed" > "$ST/svc"
OUT=$(run_installer "$ST")
assert_out "$OUT" "Service kochido läuft nicht" "Verifikation: Service gestorben → Abbruch mit Debug-Hinweis"

ST=$(new_state dns_fail)
echo "1" > "$ST/dnsfail"
OUT=$(run_installer "$ST")
assert_out "$OUT" "DNS im Container defekt" "DNS-Fail: Fallback-Nameserver werden geschrieben"
assert_out "$OUT" "DNS-Fallback aktiv" "DNS-Fail: Fallback greift (Hook geschrieben)"

ST=$(new_state host_fail)
echo "000" > "$ST/host_curl_code"
OUT=$(run_installer "$ST")
assert_out "$OUT" "vom Proxmox-Host nicht erreichbar" "Host-Check: warn statt stiller Erfolg"

# ── 10) Template-Download-Pfad ─────────────────────────────────────────────
ST=$(new_state template)
OUT=$(run_installer "$ST")
if grep -qF "pveam available --section system" "$ST/pveam.log" 2>/dev/null; then
    ok_case "Template: kein debian-12 vorhanden → pveam-Fallback"
else
    fail_case "Template-Fallback" "pveam available wurde nicht aufgerufen — pveam.log: $(head -c 300 "$ST/pveam.log" 2>/dev/null)"
fi

# ── 11) ONE_LINER konsistent ───────────────────────────────────────────────
if grep -qF 'raw.githubusercontent.com/HatchetMan111/Koch-I-Doo/main/install/kochido.sh' "$INSTALLER"; then
    ok_case "ONE_LINER zeigt auf Repo-Raw-URL (HatchetMan111/Koch-I-Doo)"
else
    fail_case "ONE_LINER" "Raw-URL stimmt nicht mit Repo überein"
fi

# ── 12) Repo-Name-Konsistenz (Grube 17, Live-Fund 2026-11-18: rename ohne
#         UPSTREAM_REPO-Update → codeload-404 mitten im Live-Install-Lauf)
if grep -qF 'UPSTREAM_REPO="Koch-I-Doo"' "$INSTALLER" \
   && grep -qF 'codeload.github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}' "$INSTALLER" \
   && grep -qF 'HatchetMan111/Koch-I-Doo/main/install/kochido.sh' "$INSTALLER"; then
    ok_case "Repo-Name konsistent (UPSTREAM_REPO, Tarball-URL, ONE_LINER)"
else
    fail_case "Repo-Name konsistent" "UPSTREAM_REPO / Tarball-URL / ONE_LINER zeigen auf unterschiedliche Repos"
fi

# ── 13) Neue Sicherheits-/Validierungs-Fälle ─────────────────────────────
echo "— Sicherheit & Validierung (Bugfix-Runde)"

# Port mit führender Null: 10#-Arithmetik → "08" ist sauber Port 8, kein Fehler
ST=$(new_state port08)
OUT=$(run_installer "$ST" --port 08)
assert_out "$OUT" "http://10.0.0.77:8 " "Port 08 wird dezimal als 8 interpretiert (kein oktal-Fehler)"

ST=$(new_state port0)
OUT=$(run_installer "$ST" --port 0)
assert_out "$OUT" "Ungültiger Port" "Port 0 abgelehnt"

ST=$(new_state badid)
OUT=$(run_installer "$ST" --id abc)
assert_out "$OUT" "Ungültige Container-ID" "--id abc abgelehnt"

ST=$(new_state badip)
OUT=$(run_installer "$ST" --ip '192.168.1.5/24,firewall=1')
assert_out "$OUT" "Ungültige --ip" "net0-Injection per --ip abgelehnt"

ST=$(new_state sshhttp)
OUT=$(run_installer "$ST" --sshkey http://evil.example/key.pub)
assert_out "$OUT" "nur über https" "--sshkey http:// abgelehnt (MITM)"

# Fremder Container (kein Marker, keine kochido.service) darf nicht gelöscht werden
ST=$(new_state foreign)
cat > "$ST/ct_list" <<'LST'
200 running kochido
LST
touch "$ST/nomarker"
OUT=$(run_installer "$ST" --uninstall --yes </dev/null)
assert_out "$OUT" "KEIN Koch-I-Doo-Container" "Uninstall fremder CT: Check greift"
assert_not_log "$ST" "destroy 200 --purge" "Uninstall fremder CT: kein destroy"

# Legacy-Installation (alter Installer, noch ohne Marker, aber kochido.service da):
# --update muss funktionieren und den Marker nachträglich setzen
ST=$(new_state legacy_update)
cat > "$ST/ct_list" <<'LST'
205 running kochido
LST
touch "$ST/legacy" "$ST/nomarker"
OUT=$(run_installer "$ST" --update)
assert_out "$OUT" "Legacy-Installation" "Update auf Legacy-CT (205): wird erkannt, nicht blockiert"
if [[ -f "$ST/marker-set" ]]; then ok_case "Legacy-CT: Marker wird nachträglich gesetzt"; else fail_case "Legacy-CT: Marker gesetzt" "marker-set fehlt"; fi
if [[ -f "$ST/inner-run" ]]; then ok_case "Legacy-CT: Inner-Setup läuft durch"; else fail_case "Legacy-CT: Inner-Setup" "inner-run fehlt"; fi

# Update ohne --port übernimmt den Port aus der Unit
ST=$(new_state update_port)
cat > "$ST/ct_list" <<'LST'
200 running kochido
LST
echo "8099" > "$ST/ct_port"
OUT=$(run_installer "$ST" --update)
assert_out "$OUT" "Port aus bestehender Unit übernommen: 8099" "Update: Port bleibt erhalten (kein Reset auf 8090)"
assert_out "$OUT" "http://10.0.0.77:8099" "Update: Summary mit altem Port"

# Log-Datei wird mit 0600 angelegt (mktemp) – prüfbar am Non-Root-Lauf,
# der nach dem Log-Anlegen am Root-Check stirbt
ST=$(new_state logperms)
OUT=$(HARNESS_AS_ROOT=0 run_installer "$ST")
LOGFILE=$(ls -t /tmp/kochido-installer-*.log 2>/dev/null | head -1 || true)
if [[ -n "$LOGFILE" && "$(stat -c %a "$LOGFILE")" == "600" ]]; then
    ok_case "Log-Datei hat 0600 (mktemp, kein world-readable Log)"
else
    fail_case "Log-Datei 0600" "Log: ${LOGFILE:-keine gefunden}, Rechte: $([[ -n "$LOGFILE" ]] && stat -c %a "$LOGFILE")"
fi
rm -f /tmp/kochido-installer-*.log 2>/dev/null || true

echo ""
echo "━━━ Ergebnis: $PASS bestanden, $FAIL fehlgeschlagen ━━━"
if [[ $FAIL -gt 0 ]]; then
    printf '  ✘ %s\n' "${FAILED_CASES[@]}"
    exit 1
fi
exit 0
