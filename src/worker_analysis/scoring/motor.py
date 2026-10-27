import logging
from typing import List, Dict, Optional
from pydantic import BaseModel
from src.shared.schemas.domain import (
    PESOS_INICIALES,
    CategoriaRequisito,
    DictamenRequisito,
    EstadoDictamen,
    RequisitoExtraido,
)

logger = logging.getLogger(__name__)

class DesglosePuntaje(BaseModel):
    puntaje_total: float
    aporte_por_categoria: Dict[CategoriaRequisito, float]
    # Peso efectivo de cada categoría evaluada tras redistribuir el de las ausentes.
    peso_efectivo_por_categoria: Dict[CategoriaRequisito, float]
    categorias_no_aplicables: List[CategoriaRequisito]
    total_dictamenes: int
    # False cuando no hubo ningún dictamen: el puntaje no tiene respaldo y no
    # debe usarse para recomendar.
    con_evidencia: bool
    version_reglas: str

# HU-08 CA-03: los requisitos 'No verificable' se contabilizan y se tratan como incumplimiento.
PUNTOS_POR_ESTADO: Dict[EstadoDictamen, float] = {
    EstadoDictamen.CUMPLE: 1.0,
    EstadoDictamen.CUMPLE_PARCIALMENTE: 0.5,
    EstadoDictamen.NO_CUMPLE: 0.0,
    EstadoDictamen.NO_VERIFICABLE: 0.0,
}


class ReglasPuntaje(BaseModel):
    version: str
    pesos_categorias: Dict[CategoriaRequisito, float]
    puntos_por_estado: Dict[EstadoDictamen, float]

    @classmethod
    def desde_version(cls, regla: dict) -> "ReglasPuntaje":
        """Construye las reglas a partir de una versión de src.shared.reglas_repo (RF-033)."""
        return cls(
            version=str(regla["version"]),
            pesos_categorias={CategoriaRequisito(c): p for c, p in regla["pesos"].items()},
            puntos_por_estado=PUNTOS_POR_ESTADO,
        )

class MotorPuntaje:
    """
    Motor de puntaje determinista (DA-09, RF-033, RF-034).
    Calcula el puntaje de cumplimiento de 0 a 100 utilizando reglas versionadas.
    La evaluación es 100% determinista, asegurando reproducibilidad y auditoría.
    """

    def __init__(self):
        # Solo para pruebas y análisis sin versión registrada. En el flujo real las reglas
        # llegan de la versión que la tarea fijó al crearse (RF-033, RN-06).
        self.reglas_por_defecto = ReglasPuntaje(
            version="provisional",
            pesos_categorias={CategoriaRequisito(c): p for c, p in PESOS_INICIALES.items()},
            puntos_por_estado=PUNTOS_POR_ESTADO,
        )

    def calcular(
        self,
        requisitos: List[RequisitoExtraido],
        dictamenes: List[DictamenRequisito],
        reglas: Optional[ReglasPuntaje] = None,
    ) -> DesglosePuntaje:
        """
        Calcula el puntaje global y su desglose por categoría (RF-034).

        HU-08 CA-02: una categoría sin requisitos se reporta como no aplicable y su
        peso se redistribuye proporcionalmente entre las categorías evaluadas. Así no
        reduce el resultado, pero tampoco aporta puntos que nadie verificó.
        """
        reglas = reglas or self.reglas_por_defecto
        logger.info(f"Calculando puntaje de la licitación con reglas v{reglas.version}")

        mapa_requisitos = {req.identificador: req for req in requisitos}

        max_puntos_categoria = {cat: 0.0 for cat in CategoriaRequisito}
        obtenido_categoria = {cat: 0.0 for cat in CategoriaRequisito}
        total_dictamenes = 0

        for dictamen in dictamenes:
            req = mapa_requisitos.get(dictamen.identificador_requisito)
            if not req:
                logger.warning(f"Se omitió dictamen huérfano: {dictamen.identificador_requisito}")
                continue

            cat = req.categoria
            max_puntos_categoria[cat] += 1.0
            total_dictamenes += 1

            multiplicador = reglas.puntos_por_estado.get(dictamen.estado, 0.0)
            obtenido_categoria[cat] += multiplicador

        evaluadas = [cat for cat in CategoriaRequisito if max_puntos_categoria[cat] > 0]
        no_aplicables = [cat for cat in CategoriaRequisito if max_puntos_categoria[cat] == 0]
        peso_evaluadas = sum(reglas.pesos_categorias.get(cat, 0.0) for cat in evaluadas)

        aporte_final = {cat: 0.0 for cat in CategoriaRequisito}
        peso_efectivo = {cat: 0.0 for cat in CategoriaRequisito}
        puntaje_total = 0.0

        if peso_evaluadas > 0:
            for cat in evaluadas:
                peso = reglas.pesos_categorias.get(cat, 0.0) / peso_evaluadas * 100.0
                aporte = (obtenido_categoria[cat] / max_puntos_categoria[cat]) * peso
                peso_efectivo[cat] = round(peso, 2)
                aporte_final[cat] = round(aporte, 2)
                puntaje_total += aporte
        else:
            logger.warning("No hay dictámenes válidos: el puntaje queda en 0 y sin evidencia.")

        desglose = DesglosePuntaje(
            puntaje_total=round(puntaje_total, 2),
            aporte_por_categoria=aporte_final,
            peso_efectivo_por_categoria=peso_efectivo,
            categorias_no_aplicables=no_aplicables,
            total_dictamenes=total_dictamenes,
            con_evidencia=peso_evaluadas > 0,
            version_reglas=reglas.version
        )

        logger.info(f"Puntaje total calculado: {desglose.puntaje_total}/100")
        return desglose
