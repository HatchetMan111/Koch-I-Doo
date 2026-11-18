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
    if [[ "${HARNESS_AS_ROOT:-1}" == "1" ]]; then
        unshare -rm env -i \
            PATH="$FAKEBIN:/usr/bin:/bin" \
            HOME=/root TERM=dumb \
            HARNESS_STATE="$state" \
            bash "$INSTALLER" "$@" 2>&1
    else
        env -i \
            PATH="$FAKEBIN:/usr/bin:/bin" \
            HOME=/root TERM=dumb \
            HARNESS_STATE="$state" \
            bash "$INSTALLER" "$@" 2>&1
    fi
}

new_state() {
    local name="$1"
    local st="$WORK/$name"
    mkdir -p "$st"
    # pveam available liefert (nach Download-Pfad) ein Debian-12-Template
    printf 'vztmpl/debian-13-standard_13.0-1_amd64.tar.zst\n' > "$st/pveam_avail"
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
           "mv /opt/kochido/app /opt/kochido/app.old" "rm -rf /opt/kochido/app.old" \
           "frontend/dist/index.html" "Restart=always" "After=network-online.target" \
           "KOCHIDO_DATA=/opt/kochido/data" "api/health" "dhclient-enter-hooks" \
           "systemctl enable kochido" "systemctl restart kochido" "--upgrade -r"; do
    if ! grep -qF -- "$pat" "$TMP_INNER/setup-inner.sh"; then
        fail_case "Inner-Script enthält '$pat'" "Strukturprüfung fehlgeschlagen"
        INNER_OK=0
    fi
done
[[ $INNER_OK == 1 ]] && ok_case "Inner-Script-Struktur (venv, systemd, Health-Check, DNS-Hook)"

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
OUT=$(HARNESS_AS_ROOT=0 run_installer "$ST")
assert_out "$OUT" "Bitte als root ausführen" "Fehler: Root-Check (ohne unshare)"

# ── 5) Existierender Container ─────────────────────────────────────────────
ST=$(new_state existing)
cat > "$ST/ct_list" <<'LST'
100 running alpine
200 running kochido
201 running test
LST
OUT=$(run_installer "$ST")
assert_out "$OUT" "existiert bereits" "Existierender CT: Abbruch mit Hinweis"
assert_out "$OUT" "--update" "Existierender CT: Update-Hinweis in Fehlermeldung"
assert_not_out "$OUT" "✔  Container 200 erstellt" "Existierender CT: kein zweites pct create"

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
OUT=$(cd /tmp && unshare -rm env -i PATH="$FAKEBIN:/usr/bin:/bin" HOME=/root TERM=dumb \
        HARNESS_STATE="$ST" bash -c "$(cat "$INSTALLER")" --status)
assert_out "$OUT" "Status Kochido" "\$0-Fallback: bash -c SCRIPT --status erkennt Option"

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

echo ""
echo "━━━ Ergebnis: $PASS bestanden, $FAIL fehlgeschlagen ━━━"
if [[ $FAIL -gt 0 ]]; then
    printf '  ✘ %s\n' "${FAILED_CASES[@]}"
    exit 1
fi
exit 0
