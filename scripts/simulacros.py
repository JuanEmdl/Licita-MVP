"""
Simulacros del capítulo 5 en el ambiente local (contenedores y la base de pruebas).

    python -m scripts.simulacros api        # ASR-11: tiempo de recepción de POST /analisis/ (p50, p95, p99)
    python -m scripts.simulacros caida      # ASR-04: caída abrupta con 5 análisis en curso y reanudación
    python -m scripts.simulacros fallas     # ASR-07: 429, 503 y demoras inyectadas por scripts/proxy_fallas.py
    python -m scripts.simulacros escalado   # ASR-08: duplicar trabajadores sin tocar código

Usan la base de DB_CONNECTION_STRING (apúntela a licitaciones_test con 127.0.0.1). "caida" y
"fallas" llaman al modelo con el memorando financiero de la SDP (20 páginas): tienen costo bajo.
El resultado queda en data/evaluacion/resultados/<fecha>_simulacro_<tipo>.json.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

RAIZ = Path(__file__).resolve().parent.parent
RESULTADOS = RAIZ / "data" / "evaluacion" / "resultados"
PLIEGO_SIMULACRO = "data/evaluacion/pliegos_secop/02_sdp_fabrica_software/IF_PR_600_fab_software - pliego def.pdf"
LICITACION = "SIMULACRO-SDP-LP-003-2026"


def guardar(tipo: str, datos: dict) -> Path:
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    salida = RESULTADOS / f"{datetime.now():%Y%m%d-%H%M%S}_simulacro_{tipo}.json"
    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Informe: {salida.relative_to(RAIZ)}")
    return salida


def percentil(valores: List[float], p: float) -> float:
    ordenados = sorted(valores)
    return round(ordenados[min(len(ordenados) - 1, int(round(p / 100 * (len(ordenados) - 1))))], 4)


def texto_pliego() -> str:
    from src.shared.lectura_documentos import leer_documento
    ruta = RAIZ / PLIEGO_SIMULACRO
    return "\n".join(leer_documento(ruta.name, ruta.read_bytes()).paginas)


# --- ASR-11 ---

def simulacro_api(solicitudes: int) -> dict:
    """POST /analisis/ contra la API real (base real) con el publicador de la cola sustituido."""
    import httpx
    import uvicorn
    from src.api.main import app
    from src.api.modules.analysis import router as modulo

    publicados = []

    class PublicadorDeMedicion:
        def publicar(self, mensaje, *args, **kwargs):
            publicados.append(mensaje)

        def __getattr__(self, nombre):
            return lambda *a, **k: publicados.append((nombre, a, k))

    # Sin esto, cada solicitud viajaría a Service Bus y el trabajador analizaría cientos de pliegos.
    app.dependency_overrides[modulo.obtener_publicador] = lambda: PublicadorDeMedicion()
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8098, log_level="warning"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    while not servidor.started:
        time.sleep(0.1)
    cabeceras = {"Authorization": f"Bearer {os.environ['API_TOKEN_DESARROLLO']}"}
    tiempos, codigos = [], {}
    with httpx.Client(base_url="http://127.0.0.1:8098", headers=cabeceras, timeout=30) as cliente:
        for i in range(solicitudes):
            cuerpo = {"licitacion_url": f"CO1.REQ.SIMULACRO.{uuid.uuid4().hex[:10]}",
                      "contenido_pliego": "3.1 El proponente deberá estar inscrito en el RUP."}
            inicio = time.perf_counter()
            r = cliente.post("/analisis/", json=cuerpo)
            tiempos.append(time.perf_counter() - inicio)
            codigos[r.status_code] = codigos.get(r.status_code, 0) + 1
    servidor.should_exit = True
    hilo.join(timeout=10)
    return {"solicitudes": solicitudes, "codigos": codigos, "p50_s": percentil(tiempos, 50),
            "p95_s": percentil(tiempos, 95), "p99_s": percentil(tiempos, 99), "max_s": round(max(tiempos), 4),
            "media_s": round(statistics.mean(tiempos), 4), "umbral_p99_s": 1.0,
            "cumple": percentil(tiempos, 99) <= 1.0 and set(codigos) == {202},
            "mensajes_publicados": len(publicados),
            "alcance": "Recepción completa en la API (autenticación, validación, registro en PostgreSQL y "
                       "publicación); el envío a Service Bus se sustituye para no encolar trabajo real."}


# --- ASR-04 y ASR-07: análisis reales en proceso ---

def servicio():
    from src.shared.database import init_db
    from src.worker_analysis.servicio import ServicioAnalisis, crear_checkpointer_postgres
    init_db()
    return ServicioAnalisis(crear_checkpointer_postgres())


def crear_tareas(n: int, prefijo: str) -> List[str]:
    from src.shared.tareas_repo import RepositorioTareas
    repositorio = RepositorioTareas()
    ids = [f"{prefijo}-{uuid.uuid4().hex[:8]}" for _ in range(n)]
    for tarea_id in ids:
        repositorio.crear(tarea_id, LICITACION, "scripts.simulacros")
    return ids


def etapas_cerradas(srv, tarea_id: str) -> List[str]:
    """Etapas que el checkpoint ya registró como concluidas, en orden."""
    from src.worker_analysis.orchestrator.graph import ETAPAS
    snapshot = srv.grafo.get_state(srv._config(tarea_id))
    if not snapshot.values:
        return []
    if not snapshot.next:
        return list(ETAPAS)
    siguiente = snapshot.next[0]
    return list(ETAPAS[:ETAPAS.index(siguiente)]) if siguiente in ETAPAS else []


def ejecutar_tareas(ids: List[str]) -> None:
    """Proceso hijo: corre los análisis en paralelo como lo haría el trabajador (por_cola)."""
    import logging
    registro = logging.getLogger("src.worker_analysis.servicio")
    registro.setLevel(logging.INFO)
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(logging.Formatter("%(message)s"))
    registro.addHandler(manejador)
    srv = servicio()
    pliego = texto_pliego()

    def uno(tarea_id):
        try:
            srv.iniciar_analisis(tarea_id, LICITACION, pliego, por_cola=True)
            print(f"[{tarea_id}] fin {etapas_cerradas(srv, tarea_id)}", flush=True)
        except Exception as e:  # noqa: BLE001 - el padre lee el resultado del checkpoint
            print(f"[{tarea_id}] excepción {type(e).__name__}: {e}", flush=True)

    hilos = [threading.Thread(target=uno, args=(t,)) for t in ids]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()


def _hijo(ids: List[str]) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "scripts.simulacros", "_ejecutar", *ids], cwd=RAIZ,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")


def _nodos_ejecutados(salida: str, tarea_id: str) -> List[str]:
    marca = f"Tarea {tarea_id}: nodo completado "
    return [linea.split(marca, 1)[1].strip() for linea in salida.splitlines() if marca in linea]


def simulacro_caida(n: int) -> dict:
    srv = servicio()
    ids = crear_tareas(n, "caida")
    print(f"Iniciando {n} análisis en un proceso aparte…")
    proceso = _hijo(ids)
    inicio = time.time()
    # Se espera a que todas las tareas tengan alguna etapa cerrada y al menos una esté extrayendo.
    while time.time() - inicio < 600:
        cerradas = {t: etapas_cerradas(srv, t) for t in ids}
        if all(cerradas.values()) and any("segmentando" in c for c in cerradas.values()):
            break
        time.sleep(1)
    antes = {t: etapas_cerradas(srv, t) for t in ids}
    proceso.kill()  # TerminateProcess en Windows, SIGKILL en Linux: sin cierre ordenado
    instante_caida = time.time()
    salida_previa = proceso.communicate()[0]
    print(f"Caída forzada a los {instante_caida - inicio:.0f} s. Etapas cerradas: {antes}")

    reinicio = time.time()
    proceso = _hijo(ids)  # el trabajador reiniciado recibe otra vez los mensajes (FF-08)
    salida = proceso.communicate(timeout=3600)[0]
    fin = time.time()
    tareas = {}
    for t in ids:
        ejecutados = _nodos_ejecutados(salida, t)
        if not ejecutados:
            raise RuntimeError("El proceso reiniciado no registró etapas: no se puede verificar la reanudación.")
        tareas[t] = {"cerradas_antes_de_la_caida": antes[t], "cerradas_al_final": etapas_cerradas(srv, t),
                     "nodos_ejecutados_tras_reiniciar": ejecutados,
                     "etapas_repetidas": [nodo for nodo in ejecutados if nodo in antes[t]],
                     "estado": (srv.repositorio.obtener(t) or {}).get("estado")}
    llegaron = sum("extrayendo" in d["cerradas_al_final"] for d in tareas.values())
    return {"tareas": tareas, "tareas_en_curso": n, "segundos_hasta_caida": round(instante_caida - inicio, 1),
            "segundos_reanudacion_hasta_compuerta": round(fin - reinicio, 1),
            "tareas_recuperadas": llegaron, "etapas_repetidas": sum(len(d["etapas_repetidas"]) for d in tareas.values()),
            "salida_proceso_caido": salida_previa[-3000:],
            "cumple": llegaron == n and all(not d["etapas_repetidas"] for d in tareas.values()),
            "alcance": "Caída del proceso del trabajador en la máquina local; la restauración de la base desde "
                       "respaldo (RTO 4 h, RPO 12 h) se verifica en Azure con la restauración a un punto en el tiempo."}


def simulacro_fallas(n: int, entregas: int) -> dict:
    """El proxy debe estar arriba y AZURE_OPENAI_ENDPOINT apuntar a él (lo hace main)."""
    from src.worker_analysis.servicio import ReintentoPendienteError, espera_antes_de_reintentar
    srv = servicio()
    pliego = texto_pliego()
    ids = crear_tareas(n, "fallas")
    resultado = {}

    def uno(tarea_id):
        intentos, historial = 0, []
        while intentos < entregas:
            intentos += 1
            try:
                srv.iniciar_analisis(tarea_id, LICITACION, pliego, por_cola=True)
                break
            except ReintentoPendienteError as e:
                espera = espera_antes_de_reintentar(intentos)
                historial.append({"entrega": intentos, "etapas_conservadas": etapas_cerradas(srv, tarea_id),
                                  "espera_s": round(espera, 1), "causa": str(e)[:160]})
                time.sleep(espera)  # lo mismo que hace el trabajador antes de devolver el mensaje (DEF-02)
            except Exception as e:  # noqa: BLE001 - cualquier otra excepción es una caída del núcleo
                historial.append({"entrega": intentos, "caida_del_nucleo": f"{type(e).__name__}: {e}"})
                break
        resultado[tarea_id] = {"entregas": intentos, "reintentos": historial,
                               "etapas_finales": etapas_cerradas(srv, tarea_id),
                               "estado": (srv.repositorio.obtener(tarea_id) or {}).get("estado")}

    hilos = [threading.Thread(target=uno, args=(t,)) for t in ids]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    caidas = sum(any("caida_del_nucleo" in r for r in d["reintentos"]) for d in resultado.values())
    # Ninguna entrega perdió etapas: lo cerrado en una entrega sigue cerrado en la siguiente.
    perdidas = 0
    for d in resultado.values():
        previas = []
        for r in d["reintentos"]:
            actuales = r.get("etapas_conservadas", previas)
            perdidas += len(set(previas) - set(actuales))
            previas = actuales
    return {"tareas": resultado, "caidas_del_nucleo": caidas, "etapas_perdidas": perdidas,
            "llegaron_a_revision": sum("extrayendo" in d["etapas_finales"] for d in resultado.values()),
            "cumple": caidas == 0 and perdidas == 0}


# --- ASR-08 ---

def simulacro_escalado() -> dict:
    def compose(*args):
        return subprocess.run(["docker", "compose", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
                              errors="replace")

    def cambios_en_codigo() -> str:
        return subprocess.run(["git", "status", "--porcelain", "--", "src", "docker", "docker-compose.yml"], cwd=RAIZ,
                              capture_output=True, text=True).stdout

    antes = cambios_en_codigo()
    inicio = time.time()
    compose("up", "-d", "--no-recreate", "--scale", "worker_analysis=2", "worker_analysis")
    listos, contenedores = None, []
    while time.time() - inicio < 300:
        contenedores = [c for c in compose("ps", "-q", "worker_analysis").stdout.split() if c]
        registros = [subprocess.run(["docker", "logs", c], capture_output=True, text=True, encoding="utf-8",
                                    errors="replace") for c in contenedores]
        if len(contenedores) >= 2 and all("Iniciando trabajador" in (r.stdout + r.stderr) for r in registros):
            listos = time.time()
            break
        time.sleep(2)
    compose("up", "-d", "--no-recreate", "--scale", "worker_analysis=1", "worker_analysis")
    segundos = round(listos - inicio, 1) if listos else None
    return {"replicas_alcanzadas": len(contenedores), "segundos_hasta_duplicar": segundos, "umbral_s": 300,
            "archivos_de_codigo_modificados": len(set(cambios_en_codigo().splitlines()) - set(antes.splitlines())),
            "cumple": bool(listos) and segundos <= 300,
            "alcance": "Réplicas del trabajador con Docker Compose en la máquina local. En Azure el escalado lo hace "
                       "la regla de longitud de cola de Container Apps (infra/terraform/apps.tf)."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Simulacros del capítulo 5.")
    parser.add_argument("tipo", choices=("api", "caida", "fallas", "escalado", "_ejecutar"))
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--solicitudes", type=int, default=1000)
    parser.add_argument("--tareas", type=int, default=5)
    parser.add_argument("--entregas", type=int, default=10, help="Como SERVICE_BUS_MAX_ENTREGAS.")
    parser.add_argument("--p429", type=float, default=0.2)
    parser.add_argument("--p503", type=float, default=0.1)
    parser.add_argument("--plento", type=float, default=0.05)
    parser.add_argument("--demora", type=float, default=20.0, help="Segundos de las respuestas demoradas.")
    args = parser.parse_args(argv)

    if args.tipo == "_ejecutar":
        ejecutar_tareas(args.ids)
        return 0
    if args.tipo == "api":
        os.environ["AUTH_MODE"] = "desarrollo"
        os.environ.setdefault("API_TOKEN_DESARROLLO", "simulacro-" + uuid.uuid4().hex)
        datos = simulacro_api(args.solicitudes)
    elif args.tipo == "caida":
        datos = simulacro_caida(args.tareas)
    elif args.tipo == "fallas":
        import uvicorn
        from src.shared.config import obtener_configuracion
        from scripts.proxy_fallas import crear_app
        # El tiempo de espera del cliente queda el de producción (LLM_TIMEOUT_S): una demora de más de
        # 15 s es el estímulo de ASR-07, no un error del cliente.
        app = crear_app(obtener_configuracion().azure_openai_endpoint, args.p429, args.p503, args.plento, args.demora)
        proxy = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8099, log_level="warning"))
        threading.Thread(target=proxy.run, daemon=True).start()
        while not proxy.started:
            time.sleep(0.1)
        os.environ["AZURE_OPENAI_ENDPOINT"] = "http://127.0.0.1:8099"
        obtener_configuracion.cache_clear() if hasattr(obtener_configuracion, "cache_clear") else None
        datos = simulacro_fallas(args.tareas, args.entregas)
        datos["fallas_inyectadas"] = dict(app.state.estadisticas)
        datos["probabilidades"] = {"p429": args.p429, "p503": args.p503, "plento": args.plento, "demora_s": args.demora}
        proxy.should_exit = True
    else:
        datos = simulacro_escalado()
    print(json.dumps({k: v for k, v in datos.items() if k not in ("tareas", "salida_proceso_caido")},
                     ensure_ascii=False, indent=2, default=str))
    guardar(args.tipo, datos)
    return 0 if datos.get("cumple") else 1


if __name__ == "__main__":
    sys.exit(main())
