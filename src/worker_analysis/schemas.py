from pydantic import BaseModel, Field
from typing import List, Optional

# Esquemas de validación estructural (DA-08)

class Requisito(BaseModel):
    id_interno: str = Field(description="Identificador único generado para el requisito")
    categoria: str = Field(description="Categoría del requisito (Técnico, Financiero, Jurídico, Experiencia, Personal)")
    descripcion: str = Field(description="Descripción detallada del requisito exigido en el pliego")
    criterio_evaluacion: str = Field(description="Criterio para determinar si se cumple o no el requisito")
    es_habilitante: bool = Field(description="Indica si el requisito es habilitante (pasa/no pasa)")
    puntaje_maximo: Optional[int] = Field(default=0, description="Puntaje máximo asignable si no es habilitante")

class ListaRequisitos(BaseModel):
    requisitos: List[Requisito] = Field(description="Lista de requisitos extraídos del pliego")

class Dictamen(BaseModel):
    requisito_id: str = Field(description="Identificador del requisito evaluado")
    cumple: bool = Field(description="Evaluación de cumplimiento frente al portafolio")
    evidencia_encontrada: str = Field(description="Evidencia encontrada en el portafolio que justifica el dictamen")
    justificacion: str = Field(description="Explicación detallada de por qué cumple o no cumple")

class ListaDictamenes(BaseModel):
    dictamenes: List[Dictamen] = Field(description="Lista de dictámenes de evaluación de los requisitos")

class Recomendacion(BaseModel):
    justificacion_comercial: str = Field(description="Párrafo justificando la decisión sugerida de participar o no")
