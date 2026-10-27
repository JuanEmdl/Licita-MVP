"""
Servicio de ejecución del análisis.

Punto único que construye el orquestador con su checkpointer persistente y que
ejecuta, pausa y reanuda tareas. Lo usan el worker (al consumir Service Bus) y la
API (para consultar estados, registrar la aprobación humana y, solo en desarrollo
sin Service Bus, ejecutar el análisis en su propio proceso).
"""
import logging
import threading
from datetime import datetime
from typing import Iterable, List, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver

from src.shared import telemetria
from src.shared.config import obtener_configuracion
from src.shared.schemas.domain import RequisitoExtraido
from src.shared.expediente_repo import RepositorioExpediente
from src.shared.almacen_informes import obtener_almacen
from src.shared.informes_repo import RegistroInformes
from src.shared.tareas_repo import EstadoTarea, RepositorioTareas
from src.worker_analysis.adapters.secop import AdaptadorSECOP
from src.worker_analysis.agents.evaluator import AgenteEvaluador
from src.worker_analysis.agents.extractor import AgenteExtractor
from src.worker_analysis.agents.recomendador import GeneradorRecomendacion
from src.worker_analysis.llm_gateway.gateway import ERRORES_TRANSITORIOS, CuotaAgotadaError, LLMGateway
from src.worker_analysis.llm_gateway.disyuntor import ProveedorNoDisponibleError, disyuntor_compartido
from src.worker_analysis.orchestrator.graph import (
    ETAPAS,
    NODO_COMPUERTA_HUMANA,
    NODO_PREVIO_COMPUERTA,
    OrquestadorAnalisis,
)
from src.worker_analysis.nucleo.maquina_estados import (
    ESTADO_DE_ETAPA,
    Estado,
    MaquinaEstados,
    TransicionProhibidaError,
)
from src.worker_analysis.pipeline.adendas import textos_por_documento
from src.worker_analysis.pipeline.guardia import GuardiaDocumental
from src.worker_analysis.pipeline.segmentador import SegmentadorDocumental
from src.worker_analysis.reports.auditoria import RegistradorAuditoria
from src.worker_analysis.reports.informe import GeneradorInforme
from src.worker_analysis.scoring.motor import MotorPuntaje

logger = logging.getLogger(__name__)

# Mensajes de la cola (Tabla 46). Los nombres anteriores se siguen aceptando por si
# quedan mensajes en la cola publicados por una versión previa.
TIPO_ANALISIS = "analisis.solicitado"
TIPO_REANUDACION = "analisis.reanudar"
TIPO_INDEXAR_PORTAFOLIO = "portafolio.indexar"
# Continúa una tarea suspendida por cuota cuando vuelve a haber cuota (Figura 15: Suspendida → Evaluando).
TIPO_CONTINUAR = "analisis.continuar"
_TIPOS_ANTERIORES = {"ANALISIS_LICITACION": TIPO_ANALISIS, "REANUDAR_ANALISIS": TIPO_REANUDACION}


class TransicionInvalidaError(Exception):
    """La tarea no está en el estado que exige la operación solicitada."""


class TareaNoEncontradaError(Exception):
    pass


class ReintentoPendienteError(Exception):
    """
    El proveedor del modelo no respondió (ASR-07). El trabajo debe volver a la cola: al
    reintentarlo continúa desde la última etapa cerrada, sin repetir las concluidas.
    """


CAUSA_CUOTA = "cuota"
CAUSA_INYECCION = "inyeccion"
_FALLAS_DEL_PROVEEDOR = ERRORES_TRANSITORIOS + (ProveedorNoDisponibleError,)


def espera_antes_de_reintentar(entregas: int, disyuntor=None) -> float:
    """
    Segundos que el trabajador espera antes de devolver a la cola un trabajo que el proveedor no
    atendió (ASR-07). Service Bus reentrega de inmediato: sin esta espera, todas las entregas se
    gastarían en segundos contra el disyuntor abierto (DEF-02, hallado en el simulacro de fallas).
    Se espera lo que le falta al disyuntor y, como mínimo, un tiempo que crece con cada entrega.
    """
    disyuntor = disyuntor or disyuntor_compartido()
    return max(disyuntor.segundos_para_reintentar(), float(min(2 ** max(1, entregas), 60)))


def crear_checkpointer_postgres() -> BaseCheckpointSaver:
    """PostgresSaver síncrono: el grafo se ejecuta con stream() síncrono."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        conninfo=obtener_configuracion().db_connection_string,
        max_size=10,
        # autocommit es obligatorio: setup() crea índices con CREATE INDEX CONCURRENTLY,
        # que falla dentro de una transacción.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()  # Crea las tablas de checkpoints si no existen
    return checkpointer


class ServicioAnalisis:

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver,
        repositorio: Optional[RepositorioTareas] = None,
        orquestador: Optional[OrquestadorAnalisis] = None,
        avisos=None,
    ):
        self.repositorio = repositorio or RepositorioTareas()
        # Avisos al analista de revisión pendiente o suspensión (notificador; opcional en pruebas).
        self.avisos = avisos
        if orquestador is None:
            gateway = LLMGateway()
            orquestador = OrquestadorAnalisis(
                extractor=AgenteExtractor(gateway),
                # El evaluador crea su RecuperadorPortafolio (pgvector + texto completo).
                evaluador=AgenteEvaluador(gateway),
                guardia=GuardiaDocumental(),
                segmentador=SegmentadorDocumental(),
                motor_puntaje=MotorPuntaje(),
                recomendador=GeneradorRecomendacion(gateway),
                informe=GeneradorInforme(),
                auditoria=RegistradorAuditoria(),
                adaptador_secop=AdaptadorSECOP(),
                checkpointer=checkpointer,
                registro_informes=RegistroInformes(),
                almacen_informes=obtener_almacen(),
                proveedor_expediente=RepositorioExpediente().contenido_para_analisis,
            )
        self.grafo = orquestador.graph
        self.maquina = MaquinaEstados()
        self.auditoria = orquestador.auditoria
        self.informe = orquestador.informe
        self.registro_informes = getattr(orquestador, "registro_informes", None)
        self.almacen_informes = getattr(orquestador, "almacen_informes", None)

    def _avisar(self, tarea_id: str, estado: str, motivo: Optional[str] = None) -> None:
        if self.avisos is None:
            return
        tarea = self.repositorio.obtener(tarea_id)
        if tarea is not None:
            self.avisos.avisar(tarea, estado, motivo)

    @staticmethod
    def _config(tarea_id: str) -> dict:
        return {"configurable": {"thread_id": tarea_id}}

    # --- Ejecución ---

    def iniciar_analisis(self, tarea_id: str, licitacion_url: str, contenido_pliego: Optional[str] = None,
                         reglas_version: Optional[int] = None, portafolio_version: Optional[int] = None,
                         por_cola: bool = False) -> None:
        snapshot = self.grafo.get_state(self._config(tarea_id))
        if snapshot.values:
            # Mensaje repetido por la cola (FF-08): se continúa desde el último checkpoint
            # en lugar de empezar de nuevo, o no se hace nada si ya terminó o espera revisión.
            if snapshot.next and snapshot.next != (NODO_COMPUERTA_HUMANA,):
                self._ejecutar(tarea_id, None, EstadoTarea.EN_PROCESO, por_cola)
            else:
                self.sincronizar_estado(tarea_id)
            return
        estado_inicial = {
            "tarea_id": tarea_id,
            "licitacion_url": licitacion_url,
            "contenido_pliego": contenido_pliego,
            # Fijadas al aceptar la solicitud: el análisis termina con ellas (RN-06).
            "reglas_version": reglas_version,
            "portafolio_version": portafolio_version,
        }
        previa = self._revision_previa(tarea_id, licitacion_url)
        if previa is not None:
            estado_inicial["revision_previa"] = previa
        self._ejecutar(tarea_id, estado_inicial, EstadoTarea.EN_PROCESO, por_cola)

    def _revision_previa(self, tarea_id: str, licitacion_url: str) -> Optional[dict]:
        """
        HU-06 CA-03: lista aprobada del último análisis del mismo proceso y el texto de los
        documentos con que se aprobó. Con ella, el análisis nuevo devuelve a revisión solo
        los requisitos que cambió el expediente.
        """
        buscar = getattr(self.repositorio, "ultima_aprobada", None)
        previa = buscar(licitacion_url, excluir=tarea_id) if buscar else None
        if previa is None:
            return None
        valores = self.grafo.get_state(self._config(previa["tarea_id"])).values
        if not valores.get("requisitos_aprobados"):
            return None
        return {
            "tarea_id": previa["tarea_id"],
            "aprobado_por": valores.get("aprobado_por"),
            "requisitos_aprobados": valores["requisitos_aprobados"],
            "documentos": textos_por_documento(valores.get("contenido_saneado") or ""),
        }

    def _estado_actual(self, snapshot) -> Estado:
        """Estado de la Figura 15 en que quedó el grafo según su último checkpoint."""
        valores = snapshot.values
        if not valores:
            return Estado.RECIBIDA
        if valores.get("error_msg"):
            return Estado.SUSPENDIDA
        if not snapshot.next:
            return Estado.FINALIZADA if valores.get("recomendacion") else Estado.FALLIDA
        if snapshot.next == (NODO_COMPUERTA_HUMANA,):
            return Estado.EN_ESPERA_DE_REVISION
        return ESTADO_DE_ETAPA.get(snapshot.next[0], Estado.RECIBIDA)

    def reanudar_analisis(self, tarea_id: str, por_cola: bool = False) -> None:
        snapshot = self.grafo.get_state(self._config(tarea_id))
        razon = self.maquina.razon_prohibicion(self._estado_actual(snapshot), Estado.EVALUANDO,
                                               lista_aprobada=bool(snapshot.values.get("aprobado_por")))
        if razon:
            # Un mensaje repetido o sin aprobación no avanza (FF-08, ASR-12); no es un error de la cola.
            logger.warning(f"Reanudación ignorada para la tarea {tarea_id}: {razon}")
            return
        # None reanuda desde el último checkpoint en lugar de iniciar un hilo nuevo.
        self._ejecutar(tarea_id, None, EstadoTarea.EVALUANDO, por_cola)

    def continuar_suspendida(self, tarea_id: str, por_cola: bool = False) -> None:
        """
        Continúa una tarea suspendida por cuota desde la etapa que no pudo terminar
        (Figura 15). Una suspensión por inyección no se continúa (Tabla 18).
        """
        snapshot = self.grafo.get_state(self._config(tarea_id))
        if not snapshot.values:
            raise TareaNoEncontradaError(tarea_id)
        tarea = self.repositorio.obtener(tarea_id) or {}
        if tarea.get("estado") != EstadoTarea.SUSPENDIDA:
            raise TransicionInvalidaError("Solo se continúa una tarea suspendida por cuota agotada.")
        en_evaluacion = bool(snapshot.values.get("aprobado_por"))
        # Tabla 18: no se sale de Suspendida sin resolver la causa; la cuota la verifica quien encola.
        try:
            self.maquina.validar(Estado.SUSPENDIDA, Estado.EVALUANDO if en_evaluacion else Estado.EXTRAYENDO,
                                 causa_suspension=tarea.get("causa_suspension"), lista_aprobada=en_evaluacion)
        except TransicionProhibidaError as e:
            raise TransicionInvalidaError(str(e)) from e
        if not snapshot.next:
            raise TransicionInvalidaError("La tarea no tiene etapas pendientes.")
        self._ejecutar(tarea_id, None, EstadoTarea.EVALUANDO if en_evaluacion else EstadoTarea.EN_PROCESO, por_cola)

    def _ejecutar(self, tarea_id: str, entrada: Optional[dict], estado_previo: str, por_cola: bool = False) -> None:
        """
        por_cola: lo ejecuta el trabajador a partir de un mensaje. Si el proveedor del
        modelo no responde, se lanza ReintentoPendienteError para que el mensaje vuelva
        a la cola (ASR-07); sin cola (desarrollo) la tarea queda Fallida con el motivo.
        """
        logger.info(f"Ejecutando grafo para la tarea {tarea_id}")
        self.repositorio.actualizar(tarea_id, estado_previo, detalle_error=None, causa_suspension=None)
        with telemetria.con_tarea(tarea_id), \
                telemetria.medir("analisis", telemetria.duracion_tarea, estado_inicial=estado_previo):
            try:
                for evento in self.grafo.stream(entrada, self._config(tarea_id)):
                    logger.info(f"Tarea {tarea_id}: nodo completado {list(evento.keys())[0]}")
                self.sincronizar_estado(tarea_id)
            except CuotaAgotadaError as e:
                # RN-10: la tarea que requiere más inferencia se suspende; su avance queda en el checkpoint.
                logger.warning(f"Tarea {tarea_id} suspendida: {e}")
                telemetria.tareas_suspendidas.add(1, telemetria.atributos(causa=CAUSA_CUOTA))
                self.repositorio.actualizar(tarea_id, EstadoTarea.SUSPENDIDA, detalle_error=str(e),
                                            causa_suspension=CAUSA_CUOTA)
                self._avisar(tarea_id, EstadoTarea.SUSPENDIDA, str(e))
            except _FALLAS_DEL_PROVEEDOR as e:
                motivo = (f"El proveedor del modelo no respondió ({type(e).__name__}). Las etapas cerradas se "
                          "conservan")
                if por_cola:
                    logger.warning(f"Tarea {tarea_id}: {motivo}; el trabajo vuelve a la cola.")
                    self.repositorio.actualizar(tarea_id, estado_previo,
                                                detalle_error=f"{motivo}; se reintentará automáticamente.")
                    raise ReintentoPendienteError(str(e)) from e
                logger.exception(f"Error en el análisis de la tarea {tarea_id}")
                self.repositorio.actualizar(tarea_id, EstadoTarea.FALLIDA, detalle_error=f"{motivo}: {e}")
            except Exception as e:
                # El fallo queda registrado en la tarea para que /estado lo muestre.
                logger.exception(f"Error en el análisis de la tarea {tarea_id}")
                self.repositorio.actualizar(
                    tarea_id, EstadoTarea.FALLIDA, detalle_error=f"{type(e).__name__}: {e}"
                )

    def marcar_fallida_por_reintentos(self, tarea_id: str, entregas: int) -> None:
        """El trabajador agotó las entregas del mensaje: se avisa al analista en el estado de la tarea."""
        self.repositorio.actualizar(
            tarea_id, EstadoTarea.FALLIDA,
            detalle_error=(f"El proveedor del modelo no respondió tras {entregas} intentos; el trabajo pasó a "
                           "la cola de mensajes fallidos. Las etapas cerradas se conservan."),
        )

    def sincronizar_estado(self, tarea_id: str) -> None:
        """Traslada al registro de tareas el punto en que quedó el grafo."""
        snapshot = self.grafo.get_state(self._config(tarea_id))
        valores = snapshot.values
        if valores.get("error_msg"):
            telemetria.tareas_suspendidas.add(1, telemetria.atributos(causa=CAUSA_INYECCION, tarea_id=tarea_id))
            self.repositorio.actualizar(tarea_id, EstadoTarea.SUSPENDIDA, detalle_error=valores["error_msg"],
                                        causa_suspension=CAUSA_INYECCION)
            self._avisar(tarea_id, EstadoTarea.SUSPENDIDA, "Se detectó un posible intento de manipulación en "
                                                          "el contenido del pliego (ASR-10).")
        elif snapshot.next == (NODO_COMPUERTA_HUMANA,):
            self.repositorio.actualizar(tarea_id, EstadoTarea.ESPERANDO_REVISION)
            self._avisar(tarea_id, EstadoTarea.ESPERANDO_REVISION)
        elif not snapshot.next and valores.get("recomendacion"):
            self.repositorio.actualizar(
                tarea_id,
                EstadoTarea.FINALIZADA,
                resultado_puntaje=valores.get("puntaje_global"),
                resultado_recomendacion=valores.get("recomendacion"),
            )

    def procesar_mensaje(self, mensaje: dict) -> None:
        """Lo invoca el trabajador: las fallas del proveedor devuelven el mensaje a la cola."""
        tipo = _TIPOS_ANTERIORES.get(mensaje.get("tipo_tarea"), mensaje.get("tipo_tarea"))
        if tipo == TIPO_INDEXAR_PORTAFOLIO:
            indexar_portafolio(int(mensaje["portafolio_version"]))
        elif tipo == TIPO_ANALISIS:
            self.iniciar_analisis(
                mensaje["tarea_id"], mensaje["licitacion_url"], mensaje.get("contenido_pliego"),
                reglas_version=mensaje.get("reglas_version"),
                portafolio_version=mensaje.get("portafolio_version"),
                por_cola=True,
            )
        elif tipo == TIPO_REANUDACION:
            self.reanudar_analisis(mensaje["tarea_id"], por_cola=True)
        elif tipo == TIPO_CONTINUAR:
            self.continuar_suspendida(mensaje["tarea_id"], por_cola=True)
        else:
            raise ValueError(f"Tipo de mensaje desconocido: {tipo}")

    # --- Compuerta humana (ASR-12) ---

    def _snapshot_en_compuerta(self, tarea_id: str):
        snapshot = self.grafo.get_state(self._config(tarea_id))
        if not snapshot.values:
            raise TareaNoEncontradaError(tarea_id)
        if snapshot.next != (NODO_COMPUERTA_HUMANA,):
            raise TransicionInvalidaError(
                f"La tarea {tarea_id} no está esperando revisión de requisitos."
            )
        return snapshot

    def obtener_requisitos_extraidos(self, tarea_id: str) -> List[dict]:
        return self._snapshot_en_compuerta(tarea_id).values.get("requisitos_extraidos", [])

    def obtener_revision(self, tarea_id: str) -> dict:
        """
        Lista para la pantalla de revisión: el borrador guardado si lo hay (CU-05 A1) o la
        extraída. La extraída se conserva siempre junto a lo corregido (HU-06 CA-01).
        """
        valores = self._snapshot_en_compuerta(tarea_id).values
        extraidos = valores.get("requisitos_extraidos", [])
        borrador = valores.get("requisitos_borrador")
        return {
            "requisitos": borrador if borrador is not None else extraidos,
            "extraidos": extraidos,
            "borrador": ({"guardado_por": valores.get("borrador_por"), "guardado_en": valores.get("borrador_en")}
                         if borrador is not None else None),
            # HU-06 CA-03: qué conserva la aprobación previa y qué vuelve a revisión.
            "revision": valores.get("revision_requisitos") or {},
        }

    def guardar_borrador(self, tarea_id: str, requisitos: Iterable[RequisitoExtraido], usuario: str) -> dict:
        """
        Guarda la revisión sin aprobarla (Tabla 45: 200 borrador guardado). La tarea sigue
        en espera de revisión y el borrador sobrevive a la caducidad de la sesión (CU-05 E1).
        """
        snapshot = self._snapshot_en_compuerta(tarea_id)
        if snapshot.values.get("aprobado_por"):
            raise TransicionInvalidaError(f"La lista de requisitos de la tarea {tarea_id} ya fue aprobada.")
        requisitos = [r.model_dump(mode="json") for r in requisitos]
        ahora = datetime.utcnow().isoformat()
        self.grafo.update_state(
            self._config(tarea_id),
            {"requisitos_borrador": requisitos, "borrador_por": usuario, "borrador_en": ahora},
            as_node=NODO_PREVIO_COMPUERTA,
        )
        return {"total": len(requisitos), "guardado_por": usuario, "guardado_en": ahora}

    def progreso(self, tarea_id: str) -> dict:
        """Etapa en curso y etapas cerradas según el último checkpoint (Tabla 45, GET /analisis/{id})."""
        snapshot = self.grafo.get_state(self._config(tarea_id))
        valores = snapshot.values
        if not valores:
            return {"etapa_actual": None, "etapas_cerradas": []}
        if valores.get("error_msg"):
            # La guardia desvió el flujo a «suspendida» después de sanear (ASR-10).
            return {"etapa_actual": "suspendida", "etapas_cerradas": list(ETAPAS[:ETAPAS.index("saneando") + 1])}
        if not snapshot.next:
            return {"etapa_actual": None, "etapas_cerradas": list(ETAPAS)}
        siguiente = snapshot.next[0]
        cerradas = list(ETAPAS[:ETAPAS.index(siguiente)]) if siguiente in ETAPAS else []
        if siguiente == NODO_COMPUERTA_HUMANA and not valores.get("aprobado_por"):
            siguiente = "esperando_revision"
        return {"etapa_actual": siguiente, "etapas_cerradas": cerradas}

    def registrar_aprobacion(self, tarea_id: str, requisitos: Iterable[RequisitoExtraido], usuario: str) -> None:
        """
        Sella en el checkpoint la lista revisada por el analista. El grafo sigue
        detenido; la reanudación la hace el worker (o la API en desarrollo).
        """
        snapshot = self._snapshot_en_compuerta(tarea_id)
        if snapshot.values.get("aprobado_por"):
            # La evaluación pudo fallar después de aprobar (cuota, proveedor): la lista ya está sellada.
            raise TransicionInvalidaError(f"La lista de requisitos de la tarea {tarea_id} ya fue aprobada.")
        requisitos = list(requisitos)
        extraidos = {r.get("identificador") for r in snapshot.values.get("requisitos_extraidos", [])}
        aprobados = {r.identificador for r in requisitos}
        # RF-007: la aprobación humana es un evento crítico. Se registra antes de
        # sellarla; si la bitácora no lo acepta, la aprobación no se confirma.
        self.auditoria.registrar_evento(
            tarea_id,
            "REQUISITOS_APROBADOS",
            {
                "total_aprobados": len(aprobados),
                "agregados": sorted(aprobados - extraidos),
                "eliminados": sorted(extraidos - aprobados),
            },
            registrado_por=usuario,
        )
        self.grafo.update_state(
            self._config(tarea_id),
            {
                "requisitos_aprobados": [r.model_dump(mode="json") for r in requisitos],
                "aprobado_por": usuario,
            },
            as_node=NODO_PREVIO_COMPUERTA,
        )
        self.repositorio.actualizar(tarea_id, EstadoTarea.EVALUANDO, aprobado_por=usuario)

    def obtener_resultado(self, tarea_id: str) -> dict:
        snapshot = self.grafo.get_state(self._config(tarea_id))
        valores = snapshot.values
        if not valores:
            raise TareaNoEncontradaError(tarea_id)
        if snapshot.next or not valores.get("recomendacion"):
            raise TransicionInvalidaError(f"La tarea {tarea_id} aún no tiene resultado.")
        return {
            "puntaje": valores.get("puntaje_global"),
            "desglose": valores.get("desglose_puntaje"),
            "recomendacion": valores.get("recomendacion"),
            "justificacion": valores.get("justificacion_recomendacion"),
            "dictamenes": valores.get("dictamenes", []),
            "requisitos_aprobados": valores.get("requisitos_aprobados", []),
            "aprobado_por": valores.get("aprobado_por"),
            "informe_path": valores.get("informe_path"),
            "version_prompts": valores.get("version_prompts"),
            "reglas_version": valores.get("reglas_version"),
            "reglas": valores.get("reglas_aplicadas"),
            "portafolio_version": valores.get("portafolio_version"),
            "huella_informe": valores.get("huella_informe"),
        }

    def _informe(self, tarea_id: str) -> dict:
        """Ruta y huella del informe emitido. Requiere que la tarea haya finalizado."""
        resultado = self.obtener_resultado(tarea_id)
        registrado = self.registro_informes.obtener(tarea_id) if self.registro_informes else None
        if registrado:
            return registrado
        # Análisis emitidos antes del informe en PDF: solo existe la versión en texto.
        ruta = resultado.get("informe_path") or self.informe.ruta_informe(tarea_id)
        return {"ruta_pdf": ruta if ruta.endswith(".pdf") else None,
                "ruta_texto": ruta if ruta.endswith(".txt") else self.informe.ruta_texto(tarea_id),
                "huella_sha256": resultado.get("huella_informe"), "emitido_en": None}

    def _leer(self, ruta: Optional[str], binario: bool):
        """Del volumen INFORMES_DIR o, si no está en este proceso, del almacén inmutable (DA-06)."""
        import os

        if ruta and os.path.exists(ruta):
            with open(ruta, "rb") as f:
                datos = f.read()
        elif ruta and self.almacen_informes is not None:
            datos = self.almacen_informes.leer(ruta)
        else:
            raise FileNotFoundError(
                "El informe no está en el almacenamiento de este proceso. Con Service Bus, la API y "
                "el worker deben compartir el volumen INFORMES_DIR (ver docker-compose.yml) o el "
                "almacén inmutable ALMACEN_INFORMES_URL."
            )
        return datos if binario else datos.decode("utf-8")

    def obtener_informe_pdf(self, tarea_id: str) -> tuple:
        """(bytes del PDF sellado, huella registrada) (RF-037)."""
        informe = self._informe(tarea_id)
        if not informe.get("ruta_pdf"):
            raise FileNotFoundError("Este análisis se emitió antes del informe en PDF: consulte la versión en texto.")
        return self._leer(informe["ruta_pdf"], binario=True), informe.get("huella_sha256")

    def obtener_informe(self, tarea_id: str) -> str:
        """Vista previa en texto del informe emitido."""
        return self._leer(self._informe(tarea_id).get("ruta_texto"), binario=False)

    def verificar_informe(self, tarea_id: str) -> dict:
        """
        ASR-06: recalcula la huella del PDF guardado y la compara con la que quedó en la
        bitácora al emitirlo. Cualquier alteración del archivo se detecta.
        """
        informe = self._informe(tarea_id)
        if not informe.get("ruta_pdf"):
            raise FileNotFoundError("Este análisis no tiene informe en PDF.")
        import hashlib
        # La huella se recalcula sobre lo que se sirve, venga del volumen o del almacén inmutable.
        actual = hashlib.sha256(self._leer(informe["ruta_pdf"], binario=True)).hexdigest()
        registrada = informe.get("huella_sha256")
        return {"tarea_id": tarea_id, "huella_registrada": registrada, "huella_actual": actual,
                "coincide": actual == registrada, "emitido_en": informe.get("emitido_en")}


def indexar_portafolio(portafolio_version: int) -> int:
    """
    Vectoriza las capacidades nuevas o modificadas de una versión del portafolio (RF-010).
    La invoca el trabajador al recibir portafolio.indexar, o la API sin Service Bus.
    """
    from src.shared.portfolio_repo import RepositorioVersionesPortafolio

    modelo = LLMGateway().obtener_modelo_embeddings() if obtener_configuracion().llm_configurado else None
    return RepositorioVersionesPortafolio().indexar(portafolio_version, modelo)


_servicio: Optional[ServicioAnalisis] = None
_candado = threading.Lock()


def obtener_servicio() -> ServicioAnalisis:
    """Instancia compartida por proceso: un solo pool de conexiones al checkpointer."""
    global _servicio
    with _candado:
        if _servicio is None:
            from src.worker_vigilance.notificador import AvisosAnalisis
            _servicio = ServicioAnalisis(checkpointer=crear_checkpointer_postgres(), avisos=AvisosAnalisis())
        return _servicio
