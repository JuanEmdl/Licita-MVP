import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from src.api.middleware.auth import requiere_permiso
from src.api.modules.analysis.router import router as analisis_router
from src.api.modules.identity.router import router_auth, router_usuarios
from src.api.modules.opportunities.router import router as vigilancia_router
from src.api.modules.opportunities.router import router_oportunidades, router_perfiles
from src.api.modules.portfolio.router import router as portafolio_router
from src.api.modules.results.router import router as resultados_router
from src.api.modules.scoring_rules.router import router as reglas_router
from src.api.modules.consumption.router import router as consumo_router
from src.api.modules.audit.router import router as auditoria_router
from src.api.modules.notifications.router import router as notificaciones_router
from src.api.modules.results.gestion import router_carpetas, router_exportacion, router_gestion
from src.shared import telemetria
from src.shared.config import obtener_configuracion
from src.shared.database import init_db, verificar_conexion
from src.shared.roles import Permiso

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = obtener_configuracion()
    config.registrar_diagnostico("api")
    telemetria.configurar("api")
    try:
        init_db()
        # Versiones iniciales: reglas provisionales (DT-02) y migración del portafolio previo.
        from src.shared.portfolio_repo import RepositorioVersionesPortafolio
        from src.shared.reglas_repo import RepositorioReglas
        RepositorioReglas().asegurar_version_inicial(config.umbral_ofertar, config.umbral_revision)
        RepositorioVersionesPortafolio().asegurar_version_inicial()
        if config.auth_mode in ("local", "oidc"):
            from src.api.modules.identity.servicio import obtener_servicio_identidad
            obtener_servicio_identidad().asegurar_admin_inicial()
    except Exception:
        # /health sigue respondiendo para que el orquestador de contenedores vea el problema en los logs.
        logger.exception("No se pudo inicializar la base de datos.")
    yield


app = FastAPI(
    title="Licita - API de análisis de licitaciones",
    description="Sesiones y roles, portafolio, vigilancia de SECOP II y análisis multiagente con verificación humana.",
    version="1.2.0",
    lifespan=lifespan,
)

# CORS limitado a los orígenes de la interfaz web (CORS_ORIGINS).
# Con credenciales, el navegador no acepta el comodín "*".
origenes = obtener_configuracion().cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origenes,
    allow_credentials="*" not in origenes,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Registrar los enrutadores modulares de la arquitectura
app.include_router(router_auth)
app.include_router(router_usuarios)
app.include_router(analisis_router)
app.include_router(portafolio_router)
app.include_router(vigilancia_router)
app.include_router(router_oportunidades)
app.include_router(router_perfiles)
app.include_router(resultados_router)
app.include_router(reglas_router)
app.include_router(consumo_router)
app.include_router(auditoria_router)
app.include_router(notificaciones_router)
app.include_router(router_carpetas)
app.include_router(router_gestion)
app.include_router(router_exportacion)


@app.middleware("http")
async def medir_solicitud(request: Request, call_next):
    """Disponibilidad y tiempo de respuesta de la API por ruta y código (Tabla 49)."""
    inicio = time.monotonic()
    codigo = 500
    try:
        respuesta = await call_next(request)
        codigo = respuesta.status_code
        return respuesta
    finally:
        ruta = getattr(request.scope.get("route"), "path", "sin ruta")
        telemetria.solicitudes_api.record(time.monotonic() - inicio, {
            "metodo": request.method, "ruta": ruta, "codigo": codigo})


@app.exception_handler(OperationalError)
async def base_no_disponible(request: Request, exc: OperationalError):
    # Sin detalles de la excepción: podrían incluir la cadena de conexión.
    logger.error(f"Base de datos no disponible en {request.url.path}: {type(exc).__name__}")
    return JSONResponse(status_code=503, content={"detail": "Base de datos no disponible"})


@app.get("/health", tags=["Operaciones"])
def health_check():
    """
    Endpoint de comprobación de salud para el orquestador de contenedores
    (Azure Container Apps).
    """
    base_ok = verificar_conexion()
    return {
        "status": "ok" if base_ok else "degradado",
        "base_de_datos": "ok" if base_ok else "sin conexión",
        "auth_mode": obtener_configuracion().auth_mode,
    }


@app.get("/diagnostico", tags=["Operaciones"])
def diagnostico_servicios(usuario: dict = Depends(requiere_permiso(Permiso.DIAGNOSTICO_VER))):
    """Prueba la base de datos, SECOP II, Azure OpenAI y Service Bus (sin exponer secretos)."""
    from src.shared.diagnostico import diagnosticar
    return diagnosticar()
