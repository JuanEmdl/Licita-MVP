"""
Reglas del puntaje configurables y versionadas (RF-032, RF-033, DA-14, RN-06).

Una versión de reglas fija los pesos por categoría de requisitos (suman 100) y los
umbrales de la recomendación. Nunca se edita: un cambio es una versión nueva.
Publicarla exige doble control (Tabla 61): el administrador la propone y la
gerencia comercial la confirma; quien propone no puede confirmar su propia
propuesta. Al confirmarla, la anterior pasa a Histórica y los análisis ya
emitidos conservan la versión con la que se calcularon.
"""
import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.shared.models import ReglaPuntaje
from src.shared.schemas.domain import PESOS_INICIALES, CategoriaRequisito  # noqa: F401 (se reexporta)

logger = logging.getLogger(__name__)

PROPUESTA = "Propuesta"
VIGENTE = "Vigente"
HISTORICA = "Histórica"
RECHAZADA = "Rechazada"



class ErrorReglas(Exception):
    """Error con mensaje apto para mostrar al usuario."""


class ReglasInvalidasError(ErrorReglas):
    pass


class VersionNoEncontradaError(ErrorReglas):
    pass


class OperacionReglasNoPermitidaError(ErrorReglas):
    pass


def validar_configuracion(pesos: Dict[str, float], umbral_ofertar: float, umbral_revision: float) -> Dict:
    """Devuelve la configuración normalizada o lanza ReglasInvalidasError."""
    categorias = {c.value for c in CategoriaRequisito}
    if set(pesos) != categorias:
        faltan, sobran = categorias - set(pesos), set(pesos) - categorias
        detalle = "; ".join(p for p in (
            f"faltan {', '.join(sorted(faltan))}" if faltan else "",
            f"no existen {', '.join(sorted(sobran))}" if sobran else "",
        ) if p)
        raise ReglasInvalidasError(f"Debe definir un peso para cada categoría ({detalle}).")
    if any(p < 0 for p in pesos.values()):
        raise ReglasInvalidasError("Los pesos no pueden ser negativos.")
    total = sum(pesos.values())
    if abs(total - 100.0) > 0.01:
        raise ReglasInvalidasError(f"Las ponderaciones deben sumar 100; suman {total:g}.")
    if not 0 <= umbral_revision <= umbral_ofertar <= 100:
        raise ReglasInvalidasError(
            "Los umbrales deben cumplir 0 ≤ umbral de revisión ≤ umbral para ofertar ≤ 100."
        )
    return {
        "pesos": {c: float(pesos[c]) for c in sorted(categorias)},
        "umbral_ofertar": float(umbral_ofertar),
        "umbral_revision": float(umbral_revision),
    }


class RepositorioReglas:

    def __init__(self, fabrica_sesiones: Optional[Callable[[], Session]] = None, auditoria=None):
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        self._sesiones = fabrica_sesiones
        self._auditoria = auditoria

    @property
    def auditoria(self):
        # Diferida: la bitácora usa PostgreSQL y las pruebas inyectan una falsa.
        if self._auditoria is None:
            from src.worker_analysis.reports.auditoria import RegistradorAuditoria
            self._auditoria = RegistradorAuditoria()
        return self._auditoria

    # --- Consulta ---

    def vigente(self) -> dict:
        with self._sesiones() as db:
            regla = db.execute(select(ReglaPuntaje).where(ReglaPuntaje.estado == VIGENTE)).scalar_one_or_none()
            if regla is None:
                raise VersionNoEncontradaError("No hay reglas del puntaje vigentes.")
            return self._a_dict(regla)

    def obtener(self, version: int) -> dict:
        with self._sesiones() as db:
            regla = db.get(ReglaPuntaje, version)
            if regla is None:
                raise VersionNoEncontradaError(f"No existe la versión {version} de las reglas.")
            return self._a_dict(regla)

    def historial(self) -> List[dict]:
        with self._sesiones() as db:
            consulta = select(ReglaPuntaje).order_by(ReglaPuntaje.version.desc())
            return [self._a_dict(r) for r in db.execute(consulta).scalars().all()]

    # --- Ciclo de vida ---

    def asegurar_version_inicial(self, umbral_ofertar: float, umbral_revision: float) -> None:
        """Crea la versión 1 con los valores provisionales si todavía no hay reglas vigentes."""
        with self._sesiones() as db:
            if db.execute(select(ReglaPuntaje.version).where(ReglaPuntaje.estado == VIGENTE)).first():
                return
            db.add(ReglaPuntaje(
                configuracion=validar_configuracion(PESOS_INICIALES, umbral_ofertar, umbral_revision),
                estado=VIGENTE,
                activa=True,
                nota="Valores provisionales hasta que la gerencia comercial apruebe la matriz (ASR-14).",
                creado_por="sistema",
                confirmado_por="sistema",
                confirmado_en=datetime.utcnow(),
            ))
            db.commit()
        logger.info("Reglas del puntaje: se creó la versión inicial con valores provisionales.")

    def proponer(self, pesos: Dict[str, float], umbral_ofertar: float, umbral_revision: float,
                 usuario: str, nota: Optional[str] = None) -> dict:
        configuracion = validar_configuracion(pesos, umbral_ofertar, umbral_revision)
        with self._sesiones() as db:
            pendiente = db.execute(
                select(ReglaPuntaje.version).where(ReglaPuntaje.estado == PROPUESTA)).first()
            if pendiente:
                raise OperacionReglasNoPermitidaError(
                    f"Ya hay una propuesta pendiente (versión {pendiente[0]}): la gerencia debe "
                    "confirmarla o rechazarla antes de proponer otra.")
            regla = ReglaPuntaje(configuracion=configuracion, estado=PROPUESTA, activa=False,
                                 nota=(nota or "").strip() or None, creado_por=usuario)
            db.add(regla)
            db.flush()
            self.auditoria.registrar_evento(
                f"reglas-v{regla.version}", "REGLAS_PROPUESTAS",
                {"version": regla.version, **configuracion, "nota": regla.nota}, registrado_por=usuario)
            db.commit()
            return self._a_dict(regla)

    def confirmar(self, version: int, usuario: str) -> dict:
        """Publica la propuesta: pasa a Vigente y la anterior a Histórica, en una transacción."""
        with self._sesiones() as db:
            regla = self._propuesta(db, version)
            if regla.creado_por == usuario:
                raise OperacionReglasNoPermitidaError(
                    "Doble control: quien propone una versión no puede confirmarla.")
            anterior = db.execute(select(ReglaPuntaje).where(ReglaPuntaje.estado == VIGENTE)).scalar_one_or_none()
            if anterior is not None:
                anterior.estado, anterior.activa = HISTORICA, False
                db.flush()  # El índice único admite una sola vigente: primero se retira la anterior.
            regla.estado, regla.activa = VIGENTE, True
            regla.confirmado_por, regla.confirmado_en = usuario, datetime.utcnow()
            self.auditoria.registrar_evento(
                f"reglas-v{version}", "REGLAS_PUBLICADAS",
                {"version": version, "version_anterior": anterior.version if anterior else None,
                 "propuesta_por": regla.creado_por, **regla.configuracion},
                registrado_por=usuario)
            db.commit()
            return self._a_dict(regla)

    def rechazar(self, version: int, usuario: str, motivo: str) -> dict:
        motivo = (motivo or "").strip()
        if not motivo:
            raise ReglasInvalidasError("Indique el motivo del rechazo.")
        with self._sesiones() as db:
            regla = self._propuesta(db, version)
            regla.estado = RECHAZADA
            regla.confirmado_por, regla.confirmado_en = usuario, datetime.utcnow()
            regla.nota = motivo
            self.auditoria.registrar_evento(
                f"reglas-v{version}", "REGLAS_RECHAZADAS", {"version": version, "motivo": motivo},
                registrado_por=usuario)
            db.commit()
            return self._a_dict(regla)

    @staticmethod
    def _propuesta(db: Session, version: int) -> ReglaPuntaje:
        regla = db.get(ReglaPuntaje, version)
        if regla is None:
            raise VersionNoEncontradaError(f"No existe la versión {version} de las reglas.")
        if regla.estado != PROPUESTA:
            raise OperacionReglasNoPermitidaError(
                f"La versión {version} está en estado «{regla.estado}»; solo se confirma o rechaza una propuesta.")
        return regla

    @staticmethod
    def _a_dict(r: ReglaPuntaje) -> dict:
        configuracion = r.configuracion or {}
        return {
            "version": r.version,
            "estado": r.estado,
            "pesos": configuracion.get("pesos", {}),
            "umbral_ofertar": configuracion.get("umbral_ofertar"),
            "umbral_revision": configuracion.get("umbral_revision"),
            "nota": r.nota,
            "creado_por": r.creado_por,
            "creado_en": r.creado_en.isoformat() if r.creado_en else None,
            "confirmado_por": r.confirmado_por,
            "confirmado_en": r.confirmado_en.isoformat() if r.confirmado_en else None,
        }
