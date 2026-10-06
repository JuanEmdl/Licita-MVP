from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, Float, ForeignKey, text
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector
from datetime import datetime

Base = declarative_base()

# ------------------------------------------------------------------
# Datos de Negocio
# ------------------------------------------------------------------
class Licitacion(Base):
    __tablename__ = 'licitaciones'
    
    id = Column(String, primary_key=True) # SECOP II ID
    titulo = Column(String)
    entidad = Column(String)
    estado = Column(String)
    fecha_publicacion = Column(DateTime)
    
class TareaAnalisis(Base):
    __tablename__ = 'tareas_analisis'
    
    id = Column(String, primary_key=True)
    licitacion_id = Column(String, ForeignKey('licitaciones.id'))
    estado = Column(String) # Recibida, Segmentando, Esperando revisión, Evaluando, Finalizada, Fallida
    resultado_puntaje = Column(Integer, nullable=True)
    resultado_recomendacion = Column(String, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ------------------------------------------------------------------
# Índice Vectorial (Portafolio de la Fábrica) - (ASR-05, EP-01)
# ------------------------------------------------------------------
class Portafolio(Base):
    __tablename__ = 'portafolio'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tecnologia = Column(String, index=True)
    categoria = Column(String) # Ej: Desarrollo, Experiencia, Certificación
    descripcion = Column(String) # Detalle de la capacidad o caso de éxito
    embedding = Column(Vector(1536)) # OpenAI text-embedding-3-small
    activo = Column(Boolean, default=True)

# ------------------------------------------------------------------
# Reglas y Versionado (DA-09, RF-032, RF-033)
# ------------------------------------------------------------------
class ReglaPuntaje(Base):
    __tablename__ = 'reglas_puntaje'
    
    version = Column(Integer, primary_key=True, autoincrement=True)
    configuracion = Column(JSON) # Ponderaciones y umbrales (ofertar, revision)
    creado_en = Column(DateTime, default=datetime.utcnow)
    creado_por = Column(String)
    activa = Column(Boolean, default=False)

# ------------------------------------------------------------------
# Bitácora de Auditoría (ASR-06, DA-06) - Solo anexado
# ------------------------------------------------------------------
class BitacoraAuditoria(Base):
    __tablename__ = 'bitacora_auditoria'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    licitacion_id = Column(String)
    tarea_id = Column(String)
    accion = Column(String) # Ej: EMISION_INFORME
    hash_documento = Column(String) # Huella SHA-256 del PDF emitido
    hash_previo = Column(String) # Cadena de bloques simple para inmutabilidad
    registrado_por = Column(String) # Usuario o Sistema
    fecha_registro = Column(DateTime, default=datetime.utcnow)

