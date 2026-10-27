"""
Lectura del texto de los documentos del expediente (RF-021, RF-022, RF-023).

Devuelve el texto por página para que cada fragmento conserve la página de
procedencia. PDF con pypdf; DOCX y XLSX con la biblioteca estándar (son ZIP con
XML); TXT, MD y CSV tal cual. Las filas de las tablas se escriben con " | " entre
celdas, para que el segmentador las reconozca y no las parta.

Un documento del que no se obtiene texto (escaneado, protegido, dañado o en un
formato no admitido) se marca como ilegible con el motivo, en lugar de analizarse
vacío: el expediente lo muestra así y el informe lo declara (HU-02 CA-03).
"""
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

FORMATOS_ADMITIDOS = ("pdf", "docx", "xlsx", "txt", "md", "csv")
# Menos texto que esto en todo el documento se considera ilegible (p. ej. un PDF escaneado).
MIN_CARACTERES = 80

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


@dataclass
class LecturaDocumento:
    paginas: List[str] = field(default_factory=list)
    ilegible: bool = False
    motivo: Optional[str] = None

    @property
    def caracteres(self) -> int:
        return sum(len(p) for p in self.paginas)


def extension_de(nombre: str) -> str:
    return nombre.rsplit(".", 1)[-1].lower().strip() if "." in (nombre or "") else ""


def _limpiar(texto: str) -> str:
    # PostgreSQL no admite el carácter nulo en texto ni en JSON.
    texto = (texto or "").replace("\x00", "")
    return "\n".join(linea.rstrip() for linea in texto.splitlines()).strip()


def _leer_pdf(contenido: bytes) -> List[str]:
    from pypdf import PdfReader

    lector = PdfReader(io.BytesIO(contenido))
    if lector.is_encrypted and not lector.decrypt(""):
        raise DocumentoNoAdmitidoError("el PDF está protegido con contraseña")
    return [pagina.extract_text() or "" for pagina in lector.pages]


# Un DOCX o XLSX descomprimido no debería pasar de esto; más indica una bomba de compresión.
MAX_XML_DESCOMPRIMIDO = 200 * 1024 * 1024
_DECLARACION_DTD = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


class DocumentoNoAdmitidoError(ValueError):
    """El documento se rechaza por una razón que se le puede explicar a quien lo cargó."""


def _xml(z: zipfile.ZipFile, nombre: str) -> ElementTree.Element:
    """
    XML de un documento cargado por un usuario (contenido no confiable). Office Open XML no
    usa DTD: un DOCTYPE o una entidad declarada solo sirven para ataques de expansión
    («billion laughs») o entidades externas, así que se rechazan antes de analizar.
    """
    if z.getinfo(nombre).file_size > MAX_XML_DESCOMPRIMIDO:
        raise DocumentoNoAdmitidoError("el documento descomprimido es demasiado grande")
    datos = z.read(nombre)
    if _DECLARACION_DTD.search(datos):
        raise DocumentoNoAdmitidoError("el documento declara una DTD o entidades XML, que no se admiten")
    # Sin DTD no hay expansión de entidades ni entidades externas: el aviso B314 no aplica.
    return ElementTree.fromstring(datos)  # nosec B314


def _texto_xml(nodo, etiqueta: str) -> str:
    return "".join(t.text or "" for t in nodo.iter(etiqueta))


def _leer_docx(contenido: bytes) -> List[str]:
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        cuerpo = _xml(z, "word/document.xml").find(f"{_W}body")
    paginas, actual = [], []
    for nodo in list(cuerpo) if cuerpo is not None else []:
        if nodo.tag == f"{_W}tbl":
            for fila in nodo.iter(f"{_W}tr"):
                celdas = [" ".join(_texto_xml(c, f"{_W}t").split()) for c in fila.iter(f"{_W}tc")]
                if any(celdas):
                    actual.append(" | ".join(celdas))
            continue
        if nodo.tag != f"{_W}p":
            continue
        # Word marca los saltos de página manuales y los que calculó al guardar.
        salto = any(b.get(f"{_W}type") == "page" for b in nodo.iter(f"{_W}br")) \
            or any(True for _ in nodo.iter(f"{_W}lastRenderedPageBreak"))
        if salto and actual:
            paginas.append("\n".join(actual))
            actual = []
        texto = _texto_xml(nodo, f"{_W}t")
        if texto.strip():
            actual.append(texto)
    paginas.append("\n".join(actual))
    return paginas


def _leer_xlsx(contenido: bytes) -> List[str]:
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        compartidas = []
        if "xl/sharedStrings.xml" in z.namelist():
            raiz = _xml(z, "xl/sharedStrings.xml")
            compartidas = [_texto_xml(si, f"{_S}t") for si in raiz.iter(f"{_S}si")]
        libro = _xml(z, "xl/workbook.xml")
        relaciones = _xml(z, "xl/_rels/workbook.xml.rels")
        destinos = {r.get("Id"): r.get("Target") for r in relaciones}
        paginas = []
        for hoja in libro.iter(f"{_S}sheet"):
            destino = destinos.get(hoja.get(f"{_R}id"), "")
            ruta = destino.lstrip("/") if destino.startswith("/") else f"xl/{destino}"
            if ruta not in z.namelist():
                continue
            filas = [f"Hoja: {hoja.get('name')}"]
            for fila in _xml(z, ruta).iter(f"{_S}row"):
                valores = []
                for celda in fila.iter(f"{_S}c"):
                    v = celda.find(f"{_S}v")
                    if celda.get("t") == "s" and v is not None and v.text and v.text.isdigit():
                        valores.append(compartidas[int(v.text)] if int(v.text) < len(compartidas) else "")
                    elif celda.get("t") == "inlineStr":
                        valores.append(_texto_xml(celda, f"{_S}t"))
                    else:
                        valores.append(v.text if v is not None and v.text else "")
                if any(x.strip() for x in valores):
                    filas.append(" | ".join(" ".join(x.split()) for x in valores))
            paginas.append("\n".join(filas))
        return paginas


def _leer_texto(contenido: bytes) -> List[str]:
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")
    # El salto de página (form feed) separa páginas en un texto exportado.
    return texto.split("\f")


def leer_documento(nombre: str, contenido: bytes) -> LecturaDocumento:
    extension = extension_de(nombre)
    if extension not in FORMATOS_ADMITIDOS:
        return LecturaDocumento(ilegible=True, motivo=(
            f"Formato .{extension or '?'} no admitido para el análisis; cargue el documento en PDF, DOCX, "
            "XLSX o TXT."))
    lectores = {"pdf": _leer_pdf, "docx": _leer_docx, "xlsx": _leer_xlsx}
    try:
        paginas = lectores.get(extension, _leer_texto)(contenido)
    except DocumentoNoAdmitidoError as e:
        return LecturaDocumento(ilegible=True, motivo=f"El archivo no se puede analizar: {e}.")
    except Exception as e:
        logger.info(f"No se pudo leer '{nombre}': {type(e).__name__}: {e}")
        return LecturaDocumento(ilegible=True, motivo=f"El archivo está dañado o protegido ({type(e).__name__}).")
    lectura = LecturaDocumento(paginas=[_limpiar(p) for p in paginas])
    if lectura.caracteres < MIN_CARACTERES:
        lectura.ilegible = True
        lectura.motivo = ("No se pudo extraer texto del documento (posiblemente escaneado como imagen). "
                          "Cargue una versión con texto seleccionable.")
    return lectura


def resumen_paginas(paginas: List[str]) -> str:
    """'12 páginas, 3 sin texto' para mostrar en el expediente."""
    vacias = sum(1 for p in paginas if not re.sub(r"\s+", "", p))
    total = len(paginas)
    texto = f"{total} página{'s' if total != 1 else ''}"
    return texto + (f", {vacias} sin texto" if vacias else "")
