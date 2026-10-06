import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

# DA-05: Una sola base PostgreSQL con pgvector
# Configuración segura: en producción se usaría Azure Key Vault para esta cadena de conexión
DATABASE_URL = os.getenv(
    "DB_CONNECTION_STRING", 
    "postgresql://user:password@localhost:5432/licitaciones"
)

# Motor de SQLAlchemy
engine = create_engine(
    DATABASE_URL,
    pool_size=10, 
    max_overflow=20,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db():
    """
    Proporciona una sesión transaccional para operaciones en la base de datos.
    Asegura que la sesión se cierre apropiadamente.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    """
    Inicializa los esquemas de la base de datos y habilita la extensión pgvector.
    """
    from src.shared.models import Base
    
    # Habilitar extensión pgvector si no existe
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()

    # Crear todas las tablas definidas en los modelos
    Base.metadata.create_all(bind=engine)
    print("Base de datos y esquemas inicializados correctamente.")
