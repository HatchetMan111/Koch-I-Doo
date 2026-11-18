#!/usr/bin/env bash
# =============================================================================
#  🍳 Koch-I-Doo – One-Click-Installer (Proxmox VE)
#  https://github.com/HatchetMan111/Koch-I-Doo
#
#  Erstellt einen unprivilegierten LXC-Container und installiert darin Koch-I-Doo:
#  den lokalen Cookidoo-Ersatz – Schritt-für-Schritt-Guided-Cooking für den
#  Thermomix (TM5/TM6) OHNE Abo, mit Rezept-Import von Chefkoch-URLs,
#  Freitext und cookidump-Exporten.
#
#  Tech: FastAPI + SQLite (Python) im Container, React/Vite-SPA liegt fertig
#  gebaut bei (dist/ ist committed) → im Container wird KEIN Node gebaut.
#
#  Installation (auf dem Proxmox-Host als root):
#    bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/Koch-I-Doo/main/install/kochido.sh)"
#
#  Mit Optionen (direkt hinter dem schließenden Anführungszeichen):
#    ... " --id 210 --memory 2048 --port 8090
#
#  Update / Deinstall / Status / Debug:
#    ... " --update        |  ... " --uninstall  |  ... " --status  |  ... " --debug
# =============================================================================

# shellcheck disable=SC1111  # deutsche Anführungszeichen („…“) sind Absicht
set -Eeuo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
INSTALLER_VERSION="1.0.0"
APP_NAME="kochido"
UPSTREAM_OWNER="HatchetMan111"
UPSTREAM_REPO="Kochido"
UPSTREAM_BRANCH="main"
UPSTREAM_TARBALL_URL="https://codeload.github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}/tar.gz/refs/heads/${UPSTREAM_BRANCH}"
CT_ID=""                    # leer = automatisch nächste freie ID ab ID_SCAN_START
ID_SCAN_START=200
CT_HOSTNAME="kochido"
CT_STORAGE="local-lvm"
CT_ROOTFS=4                 # GB – Python + venv + SQLite sind klein
CT_CORES=2
CT_MEMORY=1024              # MB – FastAPI/SQLite sind genügsam
CT_SWAP=256
CT_BRIDGE="vmbr0"
CT_IP="dhcp"
CT_GATEWAY=""               # nur bei statischer IP nötig, z. B. 192.168.1.1
CT_PASSWORD=""              # leer = automatisch generieren
CT_SSHKEY=""                # Pfad ODER URL zu einer Public-Key-Datei (optional)
SSH_KEY_FILE=""             # aufgelöste Key-Datei für pct create
PORT=8090                   # Web-UI-Port im Container (Kochido-API + SPA)
UNINSTALL=false
UPDATE=false
STATUS_CHECK=false
FORCE_RECREATE=false
ASSUME_YES=false
TMP_DIR=""
LOG_FILE="/tmp/${APP_NAME}-installer-$(date +%Y%m%d-%H%M%S).log"
ONE_LINER='bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/Koch-I-Doo/main/install/kochido.sh)"'

# ── Farben & Logging ───────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

info()  { echo -e "${BLUE}ℹ${NC}  $1"; }
ok()    { echo -e "${GREEN}✔${NC}  $1"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $1"; }
err()   { echo -e "${RED}✘${NC}  $1" >&2; }
die()   { err "$1"; exit 1; }
header(){ echo -e "\n${CYAN}${BOLD}━━━ $1 ━━━${NC}"; }

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
exec > >(tee "$LOG_FILE") 2>&1

# ── Cleanup & Fehlerkette ──────────────────────────────────────────────────
cleanup() {
    # if statt [[ ]] && – sonst überschreibt ein leeres TMP_DIR den Exit-Status.
    if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT

on_error() {
    local ec=$1 line=$2 cmd=$3
    err "Installationsfehler – Exit-Code ${ec} in Zeile ${line}"
    err "Fehlgeschlagener Befehl: ${cmd}"
    if [[ -f "$LOG_FILE" ]]; then
        info "Letzte Logzeilen (${LOG_FILE}):"
        tail -n 20 "$LOG_FILE" | sed 's/^/    /' || true
    fi
    if [[ -n "${CT_ID:-}" ]] && pct status "$CT_ID" &>/dev/null; then
        info "Container-Logs (Setup + Service):"
        pct exec "$CT_ID" -- sh -c '
            tail -n 40 /var/log/kochido-setup.log 2>/dev/null
            echo "--- journalctl -u kochido ---"
            journalctl -u kochido --no-pager 2>/dev/null | tail -n 25
        ' 2>/dev/null | sed 's/^/    /' || true
        info "Container $CT_ID wurde NICHT gelöscht – Inspektion: pct enter $CT_ID"
        info "Aufräumen: pct stop $CT_ID && pct destroy $CT_ID --purge"
    fi
    info "Vollständiges Log: $LOG_FILE"
    info "Neu ausführen mit vollem bash -x-Trace (exakter Befehl):"
    echo "    ${ONE_LINER} --debug"
    exit "$ec"
}
trap 'on_error $? $LINENO "$BASH_COMMAND"' ERR

if [[ "${1:-}" == "--debug" || "$0" == "--debug" ]]; then
    set -x
fi

# ── Hilfsfunktionen ────────────────────────────────────────────────────────
ct_exists() {
    # Name ist in `pct list` IMMER die letzte Spalte (Lock kann leer sein).
    if pct list 2>/dev/null | awk '{print $NF}' | grep -qx "${1:-}"; then
        return 0
    fi
    return 1
}

find_free_id() {
    local id="$ID_SCAN_START"
    while pct list 2>/dev/null | awk '{print $1}' | grep -qx "$id"; do
        id=$((id + 1))
    done
    echo "$id"
}

find_ct_id_by_hostname() {
    pct list 2>/dev/null | awk -v h="$CT_HOSTNAME" '$NF==h {print $1; exit}'
}

get_ct_ip() {
    # || true INNERHALB der Substitution (pipefail-Grube bei pct-Fehlschlag)
    local ct_id="$1"
    if [[ "$CT_IP" != "dhcp" ]]; then
        echo "${CT_IP%%/*}"
        return 0
    fi
    pct exec "$ct_id" -- hostname -I 2>/dev/null | awk '{print $1}' || true
    return 0
}

wait_for_ct_network() {
    local id="$1" tries=0 ip=""
    info "Warte auf Netzwerk im Container (DHCP) ..."
    while true; do
        ip=$(pct exec "$id" -- hostname -I 2>/dev/null | awk '{print $1}' || true)
        if [[ -n "$ip" ]]; then
            ok "Container-IP: $ip"
            return 0
        fi
        tries=$((tries + 1))
        if [[ $tries -ge 60 ]]; then
            err "Container hat nach 60 s keine IP bekommen."
            info "Prüfe: pct exec $id -- ip a   und DHCP am Bridge-Interface ($CT_BRIDGE)"
            return 1
        fi
        sleep 1
    done
}

verify_ct_dns() {
    # 3 Erfolge HINTEREINANDER verlangen – ein einzelner getent-Erfolg winkt
    # flaky DNS durch (Live-Fund 2026-11-10). Defekt → Fallback + dhclient-Hook.
    local id="$1" ok_count=0 tries=0
    info "Prüfe DNS im Container (3x hintereinander) ..."
    while true; do
        if pct exec "$id" -- getent hosts codeload.github.com >/dev/null 2>&1; then
            ok_count=$((ok_count + 1))
            if [[ $ok_count -ge 3 ]]; then
                ok "DNS im Container funktioniert (3x bestätigt)"
                return 0
            fi
        else
            ok_count=0
        fi
        tries=$((tries + 1))
        if [[ $tries -ge 10 ]]; then
            break
        fi
        sleep 2
    done
    local host_ns ns_list
    host_ns=$(grep -h '^nameserver' /etc/resolv.conf 2>/dev/null | awk '{print $2}' | grep -v '^127\.' | head -1 || true)
    ns_list="1.1.1.1 8.8.8.8 9.9.9.9"
    if [[ -n "$host_ns" ]]; then
        ns_list="$host_ns $ns_list"
    fi
    warn "DNS im Container defekt – schreibe Fallback-Nameserver ($ns_list) nach /etc/resolv.conf"
    pct exec "$id" -- sh -c "printf 'nameserver %s\n' $ns_list > /etc/resolv.conf"
    pct exec "$id" -- bash -c 'mkdir -p /etc/dhcp/dhclient-enter-hooks.d && printf "make_resolv_conf() { :; }\n" > /etc/dhcp/dhclient-enter-hooks.d/no-dns'
    if pct exec "$id" -- getent hosts codeload.github.com >/dev/null 2>&1; then
        ok "DNS-Fallback aktiv und gegen DHCP-Überschreiben geschützt – Auflösung funktioniert"
        return 0
    fi
    die "DNS im Container weiterhin ohne Funktion (auch mit Fallback).\n  Prüfe: pct exec $id -- cat /etc/resolv.conf && pct exec $id -- ping -c2 1.1.1.1\n  Firewall/Router: ausgehende DNS-Anfragen (Port 53) am Bridge-Netz erlauben."
}

ensure_ct_running() {
    # Verwaltungs-Pfade (--update/--status) müssen einen GESTOPPTEN CT selbst
    # starten – pct exec auf gestopptem CT → kryptischer Exit 255.
    local ct_id="$1"
    local state
    state=$(pct status "$ct_id" 2>/dev/null || echo "unknown")
    if [[ "$state" == *"running"* ]]; then
        return 0
    fi
    warn "Container $ct_id läuft nicht (Status: ${state}) – starte ihn ..."
    if ! pct start "$ct_id" 2>&1 | tail -2; then
        die "Container $ct_id konnte nicht gestartet werden.\n  Manuell prüfen: pct start $ct_id && pct status $ct_id"
    fi
    info "Warte auf Netzwerk des Containers ..."
    local i ip=""
    for i in $(seq 1 60); do
        ip=$(pct exec "$ct_id" -- hostname -I 2>/dev/null | tr -d ' \n' || true)
        if [[ -n "$ip" ]]; then
            ok "Container läuft (IP: ${ip%% *})"
            return 0
        fi
        sleep 1
    done
    die "Container $ct_id hat nach 60 s keine IP (Bridge/Netz prüfen: pct exec $ct_id -- ip a)"
}

# ── Argumente parsen ───────────────────────────────────────────────────────
parse_args() {
    # bash-c-Grube: `bash -c "$(wget -qLO - URL)" --id 5` belegt das ERSTE
    # Argument nach dem Script-String mit $0 – Fallback über $0-Front-Warnung.
    local args=("$@")
    if [[ "$0" == -* ]]; then
        args=("$0" "$@")
    fi
    local i=0
    while [[ $i -lt ${#args[@]} ]]; do
        case "${args[$i]}" in
            --id)            CT_ID="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --hostname)      CT_HOSTNAME="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --storage)       CT_STORAGE="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --rootfs)        CT_ROOTFS="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --cores)         CT_CORES="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --memory)        CT_MEMORY="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --swap)          CT_SWAP="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --bridge)        CT_BRIDGE="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --ip)            CT_IP="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --gateway)       CT_GATEWAY="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --password)      CT_PASSWORD="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --sshkey)        CT_SSHKEY="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --port)          PORT="${args[$((i+1))]:-}"; i=$((i+2)) ;;
            --force)         FORCE_RECREATE=true; i=$((i+1)) ;;
            --yes|-y)        ASSUME_YES=true; i=$((i+1)) ;;
            --update)        UPDATE=true; i=$((i+1)) ;;
            --uninstall)     UNINSTALL=true; i=$((i+1)) ;;
            --status)        STATUS_CHECK=true; i=$((i+1)) ;;
            --debug)         set -x; i=$((i+1)) ;;
            --help|-h)       print_help; exit 0 ;;
            *) die "Unbekannte Option: ${args[$i]}  (–help zeigt alle Optionen)" ;;
        esac
    done
    if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [[ "$PORT" -lt 1 || "$PORT" -gt 65535 ]]; then
        die "Ungültiger Port: '$PORT' (1–65535 erwartet, z. B. --port 8090)"
    fi
}

print_help() {
    cat <<'EOF'
🍳 Koch-I-Doo – Proxmox-Installer (lokaler Cookidoo-Ersatz, TM5/TM6)

Installation:   bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/Koch-I-Doo/main/install/kochido.sh)"

Optionen (hinter dem schließenden Anführungszeichen anhängen, z. B. ... " --id 210):
  --id ID          Container-ID (Default: nächste freie ab 200)
  --hostname NAME  Container-Hostname (Default: kochido)
  --storage NAME   Storage für rootfs (Default: local-lvm)
  --rootfs GB      Disk-Größe (Default: 4 – reicht für Python + Rezept-DB)
  --cores N        vCPUs (Default: 2)
  --memory MB      RAM (Default: 1024)
  --swap MB        Swap (Default: 256)
  --bridge BR      Netzwerk-Bridge (Default: vmbr0)
  --ip CIDR        Statt DHCP, z. B. 192.168.1.50/24 (+ --gateway 192.168.1.1)
                   Empfehlenswert: feste IP / DHCP-Reservierung, damit die
                   Rezept-URL auf Handy/Tablett dauerhaft stimmt.
  --gateway GW     Gateway für statische IP
  --password PW    Root-Passwort (Default: automatisch generiert)
  --sshkey PFAD    Public-Key-Datei oder URL – ssh-key-Login als root im CT
  --port PORT      Web-UI-Port im Container (Default: 8090)
  --force          Vorhandenen Container mit gleichem Hostname löschen und neu anlegen
  --yes / -y       Rückfragen überspringen
  --update         App im bestehenden Container aktualisieren (neue Version von GitHub main)
  --uninstall      Container stoppen und löschen
  --status         Status anzeigen
  --debug          Vollständiges bash -x-Trace

  Modus:  Install (Default) / --update / --uninstall / --status / --debug
EOF
}

# ── In-Container-Setup-Script (idempotent) ─────────────────────────────────
# QUOTETER Heredoc ('INNEREOF') – nichts wird vom HOST expandiert; alle Werte
# (PORT, URLs, DNS) kommen als Umgebungsvariablen via `pct exec -- env …`.
write_inner_script() {
    cat > "$TMP_DIR/setup-inner.sh" <<'INNEREOF'
#!/usr/bin/env bash
# =============================================================================
# Koch-I-Doo In-Container-Setup (idempotent – safe für Update & Re-Run)
# Variablen via env: PORT, HOST_DNS, UPSTREAM_TARBALL_URL, APP_NAME
# =============================================================================
set -Eeuo pipefail
trap 'echo "✘ Setup-Fehler: exit $? in Zeile $LINENO: $BASH_COMMAND" >&2' ERR
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C   # verhindert perl/locale-Warnungen im frischen Debian-CT

err(){ echo "✘ $1" >&2; }
die(){ err "$1"; exit 1; }

: "${PORT:?PORT fehlt (env)}"
: "${HOST_DNS:?HOST_DNS fehlt (env)}"
: "${UPSTREAM_TARBALL_URL:?UPSTREAM_TARBALL_URL fehlt (env)}"

echo ">>> Pakete installieren (python3-venv, python3-pip, curl, ca-certificates) ..."
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip curl ca-certificates >/dev/null

echo ">>> DNS festschreiben (DHCP-DNS des Netzes ist unzuverlässig) ..."
mkdir -p /etc/dhcp/dhclient-enter-hooks.d
printf '# Koch-I-Doo: resolv.conf nicht von DHCP überschreiben lassen\nmake_resolv_conf() { :; }\n' > /etc/dhcp/dhclient-enter-hooks.d/no-dns
printf 'domain home.arpa\nsearch home.arpa\nnameserver %s\nnameserver 1.1.1.1\nnameserver 8.8.8.8\nnameserver 9.9.9.9\n' "${HOST_DNS}" > /etc/resolv.conf

echo ">>> Kochido-Quellcode von GitHub laden ..."
curl -fSL --retry 3 "${UPSTREAM_TARBALL_URL}" -o /tmp/kochido.tar.gz
rm -rf /tmp/kochido-src && mkdir -p /tmp/kochido-src
tar -xzf /tmp/kochido.tar.gz -C /tmp/kochido-src --strip-components=1
if [[ ! -f /tmp/kochido-src/backend/main.py ]]; then
    die "Tarball unvollständig: backend/main.py fehlt (Repo-Struktur geändert?)."
fi
if [[ ! -f /tmp/kochido-src/frontend/dist/index.html ]]; then
    die "Tarball unvollständig: frontend/dist/index.html fehlt (dist muss committed sein)."
fi

echo ">>> Neue App-Version nach /opt/kochido/app.new vorbereiten (alte bleibt bis zum Wechsel stehen) ..."
rm -rf /opt/kochido/app.new
mkdir -p /opt/kochido/app.new
cp -a /tmp/kochido-src/backend/. /opt/kochido/app.new/
mkdir -p /opt/kochido/app.new/dist
cp -a /tmp/kochido-src/frontend/dist/. /opt/kochido/app.new/dist/

echo ">>> Python-venv anlegen / auffrischen ..."
if [[ ! -d /opt/kochido/venv ]]; then
    python3 -m venv /opt/kochido/venv
fi
/opt/kochido/venv/bin/pip install --quiet --upgrade pip
/opt/kochido/venv/bin/pip install --quiet --upgrade -r /opt/kochido/app.new/requirements.txt

echo ">>> App-Version aktivieren (atomarer Wechsel) ..."
mv /opt/kochido/app.new /opt/kochido/app

echo ">>> Datenordner sicherstellen (Rezept-DB überlebt Updates) ..."
mkdir -p /opt/kochido/data/images

echo ">>> systemd-Unit kochido.service schreiben (Port ${PORT}) ..."
cat > /etc/systemd/system/kochido.service <<UNITEOF
[Unit]
Description=Koch-I-Doo – Guided Cooking Server (lokaler Cookidoo-Ersatz)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/kochido/app
Environment=PORT=${PORT}
Environment=KOCHIDO_DATA=/opt/kochido/data
Environment=KOCHIDO_DIST=/opt/kochido/app/dist
ExecStart=/opt/kochido/venv/bin/python /opt/kochido/app/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable kochido
systemctl restart kochido

echo ">>> Prüfe, dass Kochido auf Port ${PORT} antwortet ..."
PORT_OK=""
for _ in $(seq 1 30); do
    if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/api/health"; then
        PORT_OK=1
        break
    fi
    sleep 1
done
if [ -z "$PORT_OK" ]; then
    die "Kochido antwortet nach Restart nicht auf Port ${PORT}.
  Debug: ss -tlnp | grep ${PORT} && journalctl -u kochido -e --no-pager | tail -30"
fi

echo ">>> Aufräumen ..."
rm -rf /tmp/kochido-src /tmp/kochido.tar.gz

echo ">>> Setup abgeschlossen."
INNEREOF
}

run_inner_setup() {
    local ct_id="$1"
    header "⚙️  Installiere Kochido im Container $ct_id"
    # DNS des Hosts in den Container bringen (dort resolvert das Setup garantiert)
    HOST_DNS=$(grep -h '^nameserver' /etc/resolv.conf 2>/dev/null \
               | awk '{print $2}' | grep -v '^127\.' | head -1 || true)
    write_inner_script
    pct push "$ct_id" "$TMP_DIR/setup-inner.sh" /root/setup-inner.sh
    # Variablen via env in den Container; pipefail, damit ein Inner-Crash
    # nicht durch `tee` maskiert wird.
    pct exec "$ct_id" -- env PORT="$PORT" HOST_DNS="${HOST_DNS:-1.1.1.1}" \
        UPSTREAM_TARBALL_URL="$UPSTREAM_TARBALL_URL" \
        bash -c 'set -o pipefail; bash /root/setup-inner.sh 2>&1 | tee /var/log/kochido-setup.log'
}

get_installed_version() {
    # || true INNERHALB der Substitution (pipefail + pct-Fehlschlag-Grube)
    local v=""
    v=$(pct exec "$1" -- grep -m1 -oP 'APP_VERSION = "\K[^"]+' /opt/kochido/app/main.py 2>/dev/null | tail -n 1 || true)
    echo "$v"
}

# ── Verifikation ───────────────────────────────────────────────────────────
verify_installation() {
    local ct_id="$1" tries=0 code=""

    header "✅ Verifikation"

    while true; do
        if pct exec "$ct_id" -- systemctl is-active --quiet kochido 2>/dev/null; then
            ok "Service kochido läuft (FastAPI auf Port $PORT)"
            break
        fi
        tries=$((tries + 1))
        if [[ $tries -ge 30 ]]; then
            die "Service kochido läuft nicht.\n  Debug: pct exec $ct_id -- journalctl -u kochido -e --no-pager | tail -40"
        fi
        sleep 1
    done

    if pct exec "$ct_id" -- test -f /opt/kochido/app/dist/index.html 2>/dev/null; then
        ok "Frontend-Build vorhanden (/opt/kochido/app/dist/index.html)"
    else
        die "dist/index.html fehlt im Container.\n  Debug: pct exec $ct_id -- tail -n 50 /var/log/kochido-setup.log"
    fi

    # Health-Endpunkt (curl -w gibt bei Verbindungsfehler bereits 000 aus –
    # NIE zusätzlich || echo 000 anhängen, sonst falsch-positiv)
    tries=0
    while true; do
        code=$(pct exec "$ct_id" -- curl -s -o /dev/null --max-time 3 -w '%{http_code}' \
               "http://127.0.0.1:${PORT}/api/health" || true)
        if [[ "$code" == "200" ]]; then
            ok "API antwortet (HTTP 200 auf http://127.0.0.1:${PORT}/api/health)"
            break
        fi
        tries=$((tries + 1))
        if [[ $tries -ge 30 ]]; then
            local diag
            diag=$(pct exec "$ct_id" -- sh -c '
                echo "--- Listener auf Port '"$PORT"' (ss -tlnp) ---"
                ss -tlnp 2>/dev/null | grep -E "[:.]'"$PORT"'" || echo "  (KEIN Listener auf Port '"$PORT"')"
                echo "--- journalctl -u kochido (letzte Zeilen) ---"
                journalctl -u kochido --no-pager 2>/dev/null | tail -n 12 || true
            ' 2>/dev/null || true)
            die "API antwortet nicht (letzter HTTP-Code: ${code:-unbekannt}).

${diag}
  Service manuell prüfen: pct exec $ct_id -- systemctl restart kochido"
        fi
        sleep 1
    done

    # SPA-Index checken (der SPA-Fallback ist der eigentliche Einstiegspunkt)
    code=$(pct exec "$ct_id" -- curl -s -o /dev/null --max-time 3 -w '%{http_code}' \
           "http://127.0.0.1:${PORT}/" || true)
    if [[ "$code" == "200" ]]; then
        ok "Web-UI antwortet (HTTP 200 auf http://127.0.0.1:${PORT}/)"
    else
        warn "Web-UI liefert HTTP ${code:-unbekannt} (API OK, SPA prüfen: pct exec $ct_id -- ls -la /opt/kochido/app/dist)"
    fi

    # Vom PROXMOX-HOST aus erreichbar? (die Nutzer-URL läuft über die CT-IP)
    local ct_ip="" host_code=""
    ct_ip=$(get_ct_ip "$ct_id")
    if [[ -n "$ct_ip" ]]; then
        host_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
                    "http://${ct_ip}:${PORT}/" || true)
        if [[ "$host_code" == "200" ]]; then
            ok "Vom Host erreichbar: http://${ct_ip}:${PORT} (HTTP 200)"
        else
            warn "Im CT OK, aber vom Proxmox-Host nicht erreichbar (HTTP ${host_code:-000} über http://${ct_ip}:${PORT})."
            info "Prüfe CT-Firewall (pct config $ct_id | grep -E 'net0|firewall') und Bridge-Setup."
        fi
    fi
}

# ── Zusammenfassung ────────────────────────────────────────────────────────
print_summary() {
    header "🍳  Koch-I-Doo ist bereit!"

    local ct_ip app_version=""
    ct_ip=$(get_ct_ip "$CT_ID")
    if [[ -z "$ct_ip" ]]; then
        ct_ip="<IP-ADRESSE>"
    fi
    app_version=$(get_installed_version "$CT_ID")

    echo ""
    echo -e "  ${GREEN}${BOLD}════════════════════════════════════════════════════════════${NC}"
    echo -e "  ${GREEN}  🌐 Koch-I-Doo: http://${ct_ip}:${PORT}${NC}"
    echo -e "  ${GREEN}  🐚 Terminal:  pct enter ${CT_ID}${NC}"
    if [[ -n "$CT_PASSWORD" ]]; then
        echo -e "  ${GREEN}  🔑 Root-PW:   ${CT_PASSWORD}${NC}"
    fi
    if [[ -n "$app_version" ]]; then
        echo -e "  ${GREEN}  📦 Version:   v${app_version} (upstream ${UPSTREAM_OWNER}/${UPSTREAM_REPO}@${UPSTREAM_BRANCH})${NC}"
    fi
    echo -e "  ${GREEN}  🔧 Installer: v${INSTALLER_VERSION}${NC}"
    echo -e "  ${GREEN}${BOLD}════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${CYAN}Erste Schritte:${NC}"
    echo "  1. http://${ct_ip}:${PORT} öffnen (Tablett/Handy im gleichen Netz)"
    echo "  2. „⤓ Importieren“ → Rezept-URL von Chefkoch einfügen (TM-Schritte"
    echo "     wie „3 Min./100°C/Stufe 2“ werden automatisch als Badges erkannt)"
    echo "  3. Tab „Cookidoo-Konto“: direkter Export aus deinem Abo (oder cookidump) –"
    echo "     (github.com/auino/cookidump) laufen lassen und data.json hier laden –"
    echo "     danach brauchst du Cookidoo nicht mehr."
    echo "  4. „🍳 Kochen starten“ → Vollbild Schritt für Schritt wie bei Cookidoo:"
    echo "     Einwiegen-Chips, Timer mit Pieps, Temperatur/Stufe/Linkslauf."
    echo ""
    echo -e "  ${CYAN}Nützliche Befehle (exakt kopierbar):${NC}"
    echo "  Status:    ${ONE_LINER} --status"
    echo "  Update:    ${ONE_LINER} --update"
    echo "  Deinstall: ${ONE_LINER} --uninstall"
    echo "  Logs:      pct exec ${CT_ID} -- journalctl -u kochido -f"
    echo ""
    warn "Rezepte/Bilder liegen im Container unter /opt/kochido/data (SQLite) –"
    warn "ein Update (--update) oder CT-Neustart löscht sie NICHT."
}

# ── Install ────────────────────────────────────────────────────────────────
do_install() {
    header "🍳 Installiere Koch-I-Doo (LXC)"
    info "Installer-Version: v${INSTALLER_VERSION}"

    if [[ $EUID -ne 0 ]]; then
        die "Bitte als root ausführen (auf dem Proxmox-Host)."
    fi
    if ! command -v pct >/dev/null 2>&1; then
        die "pct nicht gefunden – das Script muss auf einem Proxmox-VE-Host laufen."
    fi

    local existing
    existing=$(find_ct_id_by_hostname || true)
    if [[ -n "$existing" ]]; then
        if $FORCE_RECREATE; then
            warn "Container $existing ($CT_HOSTNAME) existiert – --force: lösche und lege neu an."
            warn "ACHTUNG: Dabei gehen Rezepte in /opt/kochido/data verloren – vorher sichern!"
            if ! $ASSUME_YES; then
                local answer=""
                if ! read -r -t 60 -p "Container inkl. Rezept-Datenbank wirklich löschen? (ja/NEIN): " answer; then
                    die "Keine Bestätigung erhalten (nicht-interaktiv?) – nichts gelöscht.\n  Erzwingen:  ${ONE_LINER} --force --yes"
                fi
                if [[ "$answer" != "ja" ]]; then
                    info "Abgebrochen – nichts gelöscht."
                    return 0
                fi
            fi
            pct stop "$existing" || true
            pct destroy "$existing" --purge
        else
            die "Container $existing mit Hostname '$CT_HOSTNAME' existiert bereits.\n  Update:  ${ONE_LINER} --update\n  Neu aufsetzen (löst Rezepte!):  ${ONE_LINER} --force"
        fi
    fi

    header "🧱 Container-Template"
    local template=""
    template=$(pveam list local 2>/dev/null | awk '{print $1}' | grep -o 'debian-1[23]-standard[^ ]*' | sort -rV | head -1 || true)
    if [[ -z "$template" ]]; then
        info "Kein Debian-12/13-Template vorhanden – lade es herunter ..."
        pveam update
        template=$(pveam available --section system 2>/dev/null | grep -o 'debian-1[23]-standard[^ ]*' | sort -rV | head -1 || true)
        if [[ -z "$template" ]]; then
            die "Kein debian-12/13-standard-Template gefunden (pveam available leer?).\n  Koch-I-Doo braucht für den Cookidoo-Konto-Import Python ≥ 3.12 (Debian 13)."
        fi
        pveam download local "$template"
    fi
    ok "Template: $template"

    if [[ -z "$CT_ID" ]]; then
        CT_ID=$(find_free_id)
        info "Nächste freie CT-ID: $CT_ID"
    fi
    if [[ -z "$CT_PASSWORD" ]]; then
        CT_PASSWORD=$(openssl rand -base64 12 2>/dev/null || true)
        if [[ -z "$CT_PASSWORD" ]]; then
            CT_PASSWORD="kd-$(date +%s)"
        fi
    fi

    header "🚀 Erzeuge Container $CT_ID ($CT_HOSTNAME)"
    local net0="name=eth0,bridge=${CT_BRIDGE},ip=${CT_IP},firewall=0"
    if [[ -n "$CT_GATEWAY" ]]; then
        net0+=",gateway=${CT_GATEWAY}"
    fi
    local ssh_keys_args=()
    if [[ -n "$CT_SSHKEY" ]]; then
        if [[ "$CT_SSHKEY" == http://* || "$CT_SSHKEY" == https://* ]]; then
            info "Lade SSH-Public-Key herunter ..."
            wget -q --tries=3 -O "$TMP_DIR/sshkey.pub" "$CT_SSHKEY" || die "SSH-Key-URL nicht ladbar: $CT_SSHKEY"
        elif [[ -f "$CT_SSHKEY" ]]; then
            cp "$CT_SSHKEY" "$TMP_DIR/sshkey.pub"
        else
            die "SSH-Key-Datei nicht gefunden: $CT_SSHKEY"
        fi
        if [[ ! -s "$TMP_DIR/sshkey.pub" ]]; then
            die "SSH-Key-Datei ist leer: $CT_SSHKEY"
        fi
        SSH_KEY_FILE="$TMP_DIR/sshkey.pub"
        ok "SSH-Public-Key wird in den Container installiert (ssh-key-Login als root)"
        ssh_keys_args=(--ssh-public-keys "$SSH_KEY_FILE")
    fi
    pct create "$CT_ID" "local:vztmpl/${template}" \
        --hostname "$CT_HOSTNAME" \
        --cores "$CT_CORES" \
        --memory "$CT_MEMORY" \
        --swap "$CT_SWAP" \
        --rootfs "${CT_STORAGE}:${CT_ROOTFS}" \
        --net0 "$net0" \
        --unprivileged 1 \
        --features nesting=1 \
        --onboot 1 \
        --start 1 \
        --password "$CT_PASSWORD" \
        "${ssh_keys_args[@]}"
    ok "Container $CT_ID erstellt und gestartet"

    wait_for_ct_network "$CT_ID"
    verify_ct_dns "$CT_ID"

    run_inner_setup "$CT_ID"
    verify_installation "$CT_ID"
    print_summary
}

# ── Update ─────────────────────────────────────────────────────────────────
do_update() {
    header "🔄 Update Kochido (neue Version von GitHub)"

    local ct_id
    ct_id=$(find_ct_id_by_hostname || true)
    if [[ -z "$ct_id" ]]; then
        die "Kein Container mit Hostname '$CT_HOSTNAME' gefunden.\n  Erst installieren:  ${ONE_LINER}"
    fi
    CT_ID="$ct_id"

    ensure_ct_running "$ct_id"
    verify_ct_dns "$ct_id"

    run_inner_setup "$ct_id"
    verify_installation "$ct_id"

    ok "Update abgeschlossen – Rezept-Datenbank (/opt/kochido/data) blieb unberührt."
    print_summary
}

# ── Uninstall ──────────────────────────────────────────────────────────────
do_uninstall() {
    header "🗑️  Deinstalliere Kochido"

    local ct_id
    ct_id=$(find_ct_id_by_hostname || true)
    if [[ -z "$ct_id" ]]; then
        warn "Kein Container mit Hostname '$CT_HOSTNAME' gefunden – nichts zu tun."
        return 0
    fi
    CT_ID="$ct_id"

    warn "Container $ct_id ($CT_HOSTNAME) wird GESTOPPT und GELÖSCHT."
    warn "Dabei gehen gespeicherte Rezepte verloren (/opt/kochido/data im Container)!"
    if ! $ASSUME_YES; then
        local answer=""
        if ! read -r -t 60 -p "Wirklich löschen? (ja/NEIN): " answer; then
            die "Keine Bestätigung erhalten (nicht-interaktiv?) – nichts gelöscht.\n  Erzwingen:  ${ONE_LINER} --uninstall --yes"
        fi
        if [[ "$answer" != "ja" ]]; then
            info "Abgebrochen – nichts gelöscht."
            return 0
        fi
    fi
    pct stop "$ct_id" || true
    pct destroy "$ct_id" --purge
    ok "Container $ct_id entfernt."
}

# ── Status ─────────────────────────────────────────────────────────────────
do_status() {
    header "📊 Status Kochido"
    info "Installer-Version: v${INSTALLER_VERSION}"

    local ct_id
    ct_id=$(find_ct_id_by_hostname || true)
    if [[ -z "$ct_id" ]]; then
        warn "Kein Container mit Hostname '$CT_HOSTNAME' gefunden."
        info "Installieren:  ${ONE_LINER}"
        return 0
    fi
    CT_ID="$ct_id"

    pct list 2>/dev/null | awk -v id="$ct_id" '$1==id {print "Container:  " $1 " (" $2 ") – " $4}'

    local state
    state=$(pct status "$ct_id" 2>/dev/null | awk '{print $2}' || true)
    if [[ "$state" != "running" ]]; then
        warn "Container $ct_id ist nicht gestartet (${state:-unbekannt}) – Service/Version/Web-UI ohne Start nicht prüfbar."
        info "Starten:    pct start $ct_id"
        return 0
    fi

    if pct exec "$ct_id" -- systemctl is-active --quiet kochido 2>/dev/null; then
        ok "Service:   kochido läuft (Port $PORT)"
    else
        err "Service:   kochido läuft NICHT"
        info "Logs:      pct exec $ct_id -- journalctl -u kochido -e --no-pager"
    fi

    local ip code="" health=""
    ip=$(get_ct_ip "$ct_id")
    if [[ -n "$ip" ]]; then
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://${ip}:${PORT}/" || true)
        if [[ "$code" == "200" ]]; then
            health=$(curl -s --max-time 5 "http://${ip}:${PORT}/api/health" 2>/dev/null || true)
            ok "Web-UI:    http://${ip}:${PORT}  (HTTP 200)  ${health}"
        else
            warn "Web-UI:    HTTP-Code ${code:-unbekannt} von http://${ip}:${PORT}"
        fi
    else
        warn "Container hat keine IP (läuft er?)."
    fi
}

# ── Main ───────────────────────────────────────────────────────────────────
parse_args "$@"

TMP_DIR=$(mktemp -d)

if $UNINSTALL; then
    do_uninstall
elif $UPDATE; then
    do_update
elif $STATUS_CHECK; then
    do_status
else
    do_install
fi
