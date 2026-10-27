import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _huella(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


class RegistradorAuditoria:
    """
    Registrador de Auditoría (RF-042, RNF-016, ASR-06).
    Anexa eventos críticos a la tabla bitacora_auditoria con autor, fecha, tarea y
    valores modificados. Cada registro guarda la huella del anterior (hash_previo), de
    modo que alterar o borrar una fila rompe la cadena y se detecta con verificar().
    Además, un disparador de PostgreSQL rechaza UPDATE, DELETE y TRUNCATE sobre la
    tabla (src/shared/database.py): la bitácora es de solo anexado.

    Si la base no acepta el registro se lanza la excepción: un evento crítico sin
    evidencia de auditoría no debe darse por confirmado (RNF-016).
    """

    def __init__(self, registrado_por: str = "sistema"):
        self.registrado_por = registrado_por

    def registrar_evento(
        self,
        tarea_id: str,
        tipo_evento: str,
        detalles: Dict[str, Any],
        hash_documento: Optional[str] = None,
        registrado_por: Optional[str] = None,
        licitacion_id: Optional[str] = None,
        db=None,
    ) -> None:
        """
        db: sesión del llamador. Si se da, el evento entra en su transacción y lo
        confirma el llamador (Tabla 19: el informe, su huella y la tarea finalizada
        quedan juntos o no queda nada). Sin ella, se abre y confirma una sesión propia.
        """
        if db is not None:
            self._anexar(db, tarea_id, tipo_evento, detalles, hash_documento, registrado_por, licitacion_id)
            return

        from src.shared.database import get_db

        with get_db() as sesion:
            self._anexar(sesion, tarea_id, tipo_evento, detalles, hash_documento, registrado_por, licitacion_id)
            sesion.commit()

    def _anexar(self, db, tarea_id, tipo_evento, detalles, hash_documento, registrado_por, licitacion_id) -> None:
        from sqlalchemy import select

        from src.shared.models import BitacoraAuditoria

        detalles_json = json.dumps(detalles, ensure_ascii=False, sort_keys=True, default=str)
        # Bloqueo de tabla corto: dos procesos no pueden encadenar sobre el mismo registro previo.
        db.execute(_sql_bloqueo())
        ultimo = db.execute(
            select(BitacoraAuditoria).order_by(BitacoraAuditoria.id.desc()).limit(1)
        ).scalar_one_or_none()
        hash_previo = self.huella_registro(ultimo) if ultimo else "GENESIS"
        db.add(BitacoraAuditoria(
            licitacion_id=licitacion_id,
            tarea_id=tarea_id,
            accion=tipo_evento,
            hash_documento=hash_documento or _huella(detalles_json),
            hash_previo=hash_previo,
            registrado_por=registrado_por or self.registrado_por,
            detalles=json.loads(detalles_json),
        ))
        db.flush()
        logger.info(f"AUDITORÍA [{tipo_evento}] tarea={tarea_id} registrada en la bitácora.")

    @staticmethod
    def huella_registro(registro) -> str:
        return _huella(f"{registro.hash_previo}|{registro.hash_documento}|{registro.accion}|{registro.tarea_id}")

    def registrar_huella_informe(self, tarea_id: str, informe_path: str, huella_sha256: str, db=None) -> None:
        """Registra la huella criptográfica de un informe emitido (ASR-06)."""
        self.registrar_evento(
            tarea_id,
            "INFORME_GENERADO",
            {"informe_path": informe_path, "huella_sha256": huella_sha256},
            hash_documento=huella_sha256,
            db=db,
        )

    # --- Verificación y consulta (RF-042, Tabla 61: la consultan el Gerente y el Administrador) ---

    def verificar(self, db=None) -> dict:
        """
        Recorre la cadena completa. Devuelve si está íntegra, cuántos registros tiene y,
        si no, el primer registro donde la cadena se rompe.
        """
        from sqlalchemy import select

        from src.shared.database import get_db
        from src.shared.models import BitacoraAuditoria

        def recorrer(sesion) -> dict:
            esperado, total = "GENESIS", 0
            for r in sesion.execute(select(BitacoraAuditoria).order_by(BitacoraAuditoria.id)).scalars():
                total += 1
                if r.hash_previo != esperado:
                    # Se alteró este registro o el anterior, o se borró alguno entre ambos.
                    return {"integra": False, "registros": total, "ruptura_en": r.id,
                            "detalle": f"La cadena se rompe en el registro {r.id}: su huella previa no coincide "
                                       "con el registro anterior."}
                esperado = self.huella_registro(r)
            return {"integra": True, "registros": total, "ruptura_en": None, "detalle": None}

        if db is not None:
            resultado = recorrer(db)
        else:
            with get_db() as sesion:
                resultado = recorrer(sesion)
        resultado["verificada_en"] = datetime.utcnow().isoformat()
        if not resultado["integra"]:
            logger.error(f"Bitácora alterada: {resultado['detalle']}")
        return resultado

    def verificar_cadena(self) -> bool:
        """True si ningún registro de la bitácora fue alterado o eliminado."""
        return self.verificar()["integra"]

    def consultar(self, accion: Optional[str] = None, tarea_id: Optional[str] = None,
                  usuario: Optional[str] = None, desde: Optional[datetime] = None,
                  hasta: Optional[datetime] = None, limite: int = 100, desplazamiento: int = 0) -> Dict[str, Any]:
        from sqlalchemy import func, select

        from src.shared.database import get_db
        from src.shared.models import BitacoraAuditoria as B

        filtros = []
        if accion:
            filtros.append(B.accion == accion)
        if tarea_id:
            filtros.append(B.tarea_id == tarea_id)
        if usuario:
            filtros.append(B.registrado_por.ilike(f"%{usuario}%"))
        if desde:
            filtros.append(B.fecha_registro >= desde)
        if hasta:
            filtros.append(B.fecha_registro <= hasta)
        with get_db() as db:
            total = db.execute(select(func.count()).select_from(B).where(*filtros)).scalar_one()
            filas = db.execute(
                select(B).where(*filtros).order_by(B.id.desc()).limit(min(limite, 500)).offset(desplazamiento)
            ).scalars().all()
            acciones = [a for (a,) in db.execute(select(B.accion).distinct().order_by(B.accion)).all()]
            return {
                "total": total,
                "acciones": acciones,
                "eventos": [{
                    "id": r.id,
                    "fecha": r.fecha_registro.isoformat() if r.fecha_registro else None,
                    "accion": r.accion,
                    "registrado_por": r.registrado_por,
                    "tarea_id": r.tarea_id,
                    "licitacion_id": r.licitacion_id,
                    "detalles": r.detalles,
                    "hash_documento": r.hash_documento,
                } for r in filas],
            }


def _sql_bloqueo():
    from sqlalchemy import text
    return text("LOCK TABLE bitacora_auditoria IN SHARE ROW EXCLUSIVE MODE")
