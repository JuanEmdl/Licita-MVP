import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# Marcas con las que el orquestador arma el contenido del expediente (ver graph.py).
MARCA_DOCUMENTO = re.compile(r"^=== DOCUMENTO: (?P<nombre>.*?) \| versión: (?P<version>.*?) \| "
                             r"procedencia: (?P<procedencia>.*?) ===$", re.MULTILINE)
MARCA_PAGINA = re.compile(r"^\[Página (\d+)\]$", re.MULTILINE)

# Un título de sección: numeral o palabra de capítulo al inicio, corto y sin cerrar en punto.
_TITULO_NUMERADO = re.compile(
    r"^\s*((cap[ií]tulo|secci[oó]n|t[ií]tulo|anexo|numeral)\s+[\w.]+|\d{1,2}(\.\d{1,2}){0,4}\.?)\s+\S", re.IGNORECASE)
# Una fila de tabla: celdas separadas por " | ", por tabuladores o por columnas de espacios.
_FILA_TABLA = re.compile(r"\s\|\s|\t|\S\s{3,}\S.*\S\s{3,}\S")


def escapar_marcas(texto: str) -> str:
    """Un documento no puede imitar las marcas de documento o página del expediente."""
    texto = re.sub(r"^=== DOCUMENTO:", "== DOCUMENTO:", texto or "", flags=re.MULTILINE)
    return re.sub(r"^\[Página (\d+)\]$", r"(Página \1)", texto, flags=re.MULTILINE)


def marca_documento(nombre: str, version: Any, procedencia: str) -> str:
    limpio = lambda v: " ".join(str(v).replace("|", "/").replace("===", "").split())  # noqa: E731
    return f"=== DOCUMENTO: {limpio(nombre)} | versión: {limpio(version)} | procedencia: {limpio(procedencia)} ==="


def es_titulo(linea: str) -> bool:
    linea = linea.strip()
    if not linea or len(linea) > 110 or _FILA_TABLA.search(linea):
        return False
    letras = [c for c in linea if c.isalpha()]
    mayusculas = bool(letras) and sum(c.isupper() for c in letras) / len(letras) > 0.7
    if _TITULO_NUMERADO.match(linea):
        return mayusculas or not linea.endswith((".", ";", ","))
    # "ENTIDAD: Alcaldía…" es un rótulo con su valor (ficha de metadatos), no un título.
    if re.match(r"^[^:]{2,60}:(\s|$)", linea):
        return False
    return mayusculas and len(letras) >= 6 and len(linea.split()) >= 2 and not linea.endswith((".", ","))


@dataclass
class Bloque:
    tipo: str  # titulo, parrafo, tabla
    lineas: List[str]
    paginas: List[int]
    seccion: Optional[str]

    @property
    def texto(self) -> str:
        return "\n".join(self.lineas)


@dataclass
class Fragmento:
    texto: str
    documento: str
    version: str
    procedencia: str
    paginas: List[int] = field(default_factory=list)
    secciones: List[str] = field(default_factory=list)

    def a_dict(self) -> Dict[str, Any]:
        return {"documento": self.documento, "version": self.version, "procedencia": self.procedencia,
                "paginas": self.paginas, "secciones": self.secciones}


class SegmentadorDocumental:
    """
    Segmentador Documental (RF-023).
    Divide el contenido de los pliegos y anexos en fragmentos más pequeños para el
    Agente Extractor (ASR-01) conservando la trazabilidad: documento de origen, versión,
    procedencia, página o páginas y sección de cada fragmento.

    - Las cláusulas no se parten: un fragmento se cierra entre bloques (título, párrafo o
      tabla), no a mitad de uno, salvo que el bloque solo supere el tamaño máximo.
    - Una tabla que continúa en la página siguiente se mantiene como un solo bloque,
      asociado al título de la sección que la introduce (HU-05 CA-02). Si es más grande
      que un fragmento, se reparte por filas repitiendo la fila de encabezado.
    - Un fragmento sin ninguna referencia de origen se descarta y queda en la traza
      (HU-05 CA-04).
    """

    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 500):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # Respaldo para un párrafo que no cabe en un fragmento.
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ".", " ", ""]
        )
        self.descartados: List[Dict[str, Any]] = []

    # --- Lectura de la estructura ---

    @staticmethod
    def _documentos(contenido: str, metadatos_origen: Dict[str, Any]) -> List[Tuple[Dict[str, str], str]]:
        marcas = list(MARCA_DOCUMENTO.finditer(contenido))
        if not marcas:
            return [({"documento": metadatos_origen.get("documento", "Documento Desconocido"),
                      "version": str(metadatos_origen.get("version", "1.0")),
                      "procedencia": metadatos_origen.get("procedencia", "")}, contenido)]
        documentos = []
        previo = contenido[:marcas[0].start()].strip()
        if previo:
            documentos.append(({"documento": metadatos_origen.get("documento", "Documento Desconocido"),
                                "version": str(metadatos_origen.get("version", "1.0")),
                                "procedencia": metadatos_origen.get("procedencia", "")}, previo))
        for i, m in enumerate(marcas):
            fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(contenido)
            documentos.append(({"documento": m["nombre"], "version": m["version"], "procedencia": m["procedencia"]},
                               contenido[m.end():fin]))
        return documentos

    @staticmethod
    def _bloques(texto: str) -> List[Bloque]:
        bloques: List[Bloque] = []
        seccion: Optional[str] = None
        pagina: Optional[int] = None
        actual: Optional[Bloque] = None

        def cerrar():
            nonlocal actual
            if actual is not None and actual.lineas:
                bloques.append(actual)
            actual = None

        for linea in texto.splitlines():
            marca = MARCA_PAGINA.match(linea.strip())
            if marca:
                pagina = int(marca.group(1))
                # Una tabla sigue abierta al cambiar de página; un párrafo se cierra.
                if actual is not None and actual.tipo != "tabla":
                    cerrar()
                continue
            if not linea.strip():
                if actual is not None and actual.tipo != "tabla":
                    cerrar()
                continue
            paginas = [pagina] if pagina is not None else []
            if _FILA_TABLA.search(linea):
                if actual is None or actual.tipo != "tabla":
                    cerrar()
                    actual = Bloque("tabla", [], [], seccion)
                elif paginas and actual.paginas and paginas[0] not in actual.paginas:
                    # La tabla sigue en otra página: se marca sin partirla.
                    actual.lineas.append(f"[Página {paginas[0]}]")
                actual.lineas.append(linea.rstrip())
                actual.paginas += [p for p in paginas if p not in actual.paginas]
                continue
            if es_titulo(linea):
                cerrar()
                seccion = " ".join(linea.split())
                bloques.append(Bloque("titulo", [linea.strip()], paginas, seccion))
                continue
            if actual is None or actual.tipo != "parrafo":
                cerrar()
                actual = Bloque("parrafo", [], [], seccion)
            actual.lineas.append(linea.rstrip())
            actual.paginas += [p for p in paginas if p not in actual.paginas]
        cerrar()
        return bloques

    def _partir(self, bloque: Bloque) -> List[Bloque]:
        """Un bloque más grande que un fragmento: la tabla por filas, el párrafo con el respaldo."""
        if len(bloque.texto) <= self.chunk_size:
            return [bloque]
        if bloque.tipo == "tabla":
            encabezado, filas = bloque.lineas[0], bloque.lineas[1:]
            partes, actual = [], [encabezado]
            for fila in filas:
                if len("\n".join(actual + [fila])) > self.chunk_size and len(actual) > 1:
                    partes.append(actual)
                    actual = [encabezado, "(continúa la tabla)"]
                actual.append(fila)
            partes.append(actual)
            return [Bloque("tabla", p, bloque.paginas, bloque.seccion) for p in partes]
        return [Bloque("parrafo", [t], bloque.paginas, bloque.seccion)
                for t in self.text_splitter.split_text(bloque.texto)]

    # --- Fragmentos ---

    def _agrupar(self, bloques: List[Bloque]) -> List[List[Bloque]]:
        grupos: List[List[Bloque]] = []
        actual: List[Bloque] = []
        tamano = 0
        for bloque in (b for original in bloques for b in self._partir(original)):
            largo = len(bloque.texto) + 1
            if actual and tamano + largo > self.chunk_size:
                grupos.append(actual)
                # Solape: el último párrafo corto se repite para no perder el contexto.
                ultimo = actual[-1]
                actual = [ultimo] if ultimo.tipo == "parrafo" and len(ultimo.texto) <= self.chunk_overlap else []
                # El título vigente acompaña al fragmento siguiente.
                titulo = next((b for b in reversed(grupos[-1]) if b.tipo == "titulo"), None)
                if titulo is not None and titulo.seccion == bloque.seccion and titulo not in actual:
                    actual.insert(0, titulo)
                tamano = sum(len(b.texto) + 1 for b in actual)
            actual.append(bloque)
            tamano += largo
        if actual:
            grupos.append(actual)
        return grupos

    @staticmethod
    def _cuerpo(grupo: List[Bloque]) -> Tuple[str, List[int], List[str]]:
        lineas, paginas, secciones = [], [], []
        pagina_previa = None
        for bloque in grupo:
            for p in bloque.paginas:
                if p not in paginas:
                    paginas.append(p)
            if bloque.paginas and bloque.paginas[0] != pagina_previa:
                lineas.append(f"[Página {bloque.paginas[0]}]")
            if bloque.seccion and bloque.seccion not in secciones:
                secciones.append(bloque.seccion)
            if bloque.tipo == "tabla" and bloque.seccion:
                lineas.append(f"(Tabla de la sección {bloque.seccion})\n{bloque.texto}")
            else:
                lineas.append(bloque.texto)
            pagina_previa = bloque.paginas[-1] if bloque.paginas else pagina_previa
        return "\n\n".join(lineas), paginas, secciones

    def segmentar_con_metadatos(self, contenido: str, metadatos_origen: Dict[str, Any]) -> List[Fragmento]:
        self.descartados = []
        fragmentos: List[Fragmento] = []
        for meta, texto in self._documentos(contenido, metadatos_origen):
            for grupo in self._agrupar(self._bloques(texto)):
                cuerpo, paginas, secciones = self._cuerpo(grupo)
                if not cuerpo.strip():
                    continue
                if not meta["documento"].strip() and not paginas and not secciones:
                    # HU-05 CA-04: sin documento, sección ni página no hay cómo citar el origen.
                    self.descartados.append({"motivo": "Fragmento sin referencia de documento, sección ni página",
                                             "caracteres": len(cuerpo)})
                    continue
                fragmentos.append(Fragmento(cuerpo, meta["documento"], meta["version"], meta["procedencia"],
                                            paginas, secciones))
        total = len(fragmentos)
        for i, f in enumerate(fragmentos, start=1):
            header = f"--- INICIO FRAGMENTO {i} ---\n"
            header += f"Documento Origen: {f.documento}\n"
            header += f"Versión: {f.version}\n"
            if f.procedencia:
                header += f"Procedencia: {f.procedencia}\n"
            if f.paginas:
                header += f"Páginas: {f.paginas[0]}" + (f"-{f.paginas[-1]}" if len(f.paginas) > 1 else "") + "\n"
            if f.secciones:
                header += f"Sección: {f.secciones[0]}" + (f" (hasta {f.secciones[-1]})" if len(f.secciones) > 1 else "") + "\n"
            header += f"Referencia de Fragmento: {i} de {total}\n"
            header += "-" * 30 + "\n\n"
            f.texto = header + f.texto
        if self.descartados:
            logger.warning(f"Se descartaron {len(self.descartados)} fragmentos sin referencia de origen.")
        return fragmentos

    def segmentar(self, contenido: str, metadatos_origen: Dict[str, Any]) -> List[str]:
        """
        Segmenta el contenido saneado y le adjunta la trazabilidad documental.

        :param contenido: El texto del expediente ya validado por el Guardia Documental.
        :param metadatos_origen: Documento y versión por defecto si el contenido no trae marcas.
        :return: Una lista de fragmentos en string con el contexto pre-anexado.
        """
        nombre_doc = metadatos_origen.get('documento', 'Documento Desconocido')
        logger.info(f"Segmentando documento '{nombre_doc}'.")
        fragmentos = [f.texto for f in self.segmentar_con_metadatos(contenido, metadatos_origen)]
        logger.info(f"Segmentación finalizada: {len(fragmentos)} fragmentos generados para '{nombre_doc}'.")
        return fragmentos


def paginas_del_fragmento(texto: str) -> List[Tuple[Optional[int], str]]:
    """[(página, texto)] según las marcas [Página N] del cuerpo de un fragmento."""
    cuerpo = texto.split("-" * 30 + "\n\n", 1)[-1]
    partes: List[Tuple[Optional[int], str]] = []
    pagina, inicio = None, 0
    for m in MARCA_PAGINA.finditer(cuerpo):
        if cuerpo[inicio:m.start()].strip():
            partes.append((pagina, cuerpo[inicio:m.start()]))
        pagina, inicio = int(m.group(1)), m.end()
    partes.append((pagina, cuerpo[inicio:]))
    return partes
