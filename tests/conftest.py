import os

# Las pruebas nunca deben leer el .env con credenciales reales (ver src/shared/config).
os.environ["CARGAR_DOTENV"] = "0"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_auditoria_de_rechazos(monkeypatch):
    """Los 403 se auditan en PostgreSQL; las pruebas que lo verifican lo reemplazan por una lista."""
    import src.api.middleware.auth as auth
    monkeypatch.setattr(auth, "auditar_rechazo", lambda *args, **kwargs: None)

from src.shared.schemas.domain import (
    CategoriaRequisito,
    DictamenRequisito,
    EstadoDictamen,
    RequisitoExtraido,
)


def req(identificador: str, categoria: CategoriaRequisito, habilitante: bool = False) -> RequisitoExtraido:
    return RequisitoExtraido(
        identificador=identificador,
        texto=f"Requisito {identificador}",
        categoria=categoria,
        condicion_habilitante_propuesta=habilitante,
        referencia_documental="Sección 1",
    )


def dic(identificador: str, estado: EstadoDictamen) -> DictamenRequisito:
    return DictamenRequisito(identificador_requisito=identificador, estado=estado, justificacion="")
