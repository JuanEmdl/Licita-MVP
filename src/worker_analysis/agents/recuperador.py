import logging
from typing import Callable, List, Optional

from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


class _EmbeddingsTolerantes(Embeddings):
    """
    Envuelve el modelo de embeddings y lo desactiva tras el primer fallo
    (p. ej. DeploymentNotFound) para no repetir una llamada inútil por cada requisito.
    """

    def __init__(self, fabrica: Callable[[], Embeddings]):
        self._fabrica = fabrica
        self._modelo: Optional[Embeddings] = None
        self.desactivado = False

    def _obtener(self) -> Embeddings:
        if self._modelo is None:
            self._modelo = self._fabrica()
        return self._modelo

    def embed_query(self, text: str) -> List[float]:
        if self.desactivado:
            raise RuntimeError("Embeddings desactivados tras un fallo previo.")
        try:
            return self._obtener().embed_query(text)
        except Exception as e:
            self.desactivado = True
            logger.warning(
                f"Embeddings no disponibles ({type(e).__name__}). Se usará solo búsqueda por texto "
                "completo hasta reiniciar el proceso. Revise AZURE_OPENAI_EMBEDDING_DEPLOYMENT."
            )
            raise

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]


class RecuperadorPortafolio:
    """
    RAG: Recuperador del Portafolio (ASR-04).
    Busca en PostgreSQL (pgvector, con respaldo de texto completo) las capacidades
    de la empresa que sirven como evidencia para un requisito.

    Devuelve una lista de evidencias con su identificador. Una lista vacía significa
    que no hay evidencia registrada: el evaluador la trata como "No verificable".
    """

    def __init__(self, fabrica_embeddings: Optional[Callable[[], Embeddings]] = None, limite: int = 4):
        self.limite = limite
        self._embeddings = _EmbeddingsTolerantes(fabrica_embeddings) if fabrica_embeddings else None

    def buscar_evidencia(self, query: str, portafolio_version: Optional[int] = None) -> List[dict]:
        # Importación diferida: las pruebas unitarias del evaluador no necesitan base de datos.
        from src.shared.database import get_db
        from src.shared.portfolio_repo import PortfolioRepository

        modelo = self._embeddings if (self._embeddings and not self._embeddings.desactivado) else None
        try:
            with get_db() as db:
                evidencias = PortfolioRepository(db, modelo).search_similar_capacities(
                    query, self.limite, version_id=portafolio_version)
        except Exception as e:
            # Una falla de la base no equivale a "sin evidencia": se detiene la tarea
            # (queda Fallida con el motivo) en vez de emitir dictámenes engañosos.
            raise RuntimeError(f"No se pudo consultar el portafolio: {type(e).__name__}") from e
        logger.info(f"Evidencias recuperadas del portafolio: {len(evidencias)}")
        return evidencias
