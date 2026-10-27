"""
Informes emitidos (RF-037, ASR-06, RN-08, Tabla 19).

Emitir un informe es una sola transacción: el registro del informe con su huella, el
evento INFORME_GENERADO en la bitácora encadenada y la tarea marcada como Finalizada
quedan juntos o no queda nada. Un informe emitido no se modifica: si la tarea ya
tiene uno, se devuelve ese y no se genera otro.
"""
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session

from src.shared.models import InformeEmitido, TareaAnalisis


class RegistroInformes:

    def __init__(self, fabrica_sesiones: Optional[Callable[[], Session]] = None):
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        self._sesiones = fabrica_sesiones

    def obtener(self, tarea_id: str) -> Optional[dict]:
        with self._sesiones() as db:
            informe = db.get(InformeEmitido, tarea_id)
            return self._a_dict(informe) if informe else None

    def emitir(self, estado: dict, resultado: dict, auditoria) -> dict:
        """
        estado: valores del grafo (tarea, puntaje, recomendación, versiones).
        resultado: lo que devolvió GeneradorInforme.generar_y_sellar().
        """
        tarea_id = estado["tarea_id"]
        with self._sesiones() as db:
            informe = InformeEmitido(
                tarea_id=tarea_id,
                ruta_pdf=resultado["informe_path"],
                ruta_texto=resultado.get("texto_path"),
                huella_sha256=resultado["huella_sha256"],
                emitido_en=datetime.fromisoformat(resultado["emitido_en"]) if resultado.get("emitido_en")
                else datetime.utcnow(),
                reglas_version=estado.get("reglas_version"),
                portafolio_version=estado.get("portafolio_version"),
            )
            db.add(informe)
            auditoria.registrar_evento(
                tarea_id, "INFORME_GENERADO",
                {"informe_path": informe.ruta_pdf, "huella_sha256": informe.huella_sha256,
                 "reglas_version": informe.reglas_version, "portafolio_version": informe.portafolio_version,
                 "recomendacion": estado.get("recomendacion"), "puntaje": estado.get("puntaje_global")},
                hash_documento=informe.huella_sha256,
                licitacion_id=estado.get("licitacion_url"),
                db=db,
            )
            tarea = db.get(TareaAnalisis, tarea_id)
            if tarea is not None:
                tarea.estado = "Finalizada"
                tarea.resultado_puntaje = estado.get("puntaje_global")
                tarea.resultado_recomendacion = estado.get("recomendacion")
                tarea.detalle_error = None
            db.commit()
            return self._a_dict(informe)

    @staticmethod
    def _a_dict(i: InformeEmitido) -> dict:
        return {
            "tarea_id": i.tarea_id,
            "ruta_pdf": i.ruta_pdf,
            "ruta_texto": i.ruta_texto,
            "huella_sha256": i.huella_sha256,
            "emitido_en": i.emitido_en.isoformat() if i.emitido_en else None,
            "reglas_version": i.reglas_version,
            "portafolio_version": i.portafolio_version,
        }
