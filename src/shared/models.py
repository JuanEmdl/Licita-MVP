from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, Float, ForeignKey, Text, UniqueConstraint
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
    estado = Column(String) # Recibida, En proceso, Esperando revisión, Evaluando, Finalizada, Suspendida, Fallida
    detalle_error = Column(String, nullable=True) # Motivo de la falla o suspensión, visible para el usuario
    solicitado_por = Column(String, nullable=True)
    aprobado_por = Column(String, nullable=True) # Analista que cerró la compuerta humana (ASR-12)
    resultado_puntaje = Column(Float, nullable=True)
    resultado_recomendacion = Column(String, nullable=True)
    # Versiones vigentes al aceptar la solicitud (RN-06, RF-033): el análisis termina con
    # ellas aunque cambien mientras corre, y el informe las declara.
    reglas_version = Column(Integer, nullable=True)
    portafolio_version = Column(Integer, nullable=True)
    # Huella del proceso y del pliego aportado: identifica un análisis reutilizable (RF-036, RN-09).
    huella_entrada = Column(String, nullable=True, index=True)
    # Por qué está Suspendida: "inyeccion" (no se reanuda) o "cuota" (se reanuda con cuota disponible).
    causa_suspension = Column(String, nullable=True)
    # Última decisión comercial registrada (RF-039); el historial está en decisiones_comerciales.
    decision_comercial = Column(String, nullable=True)
    decision_por = Column(String, nullable=True)
    decision_en = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ------------------------------------------------------------------
# Decisión comercial humana (RF-038, RF-039)
# ------------------------------------------------------------------
class DecisionComercial(Base):
    __tablename__ = 'decisiones_comerciales'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tarea_id = Column(String, ForeignKey('tareas_analisis.id'), nullable=False, index=True)
    decision = Column(String, nullable=False) # Continuar, Descartar, Solicitar información
    justificacion = Column(Text, nullable=False)
    # Lo que sugería el sistema en el momento de decidir, para saber si la persona se apartó.
    recomendacion_sistema = Column(String, nullable=True)
    puntaje = Column(Float, nullable=True)
    coincide_con_sugerencia = Column(Boolean, nullable=True)
    registrado_por = Column(String, nullable=False)
    registrado_en = Column(DateTime, default=datetime.utcnow, nullable=False)

# ------------------------------------------------------------------
# Índice Vectorial (Portafolio de la Fábrica) - (ASR-05, EP-01)
# ------------------------------------------------------------------
class PortafolioVersion(Base):
    """
    Versión publicada del portafolio (RF-008, RF-009, RN-03). Cada versión es una
    instantánea completa: sus capacidades no se modifican después de publicarla.
    Solo una está vigente; las anteriores quedan como histórico consultable.
    """
    __tablename__ = 'portafolio_versiones'

    id = Column(Integer, primary_key=True, autoincrement=True)  # Número de versión
    vigente = Column(Boolean, default=False, nullable=False)
    descripcion_cambio = Column(String, nullable=True)
    creada_por = Column(String, nullable=False)
    creada_en = Column(DateTime, default=datetime.utcnow, nullable=False)


class Portafolio(Base):
    __tablename__ = 'portafolio'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(Integer, ForeignKey('portafolio_versiones.id'), nullable=True, index=True)
    # SHA-256 de tecnología, categoría y descripción: una capacidad sin cambios entre
    # versiones conserva su vector y no se vuelve a indexar (RF-010).
    tecnologia = Column(String, index=True)
    categoria = Column(String) # Ej: Desarrollo, Experiencia, Certificación
    descripcion = Column(Text) # Detalle de la capacidad o caso de éxito
    # text-embedding-3-small produce 1536 dimensiones. NULL si se registró sin modelo
    # de embeddings: entonces solo participa en la búsqueda por texto completo.
    embedding = Column(Vector(1536), nullable=True)
    huella = Column(String, nullable=True, index=True)
    # True solo para las capacidades de la versión vigente.
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

# ------------------------------------------------------------------
# Reglas y Versionado (DA-09, RF-032, RF-033)
# ------------------------------------------------------------------
class ReglaPuntaje(Base):
    """
    Versión de las reglas del puntaje (RF-032, RF-033, DA-14). Publicarla exige doble
    control: el administrador la propone y la gerencia comercial la confirma.
    Estados: Propuesta → Vigente → Histórica, o Propuesta → Rechazada.
    """
    __tablename__ = 'reglas_puntaje'
    
    version = Column(Integer, primary_key=True, autoincrement=True)
    configuracion = Column(JSON) # {"pesos": {categoria: %}, "umbral_ofertar": n, "umbral_revision": n}
    estado = Column(String, nullable=True)
    nota = Column(Text, nullable=True)  # Motivo de la propuesta o del rechazo
    creado_en = Column(DateTime, default=datetime.utcnow)
    creado_por = Column(String)
    confirmado_por = Column(String, nullable=True)
    confirmado_en = Column(DateTime, nullable=True)
    activa = Column(Boolean, default=False)  # Igual a estado == "Vigente"; se conserva por compatibilidad

# ------------------------------------------------------------------
# Identidad: usuarios, roles y sesiones (RF-001 a RF-007, RNF-010)
# ------------------------------------------------------------------
class Usuario(Base):
    __tablename__ = 'usuarios'

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    nombre = Column(String, nullable=False)
    rol = Column(String, nullable=False) # Ver src/shared/roles.py
    password_hash = Column(String, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ultimo_acceso = Column(DateTime, nullable=True)


class Sesion(Base):
    __tablename__ = 'sesiones'

    id = Column(String, primary_key=True) # jti del token de sesión
    usuario_id = Column(Integer, ForeignKey('usuarios.id'), nullable=False, index=True)
    creada_en = Column(DateTime, default=datetime.utcnow)
    ultimo_uso = Column(DateTime, default=datetime.utcnow)
    expira_en = Column(DateTime, nullable=False) # Vigencia máxima absoluta
    cerrada_en = Column(DateTime, nullable=True)
    motivo_cierre = Column(String, nullable=True) # cierre_usuario, inactividad, usuario_deshabilitado...


# ------------------------------------------------------------------
# Vigilancia: oportunidades detectadas en SECOP II
# ------------------------------------------------------------------
class AlertaOportunidad(Base):
    __tablename__ = 'alertas_oportunidad'

    id_proceso = Column(String, primary_key=True) # ID del proceso en SECOP II
    referencia = Column(String, nullable=True)
    entidad = Column(String, nullable=True)
    objeto = Column(Text, nullable=True)
    modalidad = Column(String, nullable=True)
    precio_base = Column(Float, nullable=True)
    departamento = Column(String, nullable=True)
    fase = Column(String, nullable=True)
    fecha_publicacion = Column(DateTime, nullable=True)
    url_proceso = Column(String, nullable=True)
    afinidad = Column(Float, default=0.0)
    coincidencias = Column(JSON, nullable=True) # Términos del portafolio que coincidieron
    revision_modelo = Column(String, nullable=True) # Opinión del modelo, si estaba disponible
    estado = Column(String, default='Nueva') # Nueva, Descartada, En análisis
    tarea_id = Column(String, nullable=True)
    detectada_en = Column(DateTime, default=datetime.utcnow)
    actualizada_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ------------------------------------------------------------------
# Monitoreo de oportunidades (RF-011 a RF-023)
# ------------------------------------------------------------------
class Oportunidad(Base):
    """Proceso sincronizado desde SECOP II: uno por identificador de origen, sin duplicados (RF-012)."""
    __tablename__ = 'oportunidades'

    id_proceso = Column(String, primary_key=True) # Identificador de origen en SECOP II (CO1.REQ…)
    fuente = Column(String, nullable=False) # Conjunto de Datos Abiertos del que proviene el registro
    id_portafolio = Column(String, nullable=True, index=True) # Agrupa los documentos del proceso (CO1.BDOS…)
    referencia = Column(String, nullable=True)
    entidad = Column(String, nullable=True)
    nit_entidad = Column(String, nullable=True)
    nombre = Column(Text, nullable=True)
    objeto = Column(Text, nullable=True)
    modalidad = Column(String, nullable=True)
    precio_base = Column(Float, nullable=True) # Cuantía (COP)
    departamento = Column(String, nullable=True)
    ciudad = Column(String, nullable=True)
    fase = Column(String, nullable=True)
    estado = Column(String, nullable=True)
    fecha_publicacion = Column(DateTime, nullable=True)
    fecha_cierre = Column(DateTime, nullable=True) # Recepción de ofertas, si la fuente la publica
    url_proceso = Column(String, nullable=True)
    actualizado_en_fuente = Column(DateTime, nullable=True) # Última publicación según SECOP II
    sincronizada_en = Column(DateTime, nullable=True) # Última actualización exitosa (RF-012)
    huella = Column(String, nullable=True) # Huella de los campos vigilados (RF-019)
    texto_busqueda = Column(Text, nullable=True) # Nombre y objeto normalizados para la búsqueda (RF-013)
    origen_registro = Column(String, nullable=False, default='Sincronización') # o "Radicación manual"
    registrada_por = Column(String, nullable=True)
    responsable = Column(String, nullable=True) # Analista a cargo (Tabla 61: carga manual de documentos)
    creada_en = Column(DateTime, default=datetime.utcnow)


class SeguimientoProceso(Base):
    """Un usuario sigue un proceso para recibir sus novedades (RF-018)."""
    __tablename__ = 'seguimientos_proceso'
    __table_args__ = (UniqueConstraint('id_proceso', 'usuario', name='uq_seguimiento_usuario'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    id_proceso = Column(String, ForeignKey('oportunidades.id_proceso'), nullable=False, index=True)
    usuario = Column(String, nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    # Las novedades posteriores a esta fecha son las que el usuario aún no ha revisado.
    revisado_en = Column(DateTime, default=datetime.utcnow)


class NovedadProceso(Base):
    """Cambio publicado sobre un proceso seguido: documentos, requisitos, fechas o estado (RF-019)."""
    __tablename__ = 'novedades_proceso'

    id = Column(Integer, primary_key=True, autoincrement=True)
    id_proceso = Column(String, ForeignKey('oportunidades.id_proceso'), nullable=False, index=True)
    tipo = Column(String, nullable=False) # Documentos, Requisitos, Fechas, Estado
    campo = Column(String, nullable=False)
    antes = Column(Text, nullable=True)
    despues = Column(Text, nullable=True)
    # Análisis cuyo resultado puede quedar desactualizado por el cambio (HU-06 CA-03).
    tarea_afectada = Column(String, nullable=True)
    detectada_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    notificada_en = Column(DateTime, nullable=True) # La llena el notificador (RF-020)


class DocumentoExpediente(Base):
    """Documento del expediente de un proceso, con su procedencia y su versión (RF-011, RF-021, RF-022)."""
    __tablename__ = 'documentos_expediente'

    id = Column(Integer, primary_key=True, autoincrement=True)
    id_proceso = Column(String, ForeignKey('oportunidades.id_proceso'), nullable=False, index=True)
    nombre = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    procedencia = Column(String, nullable=False) # SECOP II (Datos Abiertos) o carga manual
    id_documento_fuente = Column(String, nullable=True) # Identificador del archivo en SECOP II
    url_fuente = Column(String, nullable=True)
    extension = Column(String, nullable=True)
    tamano_bytes = Column(Integer, nullable=True)
    publicado_en = Column(DateTime, nullable=True) # Fecha de carga en SECOP II
    obtenido_en = Column(DateTime, nullable=True) # Cuándo lo obtuvo el sistema
    estado = Column(String, nullable=False) # Disponible, Faltante, Ilegible
    motivo = Column(Text, nullable=True) # Por qué falta o no se puede leer
    ruta_archivo = Column(String, nullable=True)
    huella_sha256 = Column(String, nullable=True)
    paginas = Column(JSON, nullable=True) # Texto por página, para conservar la página de procedencia (RF-023)
    cargado_por = Column(String, nullable=True)
    # Una carga nueva del mismo documento deja la anterior como histórico.
    vigente = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)


class PerfilBusqueda(Base):
    """Criterios que definen qué oportunidades le interesan a un usuario (RF-015)."""
    __tablename__ = 'perfiles_busqueda'

    id = Column(Integer, primary_key=True, autoincrement=True)
    propietario = Column(String, nullable=False, index=True) # Tabla 61: cada quien ve solo los suyos
    nombre = Column(String, nullable=False)
    palabras_clave = Column(JSON, nullable=False)
    entidades = Column(JSON, nullable=True)
    departamentos = Column(JSON, nullable=True)
    modalidades = Column(JSON, nullable=True)
    cuantia_min = Column(Float, nullable=True)
    cuantia_max = Column(Float, nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CoincidenciaPerfil(Base):
    """Proceso que coincidió con un perfil activo; una sola vez por perfil (RF-017, HU-04 CA-02)."""
    __tablename__ = 'coincidencias_perfil'
    __table_args__ = (UniqueConstraint('perfil_id', 'id_proceso', name='uq_coincidencia_perfil'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    perfil_id = Column(Integer, ForeignKey('perfiles_busqueda.id', ondelete='CASCADE'), nullable=False, index=True)
    id_proceso = Column(String, ForeignKey('oportunidades.id_proceso'), nullable=False)
    detectada_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    notificada_en = Column(DateTime, nullable=True)


class Carpeta(Base):
    """Carpeta con que un usuario organiza sus oportunidades (RF-040); Tabla 61: solo las propias."""
    __tablename__ = 'carpetas'
    __table_args__ = (UniqueConstraint('propietario', 'nombre', name='uq_carpeta_nombre'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    propietario = Column(String, nullable=False, index=True)
    nombre = Column(String, nullable=False)
    creada_en = Column(DateTime, default=datetime.utcnow)


class CarpetaOportunidad(Base):
    """Una oportunidad puede estar en varias carpetas del mismo usuario."""
    __tablename__ = 'carpetas_oportunidades'
    __table_args__ = (UniqueConstraint('carpeta_id', 'id_proceso', name='uq_carpeta_oportunidad'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    carpeta_id = Column(Integer, ForeignKey('carpetas.id', ondelete='CASCADE'), nullable=False, index=True)
    id_proceso = Column(String, ForeignKey('oportunidades.id_proceso'), nullable=False)
    agregada_en = Column(DateTime, default=datetime.utcnow)


class NotaOportunidad(Base):
    """Nota de trabajo sobre una oportunidad, con su autor y su fecha (RF-040)."""
    __tablename__ = 'notas_oportunidad'

    id = Column(Integer, primary_key=True, autoincrement=True)
    id_proceso = Column(String, ForeignKey('oportunidades.id_proceso'), nullable=False, index=True)
    autor = Column(String, nullable=False)
    texto = Column(Text, nullable=False)
    creada_en = Column(DateTime, default=datetime.utcnow, nullable=False)


class PreferenciaNotificacion(Base):
    """Canal y frecuencia con que un usuario recibe sus notificaciones (RF-016)."""
    __tablename__ = 'preferencias_notificacion'

    usuario = Column(String, primary_key=True) # Correo institucional
    canal = Column(String, nullable=False) # "Aplicación" o "Correo y aplicación"
    frecuencia = Column(String, nullable=False) # "Inmediata" o "Resumen diario"
    ultimo_resumen_en = Column(DateTime, nullable=True)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Notificacion(Base):
    """
    Aviso para un usuario (RF-017, RF-020). Queda en la aplicación aunque el correo falle
    (Tabla 16), y la clave impide avisar dos veces lo mismo al mismo destinatario (HU-04 CA-02).
    """
    __tablename__ = 'notificaciones'
    __table_args__ = (UniqueConstraint('destinatario', 'clave', name='uq_notificacion_destinatario'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    destinatario = Column(String, nullable=False, index=True)
    tipo = Column(String, nullable=False) # Oportunidad, Novedad, Revisión pendiente, Análisis suspendido
    clave = Column(String, nullable=False)
    titulo = Column(String, nullable=False)
    cuerpo = Column(Text, nullable=False)
    id_proceso = Column(String, nullable=True)
    tarea_id = Column(String, nullable=True)
    enlace = Column(String, nullable=True)
    creada_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    leida_en = Column(DateTime, nullable=True)
    # Correo: cuándo salió, cuántas veces se intentó y por qué falló el último intento.
    enviada_en = Column(DateTime, nullable=True)
    intentos = Column(Integer, nullable=False, default=0)
    ultimo_error = Column(Text, nullable=True)


class Sincronizacion(Base):
    """Resultado de cada sincronización con SECOP II; la última exitosa fecha los datos (HU-04 CA-04)."""
    __tablename__ = 'sincronizaciones'

    id = Column(Integer, primary_key=True, autoincrement=True)
    inicio = Column(DateTime, nullable=False)
    fin = Column(DateTime, nullable=True)
    estado = Column(String, nullable=False) # Exitosa, Fallida
    procesos = Column(Integer, default=0)
    nuevos = Column(Integer, default=0)
    novedades = Column(Integer, default=0)
    coincidencias = Column(Integer, default=0)
    mensaje = Column(Text, nullable=True)


# ------------------------------------------------------------------
# Informes emitidos (RF-037, ASR-06, RN-08)
# ------------------------------------------------------------------
class InformeEmitido(Base):
    """Un informe por tarea; no se modifica después de emitido."""
    __tablename__ = 'informes_emitidos'

    tarea_id = Column(String, ForeignKey('tareas_analisis.id'), primary_key=True)
    ruta_pdf = Column(String, nullable=False)
    ruta_texto = Column(String, nullable=True)  # Vista previa con el mismo contenido
    huella_sha256 = Column(String, nullable=False)  # Huella del PDF, igual a la de la bitácora
    emitido_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    reglas_version = Column(Integer, nullable=True)
    portafolio_version = Column(Integer, nullable=True)


# ------------------------------------------------------------------
# Consumo de inferencia y cuota del periodo (RF-028, RN-10, ASR-13)
# ------------------------------------------------------------------
class ConsumoTokens(Base):
    """Una fila por invocación al proveedor del modelo. No guarda contenido (ASR-05)."""
    __tablename__ = 'consumo_tokens'

    id = Column(Integer, primary_key=True, autoincrement=True)
    periodo = Column(String, nullable=False, index=True)  # AAAA-MM (UTC)
    tarea_id = Column(String, nullable=True, index=True)
    operacion = Column(String, nullable=False)  # estructurado:ListaRequisitos, texto, embeddings…
    modelo = Column(String, nullable=True)
    tokens_entrada = Column(Integer, default=0, nullable=False)
    tokens_salida = Column(Integer, default=0, nullable=False)
    estimado = Column(Boolean, default=False, nullable=False)  # True si el proveedor no informó el uso
    registrado_en = Column(DateTime, default=datetime.utcnow, nullable=False)


class CuotaTokens(Base):
    """Límite de un periodo cuando el responsable autorizado lo amplía; si no hay fila, rige CUOTA_TOKENS_PERIODO."""
    __tablename__ = 'cuotas_tokens'

    periodo = Column(String, primary_key=True)
    limite = Column(Integer, nullable=False)
    motivo = Column(Text, nullable=True)
    ampliado_por = Column(String, nullable=False)
    ampliado_en = Column(DateTime, default=datetime.utcnow, nullable=False)


# ------------------------------------------------------------------
# Bitácora de Auditoría (ASR-06, DA-06) - Solo anexado
# ------------------------------------------------------------------
class BitacoraAuditoria(Base):
    __tablename__ = 'bitacora_auditoria'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    licitacion_id = Column(String)
    tarea_id = Column(String)
    accion = Column(String) # Ej: EMISION_INFORME
    hash_documento = Column(String) # Huella SHA-256 del informe o de los detalles del evento
    hash_previo = Column(String) # Huella del registro anterior: encadena la bitácora
    detalles = Column(JSON, nullable=True)
    registrado_por = Column(String) # Usuario o Sistema
    fecha_registro = Column(DateTime, default=datetime.utcnow)

