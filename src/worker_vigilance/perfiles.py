"""
Evaluador de perfiles de búsqueda (RF-015, RF-017).

Contrasta cada proceso sincronizado con los perfiles activos. Un proceso coincide con
un perfil cuando su nombre u objeto contiene alguna de las palabras clave y cumple
todos los demás criterios que el perfil defina (entidad, departamento, modalidad y
rango de cuantía). Un criterio vacío no restringe. Es determinista: no usa el modelo.
"""
from typing import Any, Dict, Iterable, List

from src.worker_vigilance.afinidad import _contiene, normalizar


def _alguno_contenido(valor: str, opciones: Iterable[str]) -> bool:
    texto = normalizar(valor)
    return any(normalizar(o) and normalizar(o) in texto for o in opciones)


def coincide(perfil: Dict[str, Any], proceso: Dict[str, Any]) -> bool:
    texto = normalizar(f"{proceso.get('nombre') or ''} {proceso.get('objeto') or ''}")
    palabras = [normalizar(p) for p in perfil.get("palabras_clave") or [] if normalizar(p)]
    if not palabras or not any(_contiene(texto, p) for p in palabras):
        return False
    if perfil.get("entidades") and not _alguno_contenido(proceso.get("entidad") or "", perfil["entidades"]):
        return False
    if perfil.get("departamentos") and normalizar(proceso.get("departamento") or "") not in {
            normalizar(d) for d in perfil["departamentos"]}:
        return False
    if perfil.get("modalidades") and not _alguno_contenido(proceso.get("modalidad") or "", perfil["modalidades"]):
        return False
    cuantia = proceso.get("precio_base")
    if perfil.get("cuantia_min") is not None and (cuantia is None or cuantia < perfil["cuantia_min"]):
        return False
    if perfil.get("cuantia_max") is not None and (cuantia is None or cuantia > perfil["cuantia_max"]):
        return False
    return True


def terminos_de_perfiles(perfiles: Iterable[Dict[str, Any]]) -> List[str]:
    """
    Palabras clave de los perfiles activos para el filtro grueso en SECOP II, con y sin
    tildes: el filtro del servidor compara texto literal y las entidades escriben de ambas formas.
    """
    terminos = set()
    for perfil in perfiles:
        for palabra in perfil.get("palabras_clave") or []:
            if palabra.strip():
                terminos.update({palabra.strip(), normalizar(palabra)})
    return sorted(terminos)
