"""
Notificaciones y preferencias (RF-016, RF-017, RF-020).

Cada aviso se guarda primero en la base y aparece en la aplicación; el correo es un canal
adicional que el notificador intenta después según la preferencia del usuario. Así, si el
servicio de correo falla, el aviso sigue disponible en el tablero y ningún análisis se
detiene por esa causa (Tabla 16).

- La clave de cada aviso evita repetirlo al mismo destinatario (HU-04 CA-02): una
  oportunidad se avisa una sola vez aunque coincida con varios perfiles del usuario.
- La frecuencia "Resumen diario" junta en un solo correo los avisos pendientes del día
  (HU-04 CA-03); "Inmediata" envía cada uno en la siguiente ejecución del notificador.
"""
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.shared.models import (
    CoincidenciaPerfil,
    NovedadProceso,
    Notificacion,
    Oportunidad,
    PerfilBusqueda,
    PreferenciaNotificacion,
    SeguimientoProceso,
)


class Canal:
    APLICACION = "Aplicación"
    CORREO = "Correo y aplicación"
    TODOS = (APLICACION, CORREO)


class Frecuencia:
    INMEDIATA = "Inmediata"
    RESUMEN_DIARIO = "Resumen diario"
    TODAS = (INMEDIATA, RESUMEN_DIARIO)


class TipoNotificacion:
    OPORTUNIDAD = "Oportunidad"
    NOVEDAD = "Novedad"
    REVISION = "Revisión pendiente"
    SUSPENSION = "Análisis suspendido"
    ASIGNACION = "Oportunidad asignada"


PREFERENCIA_INICIAL = {"canal": Canal.CORREO, "frecuencia": Frecuencia.INMEDIATA}


def _iso(valor: Optional[datetime]) -> Optional[str]:
    return valor.isoformat() if valor else None


def _pesos(valor: Optional[float]) -> str:
    return f"${valor:,.0f}".replace(",", ".") if valor else "sin cuantía publicada"


def _fecha(valor: Optional[datetime]) -> str:
    return valor.strftime("%Y-%m-%d") if valor else "sin fecha publicada"


class RepositorioNotificaciones:

    def __init__(self, fabrica_sesiones: Optional[Callable[[], Session]] = None):
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        self._sesiones = fabrica_sesiones

    # --- Preferencias (RF-016) ---

    def preferencias(self, usuario: str) -> dict:
        with self._sesiones() as db:
            p = db.get(PreferenciaNotificacion, usuario)
            if p is None:
                return {"usuario": usuario, **PREFERENCIA_INICIAL, "ultimo_resumen_en": None, "configurada": False}
            return {"usuario": usuario, "canal": p.canal, "frecuencia": p.frecuencia,
                    "ultimo_resumen_en": _iso(p.ultimo_resumen_en), "configurada": True}

    def guardar_preferencias(self, usuario: str, canal: str, frecuencia: str) -> dict:
        if canal not in Canal.TODOS or frecuencia not in Frecuencia.TODAS:
            raise ValueError("Canal o frecuencia no válidos.")
        with self._sesiones() as db:
            p = db.get(PreferenciaNotificacion, usuario)
            if p is None:
                p = PreferenciaNotificacion(usuario=usuario)
                db.add(p)
            p.canal, p.frecuencia = canal, frecuencia
            db.commit()
        return self.preferencias(usuario)

    def marcar_resumen(self, usuario: str, cuando: datetime) -> None:
        with self._sesiones() as db:
            p = db.get(PreferenciaNotificacion, usuario)
            if p is None:
                p = PreferenciaNotificacion(usuario=usuario, **PREFERENCIA_INICIAL)
                db.add(p)
            p.ultimo_resumen_en = cuando
            db.commit()

    # --- Generación de avisos ---

    def crear(self, destinatario: str, tipo: str, clave: str, titulo: str, cuerpo: str,
              id_proceso: Optional[str] = None, tarea_id: Optional[str] = None,
              enlace: Optional[str] = None) -> Optional[dict]:
        """Registra el aviso; None si ese destinatario ya lo recibió (misma clave)."""
        with self._sesiones() as db:
            if db.execute(select(Notificacion.id).where(Notificacion.destinatario == destinatario,
                                                        Notificacion.clave == clave)).first():
                return None
            n = Notificacion(destinatario=destinatario, tipo=tipo, clave=clave, titulo=titulo[:250],
                             cuerpo=cuerpo, id_proceso=id_proceso, tarea_id=tarea_id, enlace=enlace,
                             creada_en=datetime.utcnow())
            db.add(n)
            try:
                db.commit()
            except IntegrityError:  # otro proceso lo registró al mismo tiempo
                db.rollback()
                return None
            return self._a_dict(n)

    def generar_por_coincidencias(self, coincidencias: Iterable[Dict[str, Any]]) -> List[dict]:
        """RF-017: un aviso por oportunidad nueva al dueño de los perfiles con que coincidió."""
        por_destinatario: Dict[tuple, List[str]] = {}
        ahora = datetime.utcnow()
        with self._sesiones() as db:
            for c in coincidencias:
                perfil = db.get(PerfilBusqueda, c["perfil_id"])
                if perfil is None:
                    continue
                por_destinatario.setdefault((perfil.propietario, c["id_proceso"]), []).append(perfil.nombre)
                registro = db.execute(select(CoincidenciaPerfil).where(
                    CoincidenciaPerfil.perfil_id == c["perfil_id"],
                    CoincidenciaPerfil.id_proceso == c["id_proceso"])).scalar_one_or_none()
                if registro is not None and registro.notificada_en is None:
                    registro.notificada_en = ahora
            # Se copian antes del commit: la sesión expira los objetos al confirmar.
            oportunidades = {o.id_proceso: self._datos_oportunidad(o) for o in db.execute(select(Oportunidad).where(
                Oportunidad.id_proceso.in_({p for _, p in por_destinatario}))).scalars()}
            db.commit()
        creadas = []
        for (destinatario, id_proceso), perfiles in por_destinatario.items():
            o = oportunidades.get(id_proceso)
            if o is None:
                continue
            # HU-04 CA-01: el proceso, la entidad y la fecha de cierre disponible.
            cuerpo = (f"{o['objeto']}\n"
                      f"Entidad: {o['entidad'] or 'sin dato'}\n"
                      f"Cierre: {_fecha(o['fecha_cierre'])} · Cuantía: {_pesos(o['precio_base'])}\n"
                      f"Coincide con tu perfil: {', '.join(sorted(set(perfiles)))}")
            n = self.crear(destinatario, TipoNotificacion.OPORTUNIDAD, f"oportunidad:{id_proceso}",
                           f"Nueva oportunidad {id_proceso} · {o['entidad'] or ''}".strip(" ·"), cuerpo,
                           id_proceso=id_proceso, enlace=o['url_proceso'])
            if n:
                creadas.append(n)
        return creadas

    def generar_por_novedades(self, novedades: Iterable[Dict[str, Any]]) -> List[dict]:
        """RF-020: cada novedad de un proceso seguido, a cada usuario que lo sigue."""
        creadas = []
        ahora = datetime.utcnow()
        for novedad in novedades:
            with self._sesiones() as db:
                seguidores = list(db.execute(select(SeguimientoProceso.usuario).where(
                    SeguimientoProceso.id_proceso == novedad["id_proceso"], SeguimientoProceso.activo)).scalars())
                registro_o = db.get(Oportunidad, novedad["id_proceso"])
                o = self._datos_oportunidad(registro_o) if registro_o else None
                registro = db.get(NovedadProceso, novedad["id"])
                if registro is not None and registro.notificada_en is None:
                    registro.notificada_en = ahora
                db.commit()
            cambio = " → ".join(v for v in (novedad.get("antes"), novedad.get("despues")) if v) or "—"
            o = o or {"objeto": "", "entidad": None, "fecha_cierre": None, "url_proceso": None}
            cuerpo = (f"{o['objeto']}\n"
                      f"Entidad: {o['entidad'] or 'sin dato'} · Cierre: {_fecha(o['fecha_cierre'])}\n"
                      f"{novedad['campo']}: {cambio}")
            if novedad.get("tarea_afectada"):
                cuerpo += (f"\nEl análisis {novedad['tarea_afectada'][:8]} puede haber quedado desactualizado: "
                           "solicita uno nuevo con el documento cargado; solo los requisitos que el cambio "
                           "afecta vuelven a revisión.")
            for usuario in seguidores:
                n = self.crear(usuario, TipoNotificacion.NOVEDAD, f"novedad:{novedad['id']}",
                               f"{novedad['tipo']} en {novedad['id_proceso']}: {novedad['campo']}", cuerpo,
                               id_proceso=novedad["id_proceso"], enlace=o["url_proceso"])
                if n:
                    creadas.append(n)
        return creadas

    @staticmethod
    def _datos_oportunidad(o: Oportunidad) -> dict:
        return {"objeto": o.objeto or o.nombre or "", "entidad": o.entidad, "fecha_cierre": o.fecha_cierre,
                "precio_base": o.precio_base, "url_proceso": o.url_proceso}

    def responsable_de(self, id_proceso: Optional[str]) -> Optional[str]:
        if not id_proceso:
            return None
        with self._sesiones() as db:
            o = db.get(Oportunidad, id_proceso)
            return o.responsable if o else None

    # --- Bandeja de la aplicación ---

    def listar(self, destinatario: str, solo_no_leidas: bool = False, limite: int = 50) -> dict:
        with self._sesiones() as db:
            condiciones = [Notificacion.destinatario == destinatario]
            no_leidas = db.execute(select(func.count()).select_from(Notificacion).where(
                *condiciones, Notificacion.leida_en.is_(None))).scalar_one()
            if solo_no_leidas:
                condiciones.append(Notificacion.leida_en.is_(None))
            filas = db.execute(select(Notificacion).where(*condiciones)
                               .order_by(Notificacion.creada_en.desc(), Notificacion.id.desc())
                               .limit(max(1, min(limite, 200)))).scalars().all()
            return {"no_leidas": no_leidas, "notificaciones": [self._a_dict(n) for n in filas]}

    def marcar_leida(self, notificacion_id: int, destinatario: str) -> bool:
        with self._sesiones() as db:
            n = db.get(Notificacion, notificacion_id)
            if n is None or n.destinatario != destinatario:
                return False
            n.leida_en = n.leida_en or datetime.utcnow()
            db.commit()
            return True

    def marcar_todas_leidas(self, destinatario: str) -> int:
        with self._sesiones() as db:
            filas = db.execute(select(Notificacion).where(Notificacion.destinatario == destinatario,
                                                          Notificacion.leida_en.is_(None))).scalars().all()
            ahora = datetime.utcnow()
            for n in filas:
                n.leida_en = ahora
            db.commit()
            return len(filas)

    # --- Envío por correo ---

    def pendientes_de_correo(self, max_intentos: int) -> Dict[str, dict]:
        """Avisos sin enviar de los usuarios que eligieron el correo, con su preferencia."""
        with self._sesiones() as db:
            preferencias = {p.usuario: p for p in db.execute(select(PreferenciaNotificacion)).scalars()}
            # Lo que el usuario ya leyó en la aplicación no se le reenvía por correo.
            filas = db.execute(select(Notificacion).where(
                Notificacion.enviada_en.is_(None), Notificacion.leida_en.is_(None),
                Notificacion.intentos < max_intentos)
                .order_by(Notificacion.creada_en, Notificacion.id)).scalars().all()
            pendientes: Dict[str, dict] = {}
            for n in filas:
                p = preferencias.get(n.destinatario)
                canal = p.canal if p else PREFERENCIA_INICIAL["canal"]
                if canal != Canal.CORREO:
                    continue
                grupo = pendientes.setdefault(n.destinatario, {
                    "frecuencia": p.frecuencia if p else PREFERENCIA_INICIAL["frecuencia"],
                    "ultimo_resumen_en": p.ultimo_resumen_en if p else None, "notificaciones": []})
                grupo["notificaciones"].append(self._a_dict(n))
            return pendientes

    def registrar_envio(self, ids: Iterable[int], error: Optional[str] = None) -> None:
        with self._sesiones() as db:
            for n in db.execute(select(Notificacion).where(Notificacion.id.in_(list(ids)))).scalars():
                n.intentos += 1
                if error is None:
                    n.enviada_en, n.ultimo_error = datetime.utcnow(), None
                else:
                    n.ultimo_error = error[:500]
            db.commit()

    @staticmethod
    def _a_dict(n: Notificacion) -> dict:
        return {
            "id": n.id, "destinatario": n.destinatario, "tipo": n.tipo, "titulo": n.titulo, "cuerpo": n.cuerpo,
            "id_proceso": n.id_proceso, "tarea_id": n.tarea_id, "enlace": n.enlace,
            "creada_en": _iso(n.creada_en), "leida_en": _iso(n.leida_en), "enviada_en": _iso(n.enviada_en),
            "intentos": n.intentos, "ultimo_error": n.ultimo_error,
        }
