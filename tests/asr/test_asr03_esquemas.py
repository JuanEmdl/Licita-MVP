"""
ASR-03: la capa anticorrupción interpreta al menos el 98 % de 500 procesos históricos de SECOP II.

La muestra (tests/fixtures/secop_procesos_500.json.gz, scripts/descargar_muestra_secop.py) trae
procesos de 2019 a 2026 tal como los publica Datos Abiertos, con los cambios de esquema de cada
época (de 51 a 57 campos). Un proceso se interpreta con éxito cuando, sin error:
  - la vigilancia lo normaliza con identificador, entidad, modalidad y objeto, y no pierde ningún
    dato publicado (precio, fechas y enlace llegan convertidos al modelo interno);
  - el adaptador del análisis arma la ficha con una línea por cada campo publicado.
"""
import gzip
import json
from pathlib import Path

import pytest

from src.worker_analysis.adapters import secop as modulo_secop
from src.worker_analysis.adapters.secop import CAMPOS_PROCESO, AdaptadorSECOP
from src.worker_vigilance.sync.secop_sync import normalizar_proceso

MUESTRA = Path(__file__).resolve().parents[1] / "fixtures" / "secop_procesos_500.json.gz"
PROCESOS = json.load(gzip.open(MUESTRA, "rt", encoding="utf-8"))["procesos"]
UMBRAL = 0.98

# Campo de origen -> campo normalizado que no puede quedar vacío si la fuente lo publicó.
CONSERVADOS = {"precio_base": "precio_base", "fecha_de_publicacion_del": "fecha_publicacion",
               "fecha_de_recepcion_de": "fecha_cierre", "fecha_de_ultima_publicaci": "actualizado_en_fuente",
               "urlproceso": "url_proceso", "id_del_portafolio": "id_portafolio"}


def _publicado(valor) -> bool:
    return valor not in (None, "") and str(valor).strip().lower() not in ("no definido", "no definida")


class _Respuesta:
    def __init__(self, datos):
        self._datos = datos

    def raise_for_status(self):
        return None

    def json(self):
        return self._datos


def problemas(crudo: dict, monkeypatch) -> list:
    hallados = []
    try:
        p = normalizar_proceso(crudo)
    except Exception as e:  # noqa: BLE001 - la prueba registra cualquier falla de interpretación
        return [f"vigilancia: {type(e).__name__}"]
    for campo in ("id_proceso", "entidad", "modalidad", "objeto"):
        if not p.get(campo):
            hallados.append(f"vigilancia sin {campo}")
    for origen, destino in CONSERVADOS.items():
        if _publicado(crudo.get(origen)) and p.get(destino) is None:
            hallados.append(f"vigilancia perdió {origen}")

    monkeypatch.setattr(modulo_secop.httpx, "get", lambda *a, **k: _Respuesta([crudo]))
    try:
        ficha = AdaptadorSECOP(base_url="https://datos.invalid/resource/x.json", app_token="").recuperar_expediente(
            crudo.get("id_del_proceso", ""))["contenido_crudo"]
    except Exception as e:  # noqa: BLE001
        return hallados + [f"análisis: {type(e).__name__}"]
    for campo, etiqueta in CAMPOS_PROCESO:
        if _publicado(crudo.get(campo)) and f"{etiqueta}:" not in ficha:
            hallados.append(f"análisis perdió {campo}")
    return hallados


def test_la_muestra_cubre_500_procesos_de_ocho_anios():
    assert len(PROCESOS) == 500
    assert {p["fecha_de_publicacion_del"][:4] for p in PROCESOS} == {str(a) for a in range(2019, 2027)}


def test_asr03_interpretacion_de_esquemas_historicos(monkeypatch):
    fallidos = {}
    for crudo in PROCESOS:
        hallados = problemas(crudo, monkeypatch)
        if hallados:
            fallidos[crudo.get("id_del_proceso")] = hallados
    tasa = 1 - len(fallidos) / len(PROCESOS)
    print(f"\nASR-03: {len(PROCESOS) - len(fallidos)}/{len(PROCESOS)} interpretados ({tasa:.1%})")
    assert tasa >= UMBRAL, f"Tasa {tasa:.1%} < {UMBRAL:.0%}: {dict(list(fallidos.items())[:10])}"


@pytest.mark.parametrize("cambio", ["campo_nuevo", "sin_url", "precio_texto", "fecha_corta"])
def test_un_cambio_de_esquema_no_rompe_la_interpretacion(cambio, monkeypatch):
    crudo = dict(PROCESOS[0])
    if cambio == "campo_nuevo":
        crudo["campo_que_no_existia"] = "valor"
    elif cambio == "sin_url":
        crudo.pop("urlproceso", None)
    elif cambio == "precio_texto":
        crudo["precio_base"] = "No Definido"
    else:
        crudo["fecha_de_publicacion_del"] = "2026-10-27"
    assert problemas(crudo, monkeypatch) == []
