"""
Módulo de oportunidades (Figura 10): vigilancia automática de SECOP II, búsqueda y
filtros, radicación, seguimiento y novedades, perfiles de búsqueda y expediente
documental con carga manual (RF-011 a RF-022).

Tabla 61:
- Oportunidades y seguimiento: el analista consulta, edita y agrega; gerente y
  administrador consultan.
- Perfiles de búsqueda: cada usuario ve y modifica solo los suyos; el alcance se
  resuelve aquí, no en la interfaz.
- Expediente y carga manual: el analista sobre las oportunidades que tiene asignadas;
  el administrador consulta; el gerente no tiene acceso.
"""
import logging
import os
from datetime import date, datetime
from typing import List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

import src.api.middleware.auth as auth
from src.api.adapters.queue import PublicadorTrabajos
from src.api.middleware.auth import requiere_permiso
from src.api.modules.analysis.router import (
    AnalisisReutilizableError,
    _usuario,
    crear_tarea_analisis,
    obtener_expediente,
    obtener_publicador,
    obtener_repositorio,
    obtener_versiones_vigentes,
    verificar_cuota_disponible,
)
from src.shared.roles import Permiso, tiene_permiso
from src.shared.tareas_repo import RepositorioTareas
from src.worker_vigilance.servicio import (
    EstadoAlerta,
    FuenteNoDisponibleError,
    ProcesoNoEncontradoError,
    ServicioVigilancia,
    obtener_servicio_vigilancia,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vigilancia", tags=["Vigilancia de oportunidades"])
router_oportunidades = APIRouter(prefix="/oportunidades", tags=["Oportunidades y expediente"])
router_perfiles = APIRouter(prefix="/perfiles", tags=["Perfiles de búsqueda"])


def obtener_oportunidades():
    from src.shared.oportunidades_repo import RepositorioOportunidades
    return RepositorioOportunidades()


def obtener_perfiles():
    from src.shared.perfiles_repo import RepositorioPerfiles
    return RepositorioPerfiles()


def obtener_auditoria():
    from src.worker_analysis.reports.auditoria import RegistradorAuditoria
    return RegistradorAuditoria()


def _auditar(auditoria, referencia: str, evento: str, detalles: dict, usuario: dict) -> None:
    """RF-042: radicaciones y cargas de documentos quedan en la bitácora; si falla, no se pierde la operación."""
    try:
        auditoria.registrar_evento(referencia, evento, detalles, registrado_por=_usuario(usuario),
                                   licitacion_id=detalles.get("id_proceso"))
    except Exception as e:
        logger.error(f"No se pudo registrar {evento} en la bitácora: {type(e).__name__}")


# ---------------------------------------------------------------------------
# Vigilancia: alertas por afinidad con el portafolio
# ---------------------------------------------------------------------------

@router.get("/alertas")
def listar_alertas(
    estado: Optional[str] = None,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_VER)),
    servicio: ServicioVigilancia = Depends(obtener_servicio_vigilancia),
):
    return servicio.listar(estado=estado)


@router.get("/estado")
def estado_vigilancia(
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_VER)),
    servicio: ServicioVigilancia = Depends(obtener_servicio_vigilancia),
):
    config = servicio.config
    try:
        sincronizacion = servicio.estado_sincronizacion()
    except Exception as e:
        logger.warning(f"No se pudo leer el estado de la sincronización: {type(e).__name__}")
        sincronizacion = None
    return {
        "en_curso": servicio.en_curso,
        "ultimo_barrido": servicio.ultimo_barrido,
        # Persistida: incluye los barridos del trabajador programado (HU-04 CA-04).
        "sincronizacion": sincronizacion,
        "dias": config.vigilancia_dias,
        "umbral": config.vigilancia_umbral,
        "token_configurado": bool(config.socrata_app_token),
    }


@router.post("/barrido", status_code=status.HTTP_202_ACCEPTED)
def ejecutar_barrido(
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_GESTIONAR)),
    servicio: ServicioVigilancia = Depends(obtener_servicio_vigilancia),
):
    """Lanza un barrido de SECOP II en segundo plano; el avance se consulta en /vigilancia/estado."""
    if servicio.en_curso:
        return {"mensaje": "Ya hay un barrido en curso."}
    background_tasks.add_task(servicio.barrer)
    logger.info(f"Barrido de SECOP II solicitado por {_usuario(usuario)}.")
    return {"mensaje": "Barrido iniciado."}


@router.post("/alertas/{id_proceso}/descartar")
def descartar_alerta(
    id_proceso: str,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_GESTIONAR)),
    servicio: ServicioVigilancia = Depends(obtener_servicio_vigilancia),
):
    alerta = servicio.cambiar_estado(id_proceso, EstadoAlerta.DESCARTADA)
    if alerta is None:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    return alerta


@router.post("/alertas/{id_proceso}/analizar", status_code=status.HTTP_202_ACCEPTED)
def analizar_alerta(
    id_proceso: str,
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.ANALISIS_SOLICITAR)),
    servicio: ServicioVigilancia = Depends(obtener_servicio_vigilancia),
    repositorio: RepositorioTareas = Depends(obtener_repositorio),
    publicador: Optional[PublicadorTrabajos] = Depends(obtener_publicador),
    versiones: Tuple[Optional[int], Optional[int]] = Depends(obtener_versiones_vigentes),
    forzar_nuevo: bool = False,
    _cuota: None = Depends(verificar_cuota_disponible),
    expediente=Depends(obtener_expediente),
):
    """Solicita el análisis completo de una oportunidad detectada por la vigilancia."""
    if servicio.obtener(id_proceso) is None:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    try:
        tarea_id = crear_tarea_analisis(
            id_proceso, None, _usuario(usuario), background_tasks, repositorio, publicador,
            versiones, forzar_nuevo, expediente,
        )
    except AnalisisReutilizableError as e:
        raise e.como_http()
    servicio.cambiar_estado(id_proceso, EstadoAlerta.EN_ANALISIS, tarea_id=tarea_id)
    return {"tarea_id": tarea_id, "mensaje": "Análisis encolado."}


# ---------------------------------------------------------------------------
# Oportunidades: búsqueda, radicación, seguimiento y novedades
# ---------------------------------------------------------------------------

class SolicitudRadicacion(BaseModel):
    identificador: str = Field(..., min_length=3, max_length=300,
                               description="Enlace de SECOP II, ID del proceso (CO1.REQ…) o referencia.")


def _inicio_dia(valor: Optional[date]) -> Optional[datetime]:
    return datetime(valor.year, valor.month, valor.day) if valor else None


@router_oportunidades.get("/")
def buscar_oportunidades(
    q: Optional[str] = Query(None, max_length=200),
    entidad: Optional[str] = None,
    departamento: Optional[str] = None,
    ciudad: Optional[str] = None,
    modalidad: Optional[str] = None,
    estado: Optional[str] = None,
    cuantia_min: Optional[float] = None,
    cuantia_max: Optional[float] = None,
    publicada_desde: Optional[date] = None,
    publicada_hasta: Optional[date] = None,
    cierre_desde: Optional[date] = None,
    cierre_hasta: Optional[date] = None,
    seguidas: bool = False,
    con_novedades: bool = False,
    limite: int = 100,
    desplazamiento: int = 0,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_VER)),
    oportunidades=Depends(obtener_oportunidades),
    servicio: ServicioVigilancia = Depends(obtener_servicio_vigilancia),
):
    """RF-013 y RF-014: palabras clave sobre nombre y objeto, y filtros combinables."""
    if cuantia_min is not None and cuantia_max is not None and cuantia_min > cuantia_max:
        raise HTTPException(status_code=422, detail="La cuantía mínima no puede superar la máxima.")
    resultado = oportunidades.buscar(
        usuario=_usuario(usuario), q=q, entidad=entidad,
        departamento=departamento, ciudad=ciudad, modalidad=modalidad, estado=estado,
        cuantia_min=cuantia_min, cuantia_max=cuantia_max,
        publicada_desde=_inicio_dia(publicada_desde), publicada_hasta=_inicio_dia(publicada_hasta),
        cierre_desde=_inicio_dia(cierre_desde), cierre_hasta=_inicio_dia(cierre_hasta),
        solo_seguidas=seguidas, con_novedades=con_novedades, limite=limite, desplazamiento=desplazamiento)
    # HU-04 CA-04: con la fuente caída se ven los datos previos con su advertencia y su fecha.
    resultado["sincronizacion"] = servicio.estado_sincronizacion()
    return resultado


@router_oportunidades.get("/filtros")
def opciones_filtro(
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_VER)),
    oportunidades=Depends(obtener_oportunidades),
):
    return oportunidades.opciones_filtro()


@router_oportunidades.post("/", status_code=status.HTTP_201_CREATED)
def radicar_proceso(
    solicitud: SolicitudRadicacion,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_GESTIONAR)),
    servicio: ServicioVigilancia = Depends(obtener_servicio_vigilancia),
    auditoria=Depends(obtener_auditoria),
):
    """
    HU-02, RF-011: registra un proceso por su enlace, ID o referencia; recupera los
    metadatos y los documentos publicados e identifica los que no se pudieron obtener.
    No crea la tarea de análisis: el analista revisa el expediente y decide (HU-02 CA-02).
    """
    try:
        resultado = servicio.radicar(solicitud.identificador, _usuario(usuario))
    except ProcesoNoEncontradoError as e:
        # HU-02 CA-04: se rechaza, se informa la causa y no se crea ninguna tarea.
        raise HTTPException(status_code=404, detail=str(e))
    except FuenteNoDisponibleError as e:
        raise HTTPException(status_code=503, detail=f"{e} Intente más tarde o cargue los documentos a mano.")
    oportunidad = resultado["oportunidad"]
    _auditar(auditoria, f"oportunidad-{oportunidad['id_proceso']}", "PROCESO_RADICADO", {
        "id_proceso": oportunidad["id_proceso"], "fuente": oportunidad["fuente"],
        "documentos_nuevos": resultado["resumen"].get("nuevos", 0),
        "faltantes": len(resultado["expediente"]["faltantes"]),
        "ilegibles": len(resultado["expediente"]["ilegibles"]),
    }, usuario)
    return resultado


def _oportunidad(oportunidades, id_proceso: str, usuario: dict) -> dict:
    oportunidad = oportunidades.obtener(id_proceso, _usuario(usuario))
    if oportunidad is None:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
    return oportunidad


@router_oportunidades.get("/{id_proceso}")
def consultar_oportunidad(
    id_proceso: str,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_VER)),
    oportunidades=Depends(obtener_oportunidades),
):
    oportunidad = _oportunidad(oportunidades, id_proceso, usuario)
    return {**oportunidad, "novedades": oportunidades.novedades(id_proceso, _usuario(usuario))}


@router_oportunidades.put("/{id_proceso}/seguimiento")
def seguir_proceso(
    id_proceso: str,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_GESTIONAR)),
    oportunidades=Depends(obtener_oportunidades),
):
    """RF-018: el usuario recibe las novedades del proceso desde este momento."""
    from src.shared.oportunidades_repo import OportunidadNoEncontradaError
    try:
        # Quien sigue un proceso sin responsable queda a cargo de su expediente (Tabla 61).
        return oportunidades.seguir(id_proceso, _usuario(usuario),
                                    asignar_responsable=tiene_permiso(usuario, Permiso.EXPEDIENTE_CARGAR))
    except OportunidadNoEncontradaError:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada")


@router_oportunidades.delete("/{id_proceso}/seguimiento")
def dejar_de_seguir_proceso(
    id_proceso: str,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_GESTIONAR)),
    oportunidades=Depends(obtener_oportunidades),
):
    from src.shared.oportunidades_repo import OportunidadNoEncontradaError
    try:
        return oportunidades.dejar_de_seguir(id_proceso, _usuario(usuario))
    except OportunidadNoEncontradaError:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada")


@router_oportunidades.get("/{id_proceso}/novedades")
def novedades_proceso(
    id_proceso: str,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_VER)),
    oportunidades=Depends(obtener_oportunidades),
):
    _oportunidad(oportunidades, id_proceso, usuario)
    return oportunidades.novedades(id_proceso, _usuario(usuario))


@router_oportunidades.post("/{id_proceso}/novedades/revisadas", status_code=status.HTTP_204_NO_CONTENT)
def marcar_novedades_revisadas(
    id_proceso: str,
    usuario: dict = Depends(requiere_permiso(Permiso.VIGILANCIA_VER)),
    oportunidades=Depends(obtener_oportunidades),
):
    _oportunidad(oportunidades, id_proceso, usuario)
    oportunidades.marcar_revisadas(id_proceso, _usuario(usuario))


# ---------------------------------------------------------------------------
# Expediente documental y carga manual (RF-021, RF-022)
# ---------------------------------------------------------------------------

def _verificar_alcance(oportunidad: dict, usuario: dict, permiso: str, request: Request) -> None:
    """Tabla 61: el analista opera el expediente de las oportunidades asignadas a él (o sin asignar)."""
    if not tiene_permiso(usuario, Permiso.EXPEDIENTE_CARGAR):
        return  # el administrador consulta todas
    responsable = oportunidad.get("responsable")
    if responsable and responsable != _usuario(usuario):
        auth.auditar_rechazo(usuario, permiso, request.method, request.url.path)
        raise HTTPException(status_code=403, detail=(
            f"La oportunidad está asignada a {responsable}: solo su responsable gestiona el expediente."))


@router_oportunidades.get("/{id_proceso}/expediente")
def consultar_expediente(
    id_proceso: str,
    request: Request,
    usuario: dict = Depends(requiere_permiso(Permiso.EXPEDIENTE_VER)),
    oportunidades=Depends(obtener_oportunidades),
    expediente=Depends(obtener_expediente),
):
    """RF-021: cada documento con su versión, procedencia y fecha; faltantes e ilegibles explícitos."""
    oportunidad = _oportunidad(oportunidades, id_proceso, usuario)
    _verificar_alcance(oportunidad, usuario, Permiso.EXPEDIENTE_VER, request)
    return {**expediente.expediente(id_proceso), "responsable": oportunidad.get("responsable"),
            "ultimo_analisis": oportunidad.get("ultimo_analisis")}


@router_oportunidades.post("/{id_proceso}/expediente/actualizar")
def actualizar_expediente(
    id_proceso: str,
    request: Request,
    usuario: dict = Depends(requiere_permiso(Permiso.EXPEDIENTE_CARGAR)),
    oportunidades=Depends(obtener_oportunidades),
    servicio: ServicioVigilancia = Depends(obtener_servicio_vigilancia),
):
    """Vuelve a consultar en SECOP II los documentos publicados del proceso (RF-011)."""
    oportunidad = _oportunidad(oportunidades, id_proceso, usuario)
    _verificar_alcance(oportunidad, usuario, Permiso.EXPEDIENTE_CARGAR, request)
    try:
        resumen = servicio.actualizar_expediente(id_proceso)
    except FuenteNoDisponibleError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"resumen": resumen, "expediente": servicio.expediente.expediente(id_proceso)}


@router_oportunidades.post("/{id_proceso}/expediente/documentos", status_code=status.HTTP_201_CREATED)
def cargar_documento(
    id_proceso: str,
    request: Request,
    archivo: UploadFile = File(..., description="PDF, DOCX, XLSX o TXT"),
    reemplaza_id: Optional[int] = Form(None, description="Documento que esta carga reemplaza"),
    nota: Optional[str] = Form(None, max_length=200, description="De dónde se obtuvo el archivo"),
    usuario: dict = Depends(requiere_permiso(Permiso.EXPEDIENTE_CARGAR)),
    oportunidades=Depends(obtener_oportunidades),
    expediente=Depends(obtener_expediente),
    auditoria=Depends(obtener_auditoria),
):
    """
    RF-022: incorpora un archivo autorizado del proceso que no se pudo recuperar de la
    fuente (o una versión nueva), con su procedencia y su versión.
    """
    from src.shared.expediente_repo import DocumentoNoAdmitidoError, DocumentoNoEncontradoError

    oportunidad = _oportunidad(oportunidades, id_proceso, usuario)
    _verificar_alcance(oportunidad, usuario, Permiso.EXPEDIENTE_CARGAR, request)
    contenido = archivo.file.read(expediente.max_bytes + 1)
    try:
        documento = expediente.cargar_manual(id_proceso, archivo.filename or "documento", contenido,
                                             _usuario(usuario), reemplaza_id=reemplaza_id, nota=nota)
    except DocumentoNoAdmitidoError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except DocumentoNoEncontradoError as e:
        raise HTTPException(status_code=404, detail=str(e))
    oportunidades.asignar_responsable_si_falta(id_proceso, _usuario(usuario))
    _auditar(auditoria, f"oportunidad-{id_proceso}", "DOCUMENTO_CARGADO", {
        "id_proceso": id_proceso, "documento_id": documento["id"], "nombre": documento["nombre"],
        "version": documento["version"], "estado": documento["estado"],
        "huella_sha256": documento["huella_sha256"], "reemplaza_id": reemplaza_id,
    }, usuario)
    return documento


@router_oportunidades.get("/{id_proceso}/expediente/documentos/{documento_id}/archivo")
def descargar_documento(
    id_proceso: str,
    documento_id: int,
    request: Request,
    usuario: dict = Depends(requiere_permiso(Permiso.EXPEDIENTE_VER)),
    oportunidades=Depends(obtener_oportunidades),
    expediente=Depends(obtener_expediente),
):
    oportunidad = _oportunidad(oportunidades, id_proceso, usuario)
    _verificar_alcance(oportunidad, usuario, Permiso.EXPEDIENTE_VER, request)
    documento = expediente.documento(documento_id)
    if documento is None or documento["id_proceso"] != id_proceso:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    ruta = documento.get("ruta_archivo")
    if not ruta or not os.path.exists(ruta):
        raise HTTPException(status_code=404, detail="El sistema no tiene el archivo de este documento.")
    return FileResponse(ruta, filename=documento["nombre"], headers={"X-Huella-SHA256": documento["huella_sha256"] or ""})


# ---------------------------------------------------------------------------
# Perfiles de búsqueda (RF-015) y sus coincidencias (RF-017)
# ---------------------------------------------------------------------------

def _limpiar_lista(valores: Optional[List[str]]) -> Optional[List[str]]:
    if valores is None:
        return None
    return list(dict.fromkeys(" ".join(v.split()) for v in valores if v and v.strip()))


class _CriteriosPerfil(BaseModel):
    @field_validator("palabras_clave", "entidades", "departamentos", "modalidades", mode="before", check_fields=False)
    @classmethod
    def _listas(cls, valor):
        return _limpiar_lista(valor) if isinstance(valor, list) else valor

    @field_validator("palabras_clave", check_fields=False)
    @classmethod
    def _palabras(cls, valor):
        if valor is not None:
            if not valor:
                raise ValueError("El perfil necesita al menos una palabra clave.")
            cortas = [p for p in valor if len(p) < 3]
            if cortas:
                raise ValueError(f"Las palabras clave deben tener al menos 3 caracteres: {', '.join(cortas)}.")
        return valor

    @model_validator(mode="after")
    def _rango(self):
        minimo, maximo = getattr(self, "cuantia_min", None), getattr(self, "cuantia_max", None)
        if minimo is not None and maximo is not None and minimo > maximo:
            raise ValueError("La cuantía mínima no puede superar la máxima.")
        return self


class PerfilEntrada(_CriteriosPerfil):
    nombre: str = Field(..., min_length=1, max_length=80)
    palabras_clave: List[str] = Field(..., max_length=20)
    entidades: List[str] = Field(default_factory=list, max_length=20)
    departamentos: List[str] = Field(default_factory=list, max_length=33)
    modalidades: List[str] = Field(default_factory=list, max_length=20)
    cuantia_min: Optional[float] = Field(None, ge=0)
    cuantia_max: Optional[float] = Field(None, ge=0)
    activo: bool = True


class PerfilCambios(_CriteriosPerfil):
    nombre: Optional[str] = Field(None, min_length=1, max_length=80)
    palabras_clave: Optional[List[str]] = Field(None, max_length=20)
    entidades: Optional[List[str]] = Field(None, max_length=20)
    departamentos: Optional[List[str]] = Field(None, max_length=33)
    modalidades: Optional[List[str]] = Field(None, max_length=20)
    cuantia_min: Optional[float] = Field(None, ge=0)
    cuantia_max: Optional[float] = Field(None, ge=0)
    activo: Optional[bool] = None


@router_perfiles.get("/")
def listar_perfiles(
    usuario: dict = Depends(requiere_permiso(Permiso.PERFILES_VER)),
    perfiles=Depends(obtener_perfiles),
):
    return perfiles.listar(_usuario(usuario))


@router_perfiles.get("/coincidencias")
def coincidencias_perfiles(
    perfil_id: Optional[int] = None,
    usuario: dict = Depends(requiere_permiso(Permiso.PERFILES_VER)),
    perfiles=Depends(obtener_perfiles),
):
    """RF-017: procesos que coincidieron con mis perfiles, con la entidad y la fecha de cierre."""
    from src.shared.perfiles_repo import PerfilNoEncontradoError
    try:
        return perfiles.coincidencias(_usuario(usuario), perfil_id)
    except PerfilNoEncontradoError:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")


@router_perfiles.post("/", status_code=status.HTTP_201_CREATED)
def crear_perfil(
    entrada: PerfilEntrada,
    usuario: dict = Depends(requiere_permiso(Permiso.PERFILES_GESTIONAR)),
    perfiles=Depends(obtener_perfiles),
):
    return perfiles.crear(_usuario(usuario), entrada.model_dump())


@router_perfiles.put("/{perfil_id}")
def actualizar_perfil(
    perfil_id: int,
    cambios: PerfilCambios,
    usuario: dict = Depends(requiere_permiso(Permiso.PERFILES_EDITAR)),
    perfiles=Depends(obtener_perfiles),
):
    """Editar, activar o desactivar un perfil propio. Uno ajeno responde 404 (Tabla 61)."""
    from src.shared.perfiles_repo import PerfilNoEncontradoError
    datos = cambios.model_dump(exclude_unset=True)
    try:
        return perfiles.actualizar(perfil_id, _usuario(usuario), datos)
    except PerfilNoEncontradoError:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")


@router_perfiles.delete("/{perfil_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_perfil(
    perfil_id: int,
    usuario: dict = Depends(requiere_permiso(Permiso.PERFILES_GESTIONAR)),
    perfiles=Depends(obtener_perfiles),
):
    from src.shared.perfiles_repo import PerfilNoEncontradoError
    try:
        perfiles.eliminar(perfil_id, _usuario(usuario))
    except PerfilNoEncontradoError:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
