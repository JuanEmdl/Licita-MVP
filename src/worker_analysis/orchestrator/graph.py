import contextvars
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, List, Optional, TypeVar

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, END
from src.shared import telemetria
from src.shared.schemas.domain import DictamenRequisito, RequisitoExtraido
from src.worker_analysis.orchestrator.state import AnalisisState
from src.worker_analysis.agents.extractor import AgenteExtractor
from src.worker_analysis.agents.evaluator import AgenteEvaluador
from src.worker_analysis.agents.recomendador import GeneradorRecomendacion
from src.worker_analysis.agents.prompts import VERSION_PROMPTS
from src.worker_analysis.nucleo.maquina_estados import Estado, MaquinaEstados
from src.worker_analysis.nucleo.puertos import (
    ProveedorExpediente,
    ProveedorReglas,
    PuertoAlmacenDocumentos,
    PuertoAuditoria,
    PuertoExpediente,
    PuertoRegistroInformes,
)
from src.worker_analysis.pipeline.adendas import fusionar_con_revision_previa
from src.worker_analysis.pipeline.guardia import GuardiaDocumental, SuspectedInjectionError
from src.worker_analysis.pipeline.segmentador import (
    SegmentadorDocumental,
    escapar_marcas,
    marca_documento,
    paginas_del_fragmento,
)
from src.worker_analysis.scoring.motor import MotorPuntaje, ReglasPuntaje
from src.worker_analysis.reports.informe import GeneradorInforme
from src.worker_analysis.reports.auditoria import RegistradorAuditoria
from src.worker_analysis.adapters.secop import AdaptadorSECOP

logger = logging.getLogger(__name__)


def _clave_requisito(req: RequisitoExtraido) -> tuple:
    """Clave para detectar el mismo requisito extraído dos veces por el solape entre fragmentos."""
    return (req.categoria.value, " ".join(req.texto.lower().split()))

# Nodo antes del cual el grafo se detiene hasta que el analista apruebe (ASR-12).
NODO_COMPUERTA_HUMANA = "evaluando"
# Nodo que se declara como autor al inyectar la lista aprobada en el checkpoint.
NODO_PREVIO_COMPUERTA = "extrayendo"
# Etapas del flujo normal en su orden (Figura 15); «suspendida» es la salida de la guardia.
ETAPAS = ("recuperando_expediente", "saneando", "segmentando", "extrayendo", "evaluando",
          "calculando_puntaje", "generando_recomendacion", "generando_informe")


def _palabras(texto: str) -> set:
    return {p for p in re.findall(r"\w{4,}", (texto or "").lower())}


def completar_referencia(referencia: str, texto_requisito: str, fragmento: str) -> str:
    """
    RF-023, HU-05 CA-01: el extractor cita el numeral; el sistema agrega el documento, su
    versión y la página donde aparece la exigencia, tomados del encabezado y de las marcas
    [Página N] del fragmento. Sin páginas (pliego pegado como texto) se deja como vino.
    """
    cabecera = dict(re.findall(r"^(Documento Origen|Versión|Páginas): (.*)$", fragmento, re.MULTILINE))
    documento = cabecera.get("Documento Origen")
    if not documento or not cabecera.get("Páginas"):
        return referencia
    palabras = _palabras(texto_requisito)
    candidatas = [(len(palabras & _palabras(texto)), pagina) for pagina, texto in paginas_del_fragmento(fragmento)
                  if pagina is not None]
    pagina = max(candidatas, key=lambda c: c[0])[1] if candidatas else None
    referencia = (referencia or "").strip()
    if pagina is not None and not re.search(r"p[aá]g", referencia, re.IGNORECASE):
        referencia = f"{referencia}, página {pagina}" if referencia else f"Página {pagina}"
    return f"{documento} (v{cabecera.get('Versión', '1')}) · {referencia}"


def _requisitos(datos: List[dict]) -> List[RequisitoExtraido]:
    return [RequisitoExtraido.model_validate(d) for d in datos]


def _dictamenes(datos: List[dict]) -> List[DictamenRequisito]:
    return [DictamenRequisito.model_validate(d) for d in datos]


T = TypeVar("T")
R = TypeVar("R")


def en_paralelo(funcion: Callable[[T], R], elementos: Iterable[T], paralelismo: int) -> List[R]:
    """
    Aplica la función a cada elemento con hasta `paralelismo` hilos y devuelve los resultados
    en el orden de entrada (RNF-001, apartado 2.12): el orden fija la deduplicación y los
    identificadores, así que el resultado es el mismo que en serie. Cada hilo hereda el
    contexto de telemetría de la tarea. La primera falla se propaga y cancela lo pendiente.
    """
    elementos = list(elementos)
    if paralelismo <= 1 or len(elementos) <= 1:
        return [funcion(e) for e in elementos]
    pool = ThreadPoolExecutor(max_workers=min(paralelismo, len(elementos)), thread_name_prefix="analisis")
    try:
        futuros = [pool.submit(contextvars.copy_context().run, funcion, e) for e in elementos]
        return [f.result() for f in futuros]
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def _medida(etapa: str, funcion):
    """Envuelve una etapa del grafo en un span con su duración, sin contenido (ASR-05)."""
    def _etapa(state: AnalisisState) -> dict:
        with telemetria.con_tarea(state.get("tarea_id") or telemetria.tarea_actual.get()), \
                telemetria.medir(f"etapa {etapa}", telemetria.duracion_etapa, etapa=etapa):
            return funcion(state)
    _etapa.__name__ = etapa
    return _etapa


def _reglas_desde_base(version: int) -> dict:
    from src.shared.reglas_repo import RepositorioReglas
    return RepositorioReglas().obtener(version)


class OrquestadorAnalisis:
    """
    Orquestador del flujo de análisis (DA-03).
    Máquina de estados que fija el orden de las etapas y detiene la ejecución
    hasta la aprobación humana de los requisitos (ASR-12).
    """

    def __init__(
        self,
        extractor: AgenteExtractor,
        evaluador: AgenteEvaluador,
        guardia: GuardiaDocumental,
        segmentador: SegmentadorDocumental,
        motor_puntaje: MotorPuntaje,
        recomendador: GeneradorRecomendacion,
        informe: GeneradorInforme,
        auditoria: PuertoAuditoria,
        adaptador_secop: PuertoExpediente,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        proveedor_reglas: Optional[ProveedorReglas] = None,
        registro_informes: Optional[PuertoRegistroInformes] = None,
        proveedor_expediente: Optional[ProveedorExpediente] = None,
        paralelismo: Optional[int] = None,
        almacen_informes: Optional[PuertoAlmacenDocumentos] = None,
    ):
        self.extractor = extractor
        self.evaluador = evaluador
        self.guardia = guardia
        self.segmentador = segmentador
        self.motor_puntaje = motor_puntaje
        self.recomendador = recomendador
        self.informe = informe
        self.auditoria = auditoria
        self.adaptador_secop = adaptador_secop
        # Devuelve una versión de reglas por su número (RF-033). Por defecto, la base de datos.
        self.proveedor_reglas = proveedor_reglas or _reglas_desde_base
        # Emisión atómica del informe (Tabla 19). Sin él, el informe y su huella se registran por separado.
        self.registro_informes = registro_informes
        # Documentos vigentes del expediente (RF-021, RF-022). Sin él, solo la ficha y el pliego pegado.
        self.proveedor_expediente = proveedor_expediente
        # Blob Storage inmutable (DA-06): el informe sellado se sube antes de registrar la emisión.
        self.almacen_informes = almacen_informes
        if paralelismo is None:
            from src.shared.config import obtener_configuracion
            paralelismo = obtener_configuracion().analisis_paralelismo
        self.paralelismo = max(1, paralelismo)
        self.graph = self._construir_grafo(checkpointer)

    def _construir_grafo(self, checkpointer: Optional[BaseCheckpointSaver]):
        workflow = StateGraph(AnalisisState)

        # Añadir nodos (etapas de la Figura 9). Cada etapa se mide como un span (RF-043).
        etapas = {
            "recuperando_expediente": self._recuperar_expediente,
            "saneando": self._sanear_contenido,
            "suspendida": self._estado_suspendida,  # Estado terminal por seguridad
            "segmentando": self._segmentar_contenido,
            "extrayendo": self._extraer_requisitos,
            "evaluando": self._evaluar_requisitos,
            "calculando_puntaje": self._calcular_puntaje,
            "generando_recomendacion": self._generar_recomendacion,
            "generando_informe": self._generar_informe,
        }
        for nombre, funcion in etapas.items():
            workflow.add_node(nombre, _medida(nombre, funcion))

        # Definir los bordes (flujo secuencial)
        workflow.set_entry_point("recuperando_expediente")
        workflow.add_edge("recuperando_expediente", "saneando")

        # Borde condicional para la guardia documental (ASR-10)
        workflow.add_conditional_edges(
            "saneando",
            self._verificar_saneamiento,
            {
                "ok": "segmentando",
                "inyeccion_detectada": "suspendida"
            }
        )

        workflow.add_edge("suspendida", END)
        workflow.add_edge("segmentando", "extrayendo")
        workflow.add_edge("extrayendo", "evaluando")
        workflow.add_edge("evaluando", "calculando_puntaje")
        workflow.add_edge("calculando_puntaje", "generando_recomendacion")
        workflow.add_edge("generando_recomendacion", "generando_informe")
        workflow.add_edge("generando_informe", END)

        # ASR-12: el grafo se detiene antes de evaluar. El checkpointer debe pasarse
        # en compile(); asignarlo después no tiene efecto sobre el grafo compilado.
        # Con PostgresSaver (DA-03, ASR-04) la pausa sobrevive a reinicios y puede
        # reanudarla un proceso distinto del que la inició.
        return workflow.compile(
            checkpointer=checkpointer,
            interrupt_before=[NODO_COMPUERTA_HUMANA],
        )

    # --- Definición de las funciones de cada nodo ---
    # Cada nodo devuelve solo las claves que modifica.

    def _recuperar_expediente(self, state: AnalisisState) -> dict:
        licitacion_url = state["licitacion_url"]
        contenido_pliego = (state.get("contenido_pliego") or "").strip()

        documentos = {"documentos": [], "no_analizados": []}
        if self.proveedor_expediente is not None:
            try:
                documentos = self.proveedor_expediente(licitacion_url)
            except Exception as e:
                logger.warning(f"No se pudo leer el expediente documental ({type(e).__name__}); "
                               "se analizan la ficha y el pliego aportado.")

        # Invocamos la capa anticorrupción (Adaptador SECOP II - ASR-03)
        try:
            expediente = self.adaptador_secop.recuperar_expediente(licitacion_url)
        except Exception as e:
            if not contenido_pliego and not documentos["documentos"]:
                raise
            # Con el pliego aportado o documentos en el expediente, una falla de Datos Abiertos
            # no detiene el análisis.
            logger.warning(f"SECOP II no disponible ({e}); se analizan los documentos disponibles.")
            expediente = {"id_proceso": licitacion_url, "contenido_crudo": ""}

        ficha = expediente.get("contenido_crudo", "")

        if documentos["documentos"]:
            # Cada documento con su versión y procedencia, y su texto por página (RF-023).
            partes = []
            if ficha:
                partes.append(marca_documento("Ficha del proceso", expediente.get("version") or "N/A",
                                              "SECOP II · Datos Abiertos") + "\n" + escapar_marcas(ficha))
            for d in documentos["documentos"]:
                paginas = "\n".join(f"[Página {i}]\n{escapar_marcas(texto)}"
                                    for i, texto in enumerate(d["paginas"], start=1) if texto.strip())
                partes.append(marca_documento(d["nombre"], d["version"], d["procedencia"]) + "\n" + paginas)
            if contenido_pliego:
                partes.append(marca_documento("Pliego aportado por el analista", 1, "Texto de la solicitud")
                              + "\nPLIEGO DE CONDICIONES:\n" + escapar_marcas(contenido_pliego))
        else:
            partes = [ficha]
            if contenido_pliego:
                partes.append(f"PLIEGO DE CONDICIONES:\n{contenido_pliego}")

        return {
            # Guardamos la ruta o referencia del expediente crudo
            "expediente_path": f"storage/secop/{expediente['id_proceso']}",
            # Contenido no confiable: la guardia documental lo revisa en el siguiente nodo
            "contenido_crudo": "\n\n".join(p for p in partes if p),
            # Para el informe (HU-10): qué se analizó y qué no, con versión y procedencia.
            "ficha_recuperada": bool(ficha.strip()),
            "documentos_analizados": [{k: d.get(k) for k in ("nombre", "version", "procedencia", "obtenido_en",
                                                             "huella_sha256")} | {"paginas": len(d["paginas"])}
                                      for d in documentos["documentos"]],
            "documentos_no_analizados": documentos.get("no_analizados", []),
        }

    def _sanear_contenido(self, state: AnalisisState) -> dict:
        contenido_crudo = state.get("contenido_crudo") or ""
        try:
            return {
                "contenido_saneado": self.guardia.sanear_contenido(contenido_crudo),
                "error_msg": None,
            }
        except SuspectedInjectionError as e:
            # Capturamos el error para que el enrutador condicional cambie a Suspendida
            return {"contenido_saneado": None, "error_msg": str(e)}

    def _verificar_saneamiento(self, state: AnalisisState) -> str:
        """Función de enrutamiento condicional tras el saneamiento."""
        if state.get("error_msg"):
            return "inyeccion_detectada"
        return "ok"

    def _estado_suspendida(self, state: AnalisisState) -> dict:
        """Estado terminal cuando el análisis se suspende por seguridad (ASR-10)."""
        self.auditoria.registrar_evento(
            state.get("tarea_id", "tarea_desconocida"),
            "ANALISIS_SUSPENDIDO",
            {"motivo": state.get("error_msg")},
        )
        return {}

    def _segmentar_contenido(self, state: AnalisisState) -> dict:
        contenido = state.get("contenido_saneado")
        if not contenido:
            return {"fragmentos": []}

        metadatos_origen = {
            "documento": state.get("expediente_path") or "Expediente SECOP II",
            "version": "1.0",
            "licitacion": state.get("licitacion_url", "Desconocida")
        }

        fragmentos = self.segmentador.segmentar(contenido, metadatos_origen)
        descartados = getattr(self.segmentador, "descartados", None)
        # HU-05 CA-04: lo descartado por no tener referencia de origen queda en la traza de la tarea.
        return {"fragmentos": fragmentos,
                "fragmentos_descartados": list(descartados) if isinstance(descartados, list) else []}

    def _extraer_requisitos(self, state: AnalisisState) -> dict:
        todos_los_requisitos: List[RequisitoExtraido] = []
        vistos = set()
        fragmentos = state.get("fragmentos", [])
        # Los fragmentos se extraen en paralelo y se recorren en su orden (RNF-001).
        resultados = en_paralelo(self.extractor.extraer_requisitos, fragmentos, self.paralelismo)
        for fragmento, resultado in zip(fragmentos, resultados):
            for req in resultado.requisitos:
                if isinstance(fragmento, str):
                    req = req.model_copy(update={"referencia_documental": completar_referencia(
                        req.referencia_documental, req.texto, fragmento)})
                # Los fragmentos se solapan: el mismo requisito puede aparecer dos veces.
                clave = _clave_requisito(req)
                if clave in vistos:
                    continue
                vistos.add(clave)
                todos_los_requisitos.append(req)

        # Cada llamada al extractor numera desde REQ-1, así que los IDs del modelo se
        # repiten entre fragmentos. Se reasignan aquí para que sean únicos en la tarea;
        # de lo contrario el puntaje y la recomendación sobrescriben requisitos.
        requisitos = [
            req.model_copy(update={"identificador": f"REQ-{i:03d}"}).model_dump(mode="json")
            for i, req in enumerate(todos_los_requisitos, start=1)
        ]
        if not requisitos:
            logger.warning(
                f"Tarea {state.get('tarea_id')}: no se extrajeron requisitos. Si solo se envió el ID del "
                "proceso, Datos Abiertos no publica el pliego: aporte contenido_pliego."
            )
        previa = state.get("revision_previa")
        if previa and previa.get("requisitos_aprobados"):
            # HU-06 CA-03: lo que el cambio documental no toca conserva la aprobación previa.
            requisitos, revision = fusionar_con_revision_previa(previa, requisitos, state.get("contenido_saneado") or "")
            return {"requisitos_extraidos": requisitos, "revision_requisitos": revision,
                    "version_prompts": VERSION_PROMPTS}
        return {"requisitos_extraidos": requisitos, "version_prompts": VERSION_PROMPTS}

    def _evaluar_requisitos(self, state: AnalisisState) -> dict:
        # ASR-12: El agente evaluador solo opera sobre requisitos aprobados por el analista. La compuerta
        # del grafo ya lo impide; la máquina de estados lo verifica otra vez aquí (Tabla 18).
        MaquinaEstados().validar(Estado.EN_ESPERA_DE_REVISION, Estado.EVALUANDO,
                                 lista_aprobada=bool(state.get("aprobado_por")))
        # La evidencia sale de la versión del portafolio que fijó la tarea (RN-03).
        version = state.get("portafolio_version")
        extra = {} if version is None else {"portafolio_version": version}
        dictamenes = en_paralelo(lambda req: self.evaluador.evaluar_requisito(req, **extra).model_dump(mode="json"),
                                 _requisitos(state.get("requisitos_aprobados", [])), self.paralelismo)
        return {"dictamenes": dictamenes}

    def _calcular_puntaje(self, state: AnalisisState) -> dict:
        requisitos = _requisitos(state.get("requisitos_aprobados", []))
        dictamenes = _dictamenes(state.get("dictamenes", []))

        # Reglas de la versión que fijó la tarea (RN-06); sin versión, los valores provisionales.
        cambios = {}
        reglas = None
        if state.get("reglas_version") is not None:
            regla = self.proveedor_reglas(state["reglas_version"])
            reglas = ReglasPuntaje.desde_version(regla)
            cambios["reglas_aplicadas"] = {
                "version": regla["version"],
                "pesos": regla["pesos"],
                "umbral_ofertar": regla["umbral_ofertar"],
                "umbral_revision": regla["umbral_revision"],
            }

        # Calcular el puntaje usando el motor determinista (DA-09)
        desglose = self.motor_puntaje.calcular(requisitos, dictamenes, reglas)

        return {
            **cambios,
            "puntaje_global": desglose.puntaje_total,
            # Desglose y versión de reglas quedan en el estado para el informe y la bitácora
            "desglose_puntaje": desglose.model_dump(mode="json"),
        }

    def _generar_recomendacion(self, state: AnalisisState) -> dict:
        requisitos = _requisitos(state.get("requisitos_aprobados", []))
        dictamenes = _dictamenes(state.get("dictamenes", []))
        puntaje = state.get("puntaje_global") or 0.0

        # Invocar al Generador de Recomendación con los umbrales de la versión de reglas
        reglas = state.get("reglas_aplicadas") or {}
        resultado = self.recomendador.generar(
            puntaje, requisitos, dictamenes,
            umbral_ofertar=reglas.get("umbral_ofertar"), umbral_revision=reglas.get("umbral_revision"),
        )

        version_reglas = (state.get("desglose_puntaje") or {}).get("version_reglas", "desconocida")
        nota_tecnica = f"Puntaje calculado con reglas versión {version_reglas}."

        return {
            "recomendacion": resultado.categoria,
            # Adjuntamos la justificación redactada por el LLM a la nota técnica del motor
            "justificacion_recomendacion": f"{resultado.justificacion}\n\nNota técnica: {nota_tecnica}",
        }

    def _generar_informe(self, state: AnalisisState) -> dict:
        tarea_id = state.get("tarea_id", "tarea_desconocida")
        # Tabla 18: el informe declara el puntaje y las reglas con que se calculó.
        MaquinaEstados().validar(Estado.GENERANDO_RECOMENDACION, Estado.GENERANDO_INFORME,
                                 puntaje_calculado=state.get("puntaje_global") is not None)
        if self.registro_informes is not None:
            # RN-08: un informe emitido no se modifica; si la etapa se repite, se devuelve el mismo.
            previo = self.registro_informes.obtener(tarea_id)
            if previo is not None:
                return {"informe_path": previo["ruta_pdf"], "huella_informe": previo["huella_sha256"]}
            resultado = self.informe.generar_y_sellar(state)
            if self.almacen_informes is not None:
                # Si la subida falla, la emisión no se registra y la etapa se reintenta.
                for ruta in (resultado["informe_path"], resultado.get("texto_path")):
                    if ruta:
                        self.almacen_informes.guardar(ruta)
            # Informe, huella en la bitácora y tarea Finalizada en una sola transacción (Tabla 19).
            self.registro_informes.emitir(state, resultado, self.auditoria)
            return {"informe_path": resultado["informe_path"], "huella_informe": resultado["huella_sha256"]}

        # 1. Generamos el archivo físico (PDF) y obtenemos su huella (ASR-06)
        resultado = self.informe.generar_y_sellar(state)
        informe_path = resultado["informe_path"]
        huella = resultado["huella_sha256"]
        # 2. Registramos el evento en la bitácora inmutable (RF-042)
        self.auditoria.registrar_huella_informe(tarea_id, informe_path, huella)
        return {"informe_path": informe_path, "huella_informe": huella}
