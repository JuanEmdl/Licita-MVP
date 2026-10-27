"""
Ejecuta las pruebas de la matriz de aceptación (Tabla 27) y reporta el estado de cada escenario.

    python -m scripts.matriz_aceptacion
    TEST_DB_CONNECTION_STRING=postgresql://user:password@localhost:5432/licitaciones_test python -m scripts.matriz_aceptacion

Estado por escenario:
  Cumplido                  todas sus pruebas pasan.
  Cumplido + interfaz       sus pruebas pasan y una parte se confirma en la pantalla.
  Revisión en interfaz      solo se verifica en la pantalla.
  Parcial                   sus pruebas pasan, pero hay una brecha declarada.
  No cumplido               brecha declarada y sin prueba que lo cubra.
  Falla / Omitida           alguna prueba falla, o se omitió (p. ej. sin base de pruebas).
Deja el reporte en data/evaluacion/resultados/ (Markdown para el Anexo I y JSON).
"""
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from tests.aceptacion.matriz_gherkin import ESCENARIOS  # noqa: E402

RESULTADOS = RAIZ / "data" / "evaluacion" / "resultados"


def ejecutar(pruebas: list) -> dict:
    """Corre las pruebas y devuelve 'archivo::función' -> passed | failed | skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "aceptacion.xml"
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}",
                        *pruebas], cwd=RAIZ, check=False)
        resultado = {}
        for caso in ET.parse(junit).getroot().iter("testcase"):
            archivo = caso.get("classname", "").replace(".", "/") + ".py"
            funcion = caso.get("name", "").split("[")[0]
            estado = ("failed" if caso.find("failure") is not None or caso.find("error") is not None
                      else "skipped" if caso.find("skipped") is not None else "passed")
            clave = f"{archivo}::{funcion}"
            # Una prueba parametrizada falla si falla cualquiera de sus casos.
            if resultado.get(clave) != "failed":
                resultado[clave] = estado if resultado.get(clave) in (None, "passed") else resultado[clave]
        return resultado


def estado_escenario(e: dict, resultados: dict) -> str:
    estados = [resultados.get(p, "no ejecutada") for p in e["pruebas"]]
    if any(s in ("failed", "no ejecutada") for s in estados):
        return "Falla"
    if any(s == "skipped" for s in estados):
        return "Omitida"
    if e.get("brecha"):
        return "Parcial" if estados else "No cumplido"
    if not estados:
        return "Revisión en interfaz"
    return "Cumplido + interfaz" if e.get("interfaz") else "Cumplido"


def main() -> int:
    pruebas = sorted({p for e in ESCENARIOS.values() for p in e["pruebas"]})
    resultados = ejecutar(pruebas)
    filas = []
    for codigo, e in sorted(ESCENARIOS.items()):
        filas.append({"escenario": codigo, "titulo": e["titulo"], "estado": estado_escenario(e, resultados),
                      "pruebas": {p: resultados.get(p, "no ejecutada") for p in e["pruebas"]},
                      "interfaz": e.get("interfaz"), "brecha": e.get("brecha"), "nota": e.get("nota")})
    conteo = Counter(f["estado"] for f in filas)

    lineas = [f"# Matriz de aceptación (Tabla 27) — {datetime.now():%Y-%m-%d %H:%M}", "",
              "| Escenario | Criterio | Estado | Pruebas | Observación |", "|---|---|---|---|---|"]
    for f in filas:
        observacion = " ".join(x for x in (f["brecha"], f["interfaz"] and f"Interfaz: {f['interfaz']}", f["nota"]) if x)
        lineas.append(f"| {f['escenario']} | {f['titulo']} | {f['estado']} | {len(f['pruebas'])} | {observacion} |")
    lineas += ["", "Resumen: " + " · ".join(f"{k}: {v}" for k, v in sorted(conteo.items()))]

    RESULTADOS.mkdir(parents=True, exist_ok=True)
    marca = f"{datetime.now():%Y%m%d-%H%M%S}"
    (RESULTADOS / f"{marca}_matriz_aceptacion.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    (RESULTADOS / f"{marca}_matriz_aceptacion.json").write_text(
        json.dumps({"resumen": conteo, "escenarios": filas}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "\n".join(lineas[-1:]))
    print(f"Reporte: data/evaluacion/resultados/{marca}_matriz_aceptacion.md")
    return 0 if not conteo.get("Falla") else 1


if __name__ == "__main__":
    sys.exit(main())
