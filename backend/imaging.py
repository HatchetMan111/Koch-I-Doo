# Koch-I-Doo – Bild-Handling: Rezeptbilder lokal speichern (offline-tauglich).
# Eigenes Modul, damit Haupt-App und Dump-Job es ohne Import-Zyklus nutzen.
import hashlib
import urllib.request
from pathlib import Path

from db import IMG_DIR

_IMG_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Kochido/1.0 (+lokaler Rezept-Import)"


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
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read(10 * 1024 * 1024)
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
