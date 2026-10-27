"""
Funciones de aptitud estáticas de la Tabla 33: reglas sobre las importaciones del código.

- FF-02 (DA-02, ASR-03): ninguna dependencia va del núcleo de dominio hacia los adaptadores.
- FF-03 (ASR-05, ASR-13): ningún módulo invoca al proveedor del modelo sin pasar por la pasarela.
- FF-04 (DA-09, RNF-006): el motor de puntaje no depende de ningún módulo de inferencia.

Se leen todas las importaciones con ast, incluidas las que están dentro de funciones.
"""
import ast
from pathlib import Path
from typing import Iterator, Tuple

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SRC = RAIZ / "src"

# Núcleo de dominio (DA-02): esquemas, reglas de puntaje, procesamiento documental, máquina de
# estados y puertos (Figura 12).
NUCLEO = ["src/shared/schemas", "src/worker_analysis/scoring", "src/worker_analysis/pipeline",
          "src/worker_analysis/nucleo"]
# Lo que el núcleo no puede importar: adaptadores, infraestructura y clientes externos.
PROHIBIDO_EN_NUCLEO = (
    "src.api", "src.webui", "src.worker_analysis.adapters", "src.worker_analysis.llm_gateway",
    "src.worker_analysis.agents", "src.worker_analysis.orchestrator", "src.worker_vigilance",
    "src.shared.database", "src.shared.models", "azure", "openai", "langchain_openai", "httpx",
    "requests", "sqlalchemy", "psycopg", "sodapy",
)
# Clientes del proveedor del modelo: solo la pasarela los importa (DA-07).
CLIENTES_DEL_MODELO = ("openai", "langchain_openai", "azure.ai", "anthropic", "langchain_community")
PASARELA = "src/worker_analysis/llm_gateway"
# El motor de puntaje solo puede usar la biblioteca estándar, pydantic y los esquemas de dominio.
PERMITIDO_EN_PUNTAJE = ("pydantic", "src.shared.schemas", "src.worker_analysis.scoring")


def _modulos(carpeta: str) -> list:
    return sorted((RAIZ / carpeta).rglob("*.py"))


def _importaciones(archivo: Path) -> Iterator[Tuple[int, str]]:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                yield nodo.lineno, alias.name
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            yield nodo.lineno, nodo.module


def _coincide(modulo: str, prefijos) -> bool:
    return any(modulo == p or modulo.startswith(p + ".") for p in prefijos)


def _relativo(archivo: Path) -> str:
    return archivo.relative_to(RAIZ).as_posix()


@pytest.mark.parametrize("archivo", [a for c in NUCLEO for a in _modulos(c)], ids=_relativo)
def test_ff02_el_nucleo_no_depende_de_adaptadores(archivo):
    violaciones = [f"{_relativo(archivo)}:{linea} importa {m}" for linea, m in _importaciones(archivo)
                   if _coincide(m, PROHIBIDO_EN_NUCLEO)]
    assert not violaciones, "\n".join(violaciones)


def test_ff03_solo_la_pasarela_usa_el_cliente_del_modelo():
    violaciones = [f"{_relativo(a)}:{linea} importa {m}"
                   for a in sorted(SRC.rglob("*.py")) if not _relativo(a).startswith(PASARELA)
                   for linea, m in _importaciones(a) if _coincide(m, CLIENTES_DEL_MODELO)]
    assert not violaciones, "\n".join(violaciones)


@pytest.mark.parametrize("archivo", _modulos("src/worker_analysis/scoring"), ids=_relativo)
def test_ff04_el_puntaje_no_depende_de_inferencia(archivo):
    import sys

    estandar = sys.stdlib_module_names
    violaciones = [f"{_relativo(archivo)}:{linea} importa {m}" for linea, m in _importaciones(archivo)
                   if m.split(".")[0] not in estandar and not _coincide(m, PERMITIDO_EN_PUNTAJE)]
    assert not violaciones, "\n".join(violaciones)


def test_las_reglas_detectan_una_violacion(tmp_path):
    """La función de aptitud no pasa en vacío: una importación prohibida se reporta."""
    archivo = tmp_path / "malo.py"
    archivo.write_text("def f():\n    from langchain_openai import AzureChatOpenAI\n", encoding="utf-8")
    assert [m for _, m in _importaciones(archivo) if _coincide(m, CLIENTES_DEL_MODELO)] == ["langchain_openai"]
