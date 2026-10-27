# Prompt de contexto para continuar en otro chat de Claude

Copia todo lo que está debajo de la línea y pégalo como primer mensaje del chat nuevo.

---

Vas a continuar el desarrollo de mi trabajo de grado: **MVP Licitaciones ("Licita")**, un sistema
multiagente que analiza licitaciones públicas colombianas de SECOP II para una fábrica de software.
Te entrego el proyecto como `MVP_Licitaciones_v4.zip` (sin `.venv`). Responde en español.

## Stack y versiones (no las cambies sin avisarme)
- Python **3.12.10**. Versiones fijadas en `requirements.txt`. Un venv que funcionaba tenía:
  nicegui 3.18.0, fastapi 0.143.0, openai 3.28.0, langgraph 1.2.15, sqlalchemy 2.1.4, psycopg 3,
  pypdf 6.21.2 (agregada en el bloque D con autorización).
- API: FastAPI (`src/api`, puerto 8000). Interfaz: NiceGUI (`src/webui/main.py`, puerto 8080).
- Workers: `src/worker_analysis` (grafo LangGraph con checkpoints en Postgres) y `src/worker_vigilance`.
- PostgreSQL 16 con la extensión `vector` (pgvector). Azure OpenAI, Azure Service Bus (opcional) y
  Datos Abiertos de SECOP II (Socrata).
- Rama de git: `feature/roles-sesiones-vigilancia` (sale de `develop`). **Los cambios no están
  commiteados**: están en el árbol de trabajo del zip.

## Flujo del sistema
Analista indica un proceso SECOP II (o lo toma de una alerta de vigilancia) → se recupera la ficha
de Datos Abiertos (+ texto del pliego opcional) → guardia anti-inyección → segmentación → Agente
Extractor (LLM) → **verificación humana** (el grafo se pausa en "Esperando revisión") → Agente
Evaluador contra el portafolio → motor de puntaje determinista → recomendación → informe sellado.

## Lo que se hizo en la última sesión (2026-10-19)
1. **Roles, inicio de sesión y sesiones** (`AUTH_MODE=local`):
   - Tablas `usuarios` y `sesiones` (`src/shared/models.py`). Contraseñas PBKDF2-SHA256.
   - `src/api/modules/identity/`: `seguridad.py` (hash y JWT HS256), `servicio.py` (login, validar,
     logout, usuarios), `router.py` (`/auth/login|logout|yo|sesion`, `/usuarios/...`).
   - La sesión pierde vigencia al cerrarla, por inactividad (`SESION_INACTIVIDAD_MIN`), por
     vencimiento (`SESION_DURACION_MIN`), al cambiar la contraseña o al deshabilitar al usuario.
     Bloqueo tras `LOGIN_MAX_INTENTOS` fallidos.
   - Matriz de roles en `src/shared/roles.py`: Analista Comercial, Gerente Comercial,
     Administrador del Sistema. Se aplica con `requiere_permiso(...)` en `src/api/middleware/auth.py`.
   - Las consultas automáticas de la UI mandan `X-Sin-Actividad: 1` para no renovar la inactividad.
   - Admin inicial desde `ADMIN_EMAIL`/`ADMIN_PASSWORD` del `.env`, o `python -m scripts.crear_usuario`.
2. **Interfaz** (`src/webui/main.py` + `src/webui/cliente_api.py`): pantalla de login, menú según
   rol, cierre de sesión, aviso antes de expirar, pantallas Portafolio, Vigilancia, **Seguimiento**
   (nueva), Revisión de requisitos, Resultados y **Usuarios + Diagnóstico** (admin). Se quitaron de
   la interfaz las referencias ASR/DA/RF/EP y los datos simulados.
3. **Lectura automática de SECOP II** (antes era simulada): `src/worker_vigilance/sync/secop_sync.py`
   consulta Datos Abiertos con `SOCRATA_APP_TOKEN`; `afinidad.py` calcula afinidad determinista con
   el portafolio; `servicio.py` guarda alertas en la tabla `alertas_oportunidad`. Endpoints en
   `src/api/modules/opportunities/router.py` (`/vigilancia/...`). Probado con datos reales.
4. **Azure OpenAI**: errores de configuración traducidos a mensajes claros (`llm_gateway/gateway.py`),
   `GET /diagnostico` y `python -m scripts.verificar_servicios`.
5. Pruebas: `tests/unit/test_identidad.py`, `tests/unit/test_vigilancia.py`. Resultado: 106 pasan +
   6 omitidas; 112 pasan con `TEST_DB_CONNECTION_STRING` apuntando a un Postgres de pruebas.
6. Documentación actualizada: `README.md`, `GUIA_PRUEBAS.md`, `CAMBIOS.md` (la primera sección
   resume todo esto), `.env.example`.

7. **Decisión comercial persistente** (RF-038, RF-039): tabla `decisiones_comerciales` con
   historial, columnas `decision_*` en `tareas_analisis`, módulo `src/api/modules/results/`
   (`/resultados/...`), evento `DECISION_COMERCIAL` en la bitácora y pantalla *Resultados*
   conectada (filtros, historial, justificación obligatoria). Opciones: Continuar, Descartar,
   Solicitar información. 118 pasan + 7 omitidas; 125 con Postgres de pruebas
   (`TEST_DB_CONNECTION_STRING` con `127.0.0.1`, no `localhost`, en Windows).

8. **Azure AI Foundry y gpt-5-mini**: el endpoint de proyecto se reduce a la raíz del recurso;
   la temperatura se omite con modelos de razonamiento (`LLM_TEMPERATURA`).
19. **Capítulo 5, evaluación del MVP (2026-10-27)**: corpus de 8 pliegos de SECOP II con referencia y
   portafolio por pliego (`data/evaluacion/corpus/`, `scripts/evaluar_corpus.py`; dos corridas: exactitud
   0,765 y 0,828, exhaustividad 0,941 y 0,949, precisión 0,376), matriz de los 38 Gherkin
   (`tests/aceptacion/`), ASR-10 con 50 casos, ASR-03 con 500 procesos, simulacros ASR-04/07/08/11
   (`scripts/simulacros.py`, `scripts/proxy_fallas.py`), PB-01 (`scripts/linea_base_manual.py`) y
   DEF-01/DEF-02 corregidos. Instrucciones para el documento: `CAPITULO_5_PARA_CLAUDE_CHAT.md`. Usar
   127.0.0.1 y no localhost con la base en Windows. Pendiente: prueba de carga (ASR-01, ASR-02, FF-01).
   693 pasan con PostgreSQL.
18. **Cierre del capítulo 4 (2026-10-25)**: núcleo de dominio explícito (`worker_analysis/nucleo`:
   puertos y máquina de estados), métricas de acoplamiento, Terraform validado, estrategia de ramas
   (`CONTRIBUTING.md`) e instrucciones para actualizar el documento
   (`ACTUALIZACION_DOCUMENTO_PARA_CLAUDE_CHAT.md`). 577 pasan + 13 omitidas.
17. **Pendientes que no son RF (2026-10-25)**: `GET /analisis/{id}` con etapas y `PUT /requisitos` con
   borrador (Tabla 45); revisión parcial tras una adenda (`pipeline/adendas.py`, HU-06 CA-03);
   detalle de la evaluación en Resultados; fragmentos y requisitos en paralelo
   (`ANALISIS_PARALELISMO`); métrica de longitud de la cola; informes en Blob Storage inmutable
   (`ALMACEN_INFORMES_URL`); funciones de aptitud en `tests/aptitud` y FF-01 con Locust; canalización
   con Bandit y pip-audit; Terraform en `infra/terraform` (escrito, sin aplicar). Horas en hora local
   (`UTC_OFFSET`). 550 pasan + 13 omitidas. Lo pendiente está al final de ALINEACION_DOCUMENTO.md.
16. **Bloque G (2026-10-25)**: OIDC con la interfaz como cliente confidencial (`src/webui/oidc.py`,
   rutas `/auth/oidc/inicio` y `/auth/callback`), `POST /auth/oidc` que valida el id_token y abre la
   sesión de Licita; rol y estado desde la tabla de usuarios. Probado con un proveedor simulado; falta
   el App Registration real (GUIA_PRUEBAS.md 6.1). 43 de 43 RF en el código. Verificado con el
   App Registration real del usuario. Con `AUTH_MODE=local` y el App Registration configurado, el
   inicio de sesión ofrece ambas opciones (modo combinado, pedido por el usuario).
15. **Bloque F (2026-10-25)**: carpetas propias, notas y responsable (`gestion_repo.py`,
   `api/modules/results/gestion.py`) y exportación CSV con la biblioteca estándar
   (`/resultados/oportunidades.csv`, auditada, ASR-15 medido). 42 de 43 RF cumplidos; falta OIDC.
14. **Bloque E (2026-10-25)**: notificaciones en la aplicación (campana) y por correo SMTP
   (`notificaciones`, `preferencias_notificacion`, `worker_vigilance/notificador.py`), canal y
   frecuencia con resumen diario, avisos de oportunidades, novedades, revisión pendiente y
   suspensión. Sin dependencias nuevas. 40 de 43 RF cumplidos.
13. **Bloque D (2026-10-25)**: oportunidades sincronizadas sin duplicados, búsqueda y filtros,
   perfiles de búsqueda, seguimiento y detector de novedades, radicación con documentos de
   `dmgg-8hin` (SECOP II da 403 a la descarga: quedan faltantes), expediente con carga manual y
   versiones, segmentador con página, sección y tablas, referencia completada, pantallas
   Oportunidades y Perfiles. Dependencia nueva autorizada: `pypdf==6.21.2`. 37 de 43 RF cumplidos.
12. **Bloque C (2026-10-24)**: informe en PDF sellado (`reports/pdf.py`, sin dependencias), emisión
   atómica en `informes_emitidos`, verificación de huella; bitácora con eventos de identidad, 403 y
   vigilancia, disparadores de solo anexado, `/auditoria` y pantalla Bitácora. 27 de 43 RF cumplidos.
11. **Bloque B (2026-10-24)**: pasarela con cuota de tokens (`/consumo`, 429, Suspendida por cuota y
   *Continuar*), anonimización, disyuntor con reintento por cola y telemetría OpenTelemetry a Azure
   Monitor. `init_db` con bloqueo consultivo. 25 de 43 RF cumplidos.
10. **Bloque A (2026-10-24)**: reglas del puntaje versionadas con doble control (`/reglas-puntaje`,
   pantalla nueva), portafolio versionado con indexación incremental (`/portafolio/versiones`,
   `portafolio.indexar`) y reutilización de análisis vigentes (409 y `forzar_nuevo`). La matriz de
   roles sigue la Tabla 61. `ALINEACION_DOCUMENTO.md` lleva el avance: 23 de 43 RF cumplidos.
9. **Prompt del extractor 2.1.0** y evaluación con `python -m scripts.evaluar_extractor` (casos en
   `data/evaluacion/casos/`): de 86 % a 100 % de requisitos encontrados y de 47 % a 100 % de
   estabilidad. 146 pruebas pasan + 7 omitidas.

## Estado verificado
- Login, roles (403), logout, usuario deshabilitado con sesión abierta (401) y barrido real de
  SECOP II: funcionan contra la API real.
- El flujo con datos reales de SECOP llega a **"Esperando revisión"** y la aprobación humana desde
  la UI funciona (probado con un extractor sustituto, porque el modelo no está disponible).
- Service Bus: la cola `analisis-licitaciones` es accesible.

## BLOQUEO PRINCIPAL (pendiente)
La llave de Azure OpenAI es válida, pero el recurso **`aoai-licitaciones-mvp` no tiene ningún
deployment**: `gpt-4o-mini` y `text-embedding-3-small` responden `DeploymentNotFound`. Por eso el
análisis falla al llegar al Agente Extractor. Hay que crearlos (Azure AI Foundry > Implementaciones,
o con `az cognitiveservices account deployment create` después de `az login`):
- chat: nombre `gpt-4o-mini`, modelo gpt-4o-mini versión 2024-07-18 (soporta Structured Outputs);
- embeddings (opcional): nombre `text-embedding-3-small`.
Luego correr `python -m scripts.verificar_servicios` y probar un análisis completo.

## Otros pendientes
- Informe en PDF (RF-037); hoy es texto sellado.
- Exportación a CSV del tablero (RF-041) y carpetas/notas/responsable (RF-040).
- Inicio de sesión OIDC (Entra ID) en la interfaz; hoy se usa `AUTH_MODE=local`.
- Cambiar la contraseña del administrador inicial después del primer ingreso.
- Las credenciales de Azure del `.env` estuvieron expuestas en el historial de git: conviene rotarlas.

## Cómo levantarlo
1. Python 3.12.10 y `pip install -r requirements.txt` en un venv nuevo (el `.venv` no viaja: tiene
   rutas absolutas de la máquina donde se creó).
2. PostgreSQL 16 con pgvector: `docker compose up -d db` (o un servidor propio) y
   `DB_CONNECTION_STRING` en el `.env`.
3. `.env`: copiar de `.env.example` o usar el que viene en el zip (ya trae `AUTH_MODE=local`,
   `SESION_SECRETO`, `WEBUI_STORAGE_SECRET`, `ADMIN_*` y el token de SECOP). Para probar sin worker,
   dejar `SERVICE_BUS_CONNECTION_STRING` vacía.
4. `uvicorn src.api.main:app --port 8000` y `python src/webui/main.py`, luego
   `python -m scripts.cargar_portafolio data/ejemplos/portafolio_ejemplo.json`.
5. Entrar en http://localhost:8080 con `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

Antes de modificar algo, lee `CAMBIOS.md` y los archivos mencionados. Mantén el estilo del código
(nombres y comentarios en español) y vuelve a correr `pytest` después de cada cambio.
