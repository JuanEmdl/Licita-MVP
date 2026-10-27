from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class CategoriaRequisito(str, Enum):
    TECNICO = "tecnico"
    FINANCIERO = "financiero"
    JURIDICO = "juridico"
    EXPERIENCIA = "experiencia"
    PERSONAL = "personal"

# Pesos provisionales por categoría mientras la gerencia comercial aprueba la matriz (ASR-14,
# DT-02). Viven en el dominio para que el motor de puntaje no dependa de la base (FF-04).
PESOS_INICIALES = {
    CategoriaRequisito.TECNICO.value: 40.0,
    CategoriaRequisito.EXPERIENCIA.value: 30.0,
    CategoriaRequisito.FINANCIERO.value: 15.0,
    CategoriaRequisito.JURIDICO.value: 10.0,
    CategoriaRequisito.PERSONAL.value: 5.0,
}

class RequisitoExtraido(BaseModel):
    identificador: str = Field(..., description="Identificador único del requisito extraído del documento.")
    texto: str = Field(..., description="Texto literal o resumido del requisito.")
    categoria: CategoriaRequisito = Field(..., description="Categoría a la que pertenece el requisito.")
    condicion_habilitante_propuesta: bool = Field(..., description="Indica si el requisito es una condición habilitante (True) o puntuable (False).")
    referencia_documental: str = Field(..., description="Referencia a la sección o página del documento original.")

class ListaRequisitos(BaseModel):
    requisitos: List[RequisitoExtraido] = Field(default_factory=list, description="Lista de requisitos extraídos del documento.")

class EstadoDictamen(str, Enum):
    CUMPLE = "Cumple"
    CUMPLE_PARCIALMENTE = "Cumple parcialmente"
    NO_CUMPLE = "No cumple"
    NO_VERIFICABLE = "No verificable"

class DictamenRequisito(BaseModel):
    identificador_requisito: str = Field(..., description="Identificador del requisito evaluado.")
    estado: EstadoDictamen = Field(..., description="Estado de cumplimiento del requisito.")
    evidencia: Optional[str] = Field(None, description="Evidencia extraída del portafolio que soporta el dictamen.")
    justificacion: str = Field(..., description="Justificación detallada del dictamen emitido.")
