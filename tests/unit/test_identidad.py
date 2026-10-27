"""
Identidad: usuarios, roles y vigencia de sesiones (RF-001 a RF-007, RNF-010).

Usa SQLite en memoria con solo las tablas de identidad, así que no requiere
PostgreSQL. Cubre las cuatro causas de pérdida de vigencia de una sesión:
cierre por el usuario, inactividad, vencimiento y usuario deshabilitado.
"""
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.api.middleware.auth as auth_mod
import src.api.modules.identity.servicio as servicio_mod
from src.api.main import app
from src.api.modules.analysis import router as modulo_router
from src.api.modules.identity.seguridad import ClaveDebilError, hash_clave, verificar_clave
from src.api.modules.identity.servicio import (
    CredencialesInvalidasError,
    CuentaBloqueadaError,
    OperacionNoPermitidaError,
    ServicioIdentidad,
    SesionInvalidaError,
)
from src.shared.config import Configuracion
from src.shared.models import Sesion, Usuario
from src.shared.roles import ADMINISTRADOR, ANALISTA, GERENTE, Permiso, permisos_de

# conftest.py desactiva la auditoría de los 403; la prueba que la verifica usa la real.
_AUDITAR_RECHAZO = auth_mod.auditar_rechazo

CLAVE = "Prueba1234"


@pytest.fixture
def config():
    return replace(
        Configuracion(),
        auth_mode="local",
        sesion_secreto="s" * 48,
        sesion_inactividad_min=30,
        sesion_duracion_min=480,
        login_max_intentos=3,
        login_bloqueo_min=5,
    )


@pytest.fixture
def fabrica():
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Usuario.__table__.create(motor)
    Sesion.__table__.create(motor)
    return sessionmaker(bind=motor, expire_on_commit=False)


@pytest.fixture
def auditoria():
    class AuditoriaFalsa:
        def __init__(self):
            self.eventos = []

        def registrar_evento(self, tarea_id, tipo_evento, detalles, registrado_por=None, **kwargs):
            self.eventos.append((tipo_evento, detalles, registrado_por))
    return AuditoriaFalsa()


@pytest.fixture
def servicio(config, fabrica, auditoria):
    servicio_mod._intentos._fallos.clear()
    s = ServicioIdentidad(config, fabrica, auditoria=auditoria)
    s.crear_usuario("Admin", "admin@x.co", ADMINISTRADOR, CLAVE)
    s.crear_usuario("Ana", "ana@x.co", ANALISTA, CLAVE)
    s.crear_usuario("Gema", "gema@x.co", GERENTE, CLAVE)
    return s


def _id(fabrica, email):
    with fabrica() as db:
        return db.query(Usuario).filter_by(email=email).one().id


def _sesion(fabrica, token_info, servicio):
    perfil = servicio.validar(token_info["access_token"], tocar=False)
    return perfil["sesion_id"]


# --- Contraseñas ---

def test_hash_de_clave_verifica_y_no_guarda_texto_plano():
    h = hash_clave(CLAVE, iteraciones=1000)
    assert CLAVE not in h
    assert verificar_clave(CLAVE, h)
    assert not verificar_clave("otra1234", h)


@pytest.mark.parametrize("clave", ["corta1", "sinnumeros", "12345678"])
def test_clave_debil_rechazada(servicio, clave):
    with pytest.raises(ClaveDebilError):
        servicio.crear_usuario("X", "x@x.co", ANALISTA, clave)


# --- Inicio de sesión (RF-005) ---

def test_login_correcto_devuelve_token_y_permisos(servicio):
    datos = servicio.iniciar_sesion("ANA@x.co ", CLAVE)
    assert datos["access_token"]
    assert datos["usuario"]["rol"] == ANALISTA
    assert Permiso.REQUISITOS_APROBAR in datos["usuario"]["permisos"]


@pytest.mark.parametrize("email,clave", [("ana@x.co", "Mala12345"), ("nadie@x.co", CLAVE)])
def test_credenciales_invalidas(servicio, email, clave):
    with pytest.raises(CredencialesInvalidasError):
        servicio.iniciar_sesion(email, clave)


def test_bloqueo_tras_intentos_fallidos(servicio):
    for _ in range(3):
        with pytest.raises(CredencialesInvalidasError):
            servicio.iniciar_sesion("ana@x.co", "Mala12345")
    with pytest.raises(CuentaBloqueadaError):
        servicio.iniciar_sesion("ana@x.co", CLAVE)


# --- Pérdida de vigencia (RF-006, RF-007, RF-004, RNF-010) ---

def test_cierre_de_sesion_invalida_el_token(servicio):
    datos = servicio.iniciar_sesion("ana@x.co", CLAVE)
    servicio.cerrar_sesion(_sesion(None, datos, servicio))
    with pytest.raises(SesionInvalidaError, match="cerrada"):
        servicio.validar(datos["access_token"])


def test_expira_por_inactividad(servicio, fabrica):
    datos = servicio.iniciar_sesion("ana@x.co", CLAVE)
    sesion_id = _sesion(fabrica, datos, servicio)
    with fabrica() as db:
        sesion = db.get(Sesion, sesion_id)
        sesion.ultimo_uso -= timedelta(minutes=31)
        db.commit()
    with pytest.raises(SesionInvalidaError, match="inactividad"):
        servicio.validar(datos["access_token"])
    # Una vez cerrada, sigue cerrada aunque se vuelva a intentar.
    with pytest.raises(SesionInvalidaError):
        servicio.validar(datos["access_token"])


def test_actividad_reciente_mantiene_la_sesion(servicio, fabrica):
    datos = servicio.iniciar_sesion("ana@x.co", CLAVE)
    sesion_id = _sesion(fabrica, datos, servicio)
    with fabrica() as db:
        db.get(Sesion, sesion_id).ultimo_uso -= timedelta(minutes=29)
        db.commit()
    servicio.validar(datos["access_token"])  # cuenta como actividad
    with fabrica() as db:
        assert servicio_mod.seguridad.ahora() - db.get(Sesion, sesion_id).ultimo_uso < timedelta(minutes=1)


def test_consulta_automatica_no_renueva_la_inactividad(servicio, fabrica):
    datos = servicio.iniciar_sesion("ana@x.co", CLAVE)
    sesion_id = _sesion(fabrica, datos, servicio)
    with fabrica() as db:
        db.get(Sesion, sesion_id).ultimo_uso -= timedelta(minutes=29)
        db.commit()
    servicio.validar(datos["access_token"], tocar=False)
    with fabrica() as db:
        assert servicio_mod.seguridad.ahora() - db.get(Sesion, sesion_id).ultimo_uso > timedelta(minutes=28)


def test_vencimiento_absoluto(servicio, fabrica):
    datos = servicio.iniciar_sesion("ana@x.co", CLAVE)
    sesion_id = _sesion(fabrica, datos, servicio)
    with fabrica() as db:
        db.get(Sesion, sesion_id).expira_en = servicio_mod.seguridad.ahora() - timedelta(seconds=1)
        db.commit()
    with pytest.raises(SesionInvalidaError, match="expiró"):
        servicio.validar(datos["access_token"])


def test_deshabilitar_usuario_corta_su_sesion_abierta(servicio, fabrica):
    datos = servicio.iniciar_sesion("ana@x.co", CLAVE)
    servicio.actualizar_usuario(_id(fabrica, "ana@x.co"), actor_id=None, activo=False)
    with pytest.raises(SesionInvalidaError, match="deshabilitado"):
        servicio.validar(datos["access_token"])
    with pytest.raises(CredencialesInvalidasError, match="deshabilitado"):
        servicio.iniciar_sesion("ana@x.co", CLAVE)


def test_token_firmado_con_otra_clave_es_rechazado(servicio, config, fabrica):
    otro = ServicioIdentidad(replace(config, sesion_secreto="z" * 48), fabrica)
    datos = otro.iniciar_sesion("ana@x.co", CLAVE)
    with pytest.raises(SesionInvalidaError):
        servicio.validar(datos["access_token"])


def test_cambio_de_clave_cierra_sesiones(servicio, fabrica):
    datos = servicio.iniciar_sesion("ana@x.co", CLAVE)
    servicio.cambiar_clave(_id(fabrica, "ana@x.co"), "Nueva12345")
    with pytest.raises(SesionInvalidaError):
        servicio.validar(datos["access_token"])
    assert servicio.iniciar_sesion("ana@x.co", "Nueva12345")["access_token"]


# --- Administración de usuarios (RF-001 a RF-004) ---

def test_no_se_puede_quedar_sin_administradores(servicio, fabrica):
    admin_id = _id(fabrica, "admin@x.co")
    with pytest.raises(OperacionNoPermitidaError):
        servicio.actualizar_usuario(admin_id, actor_id=str(admin_id), activo=False)
    with pytest.raises(OperacionNoPermitidaError):
        servicio.actualizar_usuario(admin_id, actor_id=None, rol=ANALISTA)


def test_correo_duplicado_y_rol_invalido(servicio):
    with pytest.raises(OperacionNoPermitidaError):
        servicio.crear_usuario("Otra", "ANA@x.co", ANALISTA, CLAVE)
    with pytest.raises(OperacionNoPermitidaError):
        servicio.crear_usuario("Otra", "otra@x.co", "Superusuario", CLAVE)


# Matriz esperada según la Tabla 61 del documento de trabajo de grado. Si el documento cambia,
# esta tabla cambia con él: así la prueba detecta cualquier desvío del código.
P = Permiso
MATRIZ_TABLA_61 = {
    P.PORTAFOLIO_VER:       {ANALISTA, GERENTE, ADMINISTRADOR},
    P.PORTAFOLIO_GESTIONAR: {ANALISTA},                   # agregar y borrar (A, B)
    P.PORTAFOLIO_EDITAR:    {ANALISTA, ADMINISTRADOR},    # editar (E)
    P.VIGILANCIA_VER:       {ANALISTA, GERENTE, ADMINISTRADOR},
    P.VIGILANCIA_GESTIONAR: {ANALISTA},
    P.ANALISIS_SOLICITAR:   {ANALISTA, GERENTE},          # "el gerente puede solicitar, no aprobar"
    P.ANALISIS_VER:         {ANALISTA, GERENTE, ADMINISTRADOR},
    P.REQUISITOS_APROBAR:   {ANALISTA},
    P.RESULTADOS_VER:       {ANALISTA, GERENTE, ADMINISTRADOR},
    P.DECISION_REGISTRAR:   {GERENTE},                    # "solo el gerente registra la decisión"
    P.USUARIOS_GESTIONAR:   {ADMINISTRADOR},
    P.DIAGNOSTICO_VER:      {ADMINISTRADOR},              # telemetría y tableros técnicos
    P.REGLAS_VER:           {ANALISTA, GERENTE, ADMINISTRADOR},
    P.REGLAS_PROPONER:      {ADMINISTRADOR},              # doble control: propone el administrador
    P.REGLAS_CONFIRMAR:     {GERENTE},                    # y confirma la gerencia comercial
    P.CUOTA_AMPLIAR:        {ADMINISTRADOR},              # RN-10: responsable autorizado de la cuota
    P.BITACORA_VER:         {GERENTE, ADMINISTRADOR},     # el analista no la consulta
    P.PERFILES_VER:         {ANALISTA, GERENTE, ADMINISTRADOR},  # perfiles: A C,E,A,B; G C; Adm C,E
    P.PERFILES_EDITAR:      {ANALISTA, ADMINISTRADOR},
    P.PERFILES_GESTIONAR:   {ANALISTA},
    P.EXPEDIENTE_VER:       {ANALISTA, ADMINISTRADOR},    # carga manual: A C,E,A; G —; Adm C
    P.EXPEDIENTE_CARGAR:    {ANALISTA},
    P.NOTIFICACIONES_VER:   {ANALISTA, GERENTE, ADMINISTRADOR},  # misma fila que los perfiles
    P.NOTIFICACIONES_CONFIGURAR: {ANALISTA, ADMINISTRADOR},
    P.ORGANIZACION_VER:     {ANALISTA, GERENTE, ADMINISTRADOR},  # carpetas y exportación
    P.ORGANIZACION_EDITAR:  {ANALISTA, GERENTE},
    P.ORGANIZACION_BORRAR:  {ANALISTA},
}


def test_cada_permiso_tiene_fila_en_la_matriz_esperada():
    from src.shared.roles import TODOS
    assert set(MATRIZ_TABLA_61) == set(TODOS)


@pytest.mark.parametrize("permiso", sorted(MATRIZ_TABLA_61))
def test_matriz_de_roles_sigue_la_tabla_61(permiso):
    concedido = {rol for rol in (ANALISTA, GERENTE, ADMINISTRADOR) if permiso in permisos_de([rol])}
    assert concedido == MATRIZ_TABLA_61[permiso]


def test_el_administrador_no_revisa_ni_decide():
    """Segregación de funciones (Tabla 27): administrar usuarios no da acceso al negocio."""
    admin = permisos_de([ADMINISTRADOR])
    assert not admin & {P.REQUISITOS_APROBAR, P.DECISION_REGISTRAR, P.ANALISIS_SOLICITAR}


def test_rol_desconocido_no_concede_nada():
    assert permisos_de(["Rol inventado"]) == frozenset()


def test_pantalla_inicial_por_rol():
    from src.shared.roles import PANTALLA_INICIAL
    assert PANTALLA_INICIAL == {ANALISTA: "Portafolio", GERENTE: "Resultados", ADMINISTRADOR: "Usuarios"}


# --- Integración con la API ---

class RepositorioFalso:
    def obtener(self, tarea_id):
        return {"tarea_id": tarea_id, "estado": "Recibida"}

    def listar(self, estado=None):
        return []

    def crear(self, tarea_id, licitacion_id, solicitado_por, **versiones):
        pass

    def buscar_reutilizable(self, huella, reglas_version, portafolio_version):
        return None


class PublicadorFalso:
    def __init__(self):
        self.encolados = []

    def encolar_analisis(self, tarea_id, licitacion_url, contenido_pliego=None, **versiones):
        self.encolados.append(tarea_id)

    def encolar_reanudacion(self, tarea_id):
        self.encolados.append(tarea_id)


@pytest.fixture
def cliente(servicio, config, monkeypatch):
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)
    monkeypatch.setattr("src.api.modules.identity.router.obtener_configuracion", lambda: config)
    monkeypatch.setattr(servicio_mod, "_servicio", servicio)
    app.dependency_overrides[modulo_router.obtener_repositorio] = RepositorioFalso
    publicador = PublicadorFalso()
    app.dependency_overrides[modulo_router.obtener_publicador] = lambda: publicador
    app.dependency_overrides[modulo_router.obtener_versiones_vigentes] = lambda: (1, 1)
    app.dependency_overrides[modulo_router.verificar_cuota_disponible] = lambda: None
    app.dependency_overrides[modulo_router.obtener_expediente] = lambda: None
    app.dependency_overrides[servicio_mod.obtener_servicio_identidad] = lambda: servicio
    yield TestClient(app)
    app.dependency_overrides.clear()


def _login(cliente, email):
    r = cliente.post("/auth/login", json={"email": email, "password": CLAVE})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_api_login_y_logout(cliente):
    h = _login(cliente, "ana@x.co")
    assert cliente.get("/auth/yo", headers=h).json()["rol"] == ANALISTA
    assert cliente.post("/auth/logout", headers=h).status_code == 204
    assert cliente.get("/auth/yo", headers=h).status_code == 401


def test_api_rechaza_credenciales_invalidas(cliente):
    r = cliente.post("/auth/login", json={"email": "ana@x.co", "password": "Mala12345"})
    assert r.status_code == 401


def test_api_aplica_la_matriz_de_roles(cliente):
    gerente = _login(cliente, "gema@x.co")
    analista = _login(cliente, "ana@x.co")
    admin = _login(cliente, "admin@x.co")
    solicitud = {"licitacion_url": "CO1.REQ.1"}
    assert cliente.get("/analisis/t1/estado", headers=gerente).status_code == 200
    assert cliente.post("/analisis/", headers=gerente, json=solicitud).status_code == 202
    assert cliente.post("/analisis/", headers=analista, json=solicitud).status_code == 202
    assert cliente.post("/analisis/", headers=admin, json=solicitud).status_code == 403
    assert cliente.get("/analisis/t1/estado", headers=admin).status_code == 200  # consulta sí
    assert cliente.get("/usuarios/", headers=analista).status_code == 403
    assert cliente.get("/usuarios/", headers=gerente).status_code == 403
    assert cliente.get("/usuarios/", headers=admin).status_code == 200


def test_api_solo_el_analista_aprueba_requisitos(cliente):
    cuerpo = {"requisitos": [{"identificador": "REQ-001", "texto": "RUP vigente", "categoria": "juridico",
                              "condicion_habilitante_propuesta": True, "referencia_documental": "3.1"}]}
    for email in ("gema@x.co", "admin@x.co"):
        r = cliente.post("/analisis/t1/aprobacion", headers=_login(cliente, email), json=cuerpo)
        assert r.status_code == 403, email


def test_api_admin_deshabilita_y_la_sesion_abierta_cae(cliente, fabrica):
    analista = _login(cliente, "ana@x.co")
    admin = _login(cliente, "admin@x.co")
    r = cliente.patch(f"/usuarios/{_id(fabrica, 'ana@x.co')}", headers=admin, json={"activo": False})
    assert r.status_code == 200
    r = cliente.get("/analisis/t1/estado", headers=analista)
    assert r.status_code == 401
    assert "deshabilitado" in r.json()["detail"]


def test_api_el_acceso_denegado_queda_en_la_bitacora(cliente, monkeypatch):
    # HU-01 CA-03: el intento sin permiso se rechaza y deja constancia en la auditoría.
    eventos = []

    class BitacoraFalsa:
        def registrar_evento(self, tarea_id, evento, detalle, registrado_por=None):
            eventos.append((evento, detalle, registrado_por))

    monkeypatch.setattr("src.worker_analysis.reports.auditoria.RegistradorAuditoria", BitacoraFalsa)
    monkeypatch.setattr(auth_mod, "auditar_rechazo", _AUDITAR_RECHAZO)
    analista = _login(cliente, "ana@x.co")
    assert cliente.get("/usuarios/", headers=analista).status_code == 403
    assert len(eventos) == 1
    evento, detalle, autor = eventos[0]
    assert evento == "ACCESO_DENEGADO" and autor == "ana@x.co"
    assert detalle["metodo"] == "GET" and detalle["ruta"] == "/usuarios/" and detalle["rol"] == ANALISTA
