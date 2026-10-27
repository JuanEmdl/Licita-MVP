"""
Descarga la muestra histórica de ASR-03: 500 procesos de "SECOP II - Procesos de Contratación".

    python -m scripts.descargar_muestra_secop

Muestra estratificada por año de publicación (2019 a 2026, 62 o 63 procesos por año) con un
desplazamiento fijo dentro de cada año, para que la muestra sea reproducible. Los registros se
guardan completos, tal como los publica Datos Abiertos, en tests/fixtures/secop_procesos_500.json.gz:
así la prueba corre sin red y conserva las variaciones de esquema de cada época.
"""
import gzip
import json
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "tests" / "fixtures" / "secop_procesos_500.json.gz"
URL = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
ANIOS = range(2019, 2027)
TOTAL = 500
DESPLAZAMIENTO = 5000


def main() -> int:
    from src.shared.config import obtener_configuracion
    token = obtener_configuracion().socrata_app_token
    cabeceras = {"X-App-Token": token} if token else {}
    registros = []
    for i, anio in enumerate(ANIOS):
        cantidad = TOTAL // len(ANIOS) + (1 if i < TOTAL % len(ANIOS) else 0)
        parametros = {
            "$where": f"fecha_de_publicacion_del between '{anio}-01-01T00:00:00' and '{anio}-12-31T23:59:59'",
            "$order": "id_del_proceso", "$limit": cantidad, "$offset": DESPLAZAMIENTO,
        }
        respuesta = httpx.get(URL, params=parametros, headers=cabeceras, timeout=120)
        respuesta.raise_for_status()
        lote = respuesta.json()
        print(f"{anio}: {len(lote)} procesos")
        registros.extend(lote)
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(DESTINO, "wt", encoding="utf-8") as f:
        json.dump({"fuente": URL, "anios": list(ANIOS), "desplazamiento": DESPLAZAMIENTO,
                   "procesos": registros}, f, ensure_ascii=False)
    print(f"{len(registros)} procesos en {DESTINO.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
