"""
Exportación de oportunidades a CSV (RF-041, ASR-15).

ASR-15 se resolvió fuera de la arquitectura: un serializador de la biblioteca estándar
dentro del módulo de resultados. El archivo trae las columnas visibles del tablero de
oportunidades y solo lo que el usuario puede ver (sus carpetas, no las ajenas).

- Separador punto y coma y marca UTF-8 (BOM): Excel con configuración regional de Colombia
  lo abre en columnas y con tildes.
- Las celdas que empiezan por =, +, - o @ se escapan con un apóstrofo: el objeto de un
  proceso es texto de terceros y no debe ejecutarse como fórmula al abrir el archivo.
"""
import csv
import io
from typing import Iterable, List, Tuple

from src.shared.horas import texto_local

COLUMNAS: List[Tuple[str, str]] = [
    ("id_proceso", "ID del proceso"),
    ("referencia", "Referencia"),
    ("entidad", "Entidad"),
    ("objeto", "Objeto"),
    ("modalidad", "Modalidad"),
    ("departamento", "Departamento"),
    ("ciudad", "Ciudad"),
    ("precio_base", "Cuantía (COP)"),
    ("fecha_publicacion", "Fecha de publicación"),
    ("fecha_cierre", "Fecha de cierre"),
    ("estado", "Estado"),
    ("fase", "Fase"),
    ("responsable", "Responsable"),
    ("carpetas", "Mis carpetas"),
    ("seguida", "La sigo"),
    ("novedades_sin_revisar", "Novedades sin revisar"),
    ("notas", "Notas"),
    ("analisis_estado", "Estado del último análisis"),
    ("analisis_recomendacion", "Recomendación"),
    ("analisis_puntaje", "Puntaje"),
    ("url_proceso", "Enlace SECOP II"),
    ("fuente", "Fuente"),
    ("sincronizada_en", "Última sincronización"),
]


def _celda(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, float):
        return f"{valor:.0f}" if valor.is_integer() else f"{valor:.2f}".replace(".", ",")
    texto = " ".join(str(valor).split())
    return f"'{texto}" if texto[:1] in ("=", "+", "-", "@") else texto


def _fila(o: dict) -> List[str]:
    analisis = o.get("ultimo_analisis") or {}
    valores = {
        **o,
        "objeto": o.get("objeto") or o.get("nombre"),
        "fecha_publicacion": (o.get("fecha_publicacion") or "")[:10],
        "fecha_cierre": (o.get("fecha_cierre") or "")[:10],
        "sincronizada_en": texto_local(o.get("sincronizada_en")),  # hora local (UTC_OFFSET)
        "carpetas": ", ".join(c["nombre"] for c in o.get("carpetas") or []),
        "analisis_estado": analisis.get("estado"),
        "analisis_recomendacion": analisis.get("recomendacion"),
        "analisis_puntaje": analisis.get("puntaje"),
    }
    return [_celda(valores.get(campo)) for campo, _ in COLUMNAS]


def generar_csv(oportunidades: Iterable[dict]) -> bytes:
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow([titulo for _, titulo in COLUMNAS])
    for o in oportunidades:
        escritor.writerow(_fila(o))
    return ("﻿" + salida.getvalue()).encode("utf-8")
