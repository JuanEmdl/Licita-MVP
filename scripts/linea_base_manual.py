"""
PB-01: prueba de estimación de la línea base manual (eficiencia de desempeño, capítulo 5).

    python -m scripts.linea_base_manual                                   # usa la última corrida del corpus
    python -m scripts.linea_base_manual --corrida data/evaluacion/resultados/<corrida>.json

Es una estimación por modelo, no un cronometraje de analistas, y así se declara. Lo que la hace
prueba es el protocolo: entradas medidas en los pliegos reales del corpus (palabras y número de
requisitos), parámetros con fuente fijados antes de calcular, procedimiento reproducible y un
criterio de aceptación que se cumple o no.

Tiempo manual por pliego = lectura + registro + cotejo + concepto:
  lectura   palabras / velocidad de lectura (Carver, 1992: 300 palabras/min al leer para comprender,
            200 al leer para aprender y 138 al leer para memorizar; Brysbaert, 2019: 238 en promedio)
  registro  requisitos × minutos por requisito para transcribirlo a la matriz con numeral y categoría
  cotejo    requisitos × minutos por requisito para buscar la evidencia en el portafolio y dictaminar
  concepto  minutos para redactar la recomendación
Tiempo del analista con el sistema = requisitos × minutos de revisión + minutos de revisar el informe.
El procesamiento del sistema no ocupa al analista; se informa aparte con el tiempo medido.

Criterio de aceptación (fijado antes de calcular): en el escenario «manual rápido», el que más
favorece al proceso manual, el sistema reduce al menos un 70 % el tiempo del analista por pliego.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional

RAIZ = Path(__file__).resolve().parent.parent
RESULTADOS = RAIZ / "data" / "evaluacion" / "resultados"
UMBRAL_REDUCCION = 0.70

ESCENARIOS: Dict[str, dict] = {
    # Favorece al proceso manual: lectura para comprender y tiempos mínimos por requisito.
    "manual rápido": {"palabras_min": 300, "registro_min": 1.0, "cotejo_min": 2.0, "concepto_min": 30,
                      "revision_min": 1.0, "revision_informe_min": 20},
    "central": {"palabras_min": 200, "registro_min": 2.0, "cotejo_min": 4.0, "concepto_min": 45,
                "revision_min": 0.75, "revision_informe_min": 15},
    # Desfavorece al proceso manual: lectura para memorizar y tiempos amplios.
    "manual lento": {"palabras_min": 138, "registro_min": 3.0, "cotejo_min": 6.0, "concepto_min": 60,
                     "revision_min": 0.5, "revision_informe_min": 10},
}


def minutos_manual(palabras: int, requisitos: int, p: dict) -> float:
    return palabras / p["palabras_min"] + requisitos * (p["registro_min"] + p["cotejo_min"]) + p["concepto_min"]


def minutos_con_sistema(requisitos: int, p: dict) -> float:
    return requisitos * p["revision_min"] + p["revision_informe_min"]


def estimar(casos: list) -> dict:
    """Pura (la cubren las pruebas): casos con palabras, requisitos y segundos medidos del sistema."""
    resultado = {}
    for nombre, p in ESCENARIOS.items():
        filas, manual_total, sistema_total = [], 0.0, 0.0
        for c in casos:
            manual = minutos_manual(c["palabras"], c["requisitos"], p)
            sistema = minutos_con_sistema(c["requisitos"], p)
            manual_total += manual
            sistema_total += sistema
            filas.append({"caso": c["caso"], "palabras": c["palabras"], "requisitos": c["requisitos"],
                          "horas_manual": round(manual / 60, 2), "horas_analista_con_sistema": round(sistema / 60, 2),
                          "minutos_procesamiento": round(c.get("segundos_sistema", 0) / 60, 1),
                          "reduccion": round(1 - sistema / manual, 3)})
        reduccion = 1 - sistema_total / manual_total if manual_total else None
        resultado[nombre] = {"parametros": p, "casos": filas, "horas_manual": round(manual_total / 60, 1),
                             "horas_analista_con_sistema": round(sistema_total / 60, 1),
                             "reduccion": None if reduccion is None else round(reduccion, 3)}
    rapido = resultado["manual rápido"]["reduccion"]
    return {"escenarios": resultado, "umbral_reduccion": UMBRAL_REDUCCION,
            "cumple": rapido is not None and rapido >= UMBRAL_REDUCCION}


def casos_de_corrida(corrida: dict) -> list:
    return [{"caso": c["caso"], "palabras": c["palabras"], "requisitos": c["extraidos"],
             "segundos_sistema": c.get("segundos_extraccion", 0) + c.get("segundos_dictamen", 0)}
            for c in corrida["casos"] if "error" not in c]


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="PB-01: línea base manual estimada por modelo.")
    parser.add_argument("--corrida", type=Path, help="Resultado de scripts.evaluar_corpus (por defecto, el último).")
    args = parser.parse_args(argv)
    ruta = args.corrida or max(RESULTADOS.glob("*_corpus_v*.json"), key=lambda r: r.stat().st_mtime)
    datos = estimar(casos_de_corrida(json.loads(ruta.read_text(encoding="utf-8"))))
    datos["corrida"] = ruta.name
    for nombre, e in datos["escenarios"].items():
        print(f"{nombre:>14}: manual {e['horas_manual']} h · analista con el sistema "
              f"{e['horas_analista_con_sistema']} h · reducción {e['reduccion']:.0%}")
    print(f"Criterio: reducción >= {UMBRAL_REDUCCION:.0%} en «manual rápido» → {'cumple' if datos['cumple'] else 'no cumple'}")
    salida = RESULTADOS / ruta.name.replace("_corpus_", "_linea_base_")
    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Informe: {salida.relative_to(RAIZ)}")
    return 0 if datos["cumple"] else 1


if __name__ == "__main__":
    sys.exit(main())
