"""
Proxy de inyección de fallas delante de Azure OpenAI (ASR-07).

Reenvía cada petición al recurso real y, según las probabilidades configuradas, responde en su
lugar 429 (límite de tasa), 503 (servicio no disponible) o demora la respuesta más que el tiempo
de espera del cliente. Basta con apuntar AZURE_OPENAI_ENDPOINT a él; no requiere cambiar código.

    python -m scripts.proxy_fallas --puerto 8099 --p429 0.2 --p503 0.1 --plento 0.05 --demora 20

GET /_estadisticas devuelve cuántas peticiones recibió y cuántas fallas inyectó.
"""
import argparse
import asyncio
import random
from collections import Counter

import httpx
from fastapi import FastAPI, Request, Response

SALTO = {"host", "content-length", "accept-encoding", "connection", "transfer-encoding"}


def crear_app(destino: str, p429: float, p503: float, plento: float, demora: float, semilla: int = 2026) -> FastAPI:
    app = FastAPI(title="Proxy de fallas (ASR-07)")
    azar = random.Random(semilla)
    estadisticas = Counter()
    cliente = httpx.AsyncClient(base_url=destino.rstrip("/"), timeout=300)
    app.state.estadisticas = estadisticas

    @app.get("/_estadisticas")
    def ver_estadisticas() -> dict:
        return dict(estadisticas)

    @app.api_route("/{ruta:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def reenviar(ruta: str, request: Request) -> Response:
        estadisticas["peticiones"] += 1
        sorteo = azar.random()
        if sorteo < p429:
            estadisticas["inyectadas_429"] += 1
            return Response('{"error": {"code": "429", "message": "Rate limit (inyectada)"}}', status_code=429,
                            media_type="application/json", headers={"Retry-After": "1"})
        if sorteo < p429 + p503:
            estadisticas["inyectadas_503"] += 1
            return Response('{"error": {"code": "503", "message": "Unavailable (inyectada)"}}', status_code=503,
                            media_type="application/json")
        if sorteo < p429 + p503 + plento:
            estadisticas["inyectadas_demora"] += 1
            await asyncio.sleep(demora)
        cabeceras = {k: v for k, v in request.headers.items() if k.lower() not in SALTO}
        respuesta = await cliente.request(request.method, f"/{ruta}", params=request.query_params,
                                          content=await request.body(), headers=cabeceras)
        estadisticas["reenviadas"] += 1
        return Response(respuesta.content, status_code=respuesta.status_code,
                        headers={k: v for k, v in respuesta.headers.items() if k.lower() not in SALTO})

    return app


def main() -> int:
    import uvicorn
    from src.shared.config import obtener_configuracion

    parser = argparse.ArgumentParser(description="Proxy de inyección de fallas para Azure OpenAI.")
    parser.add_argument("--puerto", type=int, default=8099)
    parser.add_argument("--p429", type=float, default=0.2)
    parser.add_argument("--p503", type=float, default=0.1)
    parser.add_argument("--plento", type=float, default=0.05)
    parser.add_argument("--demora", type=float, default=20.0)
    args = parser.parse_args()
    app = crear_app(obtener_configuracion().azure_openai_endpoint, args.p429, args.p503, args.plento, args.demora)
    uvicorn.run(app, host="127.0.0.1", port=args.puerto, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
