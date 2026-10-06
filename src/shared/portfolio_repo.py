from sqlalchemy import select
from sqlalchemy.orm import Session
from src.shared.models import Portafolio
from src.worker_analysis.llm_gateway import pasarela_llm

class PortfolioRepository:
    def __init__(self, db: Session):
        self.db = db

    def add_capacity(self, tecnologia: str, categoria: str, descripcion: str):
        """
        Agrega una nueva capacidad al portafolio y genera su vector de embedding.
        """
        # Obtenemos el embedding usando el modelo configurado en la pasarela
        # Asumiendo que la pasarela expone un cliente embeddings
        # Para el MVP lo simulamos, en la práctica usaría OpenAIEmbeddings
        embedding_vector = self._generate_embedding(descripcion)
        
        nuevo_item = Portafolio(
            tecnologia=tecnologia,
            categoria=categoria,
            descripcion=descripcion,
            embedding=embedding_vector
        )
        self.db.add(nuevo_item)
        self.db.commit()
        return nuevo_item

    def search_similar_capacities(self, query: str, limit: int = 3) -> list[str]:
        """
        Busca las capacidades más similares a un requisito usando pgvector L2 distance (<->).
        """
        query_embedding = self._generate_embedding(query)
        
        # Realizar búsqueda por similitud usando pgvector
        # <-> es el operador de distancia euclidiana L2
        stmt = (
            select(Portafolio)
            .where(Portafolio.activo == True)
            .order_by(Portafolio.embedding.l2_distance(query_embedding))
            .limit(limit)
        )
        
        resultados = self.db.execute(stmt).scalars().all()
        return [r.descripcion for r in resultados]

    def _generate_embedding(self, text: str) -> list[float]:
        # TODO: Integrar con langchain_openai.OpenAIEmbeddings a través de la pasarela
        # Retorna un vector mock de longitud 1536
        return [0.0] * 1536
