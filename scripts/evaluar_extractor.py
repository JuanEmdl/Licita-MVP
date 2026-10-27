"""
Evalúa el Agente Extractor contra casos con respuesta esperada y mide su estabilidad:

    python -m scripts.evaluar_extractor                      # 3 corridas por caso
    python -m scripts.evaluar_extractor --corridas 5
    python -m scripts.evaluar_extractor --sistema otro_prompt.txt   # compara otro prompt de sistema

Cada caso (data/evaluacion/casos/*.json) trae el pliego, la ficha opcional de Datos
Abiertos, los requisitos esperados y textos que no deben extraerse. El texto recorre el
mismo camino que en el grafo: guardia, segmentador, extractor por fragmento y
eliminación de duplicados con la misma clave. Usa el modelo del .env (tiene costo) y
deja el informe en data/evaluacion/resultados/.

Un requisito esperado se da por encontrado cuando un requisito extraído contiene todas
sus claves (sin tildes ni mayúsculas). Si el extractor lo divide en varias partes,
ninguna contiene todas las claves: cuenta como no encontrado y las partes como extras.
"""
import argparse
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Optional

RAIZ = Path(__file__).resolve().parent.parent
CASOS = RAIZ / "data" / "evaluacion" / "casos"
RESULTADOS = RAIZ / "data" / "evaluacion" / "resultados"


# --- Calificación (sin red; la cubren las pruebas unitarias) ---

def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def _contiene(texto: str, claves: List[str]) -> bool:
    texto = normalizar(texto)
    return all(normalizar(c) in texto for c in claves)


def referencia_correcta(referencia: str, numeral: Optional[str]) -> bool:
    """El numeral esperado aparece completo: "3.1" no vale por "3.10" ni por "13.1"."""
    if not numeral:
        return True
    return re.search(rf"(?<![\d.]){re.escape(numeral)}(?![\d])", referencia or "") is not None


def calificar_corrida(caso: dict, requisitos: List[dict]) -> dict:
    """Empareja los requisitos extraídos con los esperados y clasifica los sobrantes."""
    libres = list(range(len(requisitos)))
    esperados = []
    for e in caso["esperados"]:
        indice = next((i for i in libres if _contiene(requisitos[i]["texto"], e["claves"])), None)
        if indice is None:
            esperados.append({"id": e["id"], "encontrado": False})
            continue
        libres.remove(indice)
        r = requisitos[indice]
        esperados.append({
            "id": e["id"],
            "encontrado": True,
            "texto": r["texto"],
            "categoria": r["categoria"],
            "categoria_ok": r["categoria"] == e["categoria"],
            "habilitante_ok": r["condicion_habilitante_propuesta"] == e["habilitante"],
            "referencia": r["referencia_documental"],
            "referencia_ok": referencia_correcta(r["referencia_documental"], e.get("referencia")),
        })

    duplicados, extras, prohibidos = [], [], []
    for i in libres:
        texto = requisitos[i]["texto"]
        if any(all(normalizar(c) in normalizar(texto) for c in p) for p in caso.get("prohibidos", [])):
            prohibidos.append(texto)
        elif any(_contiene(texto, e["claves"]) for e in caso["esperados"]):
            duplicados.append(texto)  # Otro requisito ya cubrió ese esperado: el solape no se eliminó.
        else:
            extras.append(texto)
    return {"total": len(requisitos), "esperados": esperados,
            "duplicados": duplicados, "extras": extras, "prohibidos": prohibidos}


def _firma(corrida: dict) -> tuple:
    """Resumen comparable de una corrida: dos corridas iguales producen la misma firma."""
    return (
        tuple((e["id"], e["encontrado"], e.get("categoria"), e.get("habilitante_ok")) for e in corrida["esperados"]),
        len(corrida["extras"]), len(corrida["duplicados"]), len(corrida["prohibidos"]),
    )


def _proporcion(valores: List[bool]) -> Optional[float]:
    return round(sum(valores) / len(valores), 3) if valores else None


def resumir(caso: dict, corridas: List[dict]) -> dict:
    validas = [c for c in corridas if "error" not in c]
    encontrados = [e for c in validas for e in c["esperados"] if e["encontrado"]]
    por_esperado = {}
    for e in caso["esperados"]:
        resultados = [x for c in validas for x in c["esperados"] if x["id"] == e["id"]]
        hallados = [x for x in resultados if x["encontrado"]]
        por_esperado[e["id"]] = {
            "encontrado": f"{len(hallados)}/{len(resultados)}",
            "categoria_esperada": e["categoria"],
            "categorias": dict(Counter(x["categoria"] for x in hallados)),
            "habilitante_ok": _proporcion([x["habilitante_ok"] for x in hallados]),
            "referencia_ok": _proporcion([x["referencia_ok"] for x in hallados]),
            "textos_distintos": len({normalizar(x["texto"]) for x in hallados}),
        }
    firmas = Counter(_firma(c) for c in validas)
    n = len(validas)
    return {
        "caso": caso["nombre"],
        "corridas": len(corridas),
        "errores": [c["error"] for c in corridas if "error" in c],
        "requisitos_por_corrida": [c["total"] for c in validas],
        "recall": _proporcion([e["encontrado"] for c in validas for e in c["esperados"]]),
        "categoria_ok": _proporcion([e["categoria_ok"] for e in encontrados]),
        "habilitante_ok": _proporcion([e["habilitante_ok"] for e in encontrados]),
        "referencia_ok": _proporcion([e["referencia_ok"] for e in encontrados]),
        "extras_por_corrida": round(sum(len(c["extras"]) for c in validas) / n, 2) if n else None,
        "duplicados_por_corrida": round(sum(len(c["duplicados"]) for c in validas) / n, 2) if n else None,
        "prohibidos_por_corrida": round(sum(len(c["prohibidos"]) for c in validas) / n, 2) if n else None,
        # Proporción de corridas idénticas a la más frecuente (1.0 = siempre el mismo resultado).
        "estabilidad": round(firmas.most_common(1)[0][1] / n, 3) if n else None,
        "por_esperado": por_esperado,
        "ejemplos_extras": sorted({t for c in validas for t in c["extras"]})[:8],
        "ejemplos_duplicados": sorted({t for c in validas for t in c["duplicados"]})[:8],
        "ejemplos_prohibidos": sorted({t for c in validas for t in c["prohibidos"]})[:8],
    }


# --- Casos y ejecución ---

def cargar_casos(directorio: Path = CASOS) -> List[dict]:
    casos = []
    for ruta in sorted(directorio.glob("*.json")):
        caso = json.loads(ruta.read_text(encoding="utf-8"))
        if caso.get("pliego_archivo"):
            caso["pliego"] = (RAIZ / caso["pliego_archivo"]).read_text(encoding="utf-8")
        caso["archivo"] = ruta.name
        casos.append(caso)
    return casos


def contenido_caso(caso: dict) -> str:
    """Igual que el nodo de recuperación del grafo: ficha de Datos Abiertos + pliego."""
    partes = [caso.get("ficha", ""), f"PLIEGO DE CONDICIONES:\n{caso['pliego']}" if caso.get("pliego") else ""]
    return "\n\n".join(p for p in partes if p)


def extraer(caso: dict, extractor) -> List[dict]:
    from src.worker_analysis.orchestrator.graph import _clave_requisito
    from src.worker_analysis.pipeline.guardia import GuardiaDocumental
    from src.worker_analysis.pipeline.segmentador import SegmentadorDocumental

    saneado = GuardiaDocumental().sanear_contenido(contenido_caso(caso))
    fragmentos = SegmentadorDocumental().segmentar(
        saneado, {"documento": "Expediente SECOP II", "version": "1.0"})
    vistos, requisitos = set(), []
    for fragmento in fragmentos:
        for r in extractor.extraer_requisitos(fragmento).requisitos:
            clave = _clave_requisito(r)
            if clave not in vistos:
                vistos.add(clave)
                requisitos.append(r.model_dump(mode="json"))
    return requisitos


def _ejecutar(caso: dict, extractor) -> dict:
    inicio = time.time()
    try:
        corrida = calificar_corrida(caso, extraer(caso, extractor))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    corrida["segundos"] = round(time.time() - inicio, 1)
    return corrida


def _pct(valor: Optional[float]) -> str:
    return "—" if valor is None else f"{valor * 100:.0f}%"


def imprimir(resumen: dict) -> None:
    print(f"\n■ {resumen['caso']}  ({resumen['corridas']} corridas)")
    for error in resumen["errores"]:
        print(f"  ERROR: {error}")
    print(f"  Requisitos por corrida: {resumen['requisitos_por_corrida']}")
    print(f"  Encontrados {_pct(resumen['recall'])} · categoría {_pct(resumen['categoria_ok'])} · "
          f"habilitante {_pct(resumen['habilitante_ok'])} · referencia {_pct(resumen['referencia_ok'])}")
    print(f"  Por corrida: extras {resumen['extras_por_corrida']} · duplicados {resumen['duplicados_por_corrida']} "
          f"· prohibidos {resumen['prohibidos_por_corrida']} · estabilidad {_pct(resumen['estabilidad'])}")
    for ident, d in resumen["por_esperado"].items():
        encontrados, total = map(int, d["encontrado"].split("/"))
        problemas = []
        if encontrados < total:
            problemas.append(f"encontrado {d['encontrado']}")
        if set(d["categorias"]) - {d["categoria_esperada"]}:
            problemas.append(f"categorías {d['categorias']}")
        if d["habilitante_ok"] is not None and d["habilitante_ok"] < 1:
            problemas.append(f"habilitante {_pct(d['habilitante_ok'])}")
        if d["referencia_ok"] is not None and d["referencia_ok"] < 1:
            problemas.append(f"referencia {_pct(d['referencia_ok'])}")
        if problemas:
            print(f"    - {ident}: {'; '.join(problemas)}")
    for rotulo in ("extras", "duplicados", "prohibidos"):
        for texto in resumen[f"ejemplos_{rotulo}"]:
            print(f"    {rotulo[:-1]}: {texto[:110]}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evalúa el Agente Extractor y su estabilidad.")
    parser.add_argument("--corridas", type=int, default=3, help="Corridas por caso (por defecto 3).")
    parser.add_argument("--sistema", type=Path, help="Archivo con otro prompt de sistema para comparar.")
    parser.add_argument("--casos", type=Path, default=CASOS, help="Carpeta de casos.")
    parser.add_argument("--hilos", type=int, default=4, help="Llamadas simultáneas al modelo.")
    args = parser.parse_args(argv)

    import src.worker_analysis.agents.extractor as modulo_extractor
    from src.shared.config import obtener_configuracion
    from src.worker_analysis.agents.prompts import VERSION_PROMPTS
    from src.worker_analysis.llm_gateway.gateway import LLMGateway

    etiqueta = f"v{VERSION_PROMPTS}"
    if args.sistema:
        # El extractor importa el prompt por nombre: se reemplaza en su módulo.
        modulo_extractor.SISTEMA_EXTRACTOR = args.sistema.read_text(encoding="utf-8")
        etiqueta = args.sistema.stem
    extractor = modulo_extractor.AgenteExtractor(LLMGateway())
    config = obtener_configuracion()

    casos = cargar_casos(args.casos)
    print(f"Prompt: {etiqueta} · modelo: {config.azure_openai_deployment} · "
          f"{len(casos)} casos × {args.corridas} corridas")

    with ThreadPoolExecutor(max_workers=max(1, args.hilos)) as pool:
        futuros = {(c["archivo"], i): pool.submit(_ejecutar, c, extractor)
                   for c in casos for i in range(args.corridas)}
        resumenes = [resumir(c, [futuros[(c["archivo"], i)].result() for i in range(args.corridas)])
                     for c in casos]

    for resumen in resumenes:
        imprimir(resumen)

    def promedio(campo):
        valores = [r[campo] for r in resumenes if r[campo] is not None]
        return round(sum(valores) / len(valores), 3) if valores else None

    total = {campo: promedio(campo) for campo in (
        "recall", "categoria_ok", "habilitante_ok", "referencia_ok", "estabilidad",
        "extras_por_corrida", "duplicados_por_corrida", "prohibidos_por_corrida")}
    print(f"\n■ TOTAL: encontrados {_pct(total['recall'])} · categoría {_pct(total['categoria_ok'])} · "
          f"habilitante {_pct(total['habilitante_ok'])} · referencia {_pct(total['referencia_ok'])} · "
          f"estabilidad {_pct(total['estabilidad'])} · extras {total['extras_por_corrida']} · "
          f"duplicados {total['duplicados_por_corrida']} · prohibidos {total['prohibidos_por_corrida']}")

    RESULTADOS.mkdir(parents=True, exist_ok=True)
    salida = RESULTADOS / f"{datetime.now():%Y%m%d-%H%M%S}_{etiqueta}.json"
    salida.write_text(json.dumps({
        "prompt": etiqueta, "modelo": config.azure_openai_deployment, "corridas": args.corridas,
        "total": total, "casos": resumenes,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nInforme: {salida.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
