"""
Notificaciones (RF-016, RF-017, RF-020; HU-04 CA-01 a CA-03; Tabla 16; Tabla 61).
Sin PostgreSQL (SQLite en memoria) y con un servidor SMTP mínimo en un hilo local.
"""
import socketserver
import threading
from dataclasses import replace
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.api.middleware.auth as auth_mod
from src.shared.config import Configuracion
from src.shared.models import (
    Carpeta, CarpetaOportunidad, CoincidenciaPerfil, Licitacion, NotaOportunidad, NovedadProceso, Notificacion, Oportunidad, PerfilBusqueda,
    PreferenciaNotificacion, SeguimientoProceso, TareaAnalisis,
)
from src.shared.notificaciones_repo import Canal, Frecuencia, RepositorioNotificaciones, TipoNotificacion
from src.shared.oportunidades_repo import RepositorioOportunidades
from src.shared.perfiles_repo import RepositorioPerfiles
from src.shared.roles import ADMINISTRADOR, ANALISTA, GERENTE
from src.worker_vigilance.notificador import AvisosAnalisis, EnviadorCorreo, Notificador

TABLAS = [Licitacion, TareaAnalisis, Oportunidad, SeguimientoProceso, NovedadProceso, PerfilBusqueda,
          CoincidenciaPerfil, Notificacion, PreferenciaNotificacion, Carpeta, CarpetaOportunidad, NotaOportunidad]
CONFIG = replace(Configuracion(), smtp_host="127.0.0.1", smtp_remitente="licita@fabrica.co",
                 notificaciones_hora_resumen=7, notificaciones_utc_offset=-5, notificaciones_max_intentos=3,
                 webui_url="http://licita.local")


def proceso(id_proceso="CO1.REQ.1", **campos):
    return {"id_proceso": id_proceso, "entidad": "Alcaldía de Medellín", "nombre": "Plataforma",
            "objeto": "Desarrollo de software de gestión documental", "precio_base": 850_000_000.0,
            "fecha_cierre": datetime(2026, 11, 5), "estado": "Publicado", "url_proceso": "https://secop/1", **campos}


@pytest.fixture
def fabrica():
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for tabla in TABLAS:
        tabla.__table__.create(motor)
    # Igual que en producción (SessionLocal): los objetos expiran al confirmar.
    return sessionmaker(bind=motor)


class EnviadorFalso:
    configurado = True

    def __init__(self, falla=None):
        self.enviados, self.falla = [], falla

    def enviar(self, destinatario, asunto, texto):
        if self.falla:
            raise self.falla
        self.enviados.append((destinatario, asunto, texto))


# --- Generación de avisos (RF-017, RF-020) ---

def test_una_oportunidad_se_avisa_una_vez_con_proceso_entidad_y_cierre(fabrica):
    RepositorioOportunidades(fabrica).guardar_lote([proceso()], "SECOP II")
    perfiles = RepositorioPerfiles(fabrica)
    a = perfiles.crear("ana@x.co", {"nombre": "Software", "palabras_clave": ["software"]})
    b = perfiles.crear("ana@x.co", {"nombre": "Documental", "palabras_clave": ["documental"]})
    nuevas = perfiles.registrar_coincidencias([(a["id"], "CO1.REQ.1"), (b["id"], "CO1.REQ.1")])
    repo = RepositorioNotificaciones(fabrica)

    avisos = repo.generar_por_coincidencias(nuevas)
    assert len(avisos) == 1  # dos perfiles, un solo aviso al mismo destinatario
    aviso = avisos[0]
    assert aviso["tipo"] == TipoNotificacion.OPORTUNIDAD and aviso["destinatario"] == "ana@x.co"
    assert "CO1.REQ.1" in aviso["titulo"] and "Entidad: Alcaldía de Medellín" in aviso["cuerpo"]
    assert "Cierre: 2026-11-05" in aviso["cuerpo"] and "Documental, Software" in aviso["cuerpo"]
    assert repo.generar_por_coincidencias(nuevas) == []  # HU-04 CA-02
    assert all(c["notificada_en"] for c in perfiles.coincidencias("ana@x.co"))


def test_cada_novedad_llega_a_quienes_siguen_el_proceso(fabrica):
    oportunidades = RepositorioOportunidades(fabrica)
    oportunidades.guardar_lote([proceso()], "SECOP II")
    oportunidades.seguir("CO1.REQ.1", "ana@x.co")
    oportunidades.seguir("CO1.REQ.1", "beto@x.co")
    oportunidades.seguir("CO1.REQ.1", "carla@x.co")
    oportunidades.dejar_de_seguir("CO1.REQ.1", "carla@x.co")
    novedades = oportunidades.guardar_lote([proceso(estado="Cerrado")], "SECOP II")["novedades"]
    repo = RepositorioNotificaciones(fabrica)

    avisos = repo.generar_por_novedades(novedades)
    assert sorted(a["destinatario"] for a in avisos) == ["ana@x.co", "beto@x.co"]
    assert "Estado del procedimiento: Publicado → Cerrado" in avisos[0]["cuerpo"]
    assert repo.generar_por_novedades(novedades) == []
    assert repo.listar("ana@x.co")["no_leidas"] == 1


# --- Envío por correo (RF-016, Tabla 16) ---

def _avisos(repo, destinatario="ana@x.co", n=2):
    for i in range(n):
        repo.crear(destinatario, TipoNotificacion.OPORTUNIDAD, f"oportunidad:{i}", f"Oportunidad {i}",
                   f"Cuerpo {i}", enlace=f"https://secop/{i}")


def test_frecuencia_inmediata_envia_cada_aviso_una_vez(fabrica):
    repo = RepositorioNotificaciones(fabrica)
    _avisos(repo)
    enviador = EnviadorFalso()
    notificador = Notificador(repo, enviador, CONFIG)
    assert notificador.enviar_pendientes()["enviados"] == 2
    destinatario, asunto, texto = enviador.enviados[0]
    assert (destinatario, asunto) == ("ana@x.co", "Licita · Oportunidad 0")
    assert "https://secop/0" in texto and "http://licita.local" in texto
    assert notificador.enviar_pendientes()["enviados"] == 0
    assert all(n["enviada_en"] for n in repo.listar("ana@x.co")["notificaciones"])
    # Lo ya leído en la aplicación no se reenvía por correo.
    repo.crear("ana@x.co", TipoNotificacion.NOVEDAD, "novedad:7", "Novedad leída", "Cambio")
    repo.marcar_todas_leidas("ana@x.co")
    assert notificador.enviar_pendientes()["enviados"] == 0


def test_canal_solo_aplicacion_no_envia_correo(fabrica):
    repo = RepositorioNotificaciones(fabrica)
    repo.guardar_preferencias("ana@x.co", Canal.APLICACION, Frecuencia.INMEDIATA)
    _avisos(repo)
    enviador = EnviadorFalso()
    assert Notificador(repo, enviador, CONFIG).enviar_pendientes()["enviados"] == 0
    assert enviador.enviados == [] and repo.listar("ana@x.co")["no_leidas"] == 2


def test_resumen_diario_un_solo_envio_consolidado_al_dia(fabrica):
    repo = RepositorioNotificaciones(fabrica)
    repo.guardar_preferencias("ana@x.co", Canal.CORREO, Frecuencia.RESUMEN_DIARIO)
    _avisos(repo, n=3)
    enviador = EnviadorFalso()
    notificador = Notificador(repo, enviador, CONFIG)
    # 06:00 en Colombia (11:00 UTC): todavía no es la hora del resumen.
    assert notificador.enviar_pendientes(datetime(2026, 10, 25, 11, 0))["en_espera"] == 3
    # 08:00 en Colombia: un solo correo con los tres avisos (HU-04 CA-03).
    resultado = notificador.enviar_pendientes(datetime(2026, 10, 25, 13, 0))
    assert (resultado["resumenes"], resultado["enviados"], len(enviador.enviados)) == (1, 3, 1)
    asunto, texto = enviador.enviados[0][1:]
    assert asunto == "Licita · Resumen diario: 3 avisos" and all(f"Oportunidad {i}" in texto for i in range(3))
    # Un aviso nuevo el mismo día espera al resumen de mañana.
    repo.crear("ana@x.co", TipoNotificacion.NOVEDAD, "novedad:9", "Novedad", "Cambio de fecha")
    assert notificador.enviar_pendientes(datetime(2026, 10, 25, 20, 0))["en_espera"] == 1
    assert notificador.enviar_pendientes(datetime(2026, 10, 26, 12, 30))["resumenes"] == 1


def test_si_el_correo_falla_se_reintenta_y_el_aviso_queda_en_la_aplicacion(fabrica):
    repo = RepositorioNotificaciones(fabrica)
    _avisos(repo, n=1)
    notificador = Notificador(repo, EnviadorFalso(falla=ConnectionRefusedError("SMTP caído")), CONFIG)
    for _ in range(4):
        notificador.enviar_pendientes()
    aviso = repo.listar("ana@x.co")["notificaciones"][0]
    assert aviso["intentos"] == 3 and aviso["enviada_en"] is None  # máximo de intentos, sin insistir
    assert "SMTP caído" in aviso["ultimo_error"] and aviso["leida_en"] is None
    sin_smtp = Notificador(repo, EnviadorCorreo(replace(CONFIG, smtp_host="")), CONFIG)
    assert sin_smtp.enviar_pendientes() == {"correo_configurado": False, "enviados": 0, "fallidos": 0,
                                           "resumenes": 0, "en_espera": 0}


class _ServidorSMTP(socketserver.StreamRequestHandler):
    """Lo mínimo de SMTP para recibir un mensaje de smtplib, sin dependencias."""

    def handle(self):
        self.wfile.write(b"220 prueba\r\n")
        en_datos, lineas = False, []
        while True:
            linea = self.rfile.readline()
            if not linea:
                return
            if en_datos:
                if linea == b".\r\n":
                    self.server.mensajes.append(b"".join(lineas).decode("utf-8"))
                    en_datos, lineas = False, []
                    self.wfile.write(b"250 OK\r\n")
                else:
                    lineas.append(linea)
                continue
            orden = linea[:4].upper()
            if orden == b"DATA":
                en_datos = True
                self.wfile.write(b"354 terminar con .\r\n")
            elif orden == b"QUIT":
                self.wfile.write(b"221 adios\r\n")
                return
            else:
                self.wfile.write(b"250 OK\r\n")


def test_el_correo_sale_por_smtp():
    servidor = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _ServidorSMTP)
    servidor.mensajes = []
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        config = replace(CONFIG, smtp_puerto=servidor.server_address[1], smtp_seguridad="ninguna")
        EnviadorCorreo(config).enviar("ana@x.co", "Licita · Nueva oportunidad", "Alcaldía de Medellín\nCierre: 2026-11-05")
    finally:
        servidor.shutdown()
        servidor.server_close()
    mensaje = servidor.mensajes[0]
    assert "To: ana@x.co" in mensaje and "From: licita@fabrica.co" in mensaje and "Nueva oportunidad" in mensaje


# --- Avisos del análisis (revisión pendiente y suspensión) ---

def test_el_analisis_avisa_al_solicitante_y_al_responsable(fabrica):
    oportunidades = RepositorioOportunidades(fabrica)
    oportunidades.guardar_lote([proceso()], "SECOP II")
    oportunidades.asignar_responsable_si_falta("CO1.REQ.1", "beto@x.co")
    repo = RepositorioNotificaciones(fabrica)
    enviador = EnviadorFalso()
    avisos = AvisosAnalisis(repo, Notificador(repo, enviador, CONFIG))
    tarea = {"tarea_id": "t-123456789", "licitacion_id": "CO1.REQ.1", "solicitado_por": "gema@x.co"}

    avisos.avisar(tarea, "Esperando revisión")
    avisos.avisar(tarea, "Esperando revisión")  # la misma etapa no se avisa dos veces
    assert sorted(d for d, *_ in enviador.enviados) == ["beto@x.co", "gema@x.co"]
    assert repo.listar("beto@x.co")["notificaciones"][0]["tipo"] == TipoNotificacion.REVISION
    avisos.avisar(tarea, "Suspendida", "Cuota de tokens agotada.")
    assert "Cuota de tokens agotada." in repo.listar("gema@x.co")["notificaciones"][0]["cuerpo"]


# --- API (Tabla 61) ---

USUARIOS = {
    "tok-ana": {"user_id": "2", "email": "ana@x.co", "rol": ANALISTA, "roles": [ANALISTA]},
    "tok-gerente": {"user_id": "3", "email": "gema@x.co", "rol": GERENTE, "roles": [GERENTE]},
    "tok-admin": {"user_id": "1", "email": "admin@x.co", "rol": ADMINISTRADOR, "roles": [ADMINISTRADOR]},
}


@pytest.fixture
def cliente(fabrica, monkeypatch):
    from src.api.main import app
    from src.api.modules.notifications import router as modulo

    config = replace(Configuracion(), auth_mode="local")
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)
    monkeypatch.setattr(auth_mod, "_validar_local", lambda token, tocar=True: USUARIOS[token])
    repo = RepositorioNotificaciones(fabrica)
    app.dependency_overrides[modulo.obtener_notificaciones] = lambda: repo
    yield TestClient(app), repo
    app.dependency_overrides.clear()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_bandeja_propia_y_preferencias(cliente):
    c, repo = cliente
    _avisos(repo, "ana@x.co", 2)
    _avisos(repo, "gema@x.co", 1)
    bandeja = c.get("/notificaciones/", headers=_h("tok-ana")).json()
    assert bandeja["no_leidas"] == 2 and {n["destinatario"] for n in bandeja["notificaciones"]} == {"ana@x.co"}
    ajena = repo.listar("gema@x.co")["notificaciones"][0]["id"]
    assert c.post(f"/notificaciones/{ajena}/leida", headers=_h("tok-ana")).status_code == 404
    propia = bandeja["notificaciones"][0]["id"]
    assert c.post(f"/notificaciones/{propia}/leida", headers=_h("tok-ana")).status_code == 204
    assert c.post("/notificaciones/leidas", headers=_h("tok-ana")).json()["marcadas"] == 1
    assert c.get("/notificaciones/", params={"no_leidas": True}, headers=_h("tok-ana")).json()["notificaciones"] == []

    pref = c.get("/notificaciones/preferencias", headers=_h("tok-gerente")).json()
    assert pref["canal"] == Canal.CORREO and pref["frecuencia"] == Frecuencia.INMEDIATA and not pref["configurada"]
    cuerpo = {"canal": Canal.CORREO, "frecuencia": Frecuencia.RESUMEN_DIARIO}
    assert c.put("/notificaciones/preferencias", json=cuerpo, headers=_h("tok-gerente")).status_code == 403
    assert c.put("/notificaciones/preferencias", json=cuerpo, headers=_h("tok-ana")).json()["frecuencia"] == \
        Frecuencia.RESUMEN_DIARIO
    assert c.put("/notificaciones/preferencias", json={**cuerpo, "canal": "Paloma"},
                 headers=_h("tok-admin")).status_code == 422
