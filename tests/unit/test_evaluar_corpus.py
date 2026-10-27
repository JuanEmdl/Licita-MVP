"""Calificación del banco de corrección funcional (scripts/evaluar_corpus.py), sin red ni modelo."""
import json

import pytest

from scripts.evaluar_corpus import (
    CASOS, ESTADOS, RAIZ, cargar_casos, cifras, cifras_ancladas, coincide, emparejar, kappa,
    precision_adjudicada, resumen_dictamen,
)


def _req(texto, categoria="financiero", habilitante=True, referencia="Numeral 3.5"):
    return {"identificador": "REQ-1", "texto": texto, "categoria": categoria,
            "condicion_habilitante_propuesta": habilitante, "referencia_documental": referencia}


def test_coincide_con_claves_o_alternativas_sin_tildes():
    esperado = {"claves": ["registro unico de proponentes"], "alternativas": [["rup", "inscri"]]}
    assert coincide("Inscripción vigente en el Registro Único de Proponentes", esperado)
    assert coincide("El proponente deberá estar inscrito en el RUP", esperado)
    assert not coincide("Certificado de existencia y representación legal", esperado)


def test_emparejar_separa_encontrados_prohibidos_y_sobrantes():
    caso = {"esperados": [{"id": "Liquidez", "claves": ["liquidez", "1,5"], "categoria": "financiero",
                           "habilitante": True, "referencia": "2.1.2"}],
            "prohibidos": [["1,52"]]}
    requisitos = [_req("Índice de liquidez igual o superior a 1,52"),
                  _req("Índice de liquidez igual o superior al 1,5", referencia="Numeral 2.1.2"),
                  _req("Póliza de seriedad de la oferta", categoria="juridico")]
    r = emparejar(caso, requisitos)
    # El 1,52 de otro proceso va primero y no se confunde con el 1,5 exigido.
    assert r["esperados"][0]["encontrado"] and r["esperados"][0]["indice"] == 1
    assert r["prohibidos"] == ["Índice de liquidez igual o superior a 1,52"]
    assert r["sobrantes"] == [2]


def test_emparejar_prefiere_el_candidato_con_el_numeral_esperado():
    caso = {"esperados": [{"id": "Accesibilidad", "claves": ["accesibilidad"], "categoria": "tecnico",
                           "habilitante": True, "referencia": "6.3"}]}
    requisitos = [_req("La solución deberá ser accesible: accesibilidad WCAG", referencia="Numeral 1.2"),
                  _req("Cumplimiento de criterios de accesibilidad web", referencia="Numeral 6.3")]
    assert emparejar(caso, requisitos)["esperados"][0]["indice"] == 1


def test_cifras_coinciden_completas_con_punto_o_coma():
    esperado = {"claves": ["liquidez", "2.10"]}
    assert coincide("Índice de liquidez mayor o igual a 2,10", esperado)
    assert not coincide("Índice de liquidez mayor o igual a 2,105", esperado)
    assert coincide("Endeudamiento menor o igual al 50%", {"claves": ["endeudamiento", "50"]})
    assert not coincide("Endeudamiento menor o igual al 150%", {"claves": ["endeudamiento", "50"]})


def test_cifras_normaliza_separadores_y_miles():
    assert cifras("Liquidez >= 4,0 y endeudamiento 1.5; capital $6.351.097.824") == ["4,0", "1,5", "6351097824"]


def test_cifras_ancladas_detecta_valores_inventados():
    fuente = "Índice de liquidez Mayor o igual a 4,0. Endeudamiento menor o igual a 50%."
    assert cifras_ancladas("Liquidez mayor o igual a 4.0", fuente)
    assert not cifras_ancladas("Liquidez mayor o igual a 4,5", fuente)


def test_kappa_y_exactitud():
    pares = [("Cumple", "Cumple"), ("No cumple", "No cumple"), ("Cumple", "No verificable"),
             ("No verificable", "No verificable")]
    resumen = resumen_dictamen(pares)
    assert resumen["exactitud"] == 0.75
    assert resumen["matriz"]["Cumple"]["No verificable"] == 1
    assert kappa([("Cumple", "Cumple"), ("No cumple", "No cumple")]) == 1.0
    assert kappa([]) is None


def test_precision_adjudicada_estima_con_la_muestra():
    muestra = {"casos": {"01": {"extraidos": 20, "encontrados": 10, "sobrantes": 10, "prohibidos_validos": 0,
                                "muestra": [{"valido": True}, {"valido": False}, {"valido": None}]}}}
    r = precision_adjudicada(muestra)
    assert r["casos"]["01"]["tasa_sobrantes_validos"] == 0.5
    assert r["precision"] == 0.75


@pytest.mark.parametrize("caso", cargar_casos(), ids=lambda c: c["archivo"])
def test_casos_del_corpus_bien_formados(caso):
    ids = [e["id"] for e in caso["esperados"]]
    assert len(ids) == len(set(ids))
    for e in caso["esperados"]:
        assert e["categoria"] in ("tecnico", "financiero", "juridico", "experiencia", "personal")
        assert e["dictamen"] is None or e["dictamen"] in ESTADOS
        assert e["claves"] and all(isinstance(c, str) for c in e["claves"])
    # El portafolio es ficticio y se declara así en cada registro.
    assert all("FICTICIO" in c["descripcion"] for c in caso["portafolio"])
    if not all((RAIZ / d).exists() for d in caso["documentos"]):
        pytest.skip("Los PDF del corpus se descargan a mano de SECOP II (DV-01) y git no los versiona.")


def test_corpus_tiene_los_ocho_pliegos():
    assert len(list(CASOS.glob("*.json"))) == 8
    json.loads((CASOS / "01_contraloria_cundinamarca.json").read_text(encoding="utf-8"))
