"""
Revisión de requisitos: contrato de la Tabla 45 (GET /analisis/{id} con etapas y
PUT /analisis/{id}/requisitos con borrador) y revisión parcial tras una adenda (HU-06 CA-03).
"""
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

import src.api.middleware.auth as auth_mod
from src.api.main import app
from src.api.modules.analysis import router as modulo_router
from src.shared.config import Configuracion
from src.shared.schemas.domain import (
    CategoriaRequisito as C,
    DictamenRequisito,
    EstadoDictamen,
    ListaRequisitos,
    RequisitoExtraido,
)
from src.shared.tareas_repo import EstadoTarea
from src.worker_analysis.agents.recomendador import GeneradorRecomendacion
from src.worker_analysis.orchestrator.graph import ETAPAS, OrquestadorAnalisis
from src.worker_analysis.pipeline import adendas
from src.worker_analysis.pipeline.guardia import GuardiaDocumental
from src.worker_analysis.pipeline.segmentador import SegmentadorDocumental
from src.worker_analysis.reports.informe import GeneradorInforme
from src.worker_analysis.scoring.motor import MotorPuntaje
from src.worker_analysis.servicio import ServicioAnalisis, TransicionInvalidaError

PLIEGO_V1 = """4. REQUISITOS HABILITANTES
4.1 Experiencia: el proponente acredita tres contratos de software en los últimos cinco años.
4.2 Registro: el proponente presenta el RUP vigente con clasificación 43230000.
5. CRITERIOS DE PUNTUACIÓN
5.1 Certificación ISO 27001 vigente otorga diez puntos."""
PLIEGO_V2 = PLIEGO_V1.replace("RUP vigente con clasificación 43230000", "RUP vigente con clasificación 81110000")


def _req(identificador, texto, numeral, categoria=C.TECNICO, documento="Pliego", version=1):
    return {"identificador": identificador, "texto": texto, "categoria": categoria.value,
            "condicion_habilitante_propuesta": False,
            "referencia_documental": f"{documento} (v{version}) · Numeral {numeral}, página 1"}


def _contenido(*documentos):
    from src.worker_analysis.pipeline.segmentador import marca_documento
    return "\n\n".join(f"{marca_documento(n, 1, 'Carga manual')}\n[Página 1]\n{t}" for n, t in documentos)


APROBADOS = [
    _req("REQ-001", "Tres contratos de software en cinco años (corregido por el analista)", "4.1"),
    _req("REQ-002", "RUP vigente con clasificación 43230000", "4.2", C.JURIDICO),
    _req("REQ-003", "Certificación ISO 27001 vigente", "5.1"),
]


def _previa(*documentos):
    return {"tarea_id": "previa-123456", "aprobado_por": "ana@x.co", "requisitos_aprobados": APROBADOS,
            "documentos": adendas.textos_por_documento(_contenido(*documentos))}


# --- Reglas deterministas de la revisión parcial ---

def test_numeral_de_la_referencia_sin_confundir_la_pagina():
    assert adendas.numeral_de("Pliego (v2) · Numeral 4.2.1, página 17") == "4.2.1"
    assert adendas.numeral_de("Pliego (v1) · Página 3") is None
    assert adendas.documento_de("Pliego de condiciones (v2) · Numeral 4.2, página 7") == "Pliego de condiciones"
    assert adendas.documento_de("Agregado por el analista") is None


def test_numerales_citados_ignoran_cifras():
    texto = "Se modifica el numeral 4.2 y los numerales 5.1, 5.3 y 6. El presupuesto es 1.500.000 pesos."
    assert adendas.numerales_citados(texto) == ["4.2", "5.1", "5.3", "6"]


def test_seccion_llega_hasta_el_siguiente_numeral_hermano():
    assert adendas.seccion(PLIEGO_V1, "4.2").startswith("4.2 Registro")
    assert "5.1" not in adendas.seccion(PLIEGO_V1, "4.2")
    assert "4.2 Registro" in adendas.seccion(PLIEGO_V1, "4")  # el capítulo contiene sus subnumerales
    assert adendas.seccion(PLIEGO_V1, "9.9") is None


def test_version_nueva_solo_devuelve_a_revision_el_numeral_que_cambio():
    extraidos = [_req("REQ-001", "Tres contratos de software en cinco años", "4.1", version=2),
                 _req("REQ-002", "RUP vigente con clasificación 81110000", "4.2", C.JURIDICO, version=2),
                 _req("REQ-003", "Certificación ISO 27001 vigente", "5.1", version=2)]
    lista, revision = adendas.fusionar_con_revision_previa(
        _previa(("Pliego", PLIEGO_V1)), extraidos, _contenido(("Pliego", PLIEGO_V2)))

    estados = {i: r["estado"] for i, r in revision["requisitos"].items()}
    assert estados == {"REQ-001": adendas.CONSERVADO, "REQ-002": adendas.AFECTADO, "REQ-003": adendas.CONSERVADO}
    por_id = {r["identificador"]: r for r in lista}
    # Lo que no cambió conserva la corrección del analista; lo afectado trae el texto nuevo.
    assert por_id["REQ-001"]["texto"].endswith("(corregido por el analista)")
    assert por_id["REQ-002"]["texto"].endswith("81110000")
    assert revision["requisitos"]["REQ-002"]["texto_aprobado"].endswith("43230000")
    assert "4.2" in revision["requisitos"]["REQ-002"]["motivo"]
    assert revision["cambios"]["modificados"] == ["Pliego"]


def test_adenda_que_cita_un_capitulo_afecta_sus_requisitos_y_agrega_los_nuevos():
    adenda = "ADENDA No. 1\nSe modifica el capítulo 5: la certificación ISO 27001 otorga quince puntos."
    extraidos = [_req("REQ-001", "Certificación ISO 27001 otorga quince puntos", "5", documento="Adenda 1"),
                 _req("REQ-002", "Garantía de seriedad del 10 %", "6", C.FINANCIERO, documento="Adenda 1")]
    lista, revision = adendas.fusionar_con_revision_previa(
        _previa(("Pliego", PLIEGO_V1)), extraidos, _contenido(("Pliego", PLIEGO_V1), ("Adenda 1", adenda)))

    estados = {i: r["estado"] for i, r in revision["requisitos"].items()}
    assert estados["REQ-001"] == estados["REQ-002"] == adendas.CONSERVADO
    assert estados["REQ-003"] == adendas.AFECTADO
    nuevos = [i for i, e in estados.items() if e == adendas.NUEVO]
    assert nuevos == ["REQ-004"]
    assert {r["identificador"] for r in lista} == {"REQ-001", "REQ-002", "REQ-003", "REQ-004"}


def test_adenda_sin_numerales_devuelve_toda_la_lista():
    adenda = "ADENDA 2. Se modifican las condiciones de experiencia exigidas en el pliego."
    _, revision = adendas.fusionar_con_revision_previa(
        _previa(("Pliego", PLIEGO_V1)), [], _contenido(("Pliego", PLIEGO_V1), ("Adenda 2", adenda)))
    assert {r["estado"] for r in revision["requisitos"].values()} == {adendas.AFECTADO}


def test_sin_cambios_en_el_expediente_se_conserva_la_lista_y_se_ignora_el_ruido():
    ruido = [_req("REQ-001", "Requisito que la extracción ve distinto esta vez", "9")]
    lista, revision = adendas.fusionar_con_revision_previa(
        _previa(("Pliego", PLIEGO_V1)), ruido, _contenido(("Pliego", PLIEGO_V1)))
    assert lista == APROBADOS
    assert {r["estado"] for r in revision["requisitos"].values()} == {adendas.CONSERVADO}


# --- Servicio: etapas, borrador y revisión parcial de punta a punta ---

class RepositorioEnMemoria:
    def __init__(self):
        self.tareas = {}

    def actualizar(self, tarea_id, estado, **campos):
        self.tareas.setdefault(tarea_id, {}).update(estado=estado, **campos)

    def ultima_aprobada(self, licitacion_id, excluir=None):
        aprobadas = [t for t, d in self.tareas.items() if d.get("aprobado_por") and t != excluir]
        return {"tarea_id": aprobadas[-1]} if aprobadas else None


@pytest.fixture
def entorno(tmp_path):
    expediente = {"documentos": [{"nombre": "Pliego", "version": 1, "procedencia": "Carga manual",
                                  "paginas": [PLIEGO_V1]}], "no_analizados": []}
    extractor = MagicMock()
    extractor.extraer_requisitos.side_effect = lambda fragmento: ListaRequisitos(requisitos=[
        RequisitoExtraido(identificador="REQ-1", texto="Tres contratos de software", categoria=C.TECNICO,
                          condicion_habilitante_propuesta=True, referencia_documental="Numeral 4.1"),
        RequisitoExtraido(identificador="REQ-2", categoria=C.JURIDICO, condicion_habilitante_propuesta=True,
                          referencia_documental="Numeral 4.2",
                          texto="RUP vigente con clasificación " + ("81110000" if "81110000" in fragmento
                                                                    else "43230000")),
    ])
    evaluador = MagicMock()
    evaluador.evaluar_requisito.side_effect = lambda r: DictamenRequisito(
        identificador_requisito=r.identificador, estado=EstadoDictamen.CUMPLE, justificacion="Evidencia")
    gateway = MagicMock()
    gateway.invocar_texto.return_value = "Justificación ejecutiva."
    adaptador = MagicMock()
    adaptador.recuperar_expediente.return_value = {"id_proceso": "P1", "contenido_crudo": ""}
    checkpointer = MemorySaver()
    orquestador = OrquestadorAnalisis(
        extractor=extractor, evaluador=evaluador, guardia=GuardiaDocumental(),
        segmentador=SegmentadorDocumental(), motor_puntaje=MotorPuntaje(),
        recomendador=GeneradorRecomendacion(gateway, umbral_ofertar=80, umbral_revision=50),
        informe=GeneradorInforme(output_dir=str(tmp_path)), auditoria=MagicMock(),
        adaptador_secop=adaptador, checkpointer=checkpointer,
        proveedor_expediente=lambda _: expediente,
    )
    repo = RepositorioEnMemoria()
    return ServicioAnalisis(checkpointer=checkpointer, repositorio=repo, orquestador=orquestador), repo, expediente


def _requisito(d: dict) -> RequisitoExtraido:
    return RequisitoExtraido.model_validate(d)


def test_progreso_por_etapas(entorno):
    servicio, *_ = entorno
    assert servicio.progreso("t1") == {"etapa_actual": None, "etapas_cerradas": []}
    servicio.iniciar_analisis("t1", "P1")
    assert servicio.progreso("t1") == {"etapa_actual": "esperando_revision", "etapas_cerradas": list(ETAPAS[:4])}

    servicio.registrar_aprobacion("t1", [_requisito(r) for r in servicio.obtener_requisitos_extraidos("t1")], "ana")
    assert servicio.progreso("t1")["etapa_actual"] == "evaluando"
    servicio.reanudar_analisis("t1")
    assert servicio.progreso("t1") == {"etapa_actual": None, "etapas_cerradas": list(ETAPAS)}


def test_borrador_se_conserva_sin_aprobar(entorno):
    servicio, repo, _ = entorno
    servicio.iniciar_analisis("t1", "P1")
    extraidos = servicio.obtener_requisitos_extraidos("t1")
    corregido = _requisito({**extraidos[0], "texto": "Texto corregido"})

    guardado = servicio.guardar_borrador("t1", [corregido], "ana@x.co")
    assert guardado["total"] == 1 and guardado["guardado_por"] == "ana@x.co"

    revision = servicio.obtener_revision("t1")
    assert [r["texto"] for r in revision["requisitos"]] == ["Texto corregido"]
    assert revision["extraidos"] == extraidos  # el valor de la IA se conserva (HU-06 CA-01)
    assert revision["borrador"]["guardado_por"] == "ana@x.co"
    assert repo.tareas["t1"]["estado"] == EstadoTarea.ESPERANDO_REVISION

    servicio.registrar_aprobacion("t1", [corregido], "ana@x.co")
    with pytest.raises(TransicionInvalidaError):
        servicio.guardar_borrador("t1", [corregido], "ana@x.co")


def test_adenda_devuelve_a_revision_solo_lo_afectado(entorno):
    servicio, repo, expediente = entorno
    servicio.iniciar_analisis("t1", "P1")
    extraidos = servicio.obtener_requisitos_extraidos("t1")
    aprobados = [_requisito({**extraidos[0], "texto": "Tres contratos (corregido)"}), _requisito(extraidos[1])]
    servicio.registrar_aprobacion("t1", aprobados, "ana@x.co")
    servicio.reanudar_analisis("t1")

    # Llega la versión 2 del pliego: solo cambia el numeral 4.2.
    expediente["documentos"] = [{"nombre": "Pliego", "version": 2, "procedencia": "Carga manual",
                                 "paginas": [PLIEGO_V2]}]
    servicio.iniciar_analisis("t2", "P1")

    revision = servicio.obtener_revision("t2")
    estados = {i: r["estado"] for i, r in revision["revision"]["requisitos"].items()}
    assert estados == {"REQ-001": adendas.CONSERVADO, "REQ-002": adendas.AFECTADO}
    por_id = {r["identificador"]: r for r in revision["requisitos"]}
    assert por_id["REQ-001"]["texto"] == "Tres contratos (corregido)"
    assert por_id["REQ-002"]["texto"].endswith("81110000")
    assert revision["revision"]["tarea_previa"] == "t1"
    # Nada se evalúa hasta que el analista apruebe (compuerta humana, ASR-12).
    assert repo.tareas["t2"]["estado"] == EstadoTarea.ESPERANDO_REVISION


# --- API (Tabla 45) ---

class ServicioFalso:
    def __init__(self):
        self.borradores, self.aprobaciones = [], []

    def progreso(self, tarea_id):
        return {"etapa_actual": "esperando_revision", "etapas_cerradas": list(ETAPAS[:4])}

    def guardar_borrador(self, tarea_id, requisitos, usuario):
        self.borradores.append(list(requisitos))
        return {"total": len(self.borradores[-1]), "guardado_por": usuario, "guardado_en": "2026-10-25T14:00:00"}

    def registrar_aprobacion(self, tarea_id, requisitos, usuario):
        if self.aprobaciones:
            raise TransicionInvalidaError("La lista ya fue aprobada.")
        self.aprobaciones.append(list(requisitos))

    def reanudar_analisis(self, tarea_id):
        pass


class RepositorioFalso:
    def obtener(self, tarea_id):
        return {"tarea_id": tarea_id, "estado": "Esperando revisión", "puntaje": None, "recomendacion": None}


TOKEN = "token-de-prueba-largo"
CUERPO = {"requisitos": [{"identificador": "REQ-001", "texto": "RUP vigente", "categoria": "juridico",
                          "condicion_habilitante_propuesta": True, "referencia_documental": "3.1"}]}


@pytest.fixture
def cliente(monkeypatch):
    config = replace(Configuracion(), auth_mode="desarrollo", api_token_desarrollo=TOKEN)
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)
    servicio = ServicioFalso()
    app.dependency_overrides[modulo_router.obtener_servicio] = lambda: servicio
    app.dependency_overrides[modulo_router.obtener_repositorio] = RepositorioFalso
    app.dependency_overrides[modulo_router.obtener_publicador] = lambda: None
    yield TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}), servicio
    app.dependency_overrides.clear()


def test_get_analisis_trae_etapas(cliente):
    c, _ = cliente
    cuerpo = c.get("/analisis/t1").json()
    assert cuerpo["estado"] == "Esperando revisión" and cuerpo["requiere_accion"] is True
    assert cuerpo["etapa_actual"] == "esperando_revision" and cuerpo["etapas_cerradas"][-1] == "extrayendo"
    assert {"puntaje", "recomendacion"} <= set(cuerpo)


def test_put_requisitos_borrador_y_aprobacion(cliente):
    c, servicio = cliente
    r = c.put("/analisis/t1/requisitos", json=CUERPO)
    assert r.status_code == 200 and "Borrador" in r.json()["mensaje"]
    assert len(servicio.borradores) == 1 and not servicio.aprobaciones

    r = c.put("/analisis/t1/requisitos", json={**CUERPO, "aprobar": True})
    assert r.status_code == 202 and len(servicio.aprobaciones) == 1
    # Tabla 45: 409 lista ya aprobada.
    assert c.put("/analisis/t1/requisitos", json={**CUERPO, "aprobar": True}).status_code == 409


def test_put_requisitos_rechaza_esquema_invalido(cliente):
    c, _ = cliente
    assert c.put("/analisis/t1/requisitos", json={"requisitos": [{"identificador": "X"}]}).status_code == 422
    duplicados = {"requisitos": CUERPO["requisitos"] * 2}
    assert c.put("/analisis/t1/requisitos", json=duplicados).status_code == 422
    assert c.put("/analisis/t1/requisitos", json={"requisitos": [], "aprobar": True}).status_code == 422
