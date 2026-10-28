"""Módulo detector opcional para Irodori TTS (servicio localhost:8291 bajo demanda).

Qué hace:
- Detecta si el directorio tools/irodori (o ruta configurable vía IRODORI_PATH / IRODORI_DIR) existe.
- Verifica si el microservicio HTTP está respondiendo en localhost:8291 (o IRODORI_URL).
- Retorna el estado consolidado: instalado sólo si el directorio existe Y el servicio responde en :8291.
- Retorna motivos detallados y transparentes si está ausente o si el servicio está apagado (offline).
- Soporta inyección de prober para tests offline sin sockets de red.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from app.config import APP_ROOT

DEFAULT_IRODORI_PORT = 8291
DEFAULT_IRODORI_HOST = "127.0.0.1"
DEFAULT_IRODORI_URL = f"http://{DEFAULT_IRODORI_HOST}:{DEFAULT_IRODORI_PORT}"
DEFAULT_IRODORI_DIR = "tools/irodori"
DEFAULT_PROBE_TIMEOUT_S = 0.5


def get_irodori_dir() -> Path:
    """Obtiene la ruta configurada para tools/irodori (configurable vía IRODORI_PATH o IRODORI_DIR)."""
    env_dir = os.environ.get("IRODORI_PATH") or os.environ.get("IRODORI_DIR")
    if env_dir:
        p = Path(env_dir)
        return p if p.is_absolute() else (APP_ROOT / p).resolve()
    return (APP_ROOT / DEFAULT_IRODORI_DIR).resolve()


def get_irodori_url() -> str:
    """Obtiene la URL base configurada para el microservicio de Irodori (configurable vía IRODORI_URL)."""
    return os.environ.get("IRODORI_URL") or DEFAULT_IRODORI_URL


def probe_irodori_service(url: str, timeout: float = DEFAULT_PROBE_TIMEOUT_S) -> bool:
    """Comprueba si el microservicio en `url` responde por HTTP."""
    endpoint = url.rstrip("/") + "/health"
    try:
        req = urllib.request.Request(endpoint, headers={"User-Agent": "WaifuStudio-Irodori-Probe"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            return 200 <= status < 500
    except urllib.error.HTTPError:
        # Si devuelve cualquier código HTTP (e.g. 404, 405, 503), el socket y el servidor HTTP están respondiendo
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        # Intentar la raíz si /health falló
        try:
            req_root = urllib.request.Request(url.rstrip("/"), headers={"User-Agent": "WaifuStudio-Irodori-Probe"})
            with urllib.request.urlopen(req_root, timeout=timeout) as response:
                return int(getattr(response, "status", 200)) < 500
        except urllib.error.HTTPError:
            return True
        except Exception:
            return False
    except Exception:
        return False


def detect_irodori(
    irodori_dir: Path | str | None = None,
    url: str | None = None,
    probe_fn: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Detecta el estado de Irodori opcional (directorio en disco + servicio HTTP localhost:8291).

    Reglas de estado:
    1. Si no existe tools/irodori:
       installed=False, status='absent', motivo claro indicando directorio ausente y puerto 8291.
    2. Si existe tools/irodori pero el servicio 8291 no responde:
       installed=False, status='offline', motivo claro indicando presencia de directorio pero servicio detenido.
    3. Si existe tools/irodori Y el servicio responde en 8291:
       installed=True, status='installed', servicio en línea.
    """
    target_dir = Path(irodori_dir) if irodori_dir is not None else get_irodori_dir()
    target_url = url or get_irodori_url()
    prober = probe_fn if probe_fn is not None else probe_irodori_service

    dir_exists = target_dir.exists() and target_dir.is_dir()

    if not dir_exists:
        return {
            "installed": False,
            "status": "absent",
            "directory": str(target_dir),
            "directory_exists": False,
            "service_url": target_url,
            "service_online": False,
            "reason": (
                f"Irodori TTS no disponible: directorio '{target_dir.name}' no encontrado en "
                f"{target_dir} (microservicio localhost:8291 ausente)."
            ),
        }

    is_online = prober(target_url)

    if not is_online:
        return {
            "installed": False,
            "status": "offline",
            "directory": str(target_dir),
            "directory_exists": True,
            "service_url": target_url,
            "service_online": False,
            "reason": (
                f"Irodori TTS no disponible: el directorio '{target_dir.name}' está presente pero "
                f"el microservicio en {target_url} (localhost:8291) está detenido o no responde."
            ),
        }

    return {
        "installed": True,
        "status": "installed",
        "directory": str(target_dir),
        "directory_exists": True,
        "service_url": target_url,
        "service_online": True,
        "reason": f"Irodori microservicio listo y conectado en {target_url}.",
    }
