"""
Anonimización antes de invocar al modelo (ASR-05, DA-07).

Sustituye por marcadores ([CORREO_1], [TERMINO_2]…) los datos que no deben salir
hacia el proveedor: correos, teléfonos, NIT con dígito de verificación, URL y los
términos protegidos configurados en ANONIMIZACION_TERMINOS (nombre de la fábrica,
clientes, personas). La respuesta del modelo se restaura con el mismo mapa, de modo
que los dictámenes citan el texto real del portafolio.

Las cifras (años, valores en SMMLV, porcentajes) no se tocan: son las que permiten
contrastar el requisito con la evidencia. Lo estratégico que no tenga un patrón
reconocible debe declararse como término protegido.
"""
import re
from typing import Dict, Iterable, List, Tuple

from pydantic import BaseModel

_PATRONES: List[Tuple[str, re.Pattern]] = [
    ("CORREO", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("URL", re.compile(r"\bhttps?://[^\s<>\"]+", re.IGNORECASE)),
    # NIT con dígito de verificación: 900.123.456-7 o 900123456-7.
    ("NIT", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-\d\b")),
    # Celulares y fijos colombianos con o sin indicativo.
    ("TELEFONO", re.compile(r"(?<!\w)(?:\+?57[\s-]?)?(?:3\d{2}|60\d)[\s-]?\d{3}[\s-]?\d{4}(?!\d)")),
]

_MARCADOR = re.compile(r"\[(?:CORREO|URL|NIT|TELEFONO|TERMINO)_\d+\]")


class Anonimizador:

    def __init__(self, terminos_protegidos: Iterable[str] = ()):
        terminos = sorted({t.strip() for t in terminos_protegidos if t and t.strip()}, key=len, reverse=True)
        # Primero los más largos: "Grupo Andino S.A.S." antes que "Andino".
        self._terminos = [re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.IGNORECASE) for t in terminos]

    def anonimizar(self, texto: str) -> Tuple[str, Dict[str, str]]:
        """Devuelve el texto con marcadores y el mapa marcador → original."""
        mapa: Dict[str, str] = {}
        inverso: Dict[Tuple[str, str], str] = {}
        contadores: Dict[str, int] = {}

        def sustituir(tipo: str):
            def _hacer(m: re.Match) -> str:
                original = m.group(0)
                clave = (tipo, original.lower())
                if clave not in inverso:
                    contadores[tipo] = contadores.get(tipo, 0) + 1
                    marcador = f"[{tipo}_{contadores[tipo]}]"
                    inverso[clave] = marcador
                    mapa[marcador] = original
                return inverso[clave]
            return _hacer

        for patron in self._terminos:
            texto = patron.sub(sustituir("TERMINO"), texto)
        for tipo, patron in _PATRONES:
            texto = patron.sub(sustituir(tipo), texto)
        return texto, mapa

    @staticmethod
    def restaurar(texto: str, mapa: Dict[str, str]) -> str:
        if not mapa or not texto:
            return texto
        return _MARCADOR.sub(lambda m: mapa.get(m.group(0), m.group(0)), texto)

    @classmethod
    def restaurar_modelo(cls, modelo: BaseModel, mapa: Dict[str, str]) -> BaseModel:
        """Restaura los marcadores en todos los campos de texto de una salida estructurada."""
        if not mapa:
            return modelo

        def recorrer(valor):
            if isinstance(valor, str):
                return cls.restaurar(valor, mapa)
            if isinstance(valor, list):
                return [recorrer(v) for v in valor]
            if isinstance(valor, dict):
                return {k: recorrer(v) for k, v in valor.items()}
            return valor

        return type(modelo).model_validate(recorrer(modelo.model_dump(mode="json")))
