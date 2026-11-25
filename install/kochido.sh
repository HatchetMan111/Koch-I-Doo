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

# Log/Sicherheit: strenger umask, Log via mktemp (0600, kein Symlink-Follow)
umask 077

# ── Defaults ────────────────────────────────────────────────────────────────
INSTALLER_VERSION="1.2.0"
APP_NAME="kochido"
UPSTREAM_OWNER="HatchetMan111"
UPSTREAM_REPO="Koch-I-Doo"
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
PORT_EXPLICIT=false         # true, wenn --port übergeben wurde (Update/Status keep port)
UNINSTALL=false
UPDATE=false
STATUS_CHECK=false
FORCE_RECREATE=false
ASSUME_YES=false
TMP_DIR=""
LOG_FILE=""                 # wird per mktemp sicher angelegt (0600)
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

# Log-Datei sicher anlegen (0600, atomar, kein Symlink-Race in /tmp)
LOG_FILE=$(mktemp "/tmp/${APP_NAME}-installer-XXXXXXXX.log")
chmod 600 "$LOG_FILE"
exec > >(tee "$LOG_FILE") 2>&1

# Ausgabe, die NICHT ins Log darf (z. B. Root-Passwort): ans Terminal, nicht ins Log
out_secret() {
    if [[ -e /dev/tty ]] && echo "" > /dev/tty 2>/dev/null; then
        echo -e "$1" > /dev/tty
    else
        echo -e "$1"
    fi
}

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

# Marker-Check: Nur ein Container, den DIESER Installer angelegt hat
# (/opt/kochido/.kochido-installed), darf per --uninstall/--force/--update
# angefasst werden — sonst löscht ein --hostname <fremd> einen fremden CT.
# Legacy-Installationen (Installer < v1.2.0, noch ohne Marker) werden an
# kochido.service + /opt/kochido/app erkannt und bekommen den Marker nachträglich.
assert_kochido_ct() {
    local ct_id="$1"
    if pct exec "$ct_id" -- test -f /opt/kochido/.kochido-installed 2>/dev/null; then
        ok "Marker geprüft: Container $ct_id ist ein Koch-I-Doo-Container"
        return 0
    fi
    if pct exec "$ct_id" -- sh -c 'test -f /etc/systemd/system/kochido.service && test -d /opt/kochido/app' 2>/dev/null; then
        warn "Legacy-Installation (vor v1.2.0, noch ohne Marker) erkannt – setze Marker nachträglich."
        pct exec "$ct_id" -- touch /opt/kochido/.kochido-installed 2>/dev/null || true
        ok "Container $ct_id ist ein Koch-I-Doo-Container (Legacy-Marker gesetzt)"
        return 0
    fi
    die "Container $ct_id ist KEIN Koch-I-Doo-Container (kein Marker, keine kochido.service).\n  Abbruch aus Sicherheitsgründen — fremde Container werden nicht angefasst."
}

# Port aus der bestehenden systemd-Unit lesen (Update/Status ohne --port
# dürfen den konfigurierten Port NICHT auf 8090 zurücksetzen)
read_ct_port() {
    local ct_id="$1"
    pct exec "$ct_id" -- sed -n 's/^Environment=PORT=//p' /etc/systemd/system/kochido.service 2>/dev/null | head -1 || true
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
    # ns_list NICHT ungequotet in einen remote-sh-c-String einbetten (Injection-Muster)
    pct exec "$id" -- env NS_LIST="$ns_list" sh -c 'printf "nameserver %s\n" $NS_LIST > /etc/resolv.conf'
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
need_value() {
    # Option braucht einen Wert, der nicht wie eine Option aussieht
    local opt="$1" next="${2:-}"
    if [[ -z "$next" || "$next" == --* ]]; then
        die "Option ${opt} braucht einen Wert (z. B. ${opt} 8090)"
    fi
}

is_uint() { [[ "$1" =~ ^[0-9]+$ ]]; }
is_ipv4() {
    [[ "$1" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
    local o
    for o in "${BASH_REMATCH[@]:1}"; do (( 10#$o <= 255 )) || return 1; done
    return 0
}

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
            --id)            need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_ID="${args[$((i+1))]}"; i=$((i+2)) ;;
            --hostname)      need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_HOSTNAME="${args[$((i+1))]}"; i=$((i+2)) ;;
            --storage)       need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_STORAGE="${args[$((i+1))]}"; i=$((i+2)) ;;
            --rootfs)        need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_ROOTFS="${args[$((i+1))]}"; i=$((i+2)) ;;
            --cores)         need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_CORES="${args[$((i+1))]}"; i=$((i+2)) ;;
            --memory)        need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_MEMORY="${args[$((i+1))]}"; i=$((i+2)) ;;
            --swap)          need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_SWAP="${args[$((i+1))]}"; i=$((i+2)) ;;
            --bridge)        need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_BRIDGE="${args[$((i+1))]}"; i=$((i+2)) ;;
            --ip)            need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_IP="${args[$((i+1))]}"; i=$((i+2)) ;;
            --gateway)       need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_GATEWAY="${args[$((i+1))]}"; i=$((i+2)) ;;
            --password)      need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_PASSWORD="${args[$((i+1))]}"; i=$((i+2)) ;;
            --sshkey)        need_value "${args[$i]}" "${args[$((i+1))]:-}"; CT_SSHKEY="${args[$((i+1))]}"; i=$((i+2)) ;;
            --port)          need_value "${args[$i]}" "${args[$((i+1))]:-}"; PORT="${args[$((i+1))]}"; PORT_EXPLICIT=true; i=$((i+2)) ;;
            --)              i=$((i+1)) ;;  # bash -c "…" -- --update: "--" ist $0/Separator, ignorieren
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
    # 10# erzwingt Dezimal – führende Nullen wie "08" sind sonst oktal/Fehler
    if ! is_uint "$PORT" || (( 10#$PORT < 1 || 10#$PORT > 65535 )); then
        die "Ungültiger Port: '$PORT' (1–65535 erwartet, z. B. --port 8090)"
    fi
    PORT=$((10#$PORT))
    if [[ -n "$CT_ID" ]] && ! is_uint "$CT_ID"; then
        die "Ungültige Container-ID: '$CT_ID' (nur Ziffern erlaubt)"
    fi
    for v in "$CT_ROOTFS" "$CT_CORES" "$CT_MEMORY" "$CT_SWAP"; do
        is_uint "$v" || die "Ungültige Zahl: '$v' (nur Ziffern erlaubt)"
    done
    [[ "$CT_BRIDGE" =~ ^[A-Za-z0-9._-]+$ ]] || die "Ungültige Bridge: '$CT_BRIDGE'"
    [[ "$CT_STORAGE" =~ ^[A-Za-z0-9._-]+$ ]] || die "Ungültiger Storage-Name: '$CT_STORAGE'"
    if [[ "$CT_IP" != "dhcp" ]]; then
        if [[ "$CT_IP" =~ ^([0-9.]+)/([0-9]{1,2})$ ]] && is_ipv4 "${BASH_REMATCH[1]}" && (( 10#${BASH_REMATCH[2]} <= 32 )); then
            :
        else
            die "Ungültige --ip CIDR: '$CT_IP' (z. B. 192.168.1.50/24 oder dhcp)"
        fi
    fi
    if [[ -n "$CT_GATEWAY" ]] && ! is_ipv4 "$CT_GATEWAY"; then
        die "Ungültiges Gateway: '$CT_GATEWAY' (IPv4 erwartet)"
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
  --password PW    Root-Passwort (besser: Env KOCHIDO_PASSWORD – nicht in der History)
  --sshkey PFAD    Public-Key-Datei oder https://URL (nur https!) – ssh-key-Login als root im CT
  --port PORT      Web-UI-Port im Container (Default: 8090; --update/--status
                    übernehmen ohne --port den konfigurierten Port)
  --force          Vorhandenen Koch-I-Doo-Container gleichen Hostnamens löschen und neu anlegen
  --yes / -y       Rückfragen überspringen
  --update         App im bestehenden Container aktualisieren (neue Version von GitHub main)
  --uninstall      Container stoppen und löschen (nur mit Koch-I-Doo-Marker)
  --status         Status anzeigen
  --debug          Vollständiges bash -x-Trace

  Umgebungsvariablen (optional):
    KOCHIDO_PASSWORD         Root-Passwort (statt --password)
    KOCHIDO_TZ               Zeitzone im Container (Default: Europe/Berlin)
    KOCHIDO_TARBALL_SHA256   sha256 des Upstream-Tarballs – bei Angabe wird geprüft

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
umask 022   # Service-User kochido muss /opt/kochido traversieren (CHDIR), nie 077

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
# Optional: Tarball-Pin prüfen (Host: KOCHIDO_TARBALL_SHA256=<sha256> setzen)
if [[ -n "${EXPECTED_SHA256:-}" ]]; then
    echo ">>> SHA256 des Tarballs prüfen ..."
    echo "${EXPECTED_SHA256}  /tmp/kochido.tar.gz" | sha256sum -c - \
        || die "SHA256-Prüfung fehlgeschlagen – Tarball stammt nicht vom gepinnten Stand!"
fi
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

echo ">>> App-Version atomar aktivieren (Symlink-Wechsel, kein Crash-Fenster) ..."
# Release-Verzeichnis + Symlink tauschen: `mv -T` auf den Symlink ist atomar.
REL_DIR="/opt/kochido/releases"
mkdir -p "$REL_DIR"
REL="$REL_DIR/app-$(date +%s)"
mv /opt/kochido/app.new "$REL"
if [ -d /opt/kochido/app ] && [ ! -L /opt/kochido/app ]; then
    # einm migration: alte Installation war ein echtes Verzeichnis
    rm -rf /opt/kochido/app.old
    mv /opt/kochido/app /opt/kochido/app.old
    rm -rf /opt/kochido/app.old
fi
ln -sfn "$REL" /opt/kochido/app.link
mv -T /opt/kochido/app.link /opt/kochido/app
# alte Releases aufräumen (neueste 2 behalten)
ls -1dt "$REL_DIR"/app-* 2>/dev/null | tail -n +3 | xargs -r rm -rf

echo ">>> Datenordner sicherstellen (Rezept-DB überlebt Updates) ..."
mkdir -p /opt/kochido/data/images
# Marker für den Installer: „dieser CT gehört zu Koch-I-Doo“
# (--uninstall/--update/--force prüfen ihn, bevor sie etwas anfassen)
touch /opt/kochido/.kochido-installed

echo ">>> Systembenutzer kochido anlegen (Service läuft NICHT als root) ..."
if ! id kochido >/dev/null 2>&1; then
    useradd -r -d /opt/kochido -s /usr/sbin/nologin kochido
fi
chown -R kochido:kochido /opt/kochido/data
# WICHTIG: Der Service-User muss /opt/kochido, das Release (Symlink-Ziel von
# WorkingDirectory) und das venv traversieren/ausführen dürfen — sonst CHDIR/EXEC
# "Permission denied" (systemd-Status 200/CHDIR). Explizit setzen, unabhängig
# von der umask des aufrufenden Root-Shells.
chmod 755 /opt/kochido "$REL_DIR" "$REL" 2>/dev/null || true
chmod -R a+rX "$REL" 2>/dev/null || true
if [[ -d /opt/kochido/venv ]]; then
    chmod 755 /opt/kochido/venv 2>/dev/null || true
    chmod -R a+rX /opt/kochido/venv 2>/dev/null || true
fi

echo ">>> systemd-Unit kochido.service schreiben (Port ${PORT}, gehärtet) ..."
cat > /etc/systemd/system/kochido.service <<UNITEOF
[Unit]
Description=Koch-I-Doo – Guided Cooking Server (lokaler Cookidoo-Ersatz)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=kochido
Group=kochido
WorkingDirectory=/opt/kochido/app
Environment=PORT=${PORT}
Environment=KOCHIDO_DATA=/opt/kochido/data
Environment=KOCHIDO_DIST=/opt/kochido/app/dist
# Zeitzone für „heute“-Berechnungen (sonst weicht Server-UTC vom Browser ab)
Environment=KOCHIDO_TZ=${KOCHIDO_TZ:-Europe/Berlin}
ExecStart=/opt/kochido/venv/bin/python /opt/kochido/app/main.py
Restart=always
RestartSec=3
# Hardening: App läuft unprivilegiert, Dateisystem sonst read-only
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/kochido/data

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable kochido
systemctl restart kochido

echo ">>> Prüfe, dass Kochido auf Port ${PORT} antwortet ..."
PORT_OK=""
for _ in $(seq 1 30); do
    # -f + HTTP-Code: auch 500/502 zählen NICHT als „läuft“
    code=$(curl -s -o /dev/null --max-time 2 -w '%{http_code}' "http://127.0.0.1:${PORT}/api/health" || true)
    if [[ "$code" == "200" ]]; then
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
        EXPECTED_SHA256="${KOCHIDO_TARBALL_SHA256:-}" \
        KOCHIDO_TZ="${KOCHIDO_TZ:-Europe/Berlin}" \
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
        # Passwort NIE ins Log (tee) schreiben — nur ans Terminal
        out_secret "  ${GREEN}  🔑 Root-PW:   ${CT_PASSWORD}${NC}"
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

    if ! command -v pct >/dev/null 2>&1; then
        die "pct nicht gefunden – das Script muss auf einem Proxmox-VE-Host laufen."
    fi

    local existing
    existing=$(find_ct_id_by_hostname || true)
    if [[ -n "$existing" ]]; then
        if $FORCE_RECREATE; then
            # Marker-Check: nur echte Koch-I-Doo-CTs dürfen zerstört werden
            ensure_ct_running "$existing"
            assert_kochido_ct "$existing"
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
            # Bereits installiert → kein Fehler, sondern direkt Update-Pfad
            # (schützt vor versehentlichem Überschreiben, spart den Extra-Befehl)
            warn "Container $existing mit Hostname '$CT_HOSTNAME' ist bereits installiert – führe direkt ein Update durch."
            info "(Neu aufsetzen mit Rezept-Verlust nur bewusst: ${ONE_LINER} --force)"
            do_update
            return 0
        fi
    fi

    header "🧱 Container-Template"
    # Template-Namen robust extrahieren: pveam list/available liefern Spalte 1
    # als "<storage>:vztmpl/<name>" ODER nur "vztmpl/<name>" – wir nehmen alles
    # nach "vztmpl/" und hängen unseren Storage selbst an.
    tpl_name_in_list() {
        pveam list "$CT_STORAGE" 2>/dev/null | awk '{print $1}' \
            | sed -n 's#.*vztmpl/##p' | grep -E '^debian-1[23]-standard' | sort -rV | head -1
    }
    tpl_name_available() {
        pveam available --section system 2>/dev/null | awk '{print $1}' \
            | sed -n 's#.*vztmpl/##p' | grep -E '^debian-1[23]-standard' | sort -rV | head -1
    }
    local template=""
    template=$(tpl_name_in_list || true)
    if [[ -z "$template" ]]; then
        info "Kein Debian-12/13-Template auf '$CT_STORAGE' vorhanden – lade es herunter ..."
        pveam update
        template=$(tpl_name_available || true)
        if [[ -z "$template" ]]; then
            die "Kein debian-12/13-standard-Template in 'pveam available' gefunden.\n  Koch-I-Doo braucht für den Cookidoo-Konto-Import Python ≥ 3.12 (Debian 13).\n  Manuell prüfen: pveam available --section system | grep debian"
        fi
        pveam download "$CT_STORAGE" "$template"
        # Download verifizieren, sonst pct create mit kaputtem Template
        template=$(tpl_name_in_list || true)
        if [[ -z "$template" ]]; then
            die "Template-Download nach '$CT_STORAGE' fehlgeschlagen (pveam list $CT_STORAGE zeigt es nicht)."
        fi
    fi
    ok "Template: ${CT_STORAGE}:vztmpl/${template}"

    if [[ -z "$CT_ID" ]]; then
        CT_ID=$(find_free_id)
        info "Nächste freie CT-ID: $CT_ID"
    fi
    if [[ -z "$CT_PASSWORD" ]]; then
        # Env bevorzugen (kein Passwort in ps/Shell-History); Fallback: urandom
        CT_PASSWORD="${KOCHIDO_PASSWORD:-}"
        if [[ -z "$CT_PASSWORD" ]]; then
            CT_PASSWORD=$(head -c 24 /dev/urandom | base64 | tr -d '\n=+' | head -c 24 || true)
        fi
        if [[ -z "$CT_PASSWORD" ]]; then
            CT_PASSWORD=$(openssl rand -base64 18 2>/dev/null || true)
        fi
        [[ -n "$CT_PASSWORD" ]] || die "Konnte kein Passwort erzeugen (urandom/openssl fehlt?)"
    fi

    header "🚀 Erzeuge Container $CT_ID ($CT_HOSTNAME)"
    local net0="name=eth0,bridge=${CT_BRIDGE},ip=${CT_IP},firewall=0"
    if [[ -n "$CT_GATEWAY" ]]; then
        net0+=",gateway=${CT_GATEWAY}"
    fi
    local ssh_keys_args=()
    if [[ -n "$CT_SSHKEY" ]]; then
        if [[ "$CT_SSHKEY" == http://* ]]; then
            die "--sshkey nur über https:// erlaubt (http wäre MITM-gefährdet): $CT_SSHKEY"
        elif [[ "$CT_SSHKEY" == https://* ]]; then
            info "Lade SSH-Public-Key herunter (https) ..."
            curl -fSL --retry 3 -o "$TMP_DIR/sshkey.pub" "$CT_SSHKEY" \
                || die "SSH-Key-URL nicht ladbar: $CT_SSHKEY"
        elif [[ -f "$CT_SSHKEY" ]]; then
            cp "$CT_SSHKEY" "$TMP_DIR/sshkey.pub"
        else
            die "SSH-Key-Datei nicht gefunden: $CT_SSHKEY"
        fi
        if [[ ! -s "$TMP_DIR/sshkey.pub" ]]; then
            die "SSH-Key-Datei ist leer: $CT_SSHKEY"
        fi
        # Key-Inhalt validieren: eine Zeile, bekannter Key-Typ (kein command= etc.)
        if ! grep -qE '^(ssh-(rsa|ed25519)|ecdsa-sha2-[a-z0-9-]+) [A-Za-z0-9+/=]+( .*)?$' "$TMP_DIR/sshkey.pub" \
           || [[ "$(wc -l < "$TMP_DIR/sshkey.pub")" -gt 1 ]]; then
            die "SSH-Key-Datei sieht ungültig aus (erwartet: eine Zeile 'ssh-ed25519 AAAA…')"
        fi
        SSH_KEY_FILE="$TMP_DIR/sshkey.pub"
        ok "SSH-Public-Key wird in den Container installiert (ssh-key-Login als root)"
        ssh_keys_args=(--ssh-public-keys "$SSH_KEY_FILE")
    fi
    pct create "$CT_ID" "${CT_STORAGE}:vztmpl/${template}" \
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
    assert_kochido_ct "$ct_id"
    # ohne explizites --port: Port aus der bestehenden Unit übernehmen
    if ! $PORT_EXPLICIT; then
        local old_port
        old_port=$(read_ct_port "$ct_id")
        if [[ -n "$old_port" ]] && is_uint "$old_port"; then
            PORT=$((10#$old_port))
            info "Port aus bestehender Unit übernommen: $PORT"
        fi
    fi
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

    # Marker-Check VOR dem Löschen: nur echte Koch-I-Doo-CTs (CT ggf. starten)
    ensure_ct_running "$ct_id"
    assert_kochido_ct "$ct_id"

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

    # ohne explizites --port: Port aus der Unit lesen (nur wenn CT läuft —
    # Status startet keinen Container)
    if ! $PORT_EXPLICIT; then
        local st=""
        st=$(pct status "$ct_id" 2>/dev/null || echo "unknown")
        if [[ "$st" == *"running"* ]]; then
            local old_port=""
            old_port=$(read_ct_port "$ct_id" 2>/dev/null || true)
            if [[ -n "$old_port" ]] && is_uint "$old_port"; then
                PORT=$((10#$old_port))
            fi
        fi
    fi

    # $NF statt $4: bei leerer Lock-Spalte ist $4 leer, der Name steht immer ganz hinten
    pct list 2>/dev/null | awk -v id="$ct_id" '$1==id {print "Container:  " $1 " (" $2 ") – " $NF}'

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

# Root-Check zentral (gilt für alle Modi außer --help, das vorher exit't).
# KOCHIDO_HARNESS_NONROOT=1 ist NUR für das lokale Mock-Harness (harness/run.sh)
# — auf einem echten Proxmox-Host läuft der Installer als root.
if [[ $EUID -ne 0 && "${KOCHIDO_HARNESS_NONROOT:-0}" != "1" ]]; then
    die "Bitte als root ausführen (auf dem Proxmox-Host)."
fi

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
