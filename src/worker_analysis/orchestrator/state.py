from typing import TypedDict, List, Optional


class AnalisisState(TypedDict, total=False):
    """
    Estado del análisis para la máquina de estados de LangGraph (DA-03).
    Almacena los datos que fluyen entre los nodos de la ejecución.

    Los requisitos y dictámenes se guardan como diccionarios (model_dump de los
    esquemas de dominio) y no como objetos Pydantic: el checkpointer de Postgres
    los serializa como JSON plano y cualquier proceso (API o worker) puede leerlos.
    """
    tarea_id: str
    licitacion_url: str
    # Texto del pliego aportado por el analista. Datos Abiertos solo expone metadatos.
    contenido_pliego: Optional[str]
    expediente_path: Optional[str]
    # Expediente documental (RF-021, HU-10): lo analizado con su versión y procedencia, y lo que no.
    ficha_recuperada: Optional[bool]
    documentos_analizados: List[dict]
    documentos_no_analizados: List[dict]
    fragmentos_descartados: List[dict]  # Sin referencia de origen (HU-05 CA-04)
    contenido_crudo: Optional[str]
    contenido_saneado: Optional[str]
    fragmentos: List[str]
    requisitos_extraidos: List[dict]  # RequisitoExtraido
    # Lista de requisitos después de la compuerta humana (ASR-12)
    requisitos_aprobados: List[dict]  # RequisitoExtraido
    aprobado_por: Optional[str]
    # Revisión guardada sin aprobar (CU-05 A1, Tabla 45): sobrevive a la caducidad de la sesión.
    requisitos_borrador: Optional[List[dict]]
    borrador_por: Optional[str]
    borrador_en: Optional[str]
    # HU-06 CA-03: lista aprobada de un análisis previo del proceso y lo que cambió desde entonces.
    revision_previa: Optional[dict]
    revision_requisitos: Optional[dict]  # identificador -> {estado, motivo}
    dictamenes: List[dict]  # DictamenRequisito
    puntaje_global: Optional[float]
    desglose_puntaje: Optional[dict]  # DesglosePuntaje
    recomendacion: Optional[str]
    justificacion_recomendacion: Optional[str]
    informe_path: Optional[str]
    huella_informe: Optional[str]  # SHA-256 del PDF emitido (ASR-06)
    version_prompts: Optional[str]  # RNF-027: versión de instrucciones usada
    # Versiones fijadas al crear la tarea (RN-06, RF-033): el resultado es reproducible.
    reglas_version: Optional[int]
    portafolio_version: Optional[int]
    reglas_aplicadas: Optional[dict]  # Pesos y umbrales de esa versión de reglas
    error_msg: Optional[str]
