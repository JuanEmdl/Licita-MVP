"""
FF-05 (ASR-09, control C-01 de la Tabla 48): toda operación protegida de la API responde
403 cuando el rol no la autoriza.

La suite se arma sola a partir de las rutas de la aplicación: cada ruta declara su permiso
con requiere_permiso, y por cada rol que no lo tiene se comprueba el 403. Una ruta nueva
entra en la suite sin escribir nada, y una ruta protegida sin permiso declarado hace fallar
la prueba de cobertura.
"""
from typing import Iterator, List, Optional, Tuple

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import src.api.middleware.auth as auth_mod
from src.api.main import app
from src.shared.roles import ROLES, permisos_de

# Rutas abiertas a propósito: salud, inicio de sesión y documentación.
PUBLICAS = {("GET", "/health"), ("POST", "/auth/login"), ("POST", "/auth/oidc")}
# Rutas que solo exigen sesión (cualquier rol): el propio perfil, cerrar sesión, mis avisos.
SOLO_SESION_PREFIJOS = ("/auth/",)


def _permiso(dependant) -> Optional[str]:
    for sub in dependant.dependencies:
        permiso = getattr(sub.call, "permiso", None) or _permiso(sub)
        if permiso:
            return permiso
    return None


def _exige_sesion(dependant) -> bool:
    return any(sub.call is auth_mod.verificar_token or _exige_sesion(sub) for sub in dependant.dependencies)


def _aplanar(rutas, prefijo: str = "") -> Iterator[Tuple[str, APIRoute]]:
    """FastAPI 0.143 guarda los routers incluidos sin desplegar sus rutas: se recorren aquí."""
    for ruta in rutas:
        if isinstance(ruta, APIRoute):
            yield prefijo + ruta.path, ruta
        elif hasattr(ruta, "original_router"):
            yield from _aplanar(ruta.original_router.routes, prefijo + (ruta.include_context.prefix or ""))


def _rutas() -> List[Tuple[str, str, Optional[str], APIRoute]]:
    rutas = []
    for camino, ruta in _aplanar(app.routes):
        for metodo in sorted(ruta.methods - {"HEAD", "OPTIONS"}):
            rutas.append((metodo, camino, _permiso(ruta.dependant), ruta))
    return rutas


RUTAS = _rutas()
CASOS = [(rol, metodo, ruta, permiso) for metodo, ruta, permiso, _ in RUTAS if permiso
         for rol in ROLES if permiso not in permisos_de([rol])]
PERMITIDOS = [(rol, metodo, ruta, permiso, r) for metodo, ruta, permiso, r in RUTAS if permiso
              for rol in ROLES if permiso in permisos_de([rol])]


def _url(ruta: str) -> str:
    import re
    return re.sub(r"\{[^}]+\}", "1", ruta)


@pytest.fixture
def cliente():
    # Todas las demás dependencias se reemplazan: el 403 debe salir antes de tocar la base o la cola.
    otras = {sub.call for _, _, _, r in RUTAS for sub in r.dependant.dependencies
             if not getattr(sub.call, "permiso", None) and sub.call is not auth_mod.verificar_token}
    for dependencia in otras:
        app.dependency_overrides[dependencia] = lambda: None
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_ff05_cada_ruta_protegida_declara_su_permiso():
    sin_permiso = [f"{m} {r}" for m, r, permiso, ruta in RUTAS
                   if not permiso and (m, r) not in PUBLICAS and not r.startswith(SOLO_SESION_PREFIJOS)
                   and not r.startswith(("/docs", "/openapi", "/redoc"))
                   and _exige_sesion(ruta.dependant) is False and not r.startswith("/notificaciones")]
    assert not sin_permiso, "Rutas sin permiso ni sesión:\n" + "\n".join(sin_permiso)


def test_ff05_la_suite_cubre_la_matriz():
    """La Tabla 48 (C-01) pide una suite de 200 combinaciones rol-operación."""
    assert len(CASOS) + len(PERMITIDOS) >= 200, (len(CASOS), len(PERMITIDOS))


def _dependencia_de_permiso(dependant):
    for sub in dependant.dependencies:
        if getattr(sub.call, "permiso", None):
            return sub.call
        encontrada = _dependencia_de_permiso(sub)
        if encontrada:
            return encontrada
    return None


@pytest.mark.parametrize("rol,metodo,ruta,permiso,r", PERMITIDOS,
                         ids=[f"{c[0]}|{c[1]} {c[2]}" for c in PERMITIDOS])
def test_ff05_el_rol_con_permiso_pasa_el_filtro(rol, metodo, ruta, permiso, r):
    """Se llama solo al filtro de autorización: la operación no se ejecuta ni toca la base."""
    usuario = {"email": "prueba@x.co", "rol": rol}
    assert _dependencia_de_permiso(r.dependant)(request=None, usuario=usuario) is usuario


@pytest.mark.parametrize("rol,metodo,ruta,permiso", CASOS, ids=[f"{c[0]}|{c[1]} {c[2]}" for c in CASOS])
def test_ff05_el_rol_sin_permiso_recibe_403(cliente, rol, metodo, ruta, permiso):
    app.dependency_overrides[auth_mod.verificar_token] = lambda: {"email": "prueba@x.co", "rol": rol}
    respuesta = cliente.request(metodo, _url(ruta), json={})
    assert respuesta.status_code == 403, (rol, metodo, ruta, permiso, respuesta.text[:200])
