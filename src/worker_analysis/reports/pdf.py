"""
Escritor mínimo de PDF para el informe de viabilidad (RF-037).

Genera PDF 1.4 con las fuentes estándar Helvetica y Helvetica-Bold (no se incrustan:
todo lector de PDF las trae) y codificación WinAnsi, que cubre el español. Solo
texto: títulos, secciones, párrafos con ajuste de línea y pie de página. Se evita
así agregar una dependencia para una salida que no necesita gráficos.

La salida es determinista: los mismos datos producen los mismos bytes, de modo que
la huella SHA-256 identifica el contenido.
"""
from typing import List, Optional, Tuple

ANCHO, ALTO = 595.28, 841.89  # A4 en puntos
MARGEN_X, MARGEN_SUP, MARGEN_INF = 56.0, 64.0, 60.0

# Anchos de Helvetica en milésimas de em (AFM estándar) para ASCII imprimible.
_ANCHOS = dict(zip(
    " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~",
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
     556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015,
     667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611,
     722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333,
     556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278,
     556, 500, 722, 500, 500, 500, 334, 260, 334, 584],
))
_BASE = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
# Caracteres fuera de WinAnsi que aparecen en los dictámenes.
_SUSTITUTOS = {"≥": ">=", "≤": "<=", "→": "->", "←": "<-", "≈": "~", "✓": "si", "✗": "no", "\t": "    "}


def _texto_pdf(texto: str) -> bytes:
    for original, sustituto in _SUSTITUTOS.items():
        texto = texto.replace(original, sustituto)
    crudo = texto.encode("cp1252", errors="replace")
    return crudo.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def ancho_texto(texto: str, tamano: float, negrita: bool = False) -> float:
    total = sum(_ANCHOS.get(c.translate(_BASE), 556) for c in texto)
    return total * tamano / 1000 * (1.07 if negrita else 1.0)


def ajustar(texto: str, ancho_maximo: float, tamano: float, negrita: bool = False) -> List[str]:
    """Parte el texto en líneas que caben en el ancho, sin cortar palabras salvo que no quepan solas."""
    lineas: List[str] = []
    for parrafo in (texto or "").split("\n"):
        actual = ""
        for palabra in parrafo.split(" "):
            candidata = f"{actual} {palabra}" if actual else palabra
            if ancho_texto(candidata, tamano, negrita) <= ancho_maximo:
                actual = candidata
                continue
            if actual:
                lineas.append(actual)
            # Palabra más larga que la línea (p. ej. una huella): se corta por caracteres.
            while ancho_texto(palabra, tamano, negrita) > ancho_maximo:
                corte = len(palabra)
                while corte > 1 and ancho_texto(palabra[:corte], tamano, negrita) > ancho_maximo:
                    corte -= 1
                lineas.append(palabra[:corte])
                palabra = palabra[corte:]
            actual = palabra
        lineas.append(actual)
    return lineas


class DocumentoPDF:

    def __init__(self, titulo: str, pie: str = ""):
        self.titulo_documento = titulo
        self.pie = pie
        self._paginas: List[List[bytes]] = []
        self._y = 0.0
        self._nueva_pagina()

    # --- Composición ---

    def _nueva_pagina(self) -> None:
        self._paginas.append([])
        self._y = ALTO - MARGEN_SUP

    def _linea(self, texto: str, tamano: float, negrita: bool, x: float, gris: float = 0.0) -> None:
        interlineado = tamano * 1.35
        if self._y - interlineado < MARGEN_INF:
            self._nueva_pagina()
        self._y -= interlineado
        fuente = "F2" if negrita else "F1"
        self._paginas[-1].append(
            b"BT %.2f g /%s %.2f Tf %.2f %.2f Td (" % (gris, fuente.encode(), tamano, x, self._y)
            + _texto_pdf(texto) + b") Tj ET")

    def parrafo(self, texto: str, tamano: float = 9.5, negrita: bool = False, sangria: float = 0.0,
                gris: float = 0.0) -> None:
        x = MARGEN_X + sangria
        for linea in ajustar(texto, ANCHO - MARGEN_X - x, tamano, negrita):
            self._linea(linea, tamano, negrita, x, gris)

    def espacio(self, puntos: float = 6.0) -> None:
        self._y -= puntos

    def titulo(self, texto: str) -> None:
        self.parrafo(texto, tamano=16, negrita=True)
        self.espacio(4)

    def seccion(self, texto: str) -> None:
        # Una sección no empieza en la última línea de una página.
        if self._y - 60 < MARGEN_INF:
            self._nueva_pagina()
        self.espacio(8)
        self.parrafo(texto, tamano=11.5, negrita=True)
        self._paginas[-1].append(b"0.75 G 0.6 w %.2f %.2f m %.2f %.2f l S" % (
            MARGEN_X, self._y - 3, ANCHO - MARGEN_X, self._y - 3))
        self.espacio(6)

    def dato(self, clave: str, valor: str) -> None:
        self.parrafo(f"{clave}: {valor}")

    # --- Serialización ---

    def bytes(self) -> bytes:
        total = len(self._paginas)
        objetos: List[bytes] = []

        def agregar(contenido: bytes) -> int:
            objetos.append(contenido)
            return len(objetos)

        catalogo = agregar(b"")  # se completa al final
        paginas = agregar(b"")
        f1 = agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        hijos: List[int] = []
        for numero, operaciones in enumerate(self._paginas, start=1):
            pie = f"{self.pie}  ·  Página {numero} de {total}" if self.pie else f"Página {numero} de {total}"
            flujo = b"\n".join(operaciones + [
                b"BT 0.45 g /F1 7.5 Tf %.2f %.2f Td (" % (MARGEN_X, 32.0) + _texto_pdf(pie) + b") Tj ET"])
            contenido = agregar(b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"\nendstream")
            hijos.append(agregar(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>"
                % (paginas, ANCHO, ALTO, contenido, f1, f2)))
        objetos[paginas - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % h for h in hijos), total)
        objetos[catalogo - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % paginas
        info = agregar(b"<< /Title (" + _texto_pdf(self.titulo_documento) + b") /Producer (Licita) >>")

        salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        posiciones: List[int] = []
        for numero, contenido in enumerate(objetos, start=1):
            posiciones.append(len(salida))
            salida += b"%d 0 obj\n" % numero + contenido + b"\nendobj\n"
        inicio_xref = len(salida)
        salida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
        for posicion in posiciones:
            salida += b"%010d 00000 n \n" % posicion
        salida += (b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                   % (len(objetos) + 1, catalogo, info, inicio_xref))
        return bytes(salida)


def extraer_texto(pdf: bytes) -> str:
    """Texto de un PDF producido por DocumentoPDF (para pruebas y la vista previa)."""
    import re
    partes: List[Tuple[int, str]] = []
    for m in re.finditer(rb"\((.*?)(?<!\\)\) Tj", pdf, re.S):
        crudo = m.group(1).replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
        partes.append((m.start(), crudo.decode("cp1252", errors="replace")))
    return "\n".join(t for _, t in partes)
