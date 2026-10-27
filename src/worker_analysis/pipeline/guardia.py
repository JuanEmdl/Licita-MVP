import re
import logging
import unicodedata

logger = logging.getLogger(__name__)

# Caracteres de ancho cero y guion suave: parten una frase sin que se note al leerla.
_INVISIBLES = re.compile("[­​-‏⁠-⁤﻿]")
# Letras cirílicas y griegas que se ven iguales a las latinas ("Ignоra" con una o cirílica).
_HOMOGLIFOS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
    "Т": "T", "Х": "X", "α": "a", "ο": "o", "ν": "v", "Α": "A", "Β": "B", "Ε": "E", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Χ": "X",
})


def texto_para_deteccion(contenido: str) -> str:
    """Forma canónica para buscar patrones: ancho completo a normal, sin invisibles ni homoglifos."""
    return _INVISIBLES.sub("", unicodedata.normalize("NFKC", contenido)).translate(_HOMOGLIFOS)

class SuspectedInjectionError(Exception):
    """Excepción lanzada cuando se detecta un posible ataque de inyección de prompt."""
    pass

class GuardiaDocumental:
    """
    Guardia Documental (ASR-10, RF-024).
    Trata el contenido de los pliegos como datos no confiables y neutraliza
    los intentos de manipulación de los agentes antes de enviarlo al modelo.
    """

    # Patrones comunes de inyección de prompts, jailbreaks y manipulación de rol.
    # Se exigen límites de palabra y un contexto dirigido al modelo: frases como
    # "actúa como supervisor" o "bypass vehicular" son normales en un pliego y no
    # deben suspender el análisis.
    PATRONES_INYECCION = [
        r"\bignora\s+(todas\s+)?(las\s+|tus\s+)?instrucciones\b",
        r"\bignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions\b",
        r"\bdisregard\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions\b",
        r"\bhaz\s+caso\s+omiso\s+de\s+(las\s+|tus\s+)?instrucciones\b",
        r"\bdesatiende\s+(las\s+|tus\s+)?instrucciones\b",
        r"\bignorez\s+(toutes\s+)?(les\s+)?instructions\b",
        r"\bignore\s+(todas\s+)?(as\s+)?instru[cç][õo]es\b",
        r"\bahora\s+eres\s+(un|una|el|la)\s+(asistente|modelo|agente|ia)\b",
        r"\byou\s+are\s+now\s+(the|an?)\b",
        r"\bmodo\s+desarrollador\b",
        r"\bdeveloper\s+mode\b",
        # Intentos de cerrar el bloque de datos o de abrir un turno del sistema (ASR-10, prompts.py).
        r"</?\s*(fragmento|evidencias|requisito|sistema|system)\s*>",
        r"<\|im_(start|end)\|>",
        r"\[\s*(system|sistema)\s*\]",
        r"\bactúa\s+como\s+(si\s+fueras|un\s+(modelo|asistente|agente)|una\s+ia)\b",
        r"\bact\s+as\s+(if\s+you|an?\s+(ai|assistant|language\s+model))\b",
        r"\bolvida\s+(todo\s+)?lo\s+anterior\b",
        r"\btu\s+nuevo\s+rol\s+es\b",
        r"\btu\s+nueva\s+tarea\s+es\b",
        r"\bsimula\s+ser\b",
        r"\bsystem\s+prompt\b",
        r"\binstrucciones\s+del\s+sistema\b",
        r"\beval[uú]a\s+con\s+(el\s+)?puntaje\s+m[aá]ximo\b",
        r"\bdictamina\s+que\s+cumple\b",
        # Un pliego asigna puntaje «al proponente que acredite…», nunca a un oferente concreto (DEF-01,
        # hallado por la suite adversaria: la nota al pie llegó a la lista de requisitos).
        r"\b(asign|otorg)\w*\s+(el\s+)?(m[aá]ximo\s+puntaje|puntaje\s+m[aá]ximo|\d+\s+puntos)\s+a\s+"
        r"(este|esta)\s+(oferente|oferta|proponente|propuesta)\b",
        r"\bbypass(ea[rs]?)?\s+(la\s+|the\s+)?(seguridad|security|guardia|filtros?|restricciones)\b",
        r"\bdeshabilita\s+(la\s+)?seguridad\b",
    ]

    def __init__(self):
        self.patrones = [re.compile(patron, re.IGNORECASE) for patron in self.PATRONES_INYECCION]

    def sanear_contenido(self, contenido: str) -> str:
        """
        Analiza el contenido extraído del pliego. 
        Si detecta un patrón de inyección, suspende la ejecución levantando una excepción.
        Si no hay patrones maliciosos, devuelve el contenido con una sanitización básica.
        """
        logger.info(f"Saneando contenido documental de {len(contenido)} caracteres.")

        canonico = texto_para_deteccion(contenido)
        for patron in self.patrones:
            match = patron.search(canonico)
            if match:
                logger.warning(f"¡Alerta de seguridad! Patrón de inyección detectado: '{match.group(0)}'")
                raise SuspectedInjectionError(f"Se detectó un patrón malicioso en el documento: '{match.group(0)}'")

        # Sanitización básica: remover caracteres de control anómalos pero mantener saltos y tabulaciones
        contenido_saneado = "".join(ch for ch in contenido if ch.isprintable() or ch in ('\n', '\r', '\t'))
        
        return contenido_saneado
