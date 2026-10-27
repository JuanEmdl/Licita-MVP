"""Las fechas se guardan en UTC y se muestran en la hora local (UTC_OFFSET, Colombia -5)."""
from dataclasses import replace
from datetime import datetime, timezone

import src.shared.horas as horas
from src.shared.config import Configuracion


def test_un_instante_utc_se_muestra_en_hora_de_colombia(monkeypatch):
    monkeypatch.setattr(horas, "obtener_configuracion", lambda: replace(Configuracion(), utc_offset=-5))
    assert horas.texto_local("2026-10-25T14:23:10") == "2026-10-25 09:23"
    assert horas.texto_local("2026-10-25T14:23:10Z") == "2026-10-25 09:23"
    assert horas.texto_local("2026-10-25T03:00:00") == "2026-10-24 22:00"  # cambia el día
    assert horas.texto_local(datetime(2026, 10, 25, 14, 23, tzinfo=timezone.utc)) == "2026-10-25 09:23"
    assert horas.texto_local(None) == "" and horas.texto_local("no es fecha") == ""


def test_el_desfase_se_configura(monkeypatch):
    monkeypatch.setattr(horas, "obtener_configuracion", lambda: replace(Configuracion(), utc_offset=0))
    assert horas.texto_local("2026-10-25T14:23:10") == "2026-10-25 14:23"
