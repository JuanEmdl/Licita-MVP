"""La matriz de aceptación cubre los 38 escenarios de la Tabla 27 y solo cita pruebas que existen."""
import ast
from pathlib import Path

import pytest

from tests.aceptacion.matriz_gherkin import ESCENARIOS

RAIZ = Path(__file__).resolve().parents[2]
HISTORIAS = {"HU-01": 4, "HU-02": 4, "HU-03": 4, "HU-04": 4, "HU-05": 4,
             "HU-06": 4, "HU-07": 3, "HU-08": 4, "HU-09": 3, "HU-10": 4}


def _funciones(archivo: str) -> set:
    arbol = ast.parse((RAIZ / archivo).read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(arbol) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_la_matriz_tiene_los_38_escenarios():
    esperados = {f"{hu} CA-{i:02d}" for hu, n in HISTORIAS.items() for i in range(1, n + 1)}
    assert set(ESCENARIOS) == esperados
    assert len(ESCENARIOS) == 38


@pytest.mark.parametrize("escenario", sorted(ESCENARIOS))
def test_cada_escenario_tiene_verificacion_o_brecha_declarada(escenario):
    e = ESCENARIOS[escenario]
    # Un escenario sin pruebas automatizadas debe decir cómo se verifica o por qué no se cumple.
    assert e["pruebas"] or e.get("interfaz") or e.get("brecha"), escenario
    for prueba in e["pruebas"]:
        archivo, funcion = prueba.split("::")
        assert funcion in _funciones(archivo), prueba
