"""
Carpetas, notas y responsable (RF-040) y exportación a CSV (RF-041, ASR-15; Tabla 61).
Sin PostgreSQL: SQLite en memoria con las mismas sesiones que en producción.
"""
import csv
import io
import time
from dataclasses import replace
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.api.middleware.auth as auth_mod
from src.api.modules.results.exportacion import generar_csv
from src.shared.config import Configuracion
from src.shared.gestion_repo import (
    CarpetaDuplicadaError, CarpetaNoEncontradaError, NotaNoEncontradaError, RepositorioGestion,
    ResponsableInvalidoError,
)
from src.shared.models import (
    Carpeta, CarpetaOportunidad, Licitacion, NotaOportunidad, NovedadProceso, Notificacion, Oportunidad,
    SeguimientoProceso, TareaAnalisis, Usuario,
)
from src.shared.notificaciones_repo import RepositorioNotificaciones
from src.shared.oportunidades_repo import RepositorioOportunidades
from src.shared.roles import ADMINISTRADOR, ANALISTA, GERENTE

TABLAS = [Licitacion, TareaAnalisis, Oportunidad, SeguimientoProceso, NovedadProceso, Carpeta,
          CarpetaOportunidad, NotaOportunidad, Usuario, Notificacion]


def proceso(id_proceso, **campos):
    return {"id_proceso": id_proceso, "entidad": "Alcaldía de Medellín", "nombre": "Plataforma",
            "objeto": "Desarrollo de software documental", "modalidad": "Licitación pública",
            "departamento": "Antioquia", "precio_base": 850_000_000.0, "estado": "Publicado",
            "fecha_publicacion": datetime(2026, 10, 20), "fecha_cierre": datetime(2026, 11, 5),
            "url_proceso": f"https://secop/{id_proceso}", **campos}


@pytest.fixture
def fabrica():
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for tabla in TABLAS:
        tabla.__table__.create(motor)
    fabrica = sessionmaker(bind=motor)
    RepositorioOportunidades(fabrica).guardar_lote(
        [proceso("CO1.REQ.1"), proceso("CO1.REQ.2", objeto="=HYPERLINK(\"http://x\")", departamento="Bogotá D.C."),
         proceso("CO1.REQ.3", objeto="Mesa de ayuda", precio_base=None)], "SECOP II · Datos Abiertos (p6dx-8zbt)")
    return fabrica


def _usuarios(fabrica):
    with fabrica() as db:
        for email, rol, activo in [("ana@x.co", ANALISTA, True), ("beto@x.co", ANALISTA, False),
                                   ("gema@x.co", GERENTE, True)]:
            db.add(Usuario(email=email, nombre=email.split("@")[0], rol=rol, password_hash="x", activo=activo))
        db.commit()


# --- Carpetas, notas y responsable (RF-040) ---

def test_cada_usuario_organiza_en_sus_propias_carpetas(fabrica):
    gestion, oportunidades = RepositorioGestion(fabrica), RepositorioOportunidades(fabrica)
    carpeta = gestion.crear_carpeta("ana@x.co", "Prioritarias")
    gestion.crear_carpeta("gema@x.co", "Prioritarias")  # el mismo nombre en otro usuario no choca
    with pytest.raises(CarpetaDuplicadaError):
        gestion.crear_carpeta("ana@x.co", "Prioritarias")
    assert gestion.agregar_a_carpeta(carpeta["id"], "ana@x.co", ["CO1.REQ.1", "CO1.REQ.2", "CO1.REQ.404"]) == 2
    assert gestion.agregar_a_carpeta(carpeta["id"], "ana@x.co", ["CO1.REQ.1"]) == 0
    with pytest.raises(CarpetaNoEncontradaError):
        gestion.agregar_a_carpeta(carpeta["id"], "gema@x.co", ["CO1.REQ.3"])  # carpeta ajena
    assert gestion.carpetas("ana@x.co")[0]["oportunidades"] == 2
    en_carpeta = oportunidades.buscar(usuario="ana@x.co", carpeta_id=carpeta["id"])["oportunidades"]
    assert {o["id_proceso"] for o in en_carpeta} == {"CO1.REQ.1", "CO1.REQ.2"}
    assert en_carpeta[0]["carpetas"] == [{"id": carpeta["id"], "nombre": "Prioritarias"}]
    assert oportunidades.obtener("CO1.REQ.1", "gema@x.co")["carpetas"] == []  # no ve las de ana
    gestion.quitar_de_carpeta(carpeta["id"], "ana@x.co", ["CO1.REQ.2"])
    gestion.renombrar_carpeta(carpeta["id"], "ana@x.co", "Para ofertar")
    gestion.eliminar_carpeta(carpeta["id"], "ana@x.co")
    assert [c["nombre"] for c in gestion.carpetas("ana@x.co")] == []
    assert oportunidades.obtener("CO1.REQ.1")  # borrar la carpeta no borra la oportunidad


def test_notas_con_autor_y_solo_el_autor_las_borra(fabrica):
    gestion = RepositorioGestion(fabrica)
    nota = gestion.agregar_nota("CO1.REQ.1", "ana@x.co", "  Pedir aclaración del anexo técnico  ")
    gestion.agregar_nota("CO1.REQ.1", "gema@x.co", "Revisar con jurídica")
    assert [n["autor"] for n in gestion.notas("CO1.REQ.1")] == ["gema@x.co", "ana@x.co"]
    assert nota["texto"] == "Pedir aclaración del anexo técnico"
    with pytest.raises(NotaNoEncontradaError):
        gestion.eliminar_nota(nota["id"], "CO1.REQ.1", "gema@x.co")
    gestion.eliminar_nota(nota["id"], "CO1.REQ.1", "ana@x.co")
    assert RepositorioOportunidades(fabrica).obtener("CO1.REQ.1")["notas"] == 1


def test_el_responsable_es_un_analista_activo(fabrica):
    gestion = RepositorioGestion(fabrica)
    # Sin usuarios locales (desarrollo u OIDC) no hay contra qué validar.
    assert gestion.asignar_responsable("CO1.REQ.1", "quien@x.co") == {"antes": None, "despues": "quien@x.co"}
    _usuarios(fabrica)
    assert [a["email"] for a in gestion.analistas()] == ["ana@x.co"]
    for invalido in ("gema@x.co", "beto@x.co", "nadie@x.co"):
        with pytest.raises(ResponsableInvalidoError):
            gestion.asignar_responsable("CO1.REQ.1", invalido)
    assert gestion.asignar_responsable("CO1.REQ.1", "ana@x.co") == {"antes": "quien@x.co", "despues": "ana@x.co"}
    assert gestion.asignar_responsable("CO1.REQ.1", None)["despues"] is None


# --- CSV (RF-041) ---

def _leer(contenido: bytes):
    assert contenido.startswith("﻿".encode("utf-8"))  # Excel reconoce UTF-8
    return list(csv.reader(io.StringIO(contenido.decode("utf-8-sig")), delimiter=";"))


def test_el_csv_trae_las_columnas_visibles_y_neutraliza_formulas(fabrica):
    oportunidades = RepositorioOportunidades(fabrica).buscar(usuario="ana@x.co")["oportunidades"]
    filas = _leer(generar_csv(oportunidades))
    encabezado = filas[0]
    assert encabezado[:4] == ["ID del proceso", "Referencia", "Entidad", "Objeto"]
    por_id = {f[0]: dict(zip(encabezado, f)) for f in filas[1:]}
    assert por_id["CO1.REQ.1"]["Cuantía (COP)"] == "850000000"
    assert por_id["CO1.REQ.1"]["Fecha de cierre"] == "2026-11-05"
    assert por_id["CO1.REQ.2"]["Objeto"].startswith("'=HYPERLINK")  # no se ejecuta al abrir
    assert por_id["CO1.REQ.3"]["Cuantía (COP)"] == "" and por_id["CO1.REQ.3"]["La sigo"] == "No"


# --- API (Tabla 61) ---

USUARIOS = {
    "tok-ana": {"user_id": "2", "email": "ana@x.co", "rol": ANALISTA, "roles": [ANALISTA]},
    "tok-gerente": {"user_id": "3", "email": "gema@x.co", "rol": GERENTE, "roles": [GERENTE]},
    "tok-admin": {"user_id": "1", "email": "admin@x.co", "rol": ADMINISTRADOR, "roles": [ADMINISTRADOR]},
}


@pytest.fixture
def cliente(fabrica, monkeypatch):
    from src.api.main import app
    from src.api.modules.opportunities import router as modulo_oportunidades
    from src.api.modules.results import gestion as modulo_gestion

    config = replace(Configuracion(), auth_mode="local")
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)
    monkeypatch.setattr(auth_mod, "_validar_local", lambda token, tocar=True: USUARIOS[token])
    monkeypatch.setattr(modulo_gestion, "_enviar_correos", lambda: None)
    eventos = []

    class Auditoria:
        def registrar_evento(self, tarea, evento, detalles, **kwargs):
            eventos.append((evento, detalles, kwargs.get("registrado_por")))

    notificaciones = RepositorioNotificaciones(fabrica)
    app.dependency_overrides[modulo_oportunidades.obtener_oportunidades] = lambda: RepositorioOportunidades(fabrica)
    app.dependency_overrides[modulo_oportunidades.obtener_auditoria] = Auditoria
    app.dependency_overrides[modulo_gestion.obtener_gestion] = lambda: RepositorioGestion(fabrica)
    app.dependency_overrides[modulo_gestion.obtener_notificaciones] = lambda: notificaciones
    yield TestClient(app), eventos, notificaciones
    app.dependency_overrides.clear()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_carpetas_segun_la_tabla_61(cliente):
    c, *_ = cliente
    assert c.post("/carpetas/", json={"nombre": "Revisar"}, headers=_h("tok-admin")).status_code == 403
    carpeta = c.post("/carpetas/", json={"nombre": "  Revisar  "}, headers=_h("tok-gerente")).json()
    assert carpeta["nombre"] == "Revisar"
    assert c.post("/carpetas/", json={"nombre": "Revisar"}, headers=_h("tok-gerente")).status_code == 409
    assert c.post(f"/carpetas/{carpeta['id']}/oportunidades", json={"ids": ["CO1.REQ.1"]},
                  headers=_h("tok-gerente")).json() == {"agregadas": 1}
    assert c.post(f"/carpetas/{carpeta['id']}/oportunidades", json={"ids": ["CO1.REQ.2"]},
                  headers=_h("tok-ana")).status_code == 404  # carpeta ajena
    assert c.get("/carpetas/", headers=_h("tok-ana")).json() == []
    assert c.delete(f"/carpetas/{carpeta['id']}", headers=_h("tok-gerente")).status_code == 403  # sin B
    propia = c.post("/carpetas/", json={"nombre": "Mías"}, headers=_h("tok-ana")).json()
    assert c.delete(f"/carpetas/{propia['id']}", headers=_h("tok-ana")).status_code == 204


def test_api_notas_y_responsable(cliente):
    c, eventos, notificaciones = cliente
    assert c.post("/oportunidades/CO1.REQ.1/notas", json={"texto": "Llamar a la entidad"},
                  headers=_h("tok-admin")).status_code == 403
    nota = c.post("/oportunidades/CO1.REQ.1/notas", json={"texto": "Llamar a la entidad"}, headers=_h("tok-gerente"))
    assert nota.status_code == 201 and nota.json()["autor"] == "gema@x.co"
    assert c.post("/oportunidades/CO1.REQ.404/notas", json={"texto": "x"}, headers=_h("tok-ana")).status_code == 404
    assert len(c.get("/oportunidades/CO1.REQ.1/notas", headers=_h("tok-admin")).json()) == 1
    assert c.delete(f"/oportunidades/CO1.REQ.1/notas/{nota.json()['id']}", headers=_h("tok-ana")).status_code == 404

    assert c.put("/oportunidades/CO1.REQ.1/responsable", json={"responsable": "ana@x.co"},
                 headers=_h("tok-admin")).status_code == 403
    r = c.put("/oportunidades/CO1.REQ.1/responsable", json={"responsable": "Ana@x.co"}, headers=_h("tok-gerente"))
    assert r.status_code == 200 and r.json()["responsable"] == "ana@x.co"
    evento, detalles, autor = eventos[-1]
    assert (evento, autor) == ("RESPONSABLE_ASIGNADO", "gema@x.co")
    assert detalles["cambios"]["responsable"] == {"antes": None, "despues": "ana@x.co"}
    aviso = notificaciones.listar("ana@x.co")["notificaciones"][0]
    assert aviso["tipo"] == "Oportunidad asignada" and "Asignada por gema@x.co" in aviso["cuerpo"]


def test_api_exportacion_respeta_filtros_seleccion_y_carpetas(cliente):
    c, eventos, _ = cliente
    carpeta = c.post("/carpetas/", json={"nombre": "Ofertar"}, headers=_h("tok-ana")).json()
    c.post(f"/carpetas/{carpeta['id']}/oportunidades", json={"ids": ["CO1.REQ.1", "CO1.REQ.3"]}, headers=_h("tok-ana"))

    todas = c.get("/resultados/oportunidades.csv", headers=_h("tok-admin"))
    assert todas.status_code == 200 and todas.headers["content-type"].startswith("text/csv")
    assert "attachment" in todas.headers["content-disposition"] and todas.headers["x-registros-exportados"] == "3"
    filtradas = _leer(c.get("/resultados/oportunidades.csv", params={"departamento": "Antioquia", "cuantia_min": 1},
                            headers=_h("tok-ana")).content)
    assert [f[0] for f in filtradas[1:]] == ["CO1.REQ.1"]
    seleccion = _leer(c.get("/resultados/oportunidades.csv", params={"ids": ["CO1.REQ.2", "CO1.REQ.3"]},
                            headers=_h("tok-ana")).content)
    assert sorted(f[0] for f in seleccion[1:]) == ["CO1.REQ.2", "CO1.REQ.3"]
    de_carpeta = _leer(c.get("/resultados/oportunidades.csv", params={"carpeta_id": carpeta["id"]},
                             headers=_h("tok-ana")).content)
    columna = de_carpeta[0].index("Mis carpetas")
    assert {f[0]: f[columna] for f in de_carpeta[1:]} == {"CO1.REQ.1": "Ofertar", "CO1.REQ.3": "Ofertar"}
    # Permisos: la carpeta de otro usuario no se exporta y sus nombres no aparecen.
    assert c.get("/resultados/oportunidades.csv", params={"carpeta_id": carpeta["id"]},
                 headers=_h("tok-gerente")).status_code == 404
    del_gerente = _leer(c.get("/resultados/oportunidades.csv", headers=_h("tok-gerente")).content)
    assert all(f[columna] == "" for f in del_gerente[1:])
    evento, detalles, autor = eventos[-1]
    assert (evento, autor, detalles["registros"]) == ("EXPORTACION_CSV", "gema@x.co", 3)


def test_asr15_cien_registros_en_menos_de_dos_segundos(cliente, fabrica):
    c, *_ = cliente
    RepositorioOportunidades(fabrica).guardar_lote([proceso(f"CO1.REQ.{1000 + i}") for i in range(100)], "SECOP II")
    inicio = time.perf_counter()
    r = c.get("/resultados/oportunidades.csv", params={"q": "software"}, headers=_h("tok-ana"))
    duracion = time.perf_counter() - inicio
    assert r.headers["x-registros-exportados"] == "101" and len(_leer(r.content)) == 102
    assert duracion < 2.0, f"La exportación tardó {duracion:.2f} s"
