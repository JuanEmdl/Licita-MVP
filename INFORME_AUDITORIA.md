# Informe de auditoría técnica — MVP Licitaciones

Fecha: 2026-10-16 · Base: `MVP_Licitaciones.zip` (código del 2026-10-10)

## E. Resumen ejecutivo

**El MVP está listo para comenzar pruebas funcionales**, con una condición: se
necesitan credenciales válidas de Azure OpenAI. Sin ellas, la aplicación arranca,
autentica, registra tareas y portafolio, pero cada análisis termina en estado
`Fallida` con un mensaje que nombra las variables que faltan.

Verificado en esta auditoría con PostgreSQL 16 + pgvector reales:

- Instalación limpia de dependencias fijadas (`pip check` sin conflictos).
- Arranque de API, webui y workers. La webui responde HTTP 200.
- Autenticación: sin token y con token inválido la API devuelve 401.
- Flujo completo hasta el informe, simulando únicamente el modelo de IA y SECOP II:
  1. solicitud;
  2. pausa en la compuerta humana;
  3. edición y aprobación de requisitos;
  4. evaluación con evidencia del portafolio;
  5. puntaje, recomendación e informe;
  6. bitácora encadenada.
- Lectura del resultado desde un proceso distinto, con el checkpoint persistido en Postgres.
- 82 pruebas automatizadas aprobadas: 55 existentes, 21 unitarias nuevas y 6 de integración.

No verificado (requiere acceso externo):

- Llamadas reales a Azure OpenAI.
- Consulta en vivo de Datos Abiertos SECOP II: el dominio estaba bloqueado en el entorno de auditoría.
- Azure Service Bus.
- OIDC con Entra ID.

Bloqueos antes de considerarlo funcional:

1. Configurar y **rotar** las credenciales (ver §Riesgos).
2. Ejecutar una prueba con Azure OpenAI real (GUIA_PRUEBAS.md, caso P-05).
3. Cargar el portafolio real de la empresa: el de ejemplo es ficticio.
4. El análisis requiere pegar el texto del pliego, porque Datos Abiertos solo publica metadatos del proceso.

## B. Problemas encontrados y correcciones

### 1. Instalación y arranque

| # | Problema | Corrección | Archivo |
|---|---|---|---|
| 1.1 | `python src/webui/main.py` fallaba con `ModuleNotFoundError: src`. Afectaba a `.claude/launch.json` y a cualquier ejecución local. | El script agrega la raíz del proyecto a `sys.path`. | `src/webui/main.py` |
| 1.2 | La webui no cargaba el `.env` en local, así que `API_TOKEN` siempre llegaba vacío. | Llama a `load_dotenv` con la ruta del proyecto. | `src/webui/main.py` |
| 1.3 | `requirements.txt` sin versiones: se instalaban langchain 1.x, openai 3.x y langgraph 1.x sin control. | Versiones fijadas a las probadas. Se quitaron `langchain` y `langchain-postgres`, que no se usaban; el RAG se hace con SQLAlchemy y pgvector. | `requirements.txt` |
| 1.4 | Las imágenes usaban Python 3.11, mientras el desarrollo (`.venv` cp312) y las pruebas usan 3.12. | Imágenes `python:3.12-slim`. | `docker/*.Dockerfile` |

### 2. Configuración y credenciales

| # | Problema | Corrección |
|---|---|---|
| 2.1 | El `.env` entregado no define `AUTH_MODE`, `API_TOKEN_DESARROLLO` ni `API_TOKEN`. La API arranca en `oidc` y la webui, que no tiene login OIDC, envía un token vacío: todas las llamadas desde la interfaz eran rechazadas. | `.env.example` documenta `AUTH_MODE=desarrollo` y los dos tokens para pruebas locales. Al arrancar se registra un diagnóstico que nombra las variables faltantes sin mostrar valores. |
| 2.2 | Sin tiempo máximo en las llamadas al modelo: una llamada colgada bloqueaba la tarea indefinidamente. | `LLM_TIMEOUT_S` (120 s por defecto) en chat y embeddings. |
| 2.3 | Variables declaradas que el código no usa (`OIDC_CLIENT_SECRET`, `AZURE_STORAGE_*`, `APPLICATIONINSIGHTS_*`). | Marcadas como reservadas en `.env.example` para no inducir a cargar secretos innecesarios. |
| 2.4 | Las pruebas cargaban el `.env` real (`load_dotenv` al importar). | `CARGAR_DOTENV=0` en `tests/conftest.py`: las pruebas nunca leen credenciales reales. |
| 2.5 | URL de SECOP fija en el código y sin token de Socrata. | `SECOP_BASE_URL` y `SOCRATA_APP_TOKEN` (opcional). |

### 3. Base de datos

| # | Problema | Corrección |
|---|---|---|
| 3.1 | `create_all` no agrega columnas a tablas existentes. `CAMBIOS.md` pedía recrear el volumen, lo que implica perder datos. | `init_db` ejecuta `ADD COLUMN IF NOT EXISTS`. Es idempotente y fue probado sobre una base con el esquema antiguo. |
| 3.2 | Sin modelo de embeddings, el portafolio guardaba vectores de ceros y buscaba con ellos, con resultados sin significado. | Se guarda `NULL`. La búsqueda usa pgvector (distancia coseno) y, como respaldo, el texto completo de PostgreSQL en español. |
| 3.3 | Una base caída producía 500 con trazas en la respuesta. | Respuesta 503 sin detalles; `/health` informa el estado real de la base. |
| 3.4 | La tabla `bitacora_auditoria` existía, pero el registrador solo escribía en el log. | Inserción real, encadenada por hash, con `verificar_cadena()`. |

### 4. Agentes, prompts y flujo multiagente

| # | Problema | Corrección |
|---|---|---|
| 4.1 | **El recuperador del portafolio era un mock**: devolvía el mismo texto ficticio ("ISO 27001 vigente…") para todos los requisitos, de modo que cualquier dictamen "Cumple" se apoyaba en evidencia inventada. | `RecuperadorPortafolio` consulta la tabla `portafolio`. Si el deployment de embeddings falla, se desactiva y se usa texto completo. Si la base no responde, la tarea falla en lugar de emitir dictámenes engañosos. |
| 4.2 | Las instrucciones y el pliego viajaban mezclados en un solo mensaje, lo que facilita la inyección de prompts. | Instrucciones en el mensaje de sistema. Datos en etiquetas XML neutralizadas (`encapsular`). |
| 4.3 | El extractor no distinguía la ficha de metadatos de SECOP de los requisitos: podía convertir "PRECIO BASE" u "OBJETO" en requisitos. | El prompt define qué es y qué no es un requisito. Si el fragmento no contiene requisitos, devuelve una lista vacía. |
| 4.4 | El prompt del extractor no definía "habilitante" ni las categorías, y pedía la "página" sin que el modelo tuviera ese dato. | Define habilitante frente a ponderable (contexto colombiano) y cada categoría. La referencia usa el numeral si aparece y, si no, "Fragmento X de N". |
| 4.5 | El solape de 500 caracteres entre fragmentos duplicaba requisitos. | Deduplicación por categoría y texto normalizado en el orquestador. |
| 4.6 | El prompt del evaluador no distinguía "No cumple" de "No verificable" (RF-006) y la evidencia no era trazable. | Criterios explícitos por estado, cita obligatoria con el identificador `[P-n]` del registro y regla ante la duda: elegir el estado menos favorable. |
| 4.7 | Nada impedía un "Cumple" sin evidencia (RNF-030). | Salvaguardas en código: sin evidencias no se llama al modelo y el dictamen es "No verificable". Un dictamen que no cita un registro recuperado se degrada a "No verificable". |
| 4.8 | Un requisito habilitante con "Cumple parcialmente" podía terminar en "Ofertar" (contradice RF-030). | Pasa a "Solicitar revisión". |
| 4.9 | El prompt del recomendador recibía solo los identificadores de los requisitos, pero se le pedía nombrar el requisito incumplido. Además podía contradecir la categoría. | Recibe el texto de cada requisito y los umbrales. Tiene prohibido cambiar la categoría y su formato es acotado. |
| 4.10 | La salida inválida o el rechazo del modelo producía errores opacos y no se registraba el consumo de tokens. | `include_raw=True`: error claro con la causa y log de tokens por llamada, sin contenido. |
| 4.11 | No se registraba con qué instrucciones se produjo un análisis (RNF-027). | `VERSION_PROMPTS` se guarda en el estado, en el resultado y en el informe. |
| 4.12 | La aprobación humana no quedaba auditada (RF-007). | Evento `REQUISITOS_APROBADOS` con los requisitos agregados y eliminados. Si no puede registrarse, la aprobación no se confirma. |

**Responsabilidades resultantes (sin solapamiento)**

| Agente | Recibe | Produce | No hace |
|---|---|---|---|
| Extractor | Fragmento del expediente | `ListaRequisitos` (JSON Schema estricto) | Evaluar, puntuar, recomendar |
| Evaluador | Un requisito y sus evidencias `[P-n]` | `DictamenRequisito` | Extraer, recomendar |
| Motor de puntaje | Requisitos aprobados y dictámenes | Puntaje y desglose (determinista) | Usar el LLM |
| Recomendador | Categoría ya decidida por reglas y dictámenes | Justificación en prosa | Decidir la categoría |

Los esquemas se verificaron con el convertidor estricto de OpenAI (`to_strict_json_schema`): son compatibles con Structured Outputs.

### 5. API, workers e interfaz

| # | Problema | Corrección |
|---|---|---|
| 5.1 | Con Service Bus, el informe se escribía en el contenedor del worker y la API no podía servirlo. | Volumen `informes` compartido y endpoint `GET /analisis/{id}/informe`. |
| 5.2 | El informe se guardaba como `.pdf.txt`: aparentaba ser un PDF. | Se guarda como `.txt`. Incluye el texto de cada requisito, el modelo y la versión de instrucciones. El PDF sigue pendiente. |
| 5.3 | El módulo de portafolio de la API estaba vacío y la pestaña de la UI usaba datos en memoria. | `GET/POST /portafolio`, pestaña conectada y script `scripts/cargar_portafolio.py`. |
| 5.4 | La pestaña Resultados mostraba dos licitaciones inventadas. | Lee las tareas finalizadas de la API y muestra el informe real. |
| 5.5 | La pestaña Vigilancia y la decisión comercial mostraban datos ficticios como si fueran reales. | Etiquetadas como demostración. La decisión avisa que no se guarda (RF-027 pendiente). |
| 5.6 | Si fallaba la base de datos, el worker se caía con el mensaje bloqueado. | `abandon_message`: Service Bus reintenta y lo envía a dead-letter tras `MaxDeliveryCount`. |
| 5.7 | Entradas como `"  ID  "` o un pliego vacío pasaban sin normalizar. | Validadores en `SolicitudAnalisis`. |
| 5.8 | El puerto de Postgres de docker-compose quedaba expuesto en todas las interfaces. | Limitado a `127.0.0.1`. |

`src/shared/models.py` aparece casi entero en el diff porque se convirtieron sus finales de línea de CRLF a LF.

## Problemas pendientes (no resueltos y motivo)

| Pendiente | Requisito | Motivo |
|---|---|---|
| Worker de vigilancia (barrido SECOP, afinidad, alertas) | RF-014, RF-015, RF-021 | Funcionalidad nueva y extensa; está simulado y marcado como tal. |
| Descarga del pliego PDF desde community.secop.gov.co | RF-014, RF-025 | No hay un mecanismo autorizado documentado; hoy el pliego se pega como texto. |
| Login OIDC en la webui | RF-019 | Requiere un App Registration y un flujo de inicio de sesión; con `AUTH_MODE=oidc` la UI no funciona. |
| Matriz de roles (quién aprueba requisitos y quién gestiona el portafolio) | RF-020, RNF-015 | La matriz está "pendiente de aprobación" en los requisitos. |
| Registro persistente de la decisión comercial | RF-027 | No existe modelo de datos; se requiere definirlo. |
| Informe en PDF | RF-016 | El informe en texto sí es funcional y queda sellado. |
| Control de cuota de tokens y anonimización | RF-008, RNF-028 | Hay ganchos en la pasarela, pero faltan las reglas de negocio (cuotas y campos prohibidos). |
| Reglas de puntaje versionadas en la base | RF-026 | La tabla existe; las ponderaciones siguen en el código (v1.1.0). |
| Versionado y vigencia de las evidencias del portafolio | RF-001 | Requiere cambios de modelo y de UI. |
| Telemetría OpenTelemetry y App Insights | RF-011, RNF-021 | Dependencias instaladas, exportador sin inicializar. |
| `pyproject.toml` no coincide con `requirements.txt` | — | Los Dockerfiles usan `requirements.txt`; se recomienda derivar uno del otro. |

## Riesgos de seguridad identificados

1. **Secretos reales en el ZIP.** `.env` contiene valores con forma de credenciales reales: Service Bus `RootManageSharedAccessKey`, Azure OpenAI, Storage, OIDC client secret y App Insights. No se usaron ni se reproducen aquí. `CAMBIOS.md` indica que se filtraron en el commit `192f0f5` de `origin/develop`. **Acción:** rotarlas en Azure si no se hizo y no compartir el `.env`. El ZIP entregado no lo incluye.
2. `RootManageSharedAccessKey` otorga control total del namespace de Service Bus. Use políticas SAS separadas: *Send* para la API y *Listen* para el worker.
3. `AUTH_MODE=desarrollo` usa un token compartido sin roles. Úselo solo en local.
4. `infra/provision-webui.ps1` usa el usuario administrador de ACR. Se recomienda identidad administrada.
5. Cualquier usuario autenticado puede listar todas las tareas y aprobar requisitos (sin control de roles).
6. La bitácora detecta alteraciones, pero no las impide. Aplique `REVOKE UPDATE, DELETE ON bitacora_auditoria` al rol de la aplicación.
7. La guardia anti-inyección se basa en expresiones regulares. Se complementó con la separación sistema/datos y las salvaguardas de evidencia, pero no es infalible: valide con el banco de RNF-017.

## C. Matriz de validación

Leyenda: ✅ Correcto y probado · 🟡 Corregido, pendiente de probar · 🔑 Requiere credenciales o acceso externo · ❌ Pendiente de corrección

| Componente | Estado | Evidencia |
|---|---|---|
| Instalación de dependencias (Python 3.12) | ✅ | Entorno limpio, `pip check` sin conflictos |
| Sintaxis e importaciones de todos los módulos | ✅ | `compileall`; importación de los cuatro puntos de entrada |
| Configuración y diagnóstico de variables | ✅ | `test_gateway_y_config.py`; log de arranque real |
| Conexión a PostgreSQL y `init_db` | ✅ | Postgres 16.15 + pgvector 0.6; migración probada sobre el esquema antiguo |
| Checkpointer de LangGraph en Postgres | ✅ | Integración: pausa, reanudación y lectura desde otro proceso |
| Autenticación modo desarrollo | ✅ | 401 sin token y con token inválido (API real y pruebas) |
| Autenticación OIDC (validación JWT) | ✅ / 🔑 | Pruebas ASR-09 con JWKS simulado; falta probar con Entra ID real |
| API: análisis, estado, requisitos, aprobación, resultado, informe | ✅ | `tests/integration/test_flujo_postgres.py` |
| API: portafolio | ✅ | Integración y prueba manual con uvicorn |
| Compuerta humana (ASR-12) | ✅ | Pruebas ASR-12 e integración |
| Guardia anti-inyección (ASR-10) | ✅ | Pruebas ASR-10; suspensión auditada en la integración |
| RAG del portafolio, búsqueda por texto completo | ✅ | Integración (evidencia `[P-n]` recuperada de Postgres) |
| RAG del portafolio, búsqueda vectorial | 🔑 | Requiere el deployment de embeddings |
| Motor de puntaje y reglas de recomendación | ✅ | Pruebas existentes y nuevas |
| Prompts (estructura, delimitación, alineación con los esquemas) | ✅ | `test_prompts_y_agentes.py` |
| Calidad de las respuestas del modelo con los nuevos prompts | 🔑 | Requiere Azure OpenAI (casos P-05 a P-08 de la guía) |
| Pasarela Azure OpenAI (llamada real) | 🔑 | Lógica probada con un LLM falso; esquemas compatibles con modo estricto |
| Adaptador SECOP II (Datos Abiertos) | 🔑 | Dominio bloqueado en el entorno; ruta de respaldo con pliego probada |
| Azure Service Bus (API → worker) | 🔑 | Worker sin cola probado; la publicación requiere credenciales |
| Bitácora de auditoría encadenada | ✅ | Integración: eventos y `verificar_cadena()` |
| Informe (texto) | ✅ | Integración: contenido y huella |
| Webui: arranque | ✅ | HTTP 200 en `:8080` |
| Webui: pestañas conectadas a la API | 🟡 | Código corregido; la interacción en el navegador no se automatizó |
| Imágenes Docker y docker-compose | 🟡 | Revisados; Docker no está disponible en el entorno de auditoría |
| Worker de vigilancia | ❌ | Simulado |
| Decisión comercial, PDF, roles, cuotas | ❌ | Ver pendientes |

## Recuperación del estado original

El ZIP original sigue intacto. Todos los cambios son incrementales y no borran datos.
Para comparar, `git diff` contra el repositorio original muestra cada cambio archivo por archivo.
