"""
Gestión comercial de las oportunidades (RF-040) y exportación a CSV (RF-041).

Módulo de resultados y decisiones (Figura 10): "Informes, tablero, decisión comercial,
carpetas y exportación". Tabla 61, fila "Carpetas y exportación": el analista consulta,
edita, agrega y borra; el gerente consulta, edita y agrega; el administrador consulta. Las
carpetas son solo las del propio usuario; el alcance se resuelve en el servidor.
"""
import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator

from src.api.middleware.auth import requiere_permiso
from src.api.modules.opportunities.router import obtener_auditoria, obtener_oportunidades
from src.shared.roles import Permiso

logger = logging.getLogger(__name__)
router_carpetas = APIRouter(prefix="/carpetas", tags=["Carpetas"])
router_gestion = APIRouter(prefix="/oportunidades", tags=["Notas y responsable"])
router_exportacion = APIRouter(prefix="/resultados", tags=["Resultados y decisiones"])

# ASR-15 mide 100 registros; el tope evita que una exportación sin filtros cargue toda la base.
MAX_EXPORTACION = 5000


def obtener_gestion():
    from src.shared.gestion_repo import RepositorioGestion
    return RepositorioGestion()


def obtener_notificaciones():
    from src.shared.notificaciones_repo import RepositorioNotificaciones
    return RepositorioNotificaciones()


def _usuario(usuario: dict) -> str:
    return usuario.get("email") or usuario.get("user_id") or "desconocido"


def _auditar(auditoria, referencia: str, evento: str, detalles: dict, usuario: dict) -> None:
    try:
        auditoria.registrar_evento(referencia, evento, detalles, registrado_por=_usuario(usuario),
                                   licitacion_id=detalles.get("id_proceso"))
    except Exception as e:
        logger.error(f"No se pudo registrar {evento} en la bitácora: {type(e).__name__}")


def _oportunidad(oportunidades, id_proceso: str, usuario: dict) -> dict:
    o = oportunidades.obtener(id_proceso, _usuario(usuario))
    if o is None:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
    return o


# ---------------------------------------------------------------------------
# Carpetas (RF-040)
# ---------------------------------------------------------------------------

class NombreCarpeta(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=60)

    @field_validator("nombre")
    @classmethod
    def _sin_espacios_sobrantes(cls, valor: str) -> str:
        valor = " ".join(valor.split())
        if not valor:
            raise ValueError("El nombre de la carpeta no puede estar vacío.")
        return valor


class SeleccionOportunidades(BaseModel):
    ids: List[str] = Field(..., min_length=1, max_length=500)


@router_carpetas.get("/")
def listar_carpetas(
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_VER)),
    gestion=Depends(obtener_gestion),
):
    return gestion.carpetas(_usuario(usuario))


@router_carpetas.post("/", status_code=status.HTTP_201_CREATED)
def crear_carpeta(
    entrada: NombreCarpeta,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_EDITAR)),
    gestion=Depends(obtener_gestion),
):
    from src.shared.gestion_repo import CarpetaDuplicadaError
    try:
        return gestion.crear_carpeta(_usuario(usuario), entrada.nombre)
    except CarpetaDuplicadaError:
        raise HTTPException(status_code=409, detail=f"Ya tienes una carpeta llamada «{entrada.nombre}».")


@router_carpetas.put("/{carpeta_id}")
def renombrar_carpeta(
    carpeta_id: int,
    entrada: NombreCarpeta,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_EDITAR)),
    gestion=Depends(obtener_gestion),
):
    from src.shared.gestion_repo import CarpetaDuplicadaError, CarpetaNoEncontradaError
    try:
        return gestion.renombrar_carpeta(carpeta_id, _usuario(usuario), entrada.nombre)
    except CarpetaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")
    except CarpetaDuplicadaError:
        raise HTTPException(status_code=409, detail=f"Ya tienes una carpeta llamada «{entrada.nombre}».")


@router_carpetas.delete("/{carpeta_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_carpeta(
    carpeta_id: int,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_BORRAR)),
    gestion=Depends(obtener_gestion),
):
    """Borra la carpeta; las oportunidades siguen en el tablero."""
    from src.shared.gestion_repo import CarpetaNoEncontradaError
    try:
        gestion.eliminar_carpeta(carpeta_id, _usuario(usuario))
    except CarpetaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")


@router_carpetas.post("/{carpeta_id}/oportunidades")
def agregar_a_carpeta(
    carpeta_id: int,
    seleccion: SeleccionOportunidades,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_EDITAR)),
    gestion=Depends(obtener_gestion),
):
    from src.shared.gestion_repo import CarpetaNoEncontradaError
    try:
        return {"agregadas": gestion.agregar_a_carpeta(carpeta_id, _usuario(usuario), seleccion.ids)}
    except CarpetaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")


@router_carpetas.post("/{carpeta_id}/oportunidades/quitar")
def quitar_de_carpeta(
    carpeta_id: int,
    seleccion: SeleccionOportunidades,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_EDITAR)),
    gestion=Depends(obtener_gestion),
):
    from src.shared.gestion_repo import CarpetaNoEncontradaError
    try:
        return {"quitadas": gestion.quitar_de_carpeta(carpeta_id, _usuario(usuario), seleccion.ids)}
    except CarpetaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")


# ---------------------------------------------------------------------------
# Notas y responsable (RF-040)
# ---------------------------------------------------------------------------

class NuevaNota(BaseModel):
    texto: str = Field(..., min_length=1, max_length=2000)

    @field_validator("texto")
    @classmethod
    def _no_vacia(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("La nota no puede estar vacía.")
        return valor.strip()


class Asignacion(BaseModel):
    responsable: Optional[str] = Field(None, max_length=200, description="Correo del analista; vacío lo deja sin asignar")


@router_gestion.get("/{id_proceso}/notas")
def listar_notas(
    id_proceso: str,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_VER)),
    oportunidades=Depends(obtener_oportunidades),
    gestion=Depends(obtener_gestion),
):
    _oportunidad(oportunidades, id_proceso, usuario)
    return gestion.notas(id_proceso)


@router_gestion.post("/{id_proceso}/notas", status_code=status.HTTP_201_CREATED)
def agregar_nota(
    id_proceso: str,
    nota: NuevaNota,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_EDITAR)),
    oportunidades=Depends(obtener_oportunidades),
    gestion=Depends(obtener_gestion),
):
    _oportunidad(oportunidades, id_proceso, usuario)
    return gestion.agregar_nota(id_proceso, _usuario(usuario), nota.texto)


@router_gestion.delete("/{id_proceso}/notas/{nota_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_nota(
    id_proceso: str,
    nota_id: int,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_BORRAR)),
    gestion=Depends(obtener_gestion),
):
    """Solo el autor borra su nota; una ajena responde 404."""
    from src.shared.gestion_repo import NotaNoEncontradaError
    try:
        gestion.eliminar_nota(nota_id, id_proceso, _usuario(usuario))
    except NotaNoEncontradaError:
        raise HTTPException(status_code=404, detail="Nota no encontrada")


@router_gestion.get("/{id_proceso}/responsable/opciones")
def opciones_responsable(
    id_proceso: str,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_EDITAR)),
    gestion=Depends(obtener_gestion),
):
    """Analistas comerciales activos a los que se puede asignar la oportunidad."""
    return gestion.analistas()


@router_gestion.put("/{id_proceso}/responsable")
def asignar_responsable(
    id_proceso: str,
    asignacion: Asignacion,
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_EDITAR)),
    oportunidades=Depends(obtener_oportunidades),
    gestion=Depends(obtener_gestion),
    auditoria=Depends(obtener_auditoria),
    notificaciones=Depends(obtener_notificaciones),
):
    """
    RF-040: el responsable gestiona el expediente de la oportunidad (Tabla 61). El cambio queda
    en la bitácora con el antes y el después, y el nuevo responsable recibe un aviso.
    """
    from src.shared.gestion_repo import ResponsableInvalidoError
    from src.shared.notificaciones_repo import TipoNotificacion

    oportunidad = _oportunidad(oportunidades, id_proceso, usuario)
    responsable = (asignacion.responsable or "").strip().lower() or None
    try:
        cambio = gestion.asignar_responsable(id_proceso, responsable)
    except ResponsableInvalidoError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if cambio["antes"] != cambio["despues"]:
        _auditar(auditoria, f"oportunidad-{id_proceso}", "RESPONSABLE_ASIGNADO",
                 {"id_proceso": id_proceso, "cambios": {"responsable": cambio}}, usuario)
        if responsable and responsable != _usuario(usuario):
            try:
                notificaciones.crear(
                    responsable, TipoNotificacion.ASIGNACION, f"asignacion:{id_proceso}:{datetime.utcnow():%Y%m%d%H%M%S}",
                    f"Te asignaron la oportunidad {id_proceso}",
                    f"{oportunidad.get('objeto') or oportunidad.get('nombre') or ''}\n"
                    f"Entidad: {oportunidad.get('entidad') or 'sin dato'} · Cierre: "
                    f"{(oportunidad.get('fecha_cierre') or 'sin fecha publicada')[:10]}\n"
                    f"Asignada por {_usuario(usuario)}. Ahora gestionas su expediente documental.",
                    id_proceso=id_proceso, enlace=oportunidad.get("url_proceso"))
                background_tasks.add_task(_enviar_correos)
            except Exception as e:
                logger.warning(f"No se pudo avisar la asignación de {id_proceso}: {type(e).__name__}")
    return oportunidades.obtener(id_proceso, _usuario(usuario))


def _enviar_correos() -> None:
    try:
        from src.worker_vigilance.notificador import Notificador
        Notificador().enviar_pendientes()
    except Exception as e:
        logger.warning(f"No se pudieron enviar los correos pendientes: {type(e).__name__}")


# ---------------------------------------------------------------------------
# Exportación a CSV (RF-041, ASR-15)
# ---------------------------------------------------------------------------

def _inicio_dia(valor: Optional[date]) -> Optional[datetime]:
    return datetime(valor.year, valor.month, valor.day) if valor else None


@router_exportacion.get("/oportunidades.csv")
def exportar_oportunidades(
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
    carpeta_id: Optional[int] = None,
    ids: Optional[List[str]] = Query(None, description="Oportunidades seleccionadas; vacío exporta todas las filtradas"),
    usuario: dict = Depends(requiere_permiso(Permiso.ORGANIZACION_VER)),
    oportunidades=Depends(obtener_oportunidades),
    gestion=Depends(obtener_gestion),
    auditoria=Depends(obtener_auditoria),
):
    """
    RF-041: las oportunidades seleccionadas (o todas las filtradas) con los mismos filtros del
    tablero y solo lo que el usuario puede ver. La exportación queda en la bitácora.
    """
    from src.api.modules.results.exportacion import generar_csv
    from src.shared.gestion_repo import CarpetaNoEncontradaError

    if carpeta_id is not None:
        try:
            gestion.verificar_carpeta(carpeta_id, _usuario(usuario))
        except CarpetaNoEncontradaError:
            raise HTTPException(status_code=404, detail="Carpeta no encontrada")
    filtros = {"q": q, "entidad": entidad, "departamento": departamento, "ciudad": ciudad, "modalidad": modalidad,
               "estado": estado, "cuantia_min": cuantia_min, "cuantia_max": cuantia_max,
               "publicada_desde": _inicio_dia(publicada_desde), "publicada_hasta": _inicio_dia(publicada_hasta),
               "cierre_desde": _inicio_dia(cierre_desde), "cierre_hasta": _inicio_dia(cierre_hasta),
               "solo_seguidas": seguidas, "con_novedades": con_novedades, "carpeta_id": carpeta_id,
               "ids": [i for i in ids if i] if ids else None}
    resultado = oportunidades.buscar(usuario=_usuario(usuario), limite=MAX_EXPORTACION, **filtros)
    contenido = generar_csv(resultado["oportunidades"])
    exportadas = len(resultado["oportunidades"])
    _auditar(auditoria, f"exportacion-{_usuario(usuario)}", "EXPORTACION_CSV", {
        "registros": exportadas, "total": resultado["total"],
        "filtros": {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in filtros.items()
                    if v not in (None, False, "", [])},
    }, usuario)
    nombre = f"oportunidades_{datetime.utcnow():%Y%m%d_%H%M}.csv"
    return Response(content=contenido, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{nombre}"',
        "X-Registros-Exportados": str(exportadas), "X-Registros-Totales": str(resultado["total"]),
    })
