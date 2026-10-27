import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.shared.config import obtener_configuracion

logger = logging.getLogger(__name__)

# DA-05: Una sola base PostgreSQL con pgvector
# En producción la cadena de conexión llega desde Azure Key Vault como variable de entorno.
DATABASE_URL = obtener_configuracion().db_connection_string

# SQLAlchemy usa el driver psycopg 3 (el mismo que el checkpointer de LangGraph),
# así no hace falta instalar también psycopg2.
_SQLALCHEMY_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# El motor no abre conexiones hasta el primer uso, así que importar este módulo
# no exige que la base esté disponible.
engine = create_engine(
    _SQLALCHEMY_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    # Sin límite, una base caída deja colgada cada solicitud hasta el tiempo de espera del SO.
    connect_args={"connect_timeout": 5},
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

# create_all no altera tablas existentes. Estas sentencias agregan las columnas
# introducidas después de la primera versión sin borrar datos (idempotentes).
_COLUMNAS_NUEVAS = [
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS detalle_error VARCHAR",
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS solicitado_por VARCHAR",
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS aprobado_por VARCHAR",
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS decision_comercial VARCHAR",
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS decision_por VARCHAR",
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS decision_en TIMESTAMP",
    "ALTER TABLE portafolio ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP",
    "ALTER TABLE bitacora_auditoria ADD COLUMN IF NOT EXISTS detalles JSON",
    # Versionado del portafolio y de las reglas (RF-009, RF-010, RF-032, RF-033, RF-036)
    "ALTER TABLE portafolio ADD COLUMN IF NOT EXISTS version_id INTEGER",
    "ALTER TABLE portafolio ADD COLUMN IF NOT EXISTS huella VARCHAR",
    "ALTER TABLE reglas_puntaje ADD COLUMN IF NOT EXISTS estado VARCHAR",
    "ALTER TABLE reglas_puntaje ADD COLUMN IF NOT EXISTS nota TEXT",
    "ALTER TABLE reglas_puntaje ADD COLUMN IF NOT EXISTS confirmado_por VARCHAR",
    "ALTER TABLE reglas_puntaje ADD COLUMN IF NOT EXISTS confirmado_en TIMESTAMP",
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS reglas_version INTEGER",
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS portafolio_version INTEGER",
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS huella_entrada VARCHAR",
    "ALTER TABLE tareas_analisis ADD COLUMN IF NOT EXISTS causa_suspension VARCHAR",
    # La base, no solo el código, impide dos versiones vigentes o dos propuestas abiertas (RN-03).
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_portafolio_version_vigente ON portafolio_versiones (vigente) WHERE vigente",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_regla_vigente ON reglas_puntaje (estado) WHERE estado = 'Vigente'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_regla_propuesta ON reglas_puntaje (estado) WHERE estado = 'Propuesta'",
    # Bitácora de solo anexado (ASR-06, Tabla 19): nadie la edita, borra ni vacía, tampoco desde SQL.
    """CREATE OR REPLACE FUNCTION bitacora_solo_anexado() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'La bitacora de auditoria es de solo anexado (ASR-06)'; END;
       $$ LANGUAGE plpgsql""",
    "CREATE OR REPLACE TRIGGER bitacora_sin_cambios BEFORE UPDATE OR DELETE ON bitacora_auditoria "
    "FOR EACH ROW EXECUTE FUNCTION bitacora_solo_anexado()",
    "CREATE OR REPLACE TRIGGER bitacora_sin_vaciado BEFORE TRUNCATE ON bitacora_auditoria "
    "FOR EACH STATEMENT EXECUTE FUNCTION bitacora_solo_anexado()",
]


# Identificador arbitrario y fijo del bloqueo consultivo que serializa init_db().
_CLAVE_BLOQUEO_ESQUEMA = 4_172_026


def init_db():
    """
    Inicializa los esquemas de la base de datos y habilita la extensión pgvector.
    No borra datos: crea lo que falta y agrega columnas nuevas con IF NOT EXISTS.
    """
    from src.shared.models import Base

    # La API y los trabajadores arrancan a la vez y todos llaman a init_db: el bloqueo
    # consultivo (liberado al terminar la transacción) evita que dos procesos creen la
    # misma tabla al mismo tiempo, lo que PostgreSQL rechaza con UniqueViolation.
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": _CLAVE_BLOQUEO_ESQUEMA})
        # Habilitar extensión pgvector si no existe
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        # Crear todas las tablas definidas en los modelos
        Base.metadata.create_all(bind=conn)
        for sentencia in _COLUMNAS_NUEVAS:
            conn.execute(text(sentencia))

    logger.info("Base de datos y esquemas inicializados correctamente.")


def verificar_conexion() -> bool:
    """True si la base responde. Lo usa /health para reportar el estado real."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning(f"La base de datos no responde: {type(e).__name__}")
        return False
