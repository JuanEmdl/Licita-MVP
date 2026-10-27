"""
Puertos del núcleo de dominio (Figura 12, DA-02).

El núcleo depende de estas interfaces, que él mismo declara, y los adaptadores las implementan;
nunca al revés. Son protocolos estructurales: un adaptador cumple el puerto si ofrece los
métodos, sin heredar de él, y la prueba de aptitud lo comprueba con isinstance.

| Puerto                    | Adaptador (Figura 12)  | Implementación                                |
|---------------------------|------------------------|-----------------------------------------------|
| PuertoModeloLenguaje      | PasarelaModelos        | llm_gateway.gateway.LLMGateway                |
| PuertoExpediente          | AdaptadorSecop         | adapters.secop.AdaptadorSECOP                 |
| PuertoAlmacenDocumentos   | AdaptadorBlob          | shared.almacen_informes.AlmacenInmutable      |
| PuertoCola                | AdaptadorServiceBus    | api.adapters.queue.PublicadorTrabajos         |
| PuertoRegistroInformes    | RepositorioPostgres    | shared.informes_repo.RegistroInformes         |
| PuertoAuditoria           | RepositorioPostgres    | reports.auditoria.RegistradorAuditoria        |

Los checkpoints del flujo (guardarCheckpoint en la Figura 12) los guarda el checkpointer de
LangGraph (PostgresSaver), que ya es un puerto del propio marco, y las reglas versionadas
(leerReglas) llegan como una función que devuelve la versión pedida.
"""
from typing import Any, Callable, Dict, List, Optional, Protocol, Type, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class PuertoModeloLenguaje(Protocol):
    """Única puerta al proveedor del modelo (DA-07): cuota, anonimización, reintentos y disyuntor."""

    def invocar_estructurado(self, prompt: str, schema: Type[T], sistema: Optional[str] = None) -> T: ...

    def invocar_texto(self, prompt: str, sistema: Optional[str] = None) -> str: ...

    def embeber(self, texto: str) -> List[float]: ...


@runtime_checkable
class PuertoExpediente(Protocol):
    """Ficha del proceso en la fuente (SECOP II) traducida por la capa anticorrupción (ASR-03)."""

    def recuperar_expediente(self, licitacion_id: str) -> Dict[str, Any]: ...


@runtime_checkable
class PuertoAlmacenDocumentos(Protocol):
    """Almacén inmutable de los informes emitidos (DA-06)."""

    def guardar(self, ruta_local: str) -> str: ...

    def leer(self, ruta_local: str) -> bytes: ...


@runtime_checkable
class PuertoCola(Protocol):
    """Publicación de los mensajes de la Tabla 46."""

    def encolar_analisis(self, tarea_id: str, licitacion_url: str, contenido_pliego: Optional[str] = None,
                         reglas_version: Optional[int] = None, portafolio_version: Optional[int] = None) -> None: ...

    def encolar_reanudacion(self, tarea_id: str) -> None: ...

    def encolar_continuacion(self, tarea_id: str) -> None: ...

    def encolar_indexacion(self, portafolio_version: int) -> None: ...


@runtime_checkable
class PuertoRegistroInformes(Protocol):
    """Emisión atómica del informe con su huella y el cierre de la tarea (Tabla 19)."""

    def obtener(self, tarea_id: str) -> Optional[dict]: ...

    def emitir(self, estado: dict, resultado: dict, auditoria: Any) -> dict: ...


@runtime_checkable
class PuertoAuditoria(Protocol):
    """Bitácora de solo anexado con huellas encadenadas (RF-042)."""

    def registrar_evento(self, tarea_id: str, tipo_evento: str, detalles: Dict[str, Any],
                         hash_documento: Optional[str] = None, registrado_por: Optional[str] = None,
                         licitacion_id: Optional[str] = None, db: Any = None) -> None: ...


# Versión de reglas del puntaje por número (RF-033).
ProveedorReglas = Callable[[int], dict]
# Documentos vigentes del expediente de un proceso (RF-021, RF-022).
ProveedorExpediente = Callable[[str], dict]
