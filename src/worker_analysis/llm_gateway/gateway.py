import logging
import re
from typing import Callable, List, Optional, Type, TypeVar

import openai
from langchain_core.embeddings import Embeddings
from pydantic import BaseModel
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from src.shared import telemetria
from src.shared.config import Configuracion, obtener_configuracion
from src.worker_analysis.llm_gateway.anonimizador import Anonimizador
from src.worker_analysis.llm_gateway.disyuntor import Disyuntor, ProveedorNoDisponibleError, disyuntor_compartido

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

# Solo se reintentan fallas transitorias del proveedor (429, 5xx, red).
# Un 400/401/404 (p. ej. DeploymentNotFound) no mejora reintentando, y con el
# disyuntor abierto (ProveedorNoDisponibleError) tampoco se insiste.
ERRORES_TRANSITORIOS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)

_politica_reintentos = retry(
    wait=wait_exponential(multiplier=1, min=2, max=15),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(ERRORES_TRANSITORIOS),
    reraise=True,
)

# Familias de razonamiento: rechazan cualquier temperature distinta de la predeterminada (400).
_SIN_TEMPERATURA = re.compile(r"^(gpt-5|o1|o3|o4)", re.IGNORECASE)


def admite_temperatura(deployment: str) -> bool:
    """Por el nombre del deployment; si se llamó distinto al modelo, use LLM_TEMPERATURA vacía."""
    return not _SIN_TEMPERATURA.match(deployment or "")


class ModeloNoDisponibleError(RuntimeError):
    """Error de configuración del proveedor (deployment inexistente, llave inválida). No se reintenta."""


def traducir_error_proveedor(e: Exception, config: Configuracion, deployment: str) -> Exception:
    """Convierte los errores de configuración de Azure OpenAI en mensajes accionables."""
    if isinstance(e, openai.NotFoundError):
        return ModeloNoDisponibleError(
            f"El deployment '{deployment}' no existe en el recurso de Azure OpenAI "
            f"({config.azure_openai_endpoint}). Créelo en Azure AI Foundry (Implementaciones) "
            f"o corrija AZURE_OPENAI_DEPLOYMENT / AZURE_OPENAI_EMBEDDING_DEPLOYMENT en el .env."
        )
    if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ModeloNoDisponibleError(
            "Azure OpenAI rechazó la llave (AZURE_OPENAI_API_KEY) o el endpoint no corresponde al recurso."
        )
    if isinstance(e, openai.BadRequestError):
        mensaje = str(e)
        if "API version not supported" in mensaje:
            return ModeloNoDisponibleError(
                f"Azure no acepta la versión de API '{config.azure_openai_api_version}' en "
                f"{config.azure_openai_endpoint}. Use la raíz del recurso en AZURE_OPENAI_ENDPOINT "
                f"(no el endpoint del proyecto de Foundry) o corrija AZURE_OPENAI_API_VERSION."
            )
        if "temperature" in mensaje:
            return ModeloNoDisponibleError(
                f"El modelo del deployment '{deployment}' no admite el parámetro temperature. "
                f"Deje LLM_TEMPERATURA vacía en el .env."
            )
    return e


class CuotaAgotadaError(Exception):
    """Se alcanzó la cuota de tokens del periodo: no se invoca al proveedor (RF-028, ASR-13)."""


# Nombre anterior, conservado por compatibilidad.
QuotaExceededError = CuotaAgotadaError


class _EmbeddingsDePasarela(Embeddings):
    """Embeddings que pasan por la pasarela: cuota, anonimización, disyuntor y telemetría."""

    def __init__(self, gateway: "LLMGateway"):
        self._gateway = gateway

    def embed_query(self, text: str) -> List[float]:
        return self._gateway.embeber(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]


class LLMGateway:
    """
    Pasarela de modelos de lenguaje (DA-07).
    Punto único hacia el proveedor (FF-03): ningún agente lo invoca por otra vía.
    En cada invocación, en este orden:
      1. Cuota (RF-028, ASR-13): si el periodo está agotado no sale la llamada.
      2. Disyuntor (ASR-07): si el proveedor viene fallando, falla de inmediato.
      3. Anonimización (ASR-05): los datos protegidos salen como marcadores y la
         respuesta se restaura con el mismo mapa.
      4. Reintentos con espera exponencial solo ante fallas transitorias.
      5. Registro del consumo y telemetría por tarea (RF-043), sin contenido.
    """

    def __init__(
        self,
        configuracion: Optional[Configuracion] = None,
        consumo=None,
        disyuntor: Optional[Disyuntor] = None,
        anonimizador: Optional[Anonimizador] = None,
    ):
        self.config = configuracion or obtener_configuracion()
        # Los clientes se crean en el primer uso: así la API puede construir el
        # orquestador (para consultar estados) sin exigir credenciales del modelo.
        self._llm: Optional[AzureChatOpenAI] = None
        self._embeddings: Optional[AzureOpenAIEmbeddings] = None
        self._consumo = consumo
        self._disyuntor = disyuntor
        self.anonimizador = anonimizador or Anonimizador(self.config.anonimizacion_terminos)

    @property
    def consumo(self):
        if self._consumo is None:
            from src.shared.consumo_repo import RepositorioConsumo
            self._consumo = RepositorioConsumo()
        return self._consumo

    @property
    def disyuntor(self) -> Disyuntor:
        if self._disyuntor is None:
            self._disyuntor = disyuntor_compartido()
        return self._disyuntor

    def _validar_configuracion(self) -> None:
        faltantes = [
            nombre for nombre, valor in (
                ("AZURE_OPENAI_ENDPOINT", self.config.azure_openai_endpoint),
                ("AZURE_OPENAI_API_KEY", self.config.azure_openai_api_key),
            ) if not valor
        ]
        if faltantes:
            raise RuntimeError(f"Faltan variables de entorno del modelo: {', '.join(faltantes)}")

    @property
    def llm(self) -> AzureChatOpenAI:
        if self._llm is None:
            self._validar_configuracion()
            opcionales = {}
            if self.config.llm_temperatura is not None and admite_temperatura(self.config.azure_openai_deployment):
                opcionales["temperature"] = self.config.llm_temperatura
            self._llm = AzureChatOpenAI(
                azure_endpoint=self.config.azure_openai_endpoint,
                api_key=self.config.azure_openai_api_key,
                azure_deployment=self.config.azure_openai_deployment,
                api_version=self.config.azure_openai_api_version,
                timeout=self.config.llm_timeout_s,
                max_retries=0, # Deshabilitamos reintentos internos para controlarlos con tenacity
                **opcionales,
            )
        return self._llm

    def obtener_modelo_embeddings(self) -> Embeddings:
        """Embeddings para operaciones vectoriales, controlados por la pasarela."""
        return _EmbeddingsDePasarela(self)

    def _proveedor_embeddings(self) -> AzureOpenAIEmbeddings:
        if self._embeddings is None:
            self._validar_configuracion()
            self._embeddings = AzureOpenAIEmbeddings(
                azure_endpoint=self.config.azure_openai_endpoint,
                api_key=self.config.azure_openai_api_key,
                azure_deployment=self.config.azure_openai_embedding_deployment,
                api_version=self.config.azure_openai_api_version,
                timeout=self.config.llm_timeout_s,
                max_retries=0,
            )
        return self._embeddings

    # --- Controles comunes ---

    def _verificar_cuota(self) -> None:
        """ASR-13: con la cuota del periodo agotada no sale ninguna invocación."""
        if self.consumo.agotada():
            estado = self.consumo.estado()
            raise CuotaAgotadaError(
                f"Cuota de tokens del periodo {estado['periodo']} agotada ({estado['consumido']} de "
                f"{estado['limite']}). El análisis se reanuda cuando el administrador amplíe la cuota "
                "o empiece el periodo siguiente."
            )

    def _invocar(self, operacion: str, deployment: str, llamada: Callable[[], R]) -> R:
        """Cuota, disyuntor, traducción de errores y telemetría alrededor de una llamada al proveedor."""
        self._verificar_cuota()
        self.disyuntor.permitir()
        with telemetria.medir(f"llm {operacion}", operacion=operacion, modelo=deployment):
            try:
                resultado = llamada()
            except ERRORES_TRANSITORIOS as e:
                self.disyuntor.registrar_falla()
                codigo = getattr(e, "status_code", None) or type(e).__name__
                telemetria.errores_proveedor.add(1, telemetria.atributos(operacion=operacion, codigo=str(codigo)))
                telemetria.llamadas_llm.add(1, telemetria.atributos(operacion=operacion, resultado="transitorio"))
                logger.warning(f"Falla transitoria del proveedor en {operacion}: {type(e).__name__}")
                raise
            except Exception as e:
                # El proveedor respondió (400, 401, 404…): no es una caída, el disyuntor no cuenta.
                if isinstance(e, openai.APIStatusError):
                    self.disyuntor.registrar_exito()
                else:
                    self.disyuntor.liberar_prueba()
                telemetria.llamadas_llm.add(1, telemetria.atributos(operacion=operacion, resultado="error"))
                logger.error(f"Error en la invocación al modelo: {type(e).__name__}: {e}")
                traducido = traducir_error_proveedor(e, self.config, deployment)
                if traducido is e:
                    raise
                raise traducido from e
            self.disyuntor.registrar_exito()
            telemetria.llamadas_llm.add(1, telemetria.atributos(operacion=operacion, resultado="ok"))
            return resultado

    def _registrar_consumo(self, operacion: str, entrada: int, salida: int, estimado: bool = False) -> None:
        """RF-028 y telemetría mínima de tokens por llamada (RF-043). No registra contenido."""
        deployment = (self.config.azure_openai_embedding_deployment if operacion == "embeddings"
                      else self.config.azure_openai_deployment)
        self.consumo.registrar(operacion, entrada, salida, modelo=deployment,
                               tarea_id=telemetria.tarea_actual.get(), estimado=estimado)
        for tipo, cantidad in (("entrada", entrada), ("salida", salida)):
            if cantidad:
                telemetria.tokens_consumidos.add(cantidad, telemetria.atributos(
                    tipo=tipo, operacion=operacion, modelo=deployment))
        logger.info(f"LLM {operacion} deployment={deployment} tokens_entrada={entrada} tokens_salida={salida}"
                    + (" (estimados)" if estimado else ""))

    def _registrar_uso_mensaje(self, mensaje, operacion: str) -> None:
        uso = getattr(mensaje, "usage_metadata", None) or {}
        self._registrar_consumo(operacion, uso.get("input_tokens", 0) or 0, uso.get("output_tokens", 0) or 0,
                                estimado=not uso)

    @staticmethod
    def _mensajes(prompt: str, sistema: Optional[str]) -> list:
        """
        Las instrucciones van en el mensaje de sistema y los datos (pliego, requisitos,
        evidencias) en el de usuario: así el contenido no confiable del documento no
        compite con las instrucciones del agente (ASR-10).
        """
        if sistema:
            return [("system", sistema), ("human", prompt)]
        return [("human", prompt)]

    # --- Operaciones ---

    @_politica_reintentos
    def invocar_estructurado(self, prompt: str, schema: Type[T], sistema: Optional[str] = None) -> T:
        """
        Invoca al LLM forzando una salida estructurada validada contra el esquema dado
        (Structured Outputs con JSON Schema estricto). Reintentos solo ante fallas
        transitorias (ASR-07). Si el modelo devuelve algo que no valida, se lanza
        ValueError con la causa: la tarea queda Fallida y visible en /estado.
        """
        operacion = f"estructurado:{schema.__name__}"
        prompt_anonimizado, mapa = self.anonimizador.anonimizar(prompt)
        logger.info(f"Invocando modelo (salida estructurada: {schema.__name__}, "
                    f"{len(mapa)} datos anonimizados).")
        structured_llm = self.llm.with_structured_output(schema, include_raw=True)
        respuesta = self._invocar(operacion, self.config.azure_openai_deployment,
                                  lambda: structured_llm.invoke(self._mensajes(prompt_anonimizado, sistema)))

        self._registrar_uso_mensaje(respuesta.get("raw"), operacion)
        resultado = respuesta.get("parsed")
        if resultado is None:
            causa = respuesta.get("parsing_error")
            rechazo = getattr(respuesta.get("raw"), "additional_kwargs", {}).get("refusal")
            raise ValueError(
                f"El modelo no devolvió un {schema.__name__} válido: "
                f"{Anonimizador.restaurar(str(rechazo or causa or 'respuesta vacía'), mapa)}"
            )
        return Anonimizador.restaurar_modelo(resultado, mapa)

    @_politica_reintentos
    def invocar_texto(self, prompt: str, sistema: Optional[str] = None) -> str:
        """
        Invoca al LLM para obtener una respuesta en texto plano.
        """
        prompt_anonimizado, mapa = self.anonimizador.anonimizar(prompt)
        resultado = self._invocar("texto", self.config.azure_openai_deployment,
                                  lambda: self.llm.invoke(self._mensajes(prompt_anonimizado, sistema)))
        self._registrar_uso_mensaje(resultado, "texto")
        texto = resultado.content if isinstance(resultado.content, str) else str(resultado.content)
        return Anonimizador.restaurar(texto, mapa)

    @_politica_reintentos
    def embeber(self, texto: str) -> List[float]:
        """Vector del texto anonimizado. El proveedor no informa el uso: se estima (≈ 4 caracteres por token)."""
        anonimizado, _ = self.anonimizador.anonimizar(texto)
        vector = self._invocar("embeddings", self.config.azure_openai_embedding_deployment,
                               lambda: self._proveedor_embeddings().embed_query(anonimizado))
        self._registrar_consumo("embeddings", len(anonimizado) // 4 + 1, 0, estimado=True)
        return vector
