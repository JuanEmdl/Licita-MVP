"""
Corrección funcional del MVP sobre pliegos reales de SECOP II (capítulo 5, ISO/IEC 25010:2023).

    python -m scripts.evaluar_corpus                         # extracción y dictamen de todos los casos
    python -m scripts.evaluar_corpus --fase extraccion       # solo el extractor (no necesita base)
    python -m scripts.evaluar_corpus --casos 01,04           # algunos casos
    python -m scripts.evaluar_corpus --precision data/evaluacion/resultados/<muestra>.json

Cada caso (data/evaluacion/corpus/*.json) trae los documentos descargados de SECOP II, la lista
de referencia de requisitos con su dictamen esperado y un portafolio ficticio construido para
ese pliego. El resultado esperado se fija antes de correr el sistema (oráculo por construcción).

Extracción: los documentos recorren los nodos reales del grafo (lectura, guardia, segmentador,
extractor en paralelo y eliminación de duplicados). Un requisito de referencia se da por
encontrado cuando un requisito extraído contiene todas sus claves, o todas las de una de sus
alternativas (sin tildes ni mayúsculas).

Dictamen: el portafolio del caso se publica como una versión nueva y se vectoriza; el evaluador
dictamina los requisitos encontrados, tal como los aprobaría el analista (con la categoría y el
carácter habilitante de la referencia). Un dictamen esperado null no entra en la exactitud.

Precisión: los requisitos extraídos fuera de la referencia se adjudican a mano sobre una muestra
fija (semilla 2026). La corrida deja la muestra con "valido": null para completar.

Usa el modelo y la base del .env (tiene costo). Para no tocar la base de desarrollo, apunte
DB_CONNECTION_STRING a licitaciones_test.
"""
import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from scripts.evaluar_extractor import normalizar, referencia_correcta

RAIZ = Path(__file__).resolve().parent.parent
CASOS = RAIZ / "data" / "evaluacion" / "corpus"
RESULTADOS = RAIZ / "data" / "evaluacion" / "resultados"
ESTADOS = ("Cumple", "Cumple parcialmente", "No cumple", "No verificable")
MUESTRA_POR_CASO = 10


# --- Calificación (sin red; la cubren las pruebas unitarias) ---

def _comparable(texto: str) -> str:
    """Sin tildes ni mayúsculas, con coma decimal: 2.10 y 2,10 son la misma cifra."""
    return re.sub(r"(?<=\d)\.(?=\d)", ",", normalizar(texto))


def _contiene_clave(texto: str, clave: str) -> bool:
    clave = _comparable(clave)
    if re.search(r"\d", clave):
        # Una cifra coincide completa: el 1,5 exigido no se confunde con el 1,52 de otro proceso.
        return re.search(rf"(?<![\d,]){re.escape(clave)}(?![\d]|,\d)", texto) is not None
    return clave in texto


def coincide(texto: str, esperado: dict) -> bool:
    texto = _comparable(texto)
    grupos = [esperado["claves"]] + esperado.get("alternativas", [])
    return any(all(_contiene_clave(texto, c) for c in grupo) for grupo in grupos)


def cifras(texto: str) -> List[str]:
    """Cifras del texto normalizadas (4,0 / 4.0 → 4,0; 1.000.000 → 1000000)."""
    encontradas = []
    for c in re.findall(r"\d+(?:[.,]\d+)*", texto or ""):
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", c):
            c = c.replace(".", "")
        encontradas.append(c.replace(".", ","))
    return encontradas


def cifras_ancladas(texto: str, fuente: str) -> bool:
    """Toda cifra del requisito aparece en el documento: el extractor no inventó valores."""
    disponibles = set(cifras(fuente))
    return all(c in disponibles for c in cifras(texto))


def emparejar(caso: dict, requisitos: List[dict]) -> dict:
    libres = list(range(len(requisitos)))
    esperados = []
    for e in caso["esperados"]:
        candidatos = [i for i in libres if coincide(requisitos[i]["texto"], e)]
        # Si varios coinciden, se prefiere el que cita el numeral esperado (el mismo tema aparece
        # también en el alcance o en las notas).
        indice = next((i for i in candidatos if e.get("referencia")
                       and referencia_correcta(requisitos[i]["referencia_documental"], e["referencia"])),
                      candidatos[0] if candidatos else None)
        if indice is None:
            esperados.append({"id": e["id"], "encontrado": False})
            continue
        libres.remove(indice)
        r = requisitos[indice]
        esperados.append({
            "id": e["id"], "encontrado": True, "indice": indice, "texto": r["texto"],
            "categoria_ok": r["categoria"] == e["categoria"],
            "habilitante_ok": r["condicion_habilitante_propuesta"] == e["habilitante"],
            "referencia": r["referencia_documental"],
            "referencia_ok": referencia_correcta(r["referencia_documental"], e.get("referencia")),
        })
    prohibidos, sobrantes = [], []
    for i in libres:
        texto = requisitos[i]["texto"]
        if any(all(_contiene_clave(_comparable(texto), c) for c in p) for p in caso.get("prohibidos", [])):
            prohibidos.append(texto)
        else:
            sobrantes.append(i)
    return {"esperados": esperados, "prohibidos": prohibidos, "sobrantes": sobrantes}


def proporcion(valores) -> Optional[float]:
    valores = list(valores)
    return round(sum(valores) / len(valores), 3) if valores else None


def kappa(pares: List[tuple]) -> Optional[float]:
    """Kappa de Cohen entre el dictamen esperado y el emitido."""
    n = len(pares)
    if not n:
        return None
    observado = sum(a == b for a, b in pares) / n
    esperado_azar = sum((sum(a == k for a, _ in pares) / n) * (sum(b == k for _, b in pares) / n) for k in ESTADOS)
    return round((observado - esperado_azar) / (1 - esperado_azar), 3) if esperado_azar < 1 else None


def resumen_dictamen(pares: List[tuple]) -> dict:
    matriz = {e: {o: 0 for o in ESTADOS} for e in ESTADOS}
    for esperado, obtenido in pares:
        matriz[esperado][obtenido] += 1
    return {"evaluados": len(pares), "exactitud": proporcion(a == b for a, b in pares),
            "kappa": kappa(pares), "matriz": matriz}


def precision_adjudicada(muestra: dict) -> dict:
    """Precisión = (encontrados + sobrantes válidos estimados) / total extraído, por caso y global."""
    casos, total_extraidos, total_validos = {}, 0, 0.0
    for nombre, c in muestra["casos"].items():
        juzgados = [m["valido"] for m in c["muestra"] if m["valido"] is not None]
        tasa = sum(juzgados) / len(juzgados) if juzgados else None
        validos = c["encontrados"] + c["prohibidos_validos"] + (tasa * c["sobrantes"] if tasa is not None else 0)
        casos[nombre] = {"tasa_sobrantes_validos": None if tasa is None else round(tasa, 3),
                         "precision": round(validos / c["extraidos"], 3) if c["extraidos"] else None,
                         "juzgados": len(juzgados)}
        total_extraidos += c["extraidos"]
        total_validos += validos
    return {"casos": casos, "precision": round(total_validos / total_extraidos, 3) if total_extraidos else None}


# --- Ejecución ---

class ContadorTokens:
    """Sustituye al repositorio de consumo: acumula los tokens de la corrida sin cuota (RF-043)."""

    def __init__(self):
        self.entrada = self.salida = self.llamadas = 0

    def agotada(self) -> bool:
        return False

    def estado(self) -> dict:
        return {"periodo": "evaluacion", "consumido": self.entrada + self.salida, "limite": None}

    def registrar(self, operacion, tokens_entrada, tokens_salida, modelo=None, tarea_id=None, estimado=False):
        self.entrada += tokens_entrada or 0
        self.salida += tokens_salida or 0
        self.llamadas += 1

    def tomar(self) -> dict:
        lectura = {"tokens_entrada": self.entrada, "tokens_salida": self.salida, "llamadas": self.llamadas}
        self.entrada = self.salida = self.llamadas = 0
        return lectura


class _SinFicha:
    """Datos Abiertos queda fuera: se evalúa lo que dicen los documentos del pliego."""

    def recuperar_expediente(self, licitacion_id: str) -> dict:
        return {"id_proceso": licitacion_id, "contenido_crudo": ""}


def cargar_casos(seleccion: Optional[List[str]] = None) -> List[dict]:
    casos = []
    for ruta in sorted(CASOS.glob("*.json")):
        if seleccion and not any(ruta.name.startswith(s) for s in seleccion):
            continue
        caso = json.loads(ruta.read_text(encoding="utf-8"))
        caso["archivo"] = ruta.stem
        casos.append(caso)
    return casos


def leer_documentos(caso: dict) -> List[dict]:
    from src.shared.lectura_documentos import leer_documento
    documentos = []
    for relativa in caso["documentos"]:
        ruta = RAIZ / relativa
        lectura = leer_documento(ruta.name, ruta.read_bytes())
        documentos.append({"nombre": ruta.name, "version": 1, "procedencia": "SECOP II (carga manual)",
                           "paginas": lectura.paginas})
    return documentos


def orquestador(gateway, paralelismo: int):
    from src.worker_analysis.agents.evaluator import AgenteEvaluador
    from src.worker_analysis.agents.extractor import AgenteExtractor
    from src.worker_analysis.orchestrator.graph import OrquestadorAnalisis
    from src.worker_analysis.pipeline.guardia import GuardiaDocumental
    from src.worker_analysis.pipeline.segmentador import SegmentadorDocumental
    return OrquestadorAnalisis(
        extractor=AgenteExtractor(gateway), evaluador=AgenteEvaluador(gateway), guardia=GuardiaDocumental(),
        segmentador=SegmentadorDocumental(), motor_puntaje=None, recomendador=None, informe=None,
        auditoria=None, adaptador_secop=_SinFicha(), paralelismo=paralelismo)


def extraer(caso: dict, orq) -> dict:
    """Los nodos del grafo de recuperación a extracción, con los documentos del caso."""
    documentos = leer_documentos(caso)
    orq.proveedor_expediente = lambda _url: {"documentos": documentos, "no_analizados": []}
    estado = {"tarea_id": f"evaluacion-{caso['archivo']}", "licitacion_url": caso["proceso"]}
    inicio = time.time()
    for nodo in (orq._recuperar_expediente, orq._sanear_contenido, orq._segmentar_contenido,
                 orq._extraer_requisitos):
        estado.update(nodo(estado))
        if estado.get("error_msg"):
            raise RuntimeError(f"Análisis suspendido por la guardia: {estado['error_msg']}")
    fuente = "\n".join("\n".join(d["paginas"]) for d in documentos)
    return {"segundos": round(time.time() - inicio, 1), "requisitos": estado["requisitos_extraidos"],
            "fragmentos": len(estado.get("fragmentos") or []), "fuente": fuente,
            "paginas": sum(len(d["paginas"]) for d in documentos), "palabras": len(fuente.split())}


def dictaminar(caso: dict, emparejados: List[dict], requisitos: List[dict], gateway) -> List[dict]:
    from src.shared.portfolio_repo import RepositorioVersionesPortafolio
    from src.shared.schemas.domain import RequisitoExtraido
    from src.worker_analysis.agents.evaluator import AgenteEvaluador

    repositorio = RepositorioVersionesPortafolio()
    version = repositorio.publicar(caso["portafolio"], "scripts.evaluar_corpus",
                                   f"Portafolio de evaluación {caso['archivo']}")["version"]
    repositorio.indexar(version, gateway.obtener_modelo_embeddings())
    evaluador = AgenteEvaluador(gateway)
    referencia = {e["id"]: e for e in caso["esperados"]}
    dictamenes = []
    for e in emparejados:
        esperado = referencia[e["id"]]
        if not e["encontrado"] or esperado.get("dictamen") is None:
            continue
        r = requisitos[e["indice"]]
        aprobado = RequisitoExtraido(identificador=r["identificador"], texto=r["texto"],
                                     categoria=esperado["categoria"],
                                     condicion_habilitante_propuesta=esperado["habilitante"],
                                     referencia_documental=r["referencia_documental"])
        d = evaluador.evaluar_requisito(aprobado, portafolio_version=version)
        dictamenes.append({"id": e["id"], "esperado": esperado["dictamen"], "obtenido": d.estado.value,
                           "evidencia": d.evidencia, "justificacion": d.justificacion})
    return dictamenes


def evaluar_caso(caso: dict, orq, gateway, contador: ContadorTokens, con_dictamen: bool, azar) -> dict:
    extraccion = extraer(caso, orq)
    tokens_extraccion = contador.tomar()
    requisitos = extraccion["requisitos"]
    emp = emparejar(caso, requisitos)
    encontrados = [e for e in emp["esperados"] if e["encontrado"]]
    sobrantes = [requisitos[i]["texto"] for i in emp["sobrantes"]]
    resultado = {
        "caso": caso["nombre"], "archivo": caso["archivo"], "paginas": extraccion["paginas"],
        "palabras": extraccion["palabras"], "fragmentos": extraccion["fragmentos"],
        "segundos_extraccion": extraccion["segundos"], "extraidos": len(requisitos),
        "referencia": len(caso["esperados"]), "encontrados": len(encontrados),
        "exhaustividad": proporcion(e["encontrado"] for e in emp["esperados"]),
        "categoria_ok": proporcion(e["categoria_ok"] for e in encontrados),
        "habilitante_ok": proporcion(e["habilitante_ok"] for e in encontrados),
        "referencia_ok": proporcion(e["referencia_ok"] for e in encontrados
                                    if next(x for x in caso["esperados"] if x["id"] == e["id"]).get("referencia")),
        "cifras_ancladas": proporcion(cifras_ancladas(r["texto"], extraccion["fuente"]) for r in requisitos),
        "prohibidos": emp["prohibidos"], "sobrantes": len(sobrantes),
        "no_encontrados": [e["id"] for e in emp["esperados"] if not e["encontrado"]],
        "emparejados": emp["esperados"], "tokens_extraccion": tokens_extraccion,
        # La lista completa permite revisar el emparejamiento y la precisión sin volver a extraer.
        "requisitos": requisitos,
        "muestra_precision": [{"texto": t, "valido": None}
                              for t in azar.sample(sobrantes, min(MUESTRA_POR_CASO, len(sobrantes)))],
    }
    if con_dictamen:
        inicio = time.time()
        dictamenes = dictaminar(caso, emp["esperados"], requisitos, gateway)
        resultado.update({"segundos_dictamen": round(time.time() - inicio, 1), "dictamenes": dictamenes,
                          "tokens_dictamen": contador.tomar(),
                          "dictamen": resumen_dictamen([(d["esperado"], d["obtenido"]) for d in dictamenes])})
    return resultado


def imprimir(r: dict) -> None:
    print(f"\n■ {r['caso']}  ({r['paginas']} páginas, {r['palabras']} palabras, {r['fragmentos']} fragmentos)")
    print(f"  Extracción {r['segundos_extraccion']} s · {r['extraidos']} extraídos · "
          f"exhaustividad {r['encontrados']}/{r['referencia']} ({r['exhaustividad']}) · categoría "
          f"{r['categoria_ok']} · habilitante {r['habilitante_ok']} · numeral {r['referencia_ok']} · "
          f"cifras ancladas {r['cifras_ancladas']} · prohibidos {len(r['prohibidos'])}")
    if r["no_encontrados"]:
        print(f"  No encontrados: {', '.join(r['no_encontrados'])}")
    if "dictamen" in r:
        d = r["dictamen"]
        print(f"  Dictamen: exactitud {d['exactitud']} sobre {d['evaluados']} · kappa {d['kappa']}")
        for x in r["dictamenes"]:
            if x["esperado"] != x["obtenido"]:
                print(f"    - {x['id']}: esperado {x['esperado']}, obtenido {x['obtenido']}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Corrección funcional sobre pliegos reales de SECOP II.")
    parser.add_argument("--fase", choices=("todo", "extraccion"), default="todo")
    parser.add_argument("--casos", help="Prefijos de los casos separados por coma (por defecto, todos).")
    parser.add_argument("--precision", type=Path, help="Calcula la precisión con una muestra ya adjudicada.")
    parser.add_argument("--paralelismo", type=int, help="Fragmentos en paralelo (por defecto, la configuración).")
    args = parser.parse_args(argv)

    if args.precision:
        print(json.dumps(precision_adjudicada(json.loads(args.precision.read_text(encoding="utf-8"))),
                         ensure_ascii=False, indent=2))
        return 0

    from src.shared.config import obtener_configuracion
    from src.worker_analysis.agents.prompts import VERSION_PROMPTS
    from src.worker_analysis.llm_gateway.gateway import LLMGateway

    config = obtener_configuracion()
    contador = ContadorTokens()
    gateway = LLMGateway(consumo=contador)
    paralelismo = args.paralelismo or config.analisis_paralelismo
    orq = orquestador(gateway, paralelismo)
    con_dictamen = args.fase == "todo"
    if con_dictamen:
        from src.shared.database import init_db
        init_db()

    casos = cargar_casos(args.casos.split(",") if args.casos else None)
    print(f"Prompts v{VERSION_PROMPTS} · modelo {config.azure_openai_deployment} · paralelismo {paralelismo} "
          f"· {len(casos)} casos · fase {args.fase}")
    azar = random.Random(2026)
    resultados = []
    for caso in casos:
        try:
            r = evaluar_caso(caso, orq, gateway, contador, con_dictamen, azar)
        except Exception as e:
            r = {"caso": caso["nombre"], "archivo": caso["archivo"], "error": f"{type(e).__name__}: {e}"}
            print(f"\n■ {caso['nombre']}: ERROR {r['error']}")
        else:
            imprimir(r)
        resultados.append(r)

    validos = [r for r in resultados if "error" not in r]
    referencia = sum(r["referencia"] for r in validos)
    pares = [(d["esperado"], d["obtenido"]) for r in validos for d in r.get("dictamenes", [])]
    total = {
        "casos": len(validos), "errores": len(resultados) - len(validos),
        "exhaustividad": round(sum(r["encontrados"] for r in validos) / referencia, 3) if referencia else None,
        "categoria_ok": proporcion(e["categoria_ok"] for r in validos for e in r["emparejados"] if e["encontrado"]),
        "habilitante_ok": proporcion(e["habilitante_ok"] for r in validos for e in r["emparejados"] if e["encontrado"]),
        "extraidos": sum(r["extraidos"] for r in validos),
        "prohibidos": sum(len(r["prohibidos"]) for r in validos),
        "segundos_extraccion": [r["segundos_extraccion"] for r in validos],
        "tokens": {k: sum(r.get(t, {}).get(k, 0) for r in validos for t in ("tokens_extraccion", "tokens_dictamen"))
                   for k in ("tokens_entrada", "tokens_salida", "llamadas")},
        "dictamen": resumen_dictamen(pares) if pares else None,
    }
    print(f"\n■ TOTAL: exhaustividad {total['exhaustividad']} · categoría {total['categoria_ok']} · "
          f"habilitante {total['habilitante_ok']} · prohibidos {total['prohibidos']} · tokens {total['tokens']}")
    if total["dictamen"]:
        print(f"  Dictamen: exactitud {total['dictamen']['exactitud']} sobre {total['dictamen']['evaluados']} "
              f"· kappa {total['dictamen']['kappa']}")

    RESULTADOS.mkdir(parents=True, exist_ok=True)
    marca = f"{datetime.now():%Y%m%d-%H%M%S}"
    salida = RESULTADOS / f"{marca}_corpus_v{VERSION_PROMPTS}.json"
    salida.write_text(json.dumps({"prompts": VERSION_PROMPTS, "modelo": config.azure_openai_deployment,
                                  "paralelismo": paralelismo, "fase": args.fase, "total": total,
                                  "casos": resultados}, ensure_ascii=False, indent=2), encoding="utf-8")
    muestra = RESULTADOS / f"{marca}_muestra_precision.json"
    muestra.write_text(json.dumps({"origen": salida.name, "casos": {
        r["archivo"]: {"extraidos": r["extraidos"], "encontrados": r["encontrados"], "sobrantes": r["sobrantes"],
                       "prohibidos_validos": 0, "muestra": r["muestra_precision"]} for r in validos}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nInforme: {salida.relative_to(RAIZ)}\nMuestra para adjudicar: {muestra.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
