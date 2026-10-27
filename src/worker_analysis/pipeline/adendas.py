"""
Revisión parcial tras un cambio documental (HU-06 CA-03).

Cuando un proceso ya tiene una lista de requisitos aprobada y su expediente cambia (se
publica una adenda o una versión nueva de un documento), el análisis nuevo no obliga al
analista a revisar todo otra vez: los requisitos que el cambio no toca conservan su
aprobación y solo los afectados vuelven a revisión. La comparación es determinista:

- Versión nueva de un documento: el requisito queda afectado si cambió el texto del
  numeral que cita (o si no cita numeral, o el numeral ya no se encuentra).
- Documento nuevo (adenda): el requisito queda afectado si la adenda cita su numeral, el
  capítulo que lo contiene o un subnumeral suyo. Una adenda que no cita numerales afecta
  a toda la lista, porque no se puede saber qué modifica.
- Documento retirado: los requisitos que lo citan quedan afectados.

Ante la duda se marca el requisito: un requisito modificado que se evalúa con la versión
anterior puede descalificar la oferta.
"""
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from src.worker_analysis.pipeline.segmentador import MARCA_PAGINA, SegmentadorDocumental

CONSERVADO = "Conserva la aprobación"
AFECTADO = "Pendiente de revisión"
NUEVO = "Nuevo"

_PAGINAS = re.compile(r"p[aá]g(?:ina)?s?\.?\s*\d+(?:\s*(?:-|–|,|y)\s*\d+)*", re.IGNORECASE)
_NUMERO = re.compile(r"(?<![\w.])\d+(?:\.\d+)*(?![\w])")
_CITA = re.compile(
    r"(?:numeral(?:es)?|secci[oó]n(?:es)?|cap[ií]tulos?|art[ií]culos?|[ií]tems?|literal(?:es)?|subnumeral(?:es)?|puntos?)"
    r"\s+((?:\d+(?:\.\d+)*\.?)(?:\s*(?:,|y|e|al|a|hasta)\s*\d+(?:\.\d+)*\.?)*)", re.IGNORECASE)
_ES_ADENDA = re.compile(r"adenda|modificatori|se\s+modifica|modif[ií]quese", re.IGNORECASE)
_SIMILITUD_MINIMA = 0.6


def _normalizar(texto: str) -> str:
    """Sin marcas de página ni espacios repetidos; conserva las líneas para ubicar los numerales."""
    lineas = (" ".join(l.split()) for l in MARCA_PAGINA.sub("\n", texto or "").splitlines())
    return "\n".join(l for l in lineas if l)


def _numeral_valido(token: str) -> bool:
    """Un numeral de pliego (4, 4.2, 4.2.1), no una cifra (1.500.000) ni un año."""
    partes = token.rstrip(".").split(".")
    return len(partes) <= 6 and all(1 <= len(p) <= 2 for p in partes)


def textos_por_documento(contenido: str) -> Dict[str, str]:
    """Texto normalizado de cada documento del contenido armado por el orquestador."""
    documentos = SegmentadorDocumental._documentos(contenido or "", {"documento": ""})
    return {meta["documento"]: _normalizar(texto) for meta, texto in documentos if texto.strip()}


def documento_de(referencia: str) -> Optional[str]:
    """«Pliego (v2) · Numeral 4.2, página 7» → «Pliego» (formato de completar_referencia)."""
    m = re.match(r"^(.*?) \(v[^)]*\) · ", referencia or "")
    return m.group(1) if m else None


def numeral_de(referencia: str) -> Optional[str]:
    resto = (referencia or "").split(" · ", 1)[-1]
    for token in _NUMERO.findall(_PAGINAS.sub(" ", resto)):
        if _numeral_valido(token):
            return token.rstrip(".")
    return None


def numerales_citados(texto: str) -> List[str]:
    citados = []
    for grupo in _CITA.findall(texto or ""):
        citados += [t.rstrip(".") for t in _NUMERO.findall(grupo) if _numeral_valido(t)]
    return sorted(set(citados))


def _relacionados(a: str, b: str) -> bool:
    """El mismo numeral, o uno contiene al otro (el capítulo 4 contiene el 4.2)."""
    return a == b or a.startswith(b + ".") or b.startswith(a + ".")


def seccion(texto: str, numeral: str) -> Optional[str]:
    """Texto del numeral hasta el siguiente numeral que no sea subnumeral suyo; None si no aparece."""
    lineas = [l.strip() for l in MARCA_PAGINA.sub("\n", texto or "").splitlines()]
    inicio = re.compile(rf"^(?:(?:numeral|secci[oó]n|cap[ií]tulo)\s+)?{re.escape(numeral)}\.?(\s|$)", re.IGNORECASE)
    encabezado = re.compile(r"^(?:(?:numeral|secci[oó]n|cap[ií]tulo)\s+)?(\d+(?:\.\d+)*)\.?\s+\S", re.IGNORECASE)
    for i, linea in enumerate(lineas):
        if inicio.match(linea):
            fin = len(lineas)
            for j in range(i + 1, len(lineas)):
                m = encabezado.match(lineas[j])
                if m and _numeral_valido(m.group(1)) and not m.group(1).startswith(numeral + "."):
                    fin = j
                    break
            return " ".join(" ".join(lineas[i:fin]).split())
    return None


def cambios_del_expediente(previos: Dict[str, str], actuales: Dict[str, str]) -> dict:
    return {
        "modificados": sorted(n for n in actuales if n in previos and actuales[n] != previos[n]),
        "nuevos": sorted(n for n in actuales if n not in previos),
        "retirados": sorted(n for n in previos if n not in actuales),
    }


def motivo_de_afectacion(requisito: dict, cambios: dict, previos: Dict[str, str],
                         actuales: Dict[str, str]) -> Optional[str]:
    """Por qué el cambio documental afecta al requisito; None si conserva la aprobación."""
    referencia = requisito.get("referencia_documental") or ""
    documento, numeral = documento_de(referencia), numeral_de(referencia)

    for nombre in cambios["nuevos"]:
        citados = numerales_citados(actuales[nombre])
        if numeral:
            relacionado = next((c for c in citados if _relacionados(numeral, c)), None)
            if relacionado:
                return f"«{nombre}» modifica el numeral {relacionado}."
        if not citados and _ES_ADENDA.search(f"{nombre} {actuales[nombre]}"):
            return f"«{nombre}» modifica el pliego sin citar numerales: confirme el requisito."

    if documento in cambios["retirados"]:
        return f"«{documento}» ya no está en el expediente."

    candidatos = [documento] if documento in previos or documento in actuales else cambios["modificados"]
    for nombre in candidatos:
        if nombre not in cambios["modificados"]:
            continue
        if not numeral:
            return f"«{nombre}» cambió y el requisito no cita un numeral."
        antes, despues = seccion(previos[nombre], numeral), seccion(actuales[nombre], numeral)
        if antes is None and despues is None and documento is None:
            continue  # El numeral no es de este documento.
        if antes != despues:
            return f"El numeral {numeral} de «{nombre}» cambió en la versión nueva."
    return None


def _similitud(a: dict, b: dict) -> float:
    if documento_de(a.get("referencia_documental")) and numeral_de(a.get("referencia_documental")) and (
            (documento_de(a["referencia_documental"]), numeral_de(a["referencia_documental"]))
            == (documento_de(b.get("referencia_documental")), numeral_de(b.get("referencia_documental")))):
        base = 0.3
    elif a.get("categoria") != b.get("categoria"):
        return 0.0
    else:
        base = 0.0
    texto = SequenceMatcher(None, " ".join(a.get("texto", "").lower().split()),
                            " ".join(b.get("texto", "").lower().split())).ratio()
    return min(1.0, base + texto)


def _siguiente_id(usados: set) -> str:
    numeros = [int(m.group(1)) for i in usados if (m := re.match(r"^REQ-(\d+)$", i))]
    n = max(numeros, default=0) + 1
    while f"REQ-{n:03d}" in usados:
        n += 1
    return f"REQ-{n:03d}"


def fusionar_con_revision_previa(previa: dict, extraidos: List[dict], contenido_actual: str) -> Tuple[List[dict], dict]:
    """
    Lista que verá el analista: los requisitos aprobados antes (con sus correcciones) que el
    cambio no toca, los afectados con el texto nuevo si se volvieron a extraer, y los que
    aparecen por primera vez en un documento nuevo o modificado. Devuelve (lista, revisión),
    donde revisión dice por cada identificador si conserva la aprobación o vuelve a revisión.
    """
    previos, actuales = previa.get("documentos") or {}, textos_por_documento(contenido_actual)
    cambios = cambios_del_expediente(previos, actuales)
    cambiados = set(cambios["modificados"]) | set(cambios["nuevos"])
    origen = f"Aprobado en la tarea {str(previa.get('tarea_id'))[:8]} por {previa.get('aprobado_por') or 'el analista'}."

    libres = list(extraidos)
    lista, revision = [], {}
    for aprobado in previa.get("requisitos_aprobados") or []:
        identificador = aprobado["identificador"]
        # El requisito extraído otra vez que corresponde a este aprobado no es nuevo.
        puntajes = [(_similitud(aprobado, e), i) for i, e in enumerate(libres)]
        mejor = max(puntajes, default=(0.0, None))
        pareja = libres.pop(mejor[1]) if mejor[0] >= _SIMILITUD_MINIMA else None
        motivo = motivo_de_afectacion(aprobado, cambios, previos, actuales)
        if motivo is None:
            lista.append(aprobado)
            revision[identificador] = {"estado": CONSERVADO, "motivo": origen}
            continue
        item = {**pareja, "identificador": identificador} if pareja else dict(aprobado)
        revision[identificador] = {"estado": AFECTADO, "motivo": motivo}
        if item.get("texto") != aprobado.get("texto"):
            revision[identificador]["texto_aprobado"] = aprobado.get("texto")
        lista.append(item)

    usados = {r["identificador"] for r in lista}
    for extraido in libres:
        documento = documento_de(extraido.get("referencia_documental"))
        # Un requisito nuevo solo puede venir de un documento que cambió; el resto es ruido de la extracción.
        if documento in cambiados or (documento is None and cambiados):
            identificador = _siguiente_id(usados)
            usados.add(identificador)
            lista.append({**extraido, "identificador": identificador})
            revision[identificador] = {"estado": NUEVO, "motivo": (
                f"Aparece en «{documento}», que cambió desde el análisis previo." if documento
                else "Aparece en el expediente modificado.")}
    return lista, {"cambios": cambios, "tarea_previa": previa.get("tarea_id"), "requisitos": revision}
