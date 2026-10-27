"""
Métricas de acoplamiento de Martin por agrupación de módulos (Tabla 24, apartado 3.35).

Ca: módulos de fuera que dependen de la agrupación. Ce: módulos de fuera de los que ella depende.
I = Ce / (Ca + Ce). A: proporción de clases abstractas (ABC, Protocol o con métodos abstractos).
D = |A + I - 1|: distancia a la secuencia principal.

Uso: python -m scripts.metricas_acoplamiento
"""
import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
modulos = {}
for archivo in (RAIZ / "src").rglob("*.py"):
    nombre = ".".join(archivo.relative_to(RAIZ).with_suffix("").parts).removesuffix(".__init__")
    modulos[nombre] = archivo

ADAPTADORES_SHARED = {"src.shared.database", "src.shared.models", "src.shared.almacen_informes",
                      "src.shared.longitud_cola", "src.shared.lectura_documentos"}
GRUPOS = {
    "Núcleo de dominio": lambda m: m.startswith(("src.shared.schemas", "src.worker_analysis.scoring",
                                                 "src.worker_analysis.pipeline", "src.worker_analysis.nucleo")),
    "Adaptadores de integración": lambda m: m.startswith(("src.worker_analysis.adapters",
                                                          "src.worker_analysis.llm_gateway",
                                                          "src.worker_vigilance.sync", "src.api.adapters"))
    or m in ADAPTADORES_SHARED or (m.startswith("src.shared.") and m.endswith("_repo")),
    "Módulos de la API": lambda m: m.startswith("src.api.modules"),
    "Motor de puntaje": lambda m: m.startswith("src.worker_analysis.scoring"),
}


def importa(archivo: Path) -> set:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    destinos = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            destinos |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            destinos.add(n.module)
            destinos |= {f"{n.module}.{a.name}" for a in n.names}
    return {d for d in destinos if d in modulos}


def abstraccion(archivos) -> tuple:
    clases = abstractas = 0
    for a in archivos:
        for n in ast.walk(ast.parse(a.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ClassDef):
                clases += 1
                bases = {getattr(b, "id", getattr(b, "attr", "")) for b in n.bases}
                metodos_abstractos = any(isinstance(d, ast.FunctionDef) and any(
                    getattr(x, "id", getattr(x, "attr", "")) == "abstractmethod" for x in d.decorator_list)
                    for d in n.body)
                if bases & {"ABC", "Protocol"} or metodos_abstractos:
                    abstractas += 1
    return abstractas, clases


if __name__ == "__main__":
    grafo = {m: importa(a) for m, a in modulos.items()}
    print("Agrupación | Módulos | Ca | Ce | I | A | D")
    for grupo, pertenece in GRUPOS.items():
        dentro = {m for m in modulos if pertenece(m)}
        ca = {m for m in modulos if m not in dentro and grafo[m] & dentro}
        ce = {d for m in dentro for d in grafo[m] if d not in dentro}
        i = len(ce) / (len(ca) + len(ce)) if ca or ce else 0
        abstractas, clases = abstraccion([modulos[m] for m in dentro])
        a = abstractas / clases if clases else 0
        print(f"{grupo} | {len(dentro)} | {len(ca)} | {len(ce)} | {i:.2f} | {a:.2f} | {abs(a + i - 1):.2f}")
