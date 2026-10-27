"""
Verifica la conexión con los servicios externos usando el .env actual:

    python -m scripts.verificar_servicios

Base de datos, SECOP II (token de aplicación), Azure OpenAI (deployment de chat y
de embeddings) y Service Bus. No imprime secretos.
"""
import sys

from src.shared.diagnostico import diagnosticar


def main() -> int:
    resultados = diagnosticar()
    for r in resultados:
        marca = "OK   " if r["ok"] else "FALLA"
        print(f"[{marca}] {r['servicio']}: {r['detalle']}")
        if r["accion"]:
            print(f"        -> {r['accion']}")
    return 0 if all(r["ok"] for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
