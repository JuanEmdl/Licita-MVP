"""
Afinidad entre un proceso de SECOP II y el portafolio de la fábrica.

Puntaje determinista 0-100 por coincidencia de términos (sin modelo), para que
la vigilancia funcione aunque no haya deployment de embeddings:
  - tecnologías y certificaciones del portafolio mencionadas en el objeto: 30 puntos cada una;
  - términos fuertes de servicios de software: 20 puntos cada uno;
  - términos de tecnología de apoyo: 8 puntos cada uno;
  - palabras significativas de las descripciones del portafolio: 4 puntos cada una (máx. 12).
Sin ninguna tecnología ni término de software el puntaje es 0: las palabras
sueltas del portafolio solo matizan, no crean alertas por sí solas.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, List, Set

PESO_TECNOLOGIA = 30
PESO_TERMINO_FUERTE = 20
PESO_TERMINO_APOYO = 8
PESO_PALABRA = 4
TOPE_PALABRAS = 12

TERMINOS_FUERTES = [
    "software", "desarrollo de software", "fabrica de software", "plataforma tecnologica",
    "sistema de informacion", "sistemas de informacion", "aplicacion web", "aplicacion movil",
    "aplicativo", "portal web", "pagina web", "sitio web", "interoperabilidad",
    "transformacion digital", "inteligencia artificial", "ciberseguridad", "mesa de ayuda",
]
TERMINOS_APOYO = [
    "plataforma", "nube", "cloud", "licencia", "licencias", "base de datos", "bases de datos",
    "seguridad de la informacion", "analitica", "automatizacion", "digitalizacion", "web",
    "soporte tecnico", "tecnologias de la informacion", "infraestructura tecnologica",
]
# Categorías del portafolio que no describen una tecnología (no se buscan como término).
CATEGORIAS_NO_TECNICAS = {"experiencia"}
TERMINOS_GENERALES = TERMINOS_FUERTES + TERMINOS_APOYO

_PALABRAS_VACIAS = {
    "para", "como", "entre", "sobre", "desde", "hasta", "donde", "cuando", "proyecto", "proyectos",
    "dato", "datos", "prueba", "ficticio", "ejemplo", "anos", "experiencia", "valor", "total",
    "contrato", "contratos", "ejecutados", "entidades", "publicas", "codigo", "vigente", "servicio",
    "servicios", "empresa", "certificacion", "desarrollo", "gestion", "sistema", "sistemas",
    "informacion", "seguridad", "aplicaciones", "certificado", "diciembre", "administrado",
}


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios simples."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9/+#.]+", " ", sin_tildes.lower()).split())


def _contiene(texto: str, termino: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(termino)}(?![a-z0-9])", texto) is not None


def terminos_tecnologia(tecnologia: str) -> List[str]:
    """
    'EJEMPLO - Python / FastAPI' -> ['python', 'fastapi'].
    Solo se separa por " / ", "," o " y ": 'ISO/IEC 27001' queda como un único término.
    """
    limpio = re.sub(r"^\s*ejemplo\s*-\s*", "", tecnologia or "", flags=re.IGNORECASE)
    partes = re.split(r"\s+/\s+|[,;|]|\s+y\s+", limpio)
    return [n for n in (normalizar(p) for p in partes) if len(n) >= 4]


@dataclass
class PerfilPortafolio:
    tecnologias: Set[str] = field(default_factory=set)
    palabras: Set[str] = field(default_factory=set)

    @classmethod
    def desde_capacidades(cls, capacidades: Iterable[dict]) -> "PerfilPortafolio":
        perfil = cls()
        for c in capacidades:
            if normalizar(c.get("categoria", "")) not in CATEGORIAS_NO_TECNICAS:
                perfil.tecnologias.update(terminos_tecnologia(c.get("tecnologia", "")))
            for palabra in normalizar(c.get("descripcion", "")).split():
                palabra = palabra.strip("./+#")
                if len(palabra) >= 6 and palabra not in _PALABRAS_VACIAS and not palabra.isdigit():
                    perfil.palabras.add(palabra)
        return perfil

    def terminos_busqueda(self) -> List[str]:
        """Términos del portafolio que se agregan al filtro de SECOP II."""
        return sorted(t for t in self.tecnologias if len(t) >= 4)


@dataclass
class ResultadoAfinidad:
    puntaje: float
    coincidencias: List[str]


def calcular_afinidad(texto_proceso: str, perfil: PerfilPortafolio) -> ResultadoAfinidad:
    texto = normalizar(texto_proceso)
    coincidencias: List[str] = []
    puntaje = 0.0

    def sumar(terminos: Iterable[str], peso: float) -> float:
        total = 0.0
        for termino in terminos:
            # Un término contenido en otro ya contado ("web" en "portal web") no suma dos veces.
            if any(termino in previo for previo in coincidencias):
                continue
            if _contiene(texto, termino):
                coincidencias.append(termino)
                total += peso
        return total

    puntaje += sumar(sorted(perfil.tecnologias, key=len, reverse=True), PESO_TECNOLOGIA)
    puntaje += sumar(sorted(TERMINOS_FUERTES, key=len, reverse=True), PESO_TERMINO_FUERTE)
    puntaje += sumar(sorted(TERMINOS_APOYO, key=len, reverse=True), PESO_TERMINO_APOYO)
    if puntaje == 0:
        return ResultadoAfinidad(puntaje=0.0, coincidencias=[])
    puntaje += min(sumar(sorted(perfil.palabras), PESO_PALABRA), TOPE_PALABRAS)

    return ResultadoAfinidad(puntaje=min(100.0, puntaje), coincidencias=coincidencias)
