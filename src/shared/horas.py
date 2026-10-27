"""
Horas para mostrar a las personas.

La base y la API guardan las fechas en UTC (sin zona), que es lo correcto para ordenar y
comparar entre contenedores. Al mostrarlas se convierten a la hora local de la fábrica con
UTC_OFFSET (Colombia: -5, sin horario de verano). Los informes sellados siguen declarando UTC.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from src.shared.config import obtener_configuracion


def a_local(valor: Union[str, datetime, None]) -> Optional[datetime]:
    """Fecha y hora local (sin zona) de un instante guardado en UTC; None si no se puede leer."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    if valor.tzinfo is not None:
        valor = valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor + timedelta(hours=obtener_configuracion().utc_offset)


def texto_local(valor: Union[str, datetime, None], formato: str = "%Y-%m-%d %H:%M") -> str:
    local = a_local(valor)
    return local.strftime(formato) if local else ""
