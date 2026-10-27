import logging
import uuid
from typing import List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, field_validator

from src.api.adapters.queue import PublicadorTrabajos
from src.api.middleware.auth import requiere_permiso
from src.shared.config import obtener_configuracion
from src.shared.roles import Permiso
from src.shared.schemas.domain import RequisitoExtraido
from src.shared.tareas_repo import EstadoTarea, RepositorioTareas, huella_entrada
from src.worker_analysis.servicio import (
    ServicioAnalisis,
    TareaNoEncontradaError,
    TransicionInvalidaError,
    obtener_servicio,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analisis", tags=["Análisis de Licitaciones"])

# Service Bus admite mensajes de 256 KB en el plan Standard. Un pliego más grande
# debe subirse a Blob Storage y enviarse por referencia.
MAX_CARACTERES_PLIEGO = 100_000

class SolicitudAnalisis(BaseModel):
    licitacion_url: str = Field(..., min_length=1, max_length=200, description="ID o referencia del proceso en SECOP II")
    contenido_pliego: Optional[str] = Field(
        None,
        max_length=MAX_CARACTERES_PLIEGO,
        description="Texto del pliego. Datos Abiertos solo publica metadatos del proceso.",
    )
    forzar_nuevo: bool = Field(
        False,
        description="Analizar de nuevo aunque exista un análisis vigente con la misma entrada y versiones (RN-09).",
    )

    @field_validator("licitacion_url")
    @classmethod
    def _id_sin_espacios(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("El ID del proceso no puede estar vacío.")
        return valor

    @field_validator("contenido_pliego")
    @classmethod
    def _pliego_vacio_es_none(cls, valor: Optional[str]) -> Optional[str]:
        return valor if valor and valor.strip() else None

class TareaResponse(BaseModel):
    tarea_id: str
    mensaje: str

class AprobacionRequisitos(BaseModel):
    requisitos: List[RequisitoExtraido] = Field(..., min_length=1)


class RevisionRequisitos(BaseModel):
    """PUT /analisis/{id}/requisitos (Tabla 45): aprobar=False guarda un borrador; True sella la lista."""
    requisitos: List[RequisitoExtraido] = Field(default_factory=list)
    aprobar: bool = False


def obtener_repositorio() -> RepositorioTareas:
    return RepositorioTareas()

def obtener_publicador() -> Optional[PublicadorTrabajos]:
    """None cuando no hay Service Bus: el análisis corre dentro de la API (solo desarrollo)."""
    return PublicadorTrabajos() if obtener_configuracion().usa_service_bus else None


def obtener_versiones_vigentes() -> Tuple[Optional[int], Optional[int]]:
    """(versión de reglas, versión del portafolio) vigentes al aceptar la solicitud (RN-06)."""
    from src.shared.portfolio_repo import RepositorioVersionesPortafolio
    from src.shared.reglas_repo import RepositorioReglas, VersionNoEncontradaError

    try:
        reglas = RepositorioReglas().vigente()["version"]
    except VersionNoEncontradaError:
        reglas = None
    return reglas, RepositorioVersionesPortafolio().vigente()


def obtener_expediente():
    """Repositorio del expediente documental (RF-021); sus huellas entran en la reutilización (RF-036)."""
    from src.shared.expediente_repo import RepositorioExpediente
    return RepositorioExpediente()


def verificar_cuota_disponible() -> None:
    """RN-10: con la cuota de tokens del periodo agotada no se aceptan solicitudes nuevas (429)."""
    from src.shared.consumo_repo import RepositorioConsumo

    repositorio = RepositorioConsumo()
    if repositorio.agotada():
        estado = repositorio.estado()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=(
            f"La cuota de tokens del periodo {estado['periodo']} está agotada ({estado['consumido']} de "
            f"{estado['limite']}). No se aceptan análisis nuevos hasta que el administrador amplíe la cuota "
            "o empiece el periodo siguiente."))


class AnalisisReutilizableError(Exception):
    """Ya existe un análisis finalizado con la misma entrada y las mismas versiones (RF-036)."""

    def __init__(self, tarea: dict):
        super().__init__(tarea["tarea_id"])
        self.tarea = tarea

    def como_http(self) -> HTTPException:
        from src.shared.horas import texto_local
        fecha = texto_local(self.tarea.get("actualizado_en"))
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "mensaje": (f"Ya existe un análisis vigente de este proceso, finalizado el {fecha}, con el mismo "
                        "pliego y las mismas versiones de reglas y de portafolio. Consulte su resultado "
                        "o solicite uno nuevo."),
            "tarea_id": self.tarea["tarea_id"],
            "finalizado_en": self.tarea.get("actualizado_en"),
            "recomendacion": self.tarea.get("recomendacion"),
            "puntaje": self.tarea.get("puntaje"),
        })

def _usuario(usuario: dict) -> str:
    return usuario.get("email") or usuario.get("user_id") or "desconocido"


def crear_tarea_analisis(
    licitacion_url: str,
    contenido_pliego: Optional[str],
    solicitado_por: str,
    background_tasks: BackgroundTasks,
    repositorio: RepositorioTareas,
    publicador: Optional[PublicadorTrabajos],
    versiones: Tuple[Optional[int], Optional[int]],
    forzar_nuevo: bool = False,
    expediente=None,
) -> str:
    """
    Registra la tarea y la encola (o la ejecuta en segundo plano sin Service Bus).
    La tarea fija las versiones vigentes de reglas y de portafolio (RN-06). Si ya hay un
    análisis vigente con la misma entrada y versiones, lanza AnalisisReutilizableError
    salvo que se pida forzar uno nuevo (RN-09).
    """
    reglas_version, portafolio_version = versiones
    documentos = expediente.huellas_vigentes(licitacion_url) if expediente is not None else []
    huella = huella_entrada(licitacion_url, contenido_pliego, documentos)
    if not forzar_nuevo:
        previa = repositorio.buscar_reutilizable(huella, reglas_version, portafolio_version)
        if previa is not None:
            raise AnalisisReutilizableError(previa)

    tarea_id = str(uuid.uuid4())
    repositorio.crear(tarea_id, licitacion_url, solicitado_por, reglas_version=reglas_version,
                      portafolio_version=portafolio_version, huella=huella)

    if publicador:
        publicador.encolar_analisis(tarea_id, licitacion_url, contenido_pliego,
                                    reglas_version=reglas_version, portafolio_version=portafolio_version)
    else:
        logger.warning("Sin Service Bus: el análisis se ejecuta dentro de la API (solo desarrollo).")
        background_tasks.add_task(
            lambda: obtener_servicio().iniciar_analisis(
                tarea_id, licitacion_url, contenido_pliego,
                reglas_version=reglas_version, portafolio_version=portafolio_version)
        )
    return tarea_id


@router.post("/", response_model=TareaResponse, status_code=status.HTTP_202_ACCEPTED)
def solicitar_analisis(
    solicitud: SolicitudAnalisis,
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.ANALISIS_SOLICITAR)),
    repositorio: RepositorioTareas = Depends(obtener_repositorio),
    publicador: Optional[PublicadorTrabajos] = Depends(obtener_publicador),
    versiones: Tuple[Optional[int], Optional[int]] = Depends(obtener_versiones_vigentes),
    _cuota: None = Depends(verificar_cuota_disponible),
    expediente=Depends(obtener_expediente),
):
    """
    ASR-11: Registra la tarea, la encola en Service Bus y devuelve la respuesta
    inmediata sin bloquear. RF-036: 409 si ya existe un análisis vigente reutilizable.
    RN-10: 429 si la cuota de tokens del periodo está agotada.
    """
    try:
        tarea_id = crear_tarea_analisis(
            solicitud.licitacion_url, solicitud.contenido_pliego, _usuario(usuario),
            background_tasks, repositorio, publicador, versiones, solicitud.forzar_nuevo, expediente,
        )
    except AnalisisReutilizableError as e:
        raise e.como_http()
    return TareaResponse(
        tarea_id=tarea_id,
        mensaje="Análisis encolado. Consulta /analisis/{tarea_id} para seguir su avance.",
    )


@router.get("/")
def listar_tareas(
    estado: Optional[str] = None,
    usuario: dict = Depends(requiere_permiso(Permiso.ANALISIS_VER)),
    repositorio: RepositorioTareas = Depends(obtener_repositorio),
):
    """Lista las tareas recientes; con ?estado=Esperando revisión, la bandeja del analista."""
    return repositorio.listar(estado=estado)


def _tarea_o_404(repositorio: RepositorioTareas, tarea_id: str) -> dict:
    tarea = repositorio.obtener(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    tarea["requiere_accion"] = tarea["estado"] == EstadoTarea.ESPERANDO_REVISION
    return tarea


@router.get("/{tarea_id}/estado", deprecated=True)
def consultar_estado_tarea(
    tarea_id: str,
    usuario: dict = Depends(requiere_permiso(Permiso.ANALISIS_VER)),
    repositorio: RepositorioTareas = Depends(obtener_repositorio),
):
    """
    RF-026: estado de la tarea sin leer el checkpoint (sondeo liviano).
    Si la tarea falló o se suspendió, detalle_error explica el motivo. Use GET /analisis/{id}.
    """
    return _tarea_o_404(repositorio, tarea_id)


@router.get("/{tarea_id}")
def consultar_tarea(
    tarea_id: str,
    usuario: dict = Depends(requiere_permiso(Permiso.ANALISIS_VER)),
    repositorio: RepositorioTareas = Depends(obtener_repositorio),
    servicio: ServicioAnalisis = Depends(obtener_servicio),
):
    """
    RF-026, CU-04 (Tabla 45): estado, etapa en curso, etapas cerradas, puntaje y
    recomendación. Las etapas salen del último checkpoint del grafo.
    """
    tarea = _tarea_o_404(repositorio, tarea_id)
    return {**tarea, **servicio.progreso(tarea_id)}


@router.get("/{tarea_id}/requisitos")
def consultar_requisitos(
    tarea_id: str,
    usuario: dict = Depends(requiere_permiso(Permiso.ANALISIS_VER)),
    servicio: ServicioAnalisis = Depends(obtener_servicio),
):
    """
    ASR-12: lista que el analista debe revisar antes de la evaluación: el borrador
    guardado si lo hay, la extraída y, si hubo un análisis previo aprobado del mismo
    proceso, qué requisitos conservan la aprobación y cuáles vuelven a revisión (HU-06 CA-03).
    """
    try:
        return {"tarea_id": tarea_id, **servicio.obtener_revision(tarea_id)}
    except TareaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    except TransicionInvalidaError as e:
        raise HTTPException(status_code=409, detail=str(e))


def _ids_unicos(requisitos: List[RequisitoExtraido]) -> None:
    identificadores = [r.identificador for r in requisitos]
    if len(identificadores) != len(set(identificadores)):
        raise HTTPException(status_code=422, detail="Los identificadores de requisito deben ser únicos.")


def _aprobar(tarea_id: str, requisitos: List[RequisitoExtraido], usuario: dict, background_tasks: BackgroundTasks,
             servicio: ServicioAnalisis, publicador: Optional[PublicadorTrabajos]) -> dict:
    """Sella la lista en el checkpoint y encola la reanudación hacia la evaluación (ASR-12)."""
    if not requisitos:
        raise HTTPException(status_code=422, detail="La lista aprobada debe tener al menos un requisito.")
    _ids_unicos(requisitos)
    try:
        servicio.registrar_aprobacion(tarea_id, requisitos, _usuario(usuario))
    except TareaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    except TransicionInvalidaError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if publicador:
        publicador.encolar_reanudacion(tarea_id)
    else:
        background_tasks.add_task(servicio.reanudar_analisis, tarea_id)
    return {"tarea_id": tarea_id, "mensaje": "Lista aprobada. La evaluación se reanudó."}


@router.put("/{tarea_id}/requisitos", responses={202: {"description": "Lista aprobada y flujo reanudado"}})
def revisar_requisitos(
    tarea_id: str,
    revision: RevisionRequisitos,
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.REQUISITOS_APROBAR)),
    servicio: ServicioAnalisis = Depends(obtener_servicio),
    publicador: Optional[PublicadorTrabajos] = Depends(obtener_publicador),
):
    """
    CU-05, RF-030 (Tabla 45). Con aprobar=False guarda la revisión como borrador (200) y la
    tarea sigue en espera; con aprobar=True la sella y reanuda la evaluación (202).
    409 si la tarea no espera revisión o la lista ya fue aprobada; 422 si el esquema no es válido.
    """
    if revision.aprobar:
        cuerpo = _aprobar(tarea_id, revision.requisitos, usuario, background_tasks, servicio, publicador)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=cuerpo)
    _ids_unicos(revision.requisitos)
    try:
        guardado = servicio.guardar_borrador(tarea_id, revision.requisitos, _usuario(usuario))
    except TareaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    except TransicionInvalidaError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"tarea_id": tarea_id, "mensaje": "Borrador guardado. La tarea sigue en espera de revisión.", **guardado}


@router.post("/{tarea_id}/aprobacion", status_code=status.HTTP_202_ACCEPTED, deprecated=True)
def aprobar_requisitos(
    tarea_id: str,
    aprobacion: AprobacionRequisitos,
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.REQUISITOS_APROBAR)),
    servicio: ServicioAnalisis = Depends(obtener_servicio),
    publicador: Optional[PublicadorTrabajos] = Depends(obtener_publicador),
):
    """Equivale a PUT /analisis/{id}/requisitos con aprobar=True; se conserva por compatibilidad."""
    return _aprobar(tarea_id, aprobacion.requisitos, usuario, background_tasks, servicio, publicador)


@router.post("/{tarea_id}/continuar", status_code=status.HTTP_202_ACCEPTED)
def continuar_tarea_suspendida(
    tarea_id: str,
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.ANALISIS_SOLICITAR)),
    repositorio: RepositorioTareas = Depends(obtener_repositorio),
    publicador: Optional[PublicadorTrabajos] = Depends(obtener_publicador),
    _cuota: None = Depends(verificar_cuota_disponible),
):
    """
    Figura 15 (Suspendida → Evaluando): continúa una tarea suspendida por cuota desde la
    etapa que no pudo terminar, cuando vuelve a haber cuota. Una suspensión por
    inyección no se continúa (Tabla 18): se solicita un análisis nuevo.
    """
    tarea = repositorio.obtener(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    if tarea["estado"] != EstadoTarea.SUSPENDIDA or tarea.get("causa_suspension") != "cuota":
        raise HTTPException(status_code=409, detail="Solo se continúa una tarea suspendida por cuota agotada.")
    if publicador:
        publicador.encolar_continuacion(tarea_id)
    else:
        background_tasks.add_task(obtener_servicio().continuar_suspendida, tarea_id)
    return {"tarea_id": tarea_id, "mensaje": "La tarea continúa desde la etapa que quedó pendiente."}


@router.get("/{tarea_id}/resultado")
def consultar_resultado(
    tarea_id: str,
    usuario: dict = Depends(requiere_permiso(Permiso.RESULTADOS_VER)),
    servicio: ServicioAnalisis = Depends(obtener_servicio),
):
    """RF-034 / RF-035: Puntaje con desglose, recomendación, justificación y dictámenes."""
    try:
        return servicio.obtener_resultado(tarea_id)
    except TareaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    except TransicionInvalidaError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{tarea_id}/informe")
def descargar_informe(
    tarea_id: str,
    usuario: dict = Depends(requiere_permiso(Permiso.RESULTADOS_VER)),
    servicio: ServicioAnalisis = Depends(obtener_servicio),
):
    """RF-037 (Tabla 45): el PDF sellado; la cabecera X-Huella-SHA256 lleva su huella registrada."""
    try:
        contenido, huella = servicio.obtener_informe_pdf(tarea_id)
    except TareaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    except TransicionInvalidaError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=contenido, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="informe_{tarea_id}.pdf"',
        "X-Huella-SHA256": huella or "",
    })


@router.get("/{tarea_id}/informe/verificacion")
def verificar_informe(
    tarea_id: str,
    usuario: dict = Depends(requiere_permiso(Permiso.RESULTADOS_VER)),
    servicio: ServicioAnalisis = Depends(obtener_servicio),
):
    """ASR-06: compara la huella actual del PDF con la registrada en la bitácora."""
    try:
        return servicio.verificar_informe(tarea_id)
    except TareaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    except TransicionInvalidaError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{tarea_id}/informe/texto", response_class=PlainTextResponse)
def vista_previa_informe(
    tarea_id: str,
    usuario: dict = Depends(requiere_permiso(Permiso.RESULTADOS_VER)),
    servicio: ServicioAnalisis = Depends(obtener_servicio),
):
    """Vista previa en texto, con el mismo contenido del PDF sellado."""
    try:
        return servicio.obtener_informe(tarea_id)
    except TareaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    except TransicionInvalidaError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
