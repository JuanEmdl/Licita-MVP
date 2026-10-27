"""
Oportunidades sincronizadas, seguimiento y novedades (RF-012 a RF-014, RF-018, RF-019).

- Cada proceso de SECOP II se guarda una sola vez por su identificador de origen, con la
  fuente y la fecha de la última actualización exitosa (RF-012).
- La búsqueda por palabras clave recorre el nombre y el objeto normalizados (sin tildes ni
  mayúsculas), y los filtros combinan entidad, ubicación, modalidad, cuantía, fechas y
  estado (RF-013, RF-014).
- Cada usuario sigue los procesos que le interesan (RF-018). Si un proceso seguido cambia,
  se registran sus novedades (RF-019); las que llegaron después de la última revisión del
  usuario se muestran como nuevas.
- Cada sincronización deja su resultado: si la fuente falla, la consulta sigue mostrando
  los datos previos con la fecha de la última sincronización exitosa (HU-04 CA-04).
"""
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from src.shared.models import (
    Carpeta,
    CarpetaOportunidad,
    NotaOportunidad,
    NovedadProceso,
    Oportunidad,
    SeguimientoProceso,
    Sincronizacion,
    TareaAnalisis,
)
from src.worker_vigilance.afinidad import normalizar
from src.worker_vigilance.detector import TipoNovedad, cambios_proceso, huella_proceso

ORIGEN_SINCRONIZACION = "Sincronización"
ORIGEN_RADICACION = "Radicación manual"

CAMPOS_PROCESO = (
    "id_portafolio", "referencia", "entidad", "nit_entidad", "nombre", "objeto", "modalidad",
    "precio_base", "departamento", "ciudad", "fase", "estado", "fecha_publicacion", "fecha_cierre",
    "url_proceso", "actualizado_en_fuente",
)


class OportunidadNoEncontradaError(Exception):
    pass


def _iso(valor: Optional[datetime]) -> Optional[str]:
    return valor.isoformat() if valor else None


def _texto_busqueda(proceso: Dict[str, Any]) -> str:
    return normalizar(f"{proceso.get('nombre') or ''} {proceso.get('objeto') or ''} {proceso.get('referencia') or ''}")


def _proceso_de(o: Oportunidad) -> Dict[str, Any]:
    return {campo: getattr(o, campo) for campo in CAMPOS_PROCESO}


class RepositorioOportunidades:

    def __init__(self, fabrica_sesiones: Optional[Callable[[], Session]] = None):
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        self._sesiones = fabrica_sesiones

    # --- Sincronización (RF-012) y detección de cambios (RF-019) ---

    def guardar_lote(self, procesos: Iterable[Dict[str, Any]], fuente: str, origen: str = ORIGEN_SINCRONIZACION,
                     registrada_por: Optional[str] = None) -> Dict[str, Any]:
        """
        Inserta o actualiza los procesos sin duplicarlos. En los procesos seguidos compara
        con la versión anterior y registra las novedades. Devuelve los contadores y las
        novedades creadas.
        """
        ahora = datetime.utcnow()
        nuevos, actualizados, novedades = 0, 0, []
        with self._sesiones() as db:
            seguidos = set(db.execute(
                select(SeguimientoProceso.id_proceso).where(SeguimientoProceso.activo)).scalars())
            for proceso in procesos:
                id_proceso = proceso.get("id_proceso")
                if not id_proceso:
                    continue
                o = db.get(Oportunidad, id_proceso)
                huella = huella_proceso(proceso)
                if o is None:
                    o = Oportunidad(id_proceso=id_proceso, fuente=fuente, origen_registro=origen,
                                    registrada_por=registrada_por, creada_en=ahora)
                    db.add(o)
                    nuevos += 1
                else:
                    actualizados += 1
                    if id_proceso in seguidos and o.huella and o.huella != huella:
                        for cambio in cambios_proceso(_proceso_de(o), proceso):
                            novedades.append(self._novedad(db, id_proceso, cambio, ahora))
                for campo in CAMPOS_PROCESO:
                    # Lo que la fuente deja de publicar no borra el último valor conocido.
                    if proceso.get(campo) is not None:
                        setattr(o, campo, proceso[campo])
                o.fuente = fuente
                o.huella = huella_proceso(_proceso_de(o))
                o.texto_busqueda = _texto_busqueda(_proceso_de(o))
                o.sincronizada_en = ahora
            db.commit()
        return {"nuevos": nuevos, "actualizados": actualizados, "novedades": novedades}

    def registrar_novedades(self, id_proceso: str, cambios: Iterable[Dict[str, Any]]) -> List[dict]:
        """Novedades de documentos: la misma (p. ej. un retiro) no se registra dos veces."""
        ahora = datetime.utcnow()
        with self._sesiones() as db:
            previas = {(n.tipo, n.campo, n.antes, n.despues) for n in db.execute(
                select(NovedadProceso).where(NovedadProceso.id_proceso == id_proceso)).scalars()}
            creadas = []
            for cambio in cambios:
                clave = (cambio["tipo"], cambio["campo"], cambio.get("antes"), cambio.get("despues"))
                if clave not in previas:
                    previas.add(clave)
                    creadas.append(self._novedad(db, id_proceso, cambio, ahora))
            db.commit()
        return creadas

    @staticmethod
    def _novedad(db: Session, id_proceso: str, cambio: Dict[str, Any], ahora: datetime) -> dict:
        tarea = None
        if cambio["tipo"] in (TipoNovedad.REQUISITOS, TipoNovedad.DOCUMENTOS):
            # El último análisis no fallido del proceso puede quedar desactualizado (HU-06 CA-03).
            tarea = db.execute(
                select(TareaAnalisis.id).where(TareaAnalisis.licitacion_id == id_proceso,
                                               TareaAnalisis.estado != "Fallida")
                .order_by(TareaAnalisis.creado_en.desc()).limit(1)).scalar_one_or_none()
        novedad = NovedadProceso(id_proceso=id_proceso, tipo=cambio["tipo"], campo=cambio["campo"],
                                 antes=cambio.get("antes"), despues=cambio.get("despues"),
                                 tarea_afectada=tarea, detectada_en=ahora)
        db.add(novedad)
        db.flush()
        return {"id": novedad.id, "id_proceso": id_proceso, "tipo": novedad.tipo, "campo": novedad.campo,
                "antes": novedad.antes, "despues": novedad.despues, "tarea_afectada": tarea,
                "detectada_en": _iso(ahora)}

    # --- Consulta (RF-013, RF-014) ---

    def obtener(self, id_proceso: str, usuario: Optional[str] = None) -> Optional[dict]:
        with self._sesiones() as db:
            o = db.get(Oportunidad, id_proceso)
            return self._a_dicts(db, [o], usuario)[0] if o else None

    def buscar(self, usuario: Optional[str] = None, q: Optional[str] = None, entidad: Optional[str] = None,
               departamento: Optional[str] = None, ciudad: Optional[str] = None, modalidad: Optional[str] = None,
               estado: Optional[str] = None, cuantia_min: Optional[float] = None,
               cuantia_max: Optional[float] = None, publicada_desde: Optional[datetime] = None,
               publicada_hasta: Optional[datetime] = None, cierre_desde: Optional[datetime] = None,
               cierre_hasta: Optional[datetime] = None, solo_seguidas: bool = False,
               con_novedades: bool = False, carpeta_id: Optional[int] = None,
               ids: Optional[List[str]] = None, limite: int = 100, desplazamiento: int = 0) -> dict:
        """carpeta_id debe ser una carpeta del usuario (lo verifica quien llama); ids limita a una selección."""
        condiciones = []
        if ids is not None:
            condiciones.append(Oportunidad.id_proceso.in_(ids))
        if carpeta_id is not None:
            condiciones.append(select(CarpetaOportunidad.id).where(
                CarpetaOportunidad.carpeta_id == carpeta_id,
                CarpetaOportunidad.id_proceso == Oportunidad.id_proceso).exists())
        # Todas las palabras deben aparecer, en cualquier orden (RF-013).
        for palabra in normalizar(q or "").split():
            condiciones.append(Oportunidad.texto_busqueda.like(f"%{palabra}%"))
        if entidad:
            condiciones.append(func.lower(Oportunidad.entidad).like(f"%{entidad.lower()}%"))
        if departamento:
            condiciones.append(Oportunidad.departamento == departamento)
        if ciudad:
            condiciones.append(func.lower(Oportunidad.ciudad).like(f"%{ciudad.lower()}%"))
        if modalidad:
            condiciones.append(Oportunidad.modalidad == modalidad)
        if estado:
            condiciones.append(or_(Oportunidad.estado == estado, Oportunidad.fase == estado))
        if cuantia_min is not None:
            condiciones.append(Oportunidad.precio_base >= cuantia_min)
        if cuantia_max is not None:
            condiciones.append(Oportunidad.precio_base <= cuantia_max)
        if publicada_desde:
            condiciones.append(Oportunidad.fecha_publicacion >= publicada_desde)
        if publicada_hasta:
            condiciones.append(Oportunidad.fecha_publicacion < publicada_hasta + timedelta(days=1))
        if cierre_desde:
            condiciones.append(Oportunidad.fecha_cierre >= cierre_desde)
        if cierre_hasta:
            condiciones.append(Oportunidad.fecha_cierre < cierre_hasta + timedelta(days=1))
        seguimiento = and_(SeguimientoProceso.id_proceso == Oportunidad.id_proceso,
                           SeguimientoProceso.usuario == (usuario or ""), SeguimientoProceso.activo)
        if solo_seguidas or con_novedades:
            condiciones.append(select(SeguimientoProceso.id).where(seguimiento).exists())
        if con_novedades:
            condiciones.append(select(NovedadProceso.id).where(
                NovedadProceso.id_proceso == Oportunidad.id_proceso,
                NovedadProceso.detectada_en > select(SeguimientoProceso.revisado_en).where(seguimiento)
                .scalar_subquery()).exists())
        with self._sesiones() as db:
            total = db.execute(select(func.count()).select_from(Oportunidad).where(*condiciones)).scalar_one()
            filas = db.execute(
                select(Oportunidad).where(*condiciones)
                .order_by(Oportunidad.fecha_publicacion.desc().nullslast(), Oportunidad.id_proceso)
                .limit(max(1, min(limite, 5000))).offset(max(0, desplazamiento))).scalars().all()
            return {"total": total, "oportunidades": self._a_dicts(db, filas, usuario)}

    def opciones_filtro(self) -> dict:
        """Valores presentes en la base, para los selectores de filtro de la interfaz."""
        with self._sesiones() as db:
            def distintos(columna):
                return [v for v in db.execute(select(columna).where(columna.is_not(None)).distinct()
                                              .order_by(columna).limit(300)).scalars() if v]
            return {"departamentos": distintos(Oportunidad.departamento),
                    "modalidades": distintos(Oportunidad.modalidad),
                    "estados": sorted(set(distintos(Oportunidad.estado)) | set(distintos(Oportunidad.fase)))}

    def _a_dicts(self, db: Session, filas: List[Oportunidad], usuario: Optional[str]) -> List[dict]:
        ids = [o.id_proceso for o in filas]
        if not ids:
            return []
        seguimientos = {s.id_proceso: s for s in db.execute(select(SeguimientoProceso).where(
            SeguimientoProceso.id_proceso.in_(ids), SeguimientoProceso.usuario == (usuario or ""),
            SeguimientoProceso.activo)).scalars()}
        novedades: Dict[str, List[NovedadProceso]] = {}
        for n in db.execute(select(NovedadProceso).where(NovedadProceso.id_proceso.in_(ids))
                            .order_by(NovedadProceso.detectada_en.desc())).scalars():
            novedades.setdefault(n.id_proceso, []).append(n)
        notas = dict(db.execute(select(NotaOportunidad.id_proceso, func.count()).where(
            NotaOportunidad.id_proceso.in_(ids)).group_by(NotaOportunidad.id_proceso)).all())
        # Tabla 61: cada usuario ve solo sus carpetas.
        carpetas: Dict[str, List[dict]] = {}
        for id_proceso, carpeta_id, nombre in db.execute(
                select(CarpetaOportunidad.id_proceso, Carpeta.id, Carpeta.nombre)
                .join(Carpeta, Carpeta.id == CarpetaOportunidad.carpeta_id)
                .where(CarpetaOportunidad.id_proceso.in_(ids), Carpeta.propietario == (usuario or ""))
                .order_by(Carpeta.nombre)).all():
            carpetas.setdefault(id_proceso, []).append({"id": carpeta_id, "nombre": nombre})
        tareas: Dict[str, TareaAnalisis] = {}
        for t in db.execute(select(TareaAnalisis).where(TareaAnalisis.licitacion_id.in_(ids))
                            .order_by(TareaAnalisis.creado_en.desc())).scalars():
            tareas.setdefault(t.licitacion_id, t)
        resultado = []
        for o in filas:
            s = seguimientos.get(o.id_proceso)
            propias = novedades.get(o.id_proceso, [])
            sin_revisar = [n for n in propias if s and n.detectada_en > (s.revisado_en or s.creado_en)]
            t = tareas.get(o.id_proceso)
            resultado.append({
                "id_proceso": o.id_proceso, "fuente": o.fuente, "id_portafolio": o.id_portafolio,
                "referencia": o.referencia, "entidad": o.entidad, "nit_entidad": o.nit_entidad,
                "nombre": o.nombre, "objeto": o.objeto, "modalidad": o.modalidad, "precio_base": o.precio_base,
                "departamento": o.departamento, "ciudad": o.ciudad, "fase": o.fase, "estado": o.estado,
                "fecha_publicacion": _iso(o.fecha_publicacion), "fecha_cierre": _iso(o.fecha_cierre),
                "url_proceso": o.url_proceso, "actualizado_en_fuente": _iso(o.actualizado_en_fuente),
                "sincronizada_en": _iso(o.sincronizada_en), "origen_registro": o.origen_registro,
                "registrada_por": o.registrada_por, "responsable": o.responsable,
                "seguida": s is not None,
                "notas": notas.get(o.id_proceso, 0),
                "carpetas": carpetas.get(o.id_proceso, []),
                "novedades_sin_revisar": len(sin_revisar),
                "ultima_novedad": ({"tipo": propias[0].tipo, "campo": propias[0].campo,
                                    "despues": propias[0].despues, "detectada_en": _iso(propias[0].detectada_en)}
                                   if propias else None),
                "ultimo_analisis": ({"tarea_id": t.id, "estado": t.estado, "recomendacion": t.resultado_recomendacion,
                                     "puntaje": t.resultado_puntaje, "creado_en": _iso(t.creado_en)} if t else None),
            })
        return resultado

    # --- Seguimiento (RF-018) ---

    def seguir(self, id_proceso: str, usuario: str, asignar_responsable: bool = False) -> dict:
        with self._sesiones() as db:
            o = db.get(Oportunidad, id_proceso)
            if o is None:
                raise OportunidadNoEncontradaError(id_proceso)
            s = db.execute(select(SeguimientoProceso).where(
                SeguimientoProceso.id_proceso == id_proceso, SeguimientoProceso.usuario == usuario)).scalar_one_or_none()
            ahora = datetime.utcnow()
            if s is None:
                db.add(SeguimientoProceso(id_proceso=id_proceso, usuario=usuario, activo=True,
                                          creado_en=ahora, revisado_en=ahora))
            elif not s.activo:
                s.activo, s.revisado_en = True, ahora
            if asignar_responsable and not o.responsable:
                o.responsable = usuario
            db.commit()
        return self.obtener(id_proceso, usuario)

    def dejar_de_seguir(self, id_proceso: str, usuario: str) -> dict:
        with self._sesiones() as db:
            if db.get(Oportunidad, id_proceso) is None:
                raise OportunidadNoEncontradaError(id_proceso)
            s = db.execute(select(SeguimientoProceso).where(
                SeguimientoProceso.id_proceso == id_proceso, SeguimientoProceso.usuario == usuario)).scalar_one_or_none()
            if s is not None:
                s.activo = False
            db.commit()
        return self.obtener(id_proceso, usuario)

    def asignar_responsable_si_falta(self, id_proceso: str, usuario: str) -> None:
        with self._sesiones() as db:
            o = db.get(Oportunidad, id_proceso)
            if o is not None and not o.responsable:
                o.responsable = usuario
                db.commit()

    def seguidos(self) -> List[dict]:
        """Procesos con al menos un seguidor activo: los que el trabajador revisa en cada barrido."""
        with self._sesiones() as db:
            filas = db.execute(select(Oportunidad).where(select(SeguimientoProceso.id).where(
                SeguimientoProceso.id_proceso == Oportunidad.id_proceso, SeguimientoProceso.activo)
                .exists())).scalars().all()
            return [{"id_proceso": o.id_proceso, "id_portafolio": o.id_portafolio} for o in filas]

    def novedades(self, id_proceso: str, usuario: Optional[str] = None, limite: int = 100) -> List[dict]:
        with self._sesiones() as db:
            s = db.execute(select(SeguimientoProceso).where(
                SeguimientoProceso.id_proceso == id_proceso, SeguimientoProceso.usuario == (usuario or ""),
                SeguimientoProceso.activo)).scalar_one_or_none()
            filas = db.execute(select(NovedadProceso).where(NovedadProceso.id_proceso == id_proceso)
                               .order_by(NovedadProceso.detectada_en.desc(), NovedadProceso.id.desc())
                               .limit(limite)).scalars().all()
            return [{"id": n.id, "tipo": n.tipo, "campo": n.campo, "antes": n.antes, "despues": n.despues,
                     "tarea_afectada": n.tarea_afectada, "detectada_en": _iso(n.detectada_en),
                     "nueva": bool(s and n.detectada_en > (s.revisado_en or s.creado_en))} for n in filas]

    def marcar_revisadas(self, id_proceso: str, usuario: str) -> None:
        with self._sesiones() as db:
            s = db.execute(select(SeguimientoProceso).where(
                SeguimientoProceso.id_proceso == id_proceso, SeguimientoProceso.usuario == usuario)).scalar_one_or_none()
            if s is not None:
                s.revisado_en = datetime.utcnow()
                db.commit()

    # --- Resultado de las sincronizaciones (HU-04 CA-04) ---

    def registrar_sincronizacion(self, inicio: datetime, estado: str, **datos) -> None:
        with self._sesiones() as db:
            db.add(Sincronizacion(inicio=inicio, fin=datetime.utcnow(), estado=estado, **datos))
            db.commit()

    def estado_sincronizacion(self, vigencia_horas: int) -> dict:
        with self._sesiones() as db:
            def ultima(*condiciones):
                return db.execute(select(Sincronizacion).where(*condiciones)
                                  .order_by(Sincronizacion.inicio.desc()).limit(1)).scalar_one_or_none()
            reciente, exitosa = ultima(), ultima(Sincronizacion.estado == "Exitosa")
            limite = datetime.utcnow() - timedelta(hours=vigencia_horas)
            desactualizada = exitosa is None or exitosa.fin < limite or (reciente is not None and reciente.estado != "Exitosa")
            aviso = None
            if desactualizada:
                from src.shared.horas import texto_local
                fecha = texto_local(exitosa.fin) if exitosa else None
                if reciente is not None and reciente.estado != "Exitosa":
                    aviso = (f"La última sincronización con SECOP II falló ({reciente.mensaje or 'sin detalle'}). "
                             + (f"Los datos son de la última sincronización exitosa, el {fecha}." if fecha
                                else "Aún no hay una sincronización exitosa."))
                else:
                    aviso = (f"Los datos pueden estar desactualizados: la última sincronización exitosa fue el {fecha}."
                             if fecha else "Aún no se ha sincronizado con SECOP II.")
            def a_dict(s):
                return None if s is None else {
                    "inicio": _iso(s.inicio), "fin": _iso(s.fin), "estado": s.estado, "procesos": s.procesos,
                    "nuevos": s.nuevos, "novedades": s.novedades, "coincidencias": s.coincidencias,
                    "mensaje": s.mensaje}
            return {"ultima": a_dict(reciente), "ultima_exitosa": a_dict(exitosa),
                    "desactualizada": desactualizada, "aviso": aviso}
