import asyncio
import os
from typing import TypedDict, Annotated, Sequence, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

from src.shared.database import DATABASE_URL, get_db
from src.shared.portfolio_repo import PortfolioRepository

from src.worker_analysis.agents import (
    guardia_documental,
    segmentador_documental,
    agente_extractor,
    agente_evaluador,
    motor_puntaje,
    generador_recomendacion
)

# 1. Define the state for the Orquestador del flujo de análisis
class AnalysisState(TypedDict):
    licitacion_id: str
    expediente: str
    es_seguro: bool
    fragmentos: list[str]
    requisitos_extraidos: list
    analista_aprobado: bool
    dictamenes: list
    puntaje: int
    categoria_recomendacion: str
    justificacion_recomendacion: str
    informe_path: str
    error: Optional[str]

# 2. Define the workflow nodes
async def recuperar_expediente_node(state: AnalysisState):
    print(f"Recuperando expediente para {state['licitacion_id']} desde SECOP II...")
    # Mock retrieval
    return {"expediente": "Contenido simulado del pliego de condiciones..."}

async def guardia_documental_node(state: AnalysisState):
    print("Ejecutando guardia documental (ASR-10)...")
    es_seguro = guardia_documental(state['expediente'])
    return {"es_seguro": es_seguro}

def verificar_seguridad(state: AnalysisState):
    if state.get("es_seguro"):
        return "segmentar"
    else:
        return "suspender"

async def suspender_node(state: AnalysisState):
    print("Flujo suspendido por sospecha de inyección de prompt.")
    return {"error": "Sospecha de inyección de prompt"}

async def segmentar_node(state: AnalysisState):
    print("Segmentando documento...")
    fragmentos = segmentador_documental(state['expediente'])
    return {"fragmentos": fragmentos}

async def extraer_requisitos_node(state: AnalysisState):
    print("Extrayendo requisitos (Agente Extractor)...")
    lista_reqs = agente_extractor(state['fragmentos'])
    return {"requisitos_extraidos": [r.model_dump() for r in lista_reqs.requisitos]}

# ASR-12: Compuerta de revisión humana
def human_review_node(state: AnalysisState):
    print("Esperando aprobación del analista (el flujo se detiene aquí hasta recibir confirmación)...")
    # In a real LangGraph setup with checkpoints, execution halts here and resumes on external input
    return state

async def evaluar_requisitos_node(state: AnalysisState):
    print("Evaluando requisitos (Agente Evaluador)...")
    
    with get_db() as db:
        repo = PortfolioRepository(db)
        dictamenes = agente_evaluador(state['requisitos_extraidos'], repo)
        
    return {"dictamenes": [d.model_dump() for d in dictamenes.dictamenes]}

async def calcular_puntaje_node(state: AnalysisState):
    print("Calculando puntaje (Motor determinista)...")
    # Reglas mock versionadas
    reglas = {"peso_por_defecto": 20}
    puntaje = motor_puntaje(state['dictamenes'], reglas)
    return {"puntaje": puntaje}

async def recomendar_node(state: AnalysisState):
    print("Generando recomendación comercial...")
    umbrales = {"ofertar": 80, "revision": 50}
    resultado = generador_recomendacion(state['puntaje'], state['dictamenes'], umbrales)
    return {
        "categoria_recomendacion": resultado["categoria"],
        "justificacion_recomendacion": resultado["justificacion"]
    }

async def generar_informe_node(state: AnalysisState):
    print("Generando informe PDF con huella SHA-256 (ASR-06)...")
    return {"informe_path": f"/blob/informe_{state['licitacion_id']}.pdf"}

# 3. Build the graph
workflow = StateGraph(AnalysisState)

workflow.add_node("recuperar", recuperar_expediente_node)
workflow.add_node("guardia", guardia_documental_node)
workflow.add_node("suspender", suspender_node)
workflow.add_node("segmentar", segmentar_node)
workflow.add_node("extraer", extraer_requisitos_node)
workflow.add_node("revision_humana", human_review_node)
workflow.add_node("evaluar", evaluar_requisitos_node)
workflow.add_node("puntuar", calcular_puntaje_node)
workflow.add_node("recomendar", recomendar_node)
workflow.add_node("informe", generar_informe_node)

workflow.set_entry_point("recuperar")
workflow.add_edge("recuperar", "guardia")

# Conditional edge after Guardia Documental
workflow.add_conditional_edges(
    "guardia",
    verificar_seguridad,
    {"segmentar": "segmentar", "suspender": "suspender"}
)

workflow.add_edge("suspender", END)
workflow.add_edge("segmentar", "extraer")
workflow.add_edge("extraer", "revision_humana")

# Compuerta de revisión (Se reanudaría externamente hacia evaluar)
workflow.add_edge("revision_humana", "evaluar") 
workflow.add_edge("evaluar", "puntuar")
workflow.add_edge("puntuar", "recomendar")
workflow.add_edge("recomendar", "informe")
workflow.add_edge("informe", END)

# In production, compile with checkpointer=PostgresSaver(...)
# app = workflow.compile()

async def process_message_from_queue():
    print("Iniciando escucha en Service Bus y conectando a Postgres para Checkpoints...")
    
    # Setup Postgres Checkpointer
    pool = ConnectionPool(conninfo=DATABASE_URL)
    checkpointer = PostgresSaver(pool)
    checkpointer.setup() # Asegura que la tabla de checkpoints exista
    
    app = workflow.compile(checkpointer=checkpointer)
    
    # Mocking a workflow execution
    initial_state = {"licitacion_id": "SECOP-2026-001"}
    print(f"Ejecutando orquestador para {initial_state['licitacion_id']}")
    
    # The config requires a thread_id for checkpointing
    config = {"configurable": {"thread_id": "tarea_SECOP-2026-001"}}
    
    # Run the graph until the human review node (or end if suspended)
    async for event in app.astream(initial_state, config=config):
        for node_name, node_state in event.items():
            print(f"--- Nodo completado: {node_name} ---")
            
    print("Flujo pausado o completado.")
    
    # Example of how to resume after human approval
    # state_to_update = {"analista_aprobado": True}
    # async for event in app.astream(state_to_update, config=config):
    #     ...

if __name__ == "__main__":
    print("Iniciando trabajador de análisis multi-agente...")
    asyncio.run(process_message_from_queue())
