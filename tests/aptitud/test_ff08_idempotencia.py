"""
FF-08 (ASR-04, Tabla 33): las etapas del flujo son idempotentes. Cada mensaje de la cola se
entrega de nuevo con la misma clave (idTarea y etapa, Tabla 46) y se comprueba que no
duplica extracciones, dictámenes, informes ni eventos de la bitácora.

Usa el checkpointer en memoria; la prueba de integración con PostgresSaver
(tests/integration) recorre el mismo flujo contra la base real.
"""
from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.shared.schemas.domain import (
    CategoriaRequisito as C,
    DictamenRequisito,
    EstadoDictamen,
    ListaRequisitos,
    RequisitoExtraido,
)
from src.shared.tareas_repo import EstadoTarea
from src.worker_analysis.agents.recomendador import GeneradorRecomendacion
from src.worker_analysis.orchestrator.graph import OrquestadorAnalisis
from src.worker_analysis.pipeline.guardia import GuardiaDocumental
from src.worker_analysis.pipeline.segmentador import SegmentadorDocumental
from src.worker_analysis.reports.informe import GeneradorInforme
from src.worker_analysis.scoring.motor import MotorPuntaje
from src.worker_analysis.servicio import (
    TIPO_ANALISIS,
    TIPO_REANUDACION,
    ServicioAnalisis,
    TransicionInvalidaError,
)


class Repositorio:
    def __init__(self):
        self.tareas = {}

    def actualizar(self, tarea_id, estado, **campos):
        self.tareas.setdefault(tarea_id, {}).update(estado=estado, **campos)


class RegistroInformes:
    """Emisión única por tarea, como la tabla informes_emitidos (RN-08)."""

    def __init__(self):
        self.emitidos = {}

    def obtener(self, tarea_id):
        return self.emitidos.get(tarea_id)

    def emitir(self, estado, resultado, auditoria):
        assert estado["tarea_id"] not in self.emitidos, "informe emitido dos veces"
        self.emitidos[estado["tarea_id"]] = {"ruta_pdf": resultado["informe_path"],
                                             "huella_sha256": resultado["huella_sha256"]}


@pytest.fixture
def entorno(tmp_path):
    extractor = MagicMock()
    extractor.extraer_requisitos.return_value = ListaRequisitos(requisitos=[
        RequisitoExtraido(identificador="REQ-1", texto="RUP vigente", categoria=C.JURIDICO,
                          condicion_habilitante_propuesta=True, referencia_documental="3.1")])
    evaluador = MagicMock()
    evaluador.evaluar_requisito.side_effect = lambda r: DictamenRequisito(
        identificador_requisito=r.identificador, estado=EstadoDictamen.CUMPLE, justificacion="ok")
    gateway = MagicMock()
    gateway.invocar_texto.return_value = "Justificación."
    adaptador = MagicMock()
    adaptador.recuperar_expediente.return_value = {"id_proceso": "P1", "contenido_crudo": "Objeto: software."}
    informe = GeneradorInforme(output_dir=str(tmp_path))
    informe.generar_y_sellar = MagicMock(wraps=informe.generar_y_sellar)
    auditoria = MagicMock()
    registro = RegistroInformes()
    orquestador = OrquestadorAnalisis(
        extractor=extractor, evaluador=evaluador, guardia=GuardiaDocumental(),
        segmentador=SegmentadorDocumental(), motor_puntaje=MotorPuntaje(),
        recomendador=GeneradorRecomendacion(gateway, umbral_ofertar=80, umbral_revision=50),
        informe=informe, auditoria=auditoria, adaptador_secop=adaptador,
        checkpointer=MemorySaver(), registro_informes=registro,
    )
    servicio = ServicioAnalisis(checkpointer=None, repositorio=Repositorio(), orquestador=orquestador)
    return servicio, extractor, evaluador, informe, registro, auditoria


MENSAJE = {"tipo_tarea": TIPO_ANALISIS, "tarea_id": "t1", "licitacion_url": "P1"}


def test_ff08_repetir_la_solicitud_no_vuelve_a_extraer(entorno):
    servicio, extractor, *_ = entorno
    servicio.procesar_mensaje(MENSAJE)
    llamadas = extractor.extraer_requisitos.call_count
    servicio.procesar_mensaje(MENSAJE)  # la cola entrega el mismo mensaje otra vez
    assert extractor.extraer_requisitos.call_count == llamadas
    assert servicio.repositorio.tareas["t1"]["estado"] == EstadoTarea.ESPERANDO_REVISION


def test_ff08_repetir_la_reanudacion_no_duplica_dictamenes_ni_informe(entorno):
    servicio, _, evaluador, informe, registro, auditoria = entorno
    servicio.procesar_mensaje(MENSAJE)
    requisitos = [RequisitoExtraido.model_validate(r) for r in servicio.obtener_requisitos_extraidos("t1")]
    servicio.registrar_aprobacion("t1", requisitos, "ana@x.co")
    reanudar = {"tipo_tarea": TIPO_REANUDACION, "tarea_id": "t1"}

    servicio.procesar_mensaje(reanudar)
    servicio.procesar_mensaje(reanudar)
    servicio.procesar_mensaje(MENSAJE)  # incluso la solicitud original repetida al final

    assert evaluador.evaluar_requisito.call_count == 1
    assert informe.generar_y_sellar.call_count == 1 and list(registro.emitidos) == ["t1"]
    resultado = servicio.obtener_resultado("t1")
    assert len(resultado["dictamenes"]) == 1
    assert servicio.repositorio.tareas["t1"]["estado"] == EstadoTarea.FINALIZADA
    eventos = [c.args[1] for c in auditoria.registrar_evento.call_args_list]
    assert eventos.count("REQUISITOS_APROBADOS") == 1


def test_ff08_la_aprobacion_no_se_sella_dos_veces(entorno):
    servicio, *_ = entorno
    servicio.procesar_mensaje(MENSAJE)
    requisitos = [RequisitoExtraido.model_validate(r) for r in servicio.obtener_requisitos_extraidos("t1")]
    servicio.registrar_aprobacion("t1", requisitos, "ana@x.co")
    with pytest.raises(TransicionInvalidaError):
        servicio.registrar_aprobacion("t1", requisitos, "ana@x.co")


def test_ff08_la_etapa_de_informe_repetida_devuelve_el_mismo(entorno):
    servicio, _, _, informe, registro, _ = entorno
    servicio.procesar_mensaje(MENSAJE)
    requisitos = [RequisitoExtraido.model_validate(r) for r in servicio.obtener_requisitos_extraidos("t1")]
    servicio.registrar_aprobacion("t1", requisitos, "ana@x.co")
    servicio.reanudar_analisis("t1")
    estado = servicio.grafo.get_state(servicio._config("t1")).values

    # Se ejecuta otra vez solo la etapa de informe con la misma tarea (misma clave).
    repetida = OrquestadorAnalisis._generar_informe(MagicMock(registro_informes=registro, informe=informe), estado)
    assert repetida["huella_informe"] == registro.emitidos["t1"]["huella_sha256"]
    assert informe.generar_y_sellar.call_count == 1
