"""
Carga capacidades del portafolio desde un JSON (lista de objetos con
"tecnologia", "categoria" y "descripcion").

    python -m scripts.cargar_portafolio data/ejemplos/portafolio_ejemplo.json

Publica una sola versión nueva con las capacidades vigentes más las del archivo
(RF-009); las que ya existen con el mismo contenido no se duplican y conservan su
vector. Después vectoriza solo lo nuevo si AZURE_OPENAI_* está configurado (RF-010);
si no, el evaluador encuentra las capacidades por búsqueda de texto completo.
"""
import json
import sys

from src.shared.config import obtener_configuracion
from src.shared.database import init_db
from src.shared.portfolio_repo import RepositorioVersionesPortafolio, huella_capacidad

CAMPOS = ("tecnologia", "categoria", "descripcion")


def main(ruta: str) -> None:
    with open(ruta, encoding="utf-8") as f:
        registros = json.load(f)

    init_db()
    repositorio = RepositorioVersionesPortafolio()
    repositorio.asegurar_version_inicial()
    actuales = [{k: c[k] for k in CAMPOS} for c in repositorio.capacidades()]
    existentes = {huella_capacidad(**c) for c in actuales}
    nuevas = [{k: r[k] for k in CAMPOS} for r in registros if huella_capacidad(**{k: r[k] for k in CAMPOS}) not in existentes]
    if not nuevas:
        print(f"Sin cambios: las {len(registros)} capacidades del archivo ya están en la versión vigente.")
        return

    resumen = repositorio.publicar(actuales + nuevas, "scripts.cargar_portafolio", f"Carga desde {ruta}")
    print(f"Versión {resumen['version']} publicada: {resumen['capacidades']} capacidades "
          f"({len(nuevas)} nuevas, {len(registros) - len(nuevas)} ya existentes).")

    if obtener_configuracion().llm_configurado:
        from src.worker_analysis.servicio import indexar_portafolio
        print(f"Capacidades vectorizadas: {indexar_portafolio(resumen['version'])}.")
    else:
        print("Modelo no configurado: las capacidades se guardan sin vector.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python -m scripts.cargar_portafolio <archivo.json>")
    main(sys.argv[1])
