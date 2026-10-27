"""
Gestión comercial de las oportunidades (RF-040): carpetas, notas y responsable.

- Carpetas: cada usuario organiza las oportunidades en sus propias carpetas; una carpeta
  ajena se trata como inexistente (Tabla 61, "solo las carpetas del propio usuario").
- Notas: quedan en la oportunidad con su autor y su fecha, a la vista de quien consulta la
  oportunidad; solo su autor puede borrarlas.
- Responsable: el analista a cargo de la oportunidad, que es quien gestiona su expediente
  (Tabla 61, carga manual). Se valida contra los usuarios activos con rol de analista.
"""
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.shared.models import Carpeta, CarpetaOportunidad, NotaOportunidad, Oportunidad, Usuario
from src.shared.oportunidades_repo import OportunidadNoEncontradaError
from src.shared.roles import ANALISTA


class CarpetaNoEncontradaError(Exception):
    pass


class CarpetaDuplicadaError(Exception):
    pass


class NotaNoEncontradaError(Exception):
    pass


class ResponsableInvalidoError(ValueError):
    pass


def _iso(valor: Optional[datetime]) -> Optional[str]:
    return valor.isoformat() if valor else None


class RepositorioGestion:

    def __init__(self, fabrica_sesiones: Optional[Callable[[], Session]] = None):
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        self._sesiones = fabrica_sesiones

    # --- Carpetas ---

    @staticmethod
    def _propia(db: Session, carpeta_id: int, propietario: str) -> Carpeta:
        carpeta = db.get(Carpeta, carpeta_id)
        if carpeta is None or carpeta.propietario != propietario:
            raise CarpetaNoEncontradaError(carpeta_id)
        return carpeta

    def carpetas(self, propietario: str) -> List[dict]:
        with self._sesiones() as db:
            totales = dict(db.execute(
                select(CarpetaOportunidad.carpeta_id, func.count()).join(Carpeta, Carpeta.id == CarpetaOportunidad.carpeta_id)
                .where(Carpeta.propietario == propietario).group_by(CarpetaOportunidad.carpeta_id)).all())
            return [{"id": c.id, "nombre": c.nombre, "creada_en": _iso(c.creada_en), "oportunidades": totales.get(c.id, 0)}
                    for c in db.execute(select(Carpeta).where(Carpeta.propietario == propietario)
                                        .order_by(Carpeta.nombre)).scalars()]

    def crear_carpeta(self, propietario: str, nombre: str) -> dict:
        with self._sesiones() as db:
            carpeta = Carpeta(propietario=propietario, nombre=nombre.strip(), creada_en=datetime.utcnow())
            db.add(carpeta)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise CarpetaDuplicadaError(nombre)
            return {"id": carpeta.id, "nombre": carpeta.nombre, "creada_en": _iso(carpeta.creada_en), "oportunidades": 0}

    def renombrar_carpeta(self, carpeta_id: int, propietario: str, nombre: str) -> dict:
        with self._sesiones() as db:
            carpeta = self._propia(db, carpeta_id, propietario)
            carpeta.nombre = nombre.strip()
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise CarpetaDuplicadaError(nombre)
        return next(c for c in self.carpetas(propietario) if c["id"] == carpeta_id)

    def eliminar_carpeta(self, carpeta_id: int, propietario: str) -> None:
        """Borra la carpeta, no las oportunidades que contenía."""
        with self._sesiones() as db:
            carpeta = self._propia(db, carpeta_id, propietario)
            for enlace in db.execute(select(CarpetaOportunidad).where(
                    CarpetaOportunidad.carpeta_id == carpeta_id)).scalars():
                db.delete(enlace)
            db.delete(carpeta)
            db.commit()

    def agregar_a_carpeta(self, carpeta_id: int, propietario: str, ids: Iterable[str]) -> int:
        with self._sesiones() as db:
            self._propia(db, carpeta_id, propietario)
            ids = list(dict.fromkeys(ids))
            existentes = set(db.execute(select(Oportunidad.id_proceso).where(Oportunidad.id_proceso.in_(ids))).scalars())
            ya = set(db.execute(select(CarpetaOportunidad.id_proceso).where(
                CarpetaOportunidad.carpeta_id == carpeta_id, CarpetaOportunidad.id_proceso.in_(ids))).scalars())
            nuevos = [i for i in ids if i in existentes and i not in ya]
            for id_proceso in nuevos:
                db.add(CarpetaOportunidad(carpeta_id=carpeta_id, id_proceso=id_proceso, agregada_en=datetime.utcnow()))
            db.commit()
            return len(nuevos)

    def quitar_de_carpeta(self, carpeta_id: int, propietario: str, ids: Iterable[str]) -> int:
        with self._sesiones() as db:
            self._propia(db, carpeta_id, propietario)
            enlaces = db.execute(select(CarpetaOportunidad).where(
                CarpetaOportunidad.carpeta_id == carpeta_id, CarpetaOportunidad.id_proceso.in_(list(ids)))).scalars().all()
            for enlace in enlaces:
                db.delete(enlace)
            db.commit()
            return len(enlaces)

    def verificar_carpeta(self, carpeta_id: int, propietario: str) -> None:
        with self._sesiones() as db:
            self._propia(db, carpeta_id, propietario)

    # --- Notas ---

    def notas(self, id_proceso: str) -> List[dict]:
        with self._sesiones() as db:
            return [self._nota(n) for n in db.execute(
                select(NotaOportunidad).where(NotaOportunidad.id_proceso == id_proceso)
                .order_by(NotaOportunidad.creada_en.desc(), NotaOportunidad.id.desc())).scalars()]

    def agregar_nota(self, id_proceso: str, autor: str, texto: str) -> dict:
        with self._sesiones() as db:
            nota = NotaOportunidad(id_proceso=id_proceso, autor=autor, texto=texto.strip(), creada_en=datetime.utcnow())
            db.add(nota)
            db.commit()
            return self._nota(nota)

    def eliminar_nota(self, nota_id: int, id_proceso: str, autor: str) -> dict:
        """Solo el autor borra su nota; devuelve la nota borrada para la bitácora."""
        with self._sesiones() as db:
            nota = db.get(NotaOportunidad, nota_id)
            if nota is None or nota.id_proceso != id_proceso or nota.autor != autor:
                raise NotaNoEncontradaError(nota_id)
            datos = self._nota(nota)
            db.delete(nota)
            db.commit()
            return datos

    @staticmethod
    def _nota(n: NotaOportunidad) -> dict:
        return {"id": n.id, "id_proceso": n.id_proceso, "autor": n.autor, "texto": n.texto, "creada_en": _iso(n.creada_en)}

    # --- Responsable ---

    def analistas(self) -> List[dict]:
        """Usuarios a los que se puede asignar una oportunidad."""
        with self._sesiones() as db:
            return [{"email": u.email, "nombre": u.nombre} for u in db.execute(
                select(Usuario).where(Usuario.rol == ANALISTA, Usuario.activo).order_by(Usuario.nombre)).scalars()]

    def asignar_responsable(self, id_proceso: str, responsable: Optional[str]) -> Dict[str, Optional[str]]:
        """Devuelve el responsable anterior y el nuevo. None deja la oportunidad sin asignar."""
        with self._sesiones() as db:
            o = db.get(Oportunidad, id_proceso)
            if o is None:
                raise OportunidadNoEncontradaError(id_proceso)
            if responsable:
                hay_usuarios = db.execute(select(func.count()).select_from(Usuario)).scalar_one() > 0
                usuario = db.execute(select(Usuario).where(Usuario.email == responsable)).scalar_one_or_none()
                # Sin usuarios locales (modo desarrollo u OIDC) no hay contra qué validar.
                if hay_usuarios and (usuario is None or not usuario.activo or usuario.rol != ANALISTA):
                    raise ResponsableInvalidoError(
                        f"{responsable} no es un analista comercial activo: solo un analista puede quedar a cargo.")
            antes = o.responsable
            o.responsable = responsable or None
            db.commit()
            return {"antes": antes, "despues": o.responsable}
