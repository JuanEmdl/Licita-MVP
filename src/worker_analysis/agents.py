from src.worker_analysis.llm_gateway import pasarela_llm
from src.worker_analysis.schemas import ListaRequisitos, ListaDictamenes, Recomendacion

# 1. Guardia Documental (ASR-10, DA-08)
def guardia_documental(contenido_pliego: str) -> bool:
    """
    Analiza el contenido del pliego buscando posibles inyecciones de prompts
    o instrucciones maliciosas antes de pasarlo al modelo.
    """
    # ASR-10: El contenido se trata como no confiable
    # En un escenario real, esto puede usar heurísticas o un modelo más rápido clasificador
    suspicious_patterns = ["ignora tus instrucciones", "system prompt", "forget all previous"]
    for pattern in suspicious_patterns:
        if pattern.lower() in contenido_pliego.lower():
            return False # Falló la validación
    return True

# 2. Segmentador Documental
def segmentador_documental(contenido: str) -> list[str]:
    """Divide pliegos extensos en fragmentos manejables conservando el contexto."""
    # Placeholder para la lógica de fragmentación
    return [contenido[i:i+4000] for i in range(0, len(contenido), 4000)]

# 3. Agente Extractor (DA-08)
def agente_extractor(fragmentos: list[str]) -> ListaRequisitos:
    """Extrae la lista estructurada de requisitos del pliego."""
    prompt = f"Extrae los requisitos técnicos, financieros y de experiencia del siguiente texto del pliego: {fragmentos}"
    # Se usa la pasarela con validación estructural
    resultado = pasarela_llm.invoke_structured(prompt, ListaRequisitos)
    return resultado

# 4. Agente Evaluador (DA-08)
def agente_evaluador(requisitos_aprobados: list, portfolio_repo) -> ListaDictamenes:
    """Evalúa los requisitos contra las evidencias recuperadas (RAG) usando pgvector."""
    dictamenes_totales = []
    
    # Evaluar requisito por requisito para mejorar precisión y evitar límite de contexto
    for req in requisitos_aprobados:
        desc_req = req.get("descripcion", "")
        # RAG: Búsqueda vectorial
        evidencias = portfolio_repo.search_similar_capacities(desc_req, limit=3)
        
        prompt = f"""
        Evalúa el siguiente requisito de licitación contra el portafolio de la fábrica.
        Requisito: {desc_req}
        Portafolio recuperado: {evidencias}
        
        Genera un dictamen estructurado indicando si cumple, la evidencia y la justificación.
        """
        resultado = pasarela_llm.invoke_structured(prompt, Dictamen)
        # Asignar el id_interno al dictamen para mantener la trazabilidad
        resultado.requisito_id = req.get("id_interno", "")
        dictamenes_totales.append(resultado)
        
    return ListaDictamenes(dictamenes=dictamenes_totales)

# 5. Motor de Puntaje (DA-09 determinista)
def motor_puntaje(dictamenes: list, reglas_versionadas: dict) -> int:
    """
    Calcula el puntaje de 0 a 100 de forma puramente determinista 
    basado en los dictámenes y las ponderaciones configuradas.
    """
    puntaje = 0
    for dictamen in dictamenes:
        if dictamen.get('cumple', False):
            # Lógica simple: sumar el peso del requisito
            # En realidad, cruzaría contra el peso específico del requisito en `reglas_versionadas`
            puntaje += reglas_versionadas.get("peso_por_defecto", 10)
    
    return min(puntaje, 100)

# 6. Generador de Recomendación (DA-09 determinista + LLM para redactar)
def generador_recomendacion(puntaje: int, dictamenes: list, umbrales: dict) -> dict:
    """
    Determina la categoría (Ofertar, No ofertar, Solicitar revisión) por reglas,
    y delega al modelo solo la redacción del texto de justificación.
    """
    # Categoría determinista
    categoria = "No ofertar"
    if puntaje >= umbrales.get("ofertar", 80):
        categoria = "Ofertar"
    elif puntaje >= umbrales.get("revision", 60):
        categoria = "Solicitar revisión"
        
    # El modelo solo redacta la justificación
    prompt = f"""
    Redacta un párrafo ejecutivo justificando por qué la recomendación comercial es '{categoria}'.
    El puntaje obtenido fue {puntaje}/100.
    Resumen de dictámenes: {dictamenes}
    """
    redaccion = pasarela_llm.invoke_structured(prompt, Recomendacion)
    
    return {
        "categoria": categoria,
        "justificacion": redaccion.justificacion_comercial
    }
