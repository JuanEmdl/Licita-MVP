"""
Perfiles de búsqueda (RF-015) y sus coincidencias (RF-017).

Tabla 61: cada usuario consulta y modifica solo los perfiles que él mismo creó; el
alcance por pertenencia se resuelve aquí, en el servidor, y no en la interfaz. Un
perfil ajeno se trata como inexistente (404) para no revelar los de otros usuarios.

Cada proceso coincide una sola vez con cada perfil: una sincronización posterior sin
novedades no lo vuelve a registrar ni a notificar (HU-04 CA-02).
"""
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.shared.models import CoincidenciaPerfil, Oportunidad, PerfilBusqueda

CAMPOS_EDITABLES = ("nombre", "palabras_clave", "entidades", "departamentos", "modalidades",
                    "cuantia_min", "cuantia_max", "activo")


class PerfilNoEncontradoError(Exception):
    pass


def _iso(valor: Optional[datetime]) -> Optional[str]:
    return valor.isoformat() if valor else None


class RepositorioPerfiles:

    def __init__(self, fabrica_sesiones: Optional[Callable[[], Session]] = None):
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        self._sesiones = fabrica_sesiones

    def _propio(self, db: Session, perfil_id: int, propietario: str) -> PerfilBusqueda:
        perfil = db.get(PerfilBusqueda, perfil_id)
        if perfil is None or perfil.propietario != propietario:
            raise PerfilNoEncontradoError(perfil_id)
        return perfil

    def listar(self, propietario: str) -> List[dict]:
        with self._sesiones() as db:
            perfiles = db.execute(select(PerfilBusqueda).where(PerfilBusqueda.propietario == propietario)
                                  .order_by(PerfilBusqueda.creado_en, PerfilBusqueda.id)).scalars().all()
            totales: Dict[int, int] = {}
            for perfil_id in db.execute(select(CoincidenciaPerfil.perfil_id).where(
                    CoincidenciaPerfil.perfil_id.in_([p.id for p in perfiles]))).scalars():
                totales[perfil_id] = totales.get(perfil_id, 0) + 1
            return [{**self._a_dict(p), "coincidencias": totales.get(p.id, 0)} for p in perfiles]

    def crear(self, propietario: str, datos: Dict[str, Any]) -> dict:
        with self._sesiones() as db:
            perfil = PerfilBusqueda(propietario=propietario, **{c: datos.get(c) for c in CAMPOS_EDITABLES
                                                                  if datos.get(c) is not None})
            db.add(perfil)
            db.commit()
            return self._a_dict(perfil)

    def actualizar(self, perfil_id: int, propietario: str, cambios: Dict[str, Any]) -> dict:
        with self._sesiones() as db:
            perfil = self._propio(db, perfil_id, propietario)
            for campo in CAMPOS_EDITABLES:
                if campo in cambios:
                    setattr(perfil, campo, cambios[campo])
            perfil.actualizado_en = datetime.utcnow()
            db.commit()
            return self._a_dict(perfil)

    def eliminar(self, perfil_id: int, propietario: str) -> None:
        with self._sesiones() as db:
            perfil = self._propio(db, perfil_id, propietario)
            for c in db.execute(select(CoincidenciaPerfil).where(CoincidenciaPerfil.perfil_id == perfil_id)).scalars():
                db.delete(c)
            db.delete(perfil)
            db.commit()

    def activos(self) -> List[dict]:
        with self._sesiones() as db:
            return [self._a_dict(p) for p in db.execute(
                select(PerfilBusqueda).where(PerfilBusqueda.activo)).scalars()]

    def registrar_coincidencias(self, pares: Iterable[tuple]) -> List[dict]:
        """pares: (perfil_id, id_proceso). Devuelve solo las coincidencias nuevas."""
        nuevas = []
        ahora = datetime.utcnow()
        pares = list(dict.fromkeys(pares))
        with self._sesiones() as db:
            existentes = {(c.perfil_id, c.id_proceso) for c in db.execute(select(CoincidenciaPerfil).where(
                CoincidenciaPerfil.perfil_id.in_({p for p, _ in pares}))).scalars()}
            for perfil_id, id_proceso in pares:
                if (perfil_id, id_proceso) in existentes:
                    continue
                db.add(CoincidenciaPerfil(perfil_id=perfil_id, id_proceso=id_proceso, detectada_en=ahora))
                nuevas.append({"perfil_id": perfil_id, "id_proceso": id_proceso, "detectada_en": _iso(ahora)})
            db.commit()
        return nuevas

    def coincidencias(self, propietario: str, perfil_id: Optional[int] = None, limite: int = 100) -> List[dict]:
        """Procesos que coincidieron con los perfiles del usuario, con proceso, entidad y cierre (RF-017)."""
        with self._sesiones() as db:
            consulta = (select(CoincidenciaPerfil, PerfilBusqueda, Oportunidad)
                        .join(PerfilBusqueda, PerfilBusqueda.id == CoincidenciaPerfil.perfil_id)
                        .join(Oportunidad, Oportunidad.id_proceso == CoincidenciaPerfil.id_proceso)
                        .where(PerfilBusqueda.propietario == propietario)
                        .order_by(CoincidenciaPerfil.detectada_en.desc()).limit(limite))
            if perfil_id is not None:
                self._propio(db, perfil_id, propietario)
                consulta = consulta.where(CoincidenciaPerfil.perfil_id == perfil_id)
            return [{"perfil_id": p.id, "perfil": p.nombre, "id_proceso": o.id_proceso, "entidad": o.entidad,
                     "objeto": o.objeto or o.nombre, "fecha_cierre": _iso(o.fecha_cierre),
                     "precio_base": o.precio_base, "url_proceso": o.url_proceso,
                     "detectada_en": _iso(c.detectada_en), "notificada_en": _iso(c.notificada_en)}
                    for c, p, o in db.execute(consulta).all()]

    @staticmethod
    def _a_dict(p: PerfilBusqueda) -> dict:
        return {
            "id": p.id, "propietario": p.propietario, "nombre": p.nombre,
            "palabras_clave": p.palabras_clave or [], "entidades": p.entidades or [],
            "departamentos": p.departamentos or [], "modalidades": p.modalidades or [],
            "cuantia_min": p.cuantia_min, "cuantia_max": p.cuantia_max, "activo": bool(p.activo),
            "creado_en": _iso(p.creado_en), "actualizado_en": _iso(p.actualizado_en),
        }
