# Koch-I-Doo – Bild-Handling: Rezeptbilder lokal speichern (offline-tauglich).
# Eigenes Modul, damit Haupt-App und Dump-Job es ohne Import-Zyklus nutzen.
import hashlib
import ipaddress
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from db import IMG_DIR

_IMG_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Kochido/1.0 (+lokaler Rezept-Import)"

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_HTML_BYTES = 5 * 1024 * 1024


def _ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Private/Loopback/Link-Local/Reserved/etc. → SSRF-Ziel blockieren."""
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    )


def url_allowed(url: str) -> bool:
    """Nur http(s) an öffentliche Hosts — interne Ziele (169.254.169.254,
    localhost, LAN, …) sind tabu. DNS wird aufgelöst und JEDE IP geprüft,
    damit DNS-Rebinding-artige Namen nicht durchrutschen."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").strip().rstrip(".")
    if not host:
        return False
    try:  # IP-Literal direkt prüfen
        if _ip_blocked(ipaddress.ip_address(host)):
            return False
    except ValueError:
        pass  # echter Hostname → DNS prüfen
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            if _ip_blocked(ipaddress.ip_address(info[4][0])):
                return False
        except ValueError:
            return False
    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Jeder Redirect wird erneut validiert (sonst SSRF per 302 auf intern)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not url_allowed(newurl):
            raise urllib.error.URLError(
                f"Redirect zu blockiertem Ziel abgelehnt: {newurl}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(url: str, headers: dict, timeout: float, max_bytes: int):
    """urlopen mit SSRF-Schutz + Größenlimit. Liefert (response, raw_bytes).

    Content-Length wird VOR dem Lesen geprüft; zusätzlich wird das Limit beim
    Lesen hart durchgesetzt (Chunked-Antworten ohne Content-Length)."""
    if not url_allowed(url):
        raise urllib.error.URLError(f"URL blockiert (intern/privat/nicht öffentlich): {url}")
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    resp = opener.open(req, timeout=timeout)
    try:
        cl = resp.headers.get("Content-Length")
        if cl:
            try:
                if int(cl) > max_bytes:
                    raise ValueError(f"Datei zu groß (Content-Length {cl} > {max_bytes})")
            except ValueError as exc:
                if "zu groß" in str(exc):
                    raise
        raw = resp.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError(f"Datei zu groß (> {max_bytes} Bytes)")
        return resp, raw
    except Exception:
        resp.close()
        raise


def localize_image(recipe: dict, source_override: str = "") -> tuple[dict, str | None]:
    """Lädt das Rezeptbild lokal in data/images (best effort, offline-tauglich).
    Bei 403/401 (Hotlink-Schutz) zweiter Versuch mit Referer der Rezept-URL."""
    url = recipe.get("image") or ""
    if not url or not url.startswith("http"):
        return recipe, None

    source = source_override or recipe.get("source") or ""
    attempts = [{"User-Agent": USER_AGENT}]
    if source.startswith("http"):
        attempts.append({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Referer": source,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        })

    last_err: Exception | None = None
    for headers in attempts:
        try:
            resp, raw = safe_urlopen(url, headers, timeout=15, max_bytes=MAX_IMAGE_BYTES)
            with resp:
                ctype = resp.headers.get_content_type()
            ext = _IMG_EXT.get(ctype)
            if not ext:
                return recipe, f"Bildtyp {ctype} nicht unterstützt – URL bleibt extern."
            name = hashlib.sha256(url.encode()).hexdigest()[:16] + ext
            (IMG_DIR / name).write_bytes(raw)
            recipe = {**recipe, "image": f"/images/{name}"}
            return recipe, None
        except Exception as exc:  # noqa: BLE001 – Bild ist optional
            last_err = exc
            print(f"[import] Bild-Versuch fehlgeschlagen ({url}): {type(exc).__name__}: {exc}")
    return recipe, f"Bild konnte nicht lokal gespeichert werden ({type(last_err).__name__}) – externe URL bleibt (evtl. Hotlink-Schutz)."
