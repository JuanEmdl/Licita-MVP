"""
Máquina de estados del análisis de una licitación (Figura 15, Tabla 18).

Es el contrato que implementa el orquestador y que intenta romper la prueba de ASR-12: se
separa del orquestador para poder probarla sola (FF-06). El registro de tareas guarda un estado
resumido (Recibida, En proceso, Esperando revisión, Evaluando, Suspendida, Fallida, Finalizada)
y la etapa fina sale del checkpoint; aquí se modelan los estados de la figura.

Diferencias con la Figura 15 que impone el código: Fallida se alcanza desde cualquier etapa
cuando se agotan los reintentos (no solo al recuperar el expediente), y una suspensión por cuota
continúa en la etapa que quedó pendiente (Extrayendo o Evaluando), no siempre en Evaluando.
"""
from enum import Enum
from typing import Dict, FrozenSet, Optional


class Estado(str, Enum):
    RECIBIDA = "Recibida"
    RECUPERANDO_EXPEDIENTE = "Recuperando expediente"
    SANEANDO = "Saneando"
    SEGMENTANDO = "Segmentando"
    EXTRAYENDO = "Extrayendo"
    EN_ESPERA_DE_REVISION = "En espera de revisión"
    EVALUANDO = "Evaluando"
    CALCULANDO_PUNTAJE = "Calculando puntaje"
    GENERANDO_RECOMENDACION = "Generando recomendación"
    GENERANDO_INFORME = "Generando informe"
    FINALIZADA = "Finalizada"
    SUSPENDIDA = "Suspendida"
    FALLIDA = "Fallida"


E = Estado
TERMINALES: FrozenSet[Estado] = frozenset({E.FINALIZADA, E.FALLIDA})
# Transiciones de la Figura 15. Fallida se agrega desde toda etapa no terminal (ver arriba).
TRANSICIONES: Dict[Estado, FrozenSet[Estado]] = {
    E.RECIBIDA: frozenset({E.RECUPERANDO_EXPEDIENTE}),
    E.RECUPERANDO_EXPEDIENTE: frozenset({E.SANEANDO}),
    E.SANEANDO: frozenset({E.SEGMENTANDO, E.SUSPENDIDA}),
    E.SEGMENTANDO: frozenset({E.EXTRAYENDO}),
    E.EXTRAYENDO: frozenset({E.EXTRAYENDO, E.EN_ESPERA_DE_REVISION, E.SUSPENDIDA}),
    E.EN_ESPERA_DE_REVISION: frozenset({E.EVALUANDO}),
    E.EVALUANDO: frozenset({E.CALCULANDO_PUNTAJE, E.SUSPENDIDA}),
    E.CALCULANDO_PUNTAJE: frozenset({E.GENERANDO_RECOMENDACION}),
    E.GENERANDO_RECOMENDACION: frozenset({E.GENERANDO_INFORME}),
    E.GENERANDO_INFORME: frozenset({E.FINALIZADA}),
    E.SUSPENDIDA: frozenset({E.EXTRAYENDO, E.EVALUANDO}),
    E.FINALIZADA: frozenset(),
    E.FALLIDA: frozenset(),
}

# Etapa del grafo (orchestrator.graph.ETAPAS y progreso()) => estado de la figura.
ESTADO_DE_ETAPA: Dict[str, Estado] = {
    "recuperando_expediente": E.RECUPERANDO_EXPEDIENTE,
    "saneando": E.SANEANDO,
    "segmentando": E.SEGMENTANDO,
    "extrayendo": E.EXTRAYENDO,
    "esperando_revision": E.EN_ESPERA_DE_REVISION,
    "evaluando": E.EVALUANDO,
    "calculando_puntaje": E.CALCULANDO_PUNTAJE,
    "generando_recomendacion": E.GENERANDO_RECOMENDACION,
    "generando_informe": E.GENERANDO_INFORME,
    "suspendida": E.SUSPENDIDA,
}

CAUSA_CUOTA = "cuota"
CAUSA_INYECCION = "inyeccion"


class TransicionProhibidaError(Exception):
    """La máquina no admite la transición pedida; el mensaje dice por qué (Tabla 18)."""


class MaquinaEstados:

    @staticmethod
    def razon_prohibicion(origen: Estado, destino: Estado, *, lista_aprobada: bool = False,
                          puntaje_calculado: bool = False, causa_suspension: Optional[str] = None,
                          cuota_disponible: bool = True) -> Optional[str]:
        """None si la transición se admite; si no, la razón de la Tabla 18 o de la Figura 15."""
        if origen in TERMINALES:
            return (f"Un análisis {origen.value.lower()} no se reanuda: un informe emitido es inmutable (ASR-06) y "
                    "un análisis nuevo se solicita como tarea nueva.")
        if destino == E.FALLIDA:
            return None
        if destino == E.EVALUANDO and origen != E.SUSPENDIDA and (origen != E.EN_ESPERA_DE_REVISION
                                                                 or not lista_aprobada):
            return "No se evalúa una lista que el analista no aprobó (ASR-12, RF-030)."
        if destino == E.GENERANDO_INFORME and not puntaje_calculado:
            return "El informe debe declarar el puntaje y la versión de reglas con que se calculó (RF-033, RF-037)."
        if origen == E.SUSPENDIDA:
            if causa_suspension == CAUSA_INYECCION:
                return ("Una suspensión por sospecha de inyección no se continúa (ASR-10): se solicita un "
                        "análisis nuevo con el contenido revisado.")
            if causa_suspension != CAUSA_CUOTA or not cuota_disponible:
                return "La suspensión por cuota solo se levanta cuando vuelve a haber cuota (ASR-13, RN-10)."
            if destino == E.EVALUANDO and not lista_aprobada:
                return "No se evalúa una lista que el analista no aprobó (ASR-12, RF-030)."
        if destino not in TRANSICIONES[origen]:
            return f"La Figura 15 no tiene la transición {origen.value} → {destino.value}."
        return None

    def permite(self, origen: Estado, destino: Estado, **condiciones) -> bool:
        return self.razon_prohibicion(origen, destino, **condiciones) is None

    def validar(self, origen: Estado, destino: Estado, **condiciones) -> None:
        razon = self.razon_prohibicion(origen, destino, **condiciones)
        if razon is not None:
            raise TransicionProhibidaError(razon)
