workspace "Sistema multi-agente de análisis de licitaciones públicas" "Descripción arquitectónica del MVP conforme a 
ISO/IEC/IEEE 42010:2022, expresada con el Modelo C4." {

 !impliedRelationships false

 model {

 # ------------------------------------------------------------------
 # Partes interesadas que operan el sistema (C4 Nivel 1)
 # ------------------------------------------------------------------
 analista = person "Analista Comercial" "Registra el portafolio de la fábrica, solicita análisis de licitaciones 
y revisa los requisitos extraídos antes de su evaluación."
 gerente = person "Gerente Comercial" "Consulta recomendaciones, informes y el tablero de oportunidades; registra 
la decisión comercial."
 admin = person "Administrador del Sistema" "Gestiona usuarios, roles y la configuración versionada de las reglas 
del puntaje."

 # ------------------------------------------------------------------
 # Sistemas externos fuera del control del proyecto
 # ------------------------------------------------------------------
 secop = softwareSystem "SECOP II" "Plataforma transaccional de contratación pública y datos abiertos de Colombia 
Compra Eficiente." "Externo"
 llm = softwareSystem "Proveedor de modelos de lenguaje" "Servicio de inferencia y de embeddings. Despliegue de 
referencia: Azure OpenAI Service." "Externo"
 idp = softwareSystem "Proveedor de identidad" "Autenticación federada de los usuarios mediante OpenID Connect." 
"Externo"
 correo = softwareSystem "Servicio de correo electrónico" "Entrega de notificaciones de oportunidades, novedades 
y revisiones pendientes." "Externo"

 # ------------------------------------------------------------------
 # Entidad de interés (ISO/IEC/IEEE 42010:2022)
 # ------------------------------------------------------------------
 sma = softwareSystem "Sistema multi-agente de análisis de licitaciones" "Extrae los requisitos de los pliegos 
publicados en SECOP II, evalúa su cumplimiento frente al portafolio de la fábrica de software y emite una recomendación 
explicada." {

 webui = container "Aplicación web" "Servidor de interfaz en Python para los roles comerciales y de 
administración. Mantiene la sesión del usuario en el servidor y consulta el estado de las tareas a la API por sondeo." 
"Python, NiceGUI" "Interfaz" {
 perspectives {
 "Seguridad" "Los tokens de acceso permanecen en el servidor de interfaz y no llegan al navegador; no 
toma decisiones de autorización (ASR-09)."
 }
 }

 api = container "API de aplicación" "Monolito modular síncrono. Autentica, autoriza en el servidor, gestiona 
el dominio y encola los trabajos de larga duración." "Python, FastAPI" {
 perspectives {
 "Desempeño" "Responde 202 con identificador de tarea en menos de 1 s y delega el análisis a la cola 
(ASR-11)."
 "Seguridad" "Punto único de entrada para autenticación, autorización basada en roles y verificación 
de sesión (ASR-09)."
 }
 filtroAuth = component "Filtro de autenticación y autorización" "Valida el token OIDC, comprueba la 
vigencia de la sesión y el estado del usuario, y aplica la matriz de roles en cada solicitud." "Middleware FastAPI"
 modIdentidad = component "Módulo de identidad y usuarios" "Creación, habilitación, deshabilitación y 
asignación de permisos (RF-001 a RF-007)." "Módulo Python"
 modPortafolio = component "Módulo de portafolio" "Registro y versionado del portafolio de capacidades 
(RF-008 a RF-010)." "Módulo Python"
 modOportunidades = component "Módulo de oportunidades" "Búsqueda, filtros, perfiles, seguimiento y carga 
manual de documentos (RF-013 a RF-022)." "Módulo Python"
 modAnalisis = component "Módulo de análisis" "Solicitud y estado de tareas, revisión humana de 
requisitos y reutilización de resultados vigentes (RF-025, RF-026, RF-030, RF-036)." "Módulo Python"
 modReglas = component "Módulo de reglas del puntaje" "Configuración y versionado de ponderaciones y 
umbrales (RF-032, RF-033)." "Módulo Python"
 modResultados = component "Módulo de resultados y decisiones" "Informes, tablero, decisión comercial, 
carpetas y exportación (RF-037 a RF-041)." "Módulo Python"
 publicador = component "Publicador de trabajos" "Adaptador del puerto de mensajería: publica trabajos de 
análisis, reanudación e indexación." "Adaptador Service Bus"
 auditoriaApi = component "Registrador de auditoría" "Anexa eventos críticos a la bitácora encadenada por 
hash (RF-042)." "Módulo Python"
 }

 cola = container "Cola de trabajos" "Colas durables de análisis, reanudación e indexación con confirmación 
explícita y cola de mensajes fallidos." "Azure Service Bus" "Cola" {
 perspectives {
 "Fiabilidad" "Un trabajo no confirmado vuelve a la cola si el trabajador cae (ASR-04, ASR-07)."
 "Escalabilidad" "La longitud de la cola dispara el escalado de trabajadores sin cambios de código 
(ASR-08)."
 }
 }

 worker = container "Trabajador de análisis multi-agente" "Ejecuta el flujo de análisis con agentes 
especializados. No guarda estado local y escala horizontalmente según la longitud de la cola." "Python, LangGraph" {
 perspectives {
 "Desempeño" "Procesa en paralelo los fragmentos del pliego (ASR-01, ASR-02)."
 "Fiabilidad" "Reanuda desde el último checkpoint persistido (ASR-04)."
"Escalabilidad" "Réplicas sin estado añadidas por la plataforma (ASR-08)."
 }
 consumidor = component "Consumidor de trabajos" "Recibe trabajos con bloqueo temporal, confirma al 
cerrar cada etapa y descarta duplicados por identificador de tarea." "Adaptador Service Bus"
 orquestador = component "Orquestador del flujo de análisis" "Máquina de estados que fija el orden de las 
etapas y detiene la ejecución hasta la aprobación humana de los requisitos (ASR-12)." "LangGraph StateGraph"
 checkpoints = component "Almacén de checkpoints" "Persiste el estado del flujo al cerrar cada etapa para 
reanudar tras una caída o una espera humana (ASR-04)." "LangGraph PostgresSaver"
 adaptadorSecop = component "Adaptador SECOP II" "Capa anticorrupción: traduce los esquemas externos al 
modelo interno y aísla sus cambios (ASR-03)." "Módulo Python"
 guardia = component "Guardia documental" "Trata el contenido como dato no confiable, detecta patrones de 
inyección y suspende análisis sospechosos (ASR-10)." "Módulo Python"
 segmentador = component "Segmentador documental" "Divide pliegos y anexos conservando cláusulas, tablas 
y referencia a documento y página (RF-023)." "Módulo Python"
 extractor = component "Agente Extractor" "Produce la lista estructurada de requisitos validada contra un 
esquema (RF-029)." "Agente LLM sin herramientas"
 evaluador = component "Agente Evaluador" "Emite el dictamen por requisito aprobado con evidencia del 
portafolio (RF-031)." "Agente LLM con recuperación"
 recuperador = component "Recuperador de evidencias" "Búsqueda por similitud sobre el índice vectorial 
del portafolio." "pgvector"
 indexador = component "Indexador del portafolio" "Actualiza de forma incremental el índice vectorial del 
portafolio (RF-010)." "Módulo Python"
 motorPuntaje = component "Motor de puntaje" "Calcula el puntaje de 0 a 100 con reglas versionadas, sin 
intervención del modelo de lenguaje (RF-033, RF-034)." "Módulo Python determinista"
 recomendador = component "Generador de recomendación" "Asigna la categoría por umbrales y redacta la 
justificación a partir de los dictámenes (RF-035)." "Reglas + LLM"
 generadorInforme = component "Generador de informe" "Produce el PDF y su huella SHA-256 (RF-037, ASR-
06)." "Módulo Python"
 pasarela = component "Pasarela de modelos de lenguaje" "Punto único hacia el proveedor: anonimización, 
control de cuota de tokens, reintentos con espera exponencial, disyuntor y telemetría (ASR-05, ASR-07, ASR-13)." "Módulo 
Python"
 auditoriaWorker = component "Registrador de auditoría" "Anexa eventos críticos y huellas de informes a 
la bitácora encadenada (RF-042, ASR-06)." "Módulo Python"
 }

 vigilancia = container "Trabajador de vigilancia de oportunidades" "Sincroniza procesos de SECOP II, detecta 
cambios en procesos seguidos y emite notificaciones de forma programada." "Python, tarea programada" {
 perspectives {
 "Interoperabilidad" "Usa la misma capa anticorrupción que el trabajador de análisis (ASR-03)."
"Fiabilidad" "Una falla de SECOP II no afecta los análisis en curso (ASR-07)."
 }
 }

 bd = container "Base de datos transaccional y vectorial" "Datos de negocio, checkpoints del flujo, índice 
vectorial del portafolio y bitácora de auditoría de solo anexado." "PostgreSQL con pgvector" "BaseDatos" {
 perspectives {
 "Seguridad" "Cifrado en reposo con claves custodiadas; bitácora sin permisos de actualización ni 
borrado (ASR-05, ASR-06)."
 "Fiabilidad" "Respaldo continuo con restauración a un punto en el tiempo (ASR-04)."
 }
 }

 docs = container "Almacén de documentos" "Pliegos, anexos e informes PDF. Los informes emitidos quedan bajo 
política de inmutabilidad." "Azure Blob Storage" "BaseDatos" {
 perspectives {
 "Seguridad" "Informes inmutables verificables por huella SHA-256 (ASR-06)."
 }
 }

 }

 # ------------------------------------------------------------------
 # Relaciones de Nivel 1 (contexto)
 # ------------------------------------------------------------------
 analista -> sma "Registra el portafolio, solicita análisis y revisa requisitos"
 gerente -> sma "Consulta recomendaciones e informes y registra decisiones"
 admin -> sma "Administra usuarios, roles y reglas del puntaje"
 sma -> secop "Consulta procesos y descarga documentos" "HTTPS"
 sma -> llm "Solicita inferencia y embeddings" "HTTPS"
 sma -> idp "Delega la autenticación" "OpenID Connect"
 sma -> correo "Envía notificaciones" "SMTP/TLS"

 # ------------------------------------------------------------------
 # Relaciones de Nivel 2 (contenedores)
 # ------------------------------------------------------------------
 analista -> webui "Registra portafolio, solicita y revisa análisis" "HTTPS/WebSocket"
 gerente -> webui "Consulta recomendaciones, informes y tablero" "HTTPS/WebSocket"
 admin -> webui "Administra usuarios, roles y reglas" "HTTPS/WebSocket"
 webui -> idp "Autentica al usuario como cliente confidencial" "OIDC, código de autorización"
 webui -> api "Invoca operaciones con el token del usuario" "JSON/HTTPS"
 api -> idp "Valida firma y emisor de los tokens" "OIDC/JWKS"
 api -> bd "Lee y escribe datos de negocio" "SQL/TLS"
 api -> docs "Carga manual de documentos y descarga de informes" "HTTPS"
 api -> cola "Encola trabajos y responde 202" "AMQP/TLS"
 cola -> worker "Entrega trabajos de análisis, reanudación e indexación" "AMQP/TLS"
 worker -> secop "Recupera el expediente documental" "HTTPS"
 worker -> llm "Invoca inferencia y embeddings a través de la pasarela" "HTTPS"
 worker -> bd "Guarda checkpoints, resultados y auditoría" "SQL/TLS"
 worker -> docs "Lee pliegos y guarda informes" "HTTPS"
 worker -> correo "Notifica revisiones pendientes" "SMTP/TLS"
 vigilancia -> secop "Sincroniza procesos y detecta cambios" "HTTPS (datos abiertos)"
 vigilancia -> bd "Actualiza oportunidades y novedades" "SQL/TLS"
 vigilancia -> correo "Envía alertas de oportunidades" "SMTP/TLS"

 # ------------------------------------------------------------------
 # Relaciones de Nivel 3: API de aplicación
 # ------------------------------------------------------------------
 webui -> filtroAuth "Envía solicitudes con el token del usuario" "JSON/HTTPS"
 filtroAuth -> idp "Valida tokens" "OIDC/JWKS"
 filtroAuth -> modIdentidad "Consulta estado y rol del usuario"
 filtroAuth -> modPortafolio "Delega solicitud autorizada"
 filtroAuth -> modOportunidades "Delega solicitud autorizada"
 filtroAuth -> modAnalisis "Delega solicitud autorizada"
 filtroAuth -> modReglas "Delega solicitud autorizada"
 filtroAuth -> modResultados "Delega solicitud autorizada"
 modIdentidad -> bd "Usuarios, roles y sesiones" "SQL/TLS"
 modPortafolio -> bd "Versiones del portafolio" "SQL/TLS"
 modOportunidades -> bd "Oportunidades y perfiles" "SQL/TLS"
 modOportunidades -> docs "Guarda documentos cargados" "HTTPS"
 modAnalisis -> bd "Tareas y requisitos revisados" "SQL/TLS"
 modReglas -> bd "Reglas versionadas" "SQL/TLS"
 modResultados -> bd "Resultados y decisiones" "SQL/TLS"
 modResultados -> docs "Descarga informes" "HTTPS"
 modAnalisis -> publicador "Solicita análisis o reanudación"
 modPortafolio -> publicador "Solicita reindexación"
 publicador -> cola "Publica trabajo" "AMQP/TLS"
 modIdentidad -> auditoriaApi "Registra cambios de acceso"
 modReglas -> auditoriaApi "Registra cambios de reglas"
 modResultados -> auditoriaApi "Registra decisiones"
 auditoriaApi -> bd "Anexa eventos" "SQL/TLS"

 # ------------------------------------------------------------------
 # Relaciones de Nivel 3: Trabajador de análisis multi-agente
 # ------------------------------------------------------------------
 cola -> consumidor "Entrega trabajos" "AMQP/TLS"
 consumidor -> orquestador "Inicia o reanuda el flujo"
 consumidor -> indexador "Entrega trabajos de indexación"
 orquestador -> checkpoints "Guarda y recupera estado por etapa"
 checkpoints -> bd "Persiste checkpoints" "SQL/TLS"
 orquestador -> adaptadorSecop "Recupera el expediente"
 adaptadorSecop -> secop "Descarga metadatos y documentos" "HTTPS"
 adaptadorSecop -> docs "Guarda documentos originales" "HTTPS"
 orquestador -> guardia "Sanea el contenido"
 orquestador -> segmentador "Segmenta pliegos y anexos"
 orquestador -> extractor "Solicita requisitos estructurados"
 orquestador -> evaluador "Solicita dictamen por requisito aprobado"
 orquestador -> motorPuntaje "Calcula el puntaje"
 orquestador -> recomendador "Solicita la recomendación"
 orquestador -> generadorInforme "Genera el informe"
 orquestador -> auditoriaWorker "Registra transiciones de estado"
 orquestador -> correo "Notifica revisión pendiente" "SMTP/TLS"
 evaluador -> recuperador "Busca evidencias"
 recuperador -> bd "Consulta índice vectorial" "SQL/TLS"
 indexador -> pasarela "Solicita embeddings"
 indexador -> bd "Actualiza índice vectorial" "SQL/TLS"
 extractor -> pasarela "Invoca el modelo"
 evaluador -> pasarela "Invoca el modelo"
 recomendador -> pasarela "Redacta la justificación"
 pasarela -> llm "Inferencia y embeddings" "HTTPS"
 motorPuntaje -> bd "Lee reglas versionadas" "SQL/TLS"
 generadorInforme -> docs "Guarda informe inmutable" "HTTPS"
 generadorInforme -> auditoriaWorker "Registra huella SHA-256"
 auditoriaWorker -> bd "Anexa eventos encadenados" "SQL/TLS"

 # ------------------------------------------------------------------
 # Despliegue de referencia del MVP
 # ------------------------------------------------------------------
 mvp = deploymentEnvironment "MVP" {
 azure = deploymentNode "Microsoft Azure" "Suscripción dedicada a una fábrica de software (instancia de un 
solo inquilino)." "Azure" {
 region = deploymentNode "Región de Azure" "Por definir según la política de transferencia internacional 
de datos (Ley 1581 de 2012)." {
 aca = deploymentNode "Entorno de Azure Container Apps" "Red virtual privada; escalado basado en 
KEDA." "Azure Container Apps" {
 webNode = deploymentNode "Aplicación de contenedor Interfaz web" "Afinidad de sesión activada." 
"Contenedor Docker" {
 webuiInst = containerInstance webui
 }
 apiNode = deploymentNode "Aplicación de contenedor API" "Mínimo una réplica activa." "Contenedor 
Docker" {
 apiInst = containerInstance api
 }
 workerNode = deploymentNode "Aplicación de contenedor Trabajador" "Réplicas de 0 a N según la 
longitud de la cola." "Contenedor Docker" {
 workerInst = containerInstance worker
 }
 vigNode = deploymentNode "Trabajo programado de vigilancia" "Ejecución periódica." "Container 
Apps Job" {
 vigInst = containerInstance vigilancia
 }
 }
 sbNode = deploymentNode "Azure Service Bus" "Colas con cola de mensajes fallidos." "Espacio de 
nombres Standard" {
 colaInst = containerInstance cola
 }
 pgNode = deploymentNode "Azure Database for PostgreSQL" "Servidor flexible con respaldo continuo." 
"Extensión pgvector" {
 bdInst = containerInstance bd
 }
 stNode = deploymentNode "Azure Storage" "Contenedor de blobs con política de inmutabilidad para 
informes." "Blob Storage" {
 docsInst = containerInstance docs
 }
 aoai = deploymentNode "Azure OpenAI Service" "Despliegue de modelos en la misma suscripción." 
"Servicio administrado" {
 llmInst = softwareSystemInstance llm
 }
 kv = infrastructureNode "Azure Key Vault" "Custodia de secretos y claves de cifrado." "Key Vault"
 monitor = infrastructureNode "Azure Monitor" "Métricas y trazas correlacionadas por tarea (RF-043)." 
"Application Insights, OpenTelemetry"
 }
 }
 webuiInst -> kv "Obtiene el secreto de cliente OIDC" "Identidad administrada"
 webuiInst -> monitor "Emite telemetría" "OpenTelemetry"
 apiInst -> kv "Obtiene secretos" "Identidad administrada"
 workerInst -> kv "Obtiene secretos" "Identidad administrada"
 apiInst -> monitor "Emite telemetría" "OpenTelemetry"
 workerInst -> monitor "Emite telemetría" "OpenTelemetry"
 }
 }

 views {

 properties {
 "plantuml.title" "false"
 }

 terminology {
 person "Persona"
 softwareSystem "Sistema de software"
 container "Contenedor"
 component "Componente"
 deploymentNode "Nodo de despliegue"
 infrastructureNode "Nodo de infraestructura"
 relationship "Relación"
 }

 systemContext sma "N1_Contexto" "Figura: vista de contexto del sistema multi-agente (C4 Nivel 1)." {
 include *
 autoLayout tb 300 200
 }

 container sma "N2_Contenedores" "Figura: vista de contenedores (C4 Nivel 2)." {
 include *
 autoLayout tb 300 200
 }

 component api "N3_Componentes_API" "Figura: componentes de la API de aplicación (C4 Nivel 3)." {
 include *
 autoLayout lr 150 200
 }

 component worker "N3_Componentes_Trabajador" "Figura: componentes del trabajador de análisis multi-agente (C4 
Nivel 3)." {
 include *
 autoLayout lr 150 200
 }

 dynamic sma "Dinamica_Analisis" "Figura: flujo de análisis con revisión humana en el ciclo." {
 analista -> webui "Solicita el análisis de una licitación"
 webui -> api "Envía la solicitud de análisis"
 api -> cola "Encola el trabajo y responde 202 con el identificador"
 cola -> worker "Entrega el trabajo de análisis"
 worker -> secop "Recupera el expediente documental"
 worker -> llm "Extrae requisitos a través de la pasarela"
 worker -> bd "Guarda checkpoint en espera de revisión"
 worker -> correo "Notifica la revisión pendiente"
 analista -> webui "Revisa, corrige y aprueba los requisitos"
 webui -> api "Envía la aprobación"
 api -> cola "Encola la reanudación"
 cola -> worker "Entrega la reanudación"
 worker -> llm "Evalúa cada requisito aprobado"
 worker -> docs "Guarda el informe inmutable"
 worker -> bd "Registra puntaje, recomendación y huella"
 gerente -> webui "Consulta la recomendación y el informe"
 properties {
 "plantuml.sequenceDiagram" "true"
 }
 autoLayout tb 200 150
 }

 deployment sma mvp "Despliegue_MVP" "Figura: despliegue de referencia del MVP en Azure." {
 include *
 autoLayout lr 250 150
 }

 styles {
 element "Element" {
 fontSize 22
 }
 element "Person" {
 shape Person
 background #08427b
 color #ffffff
 }
 element "Software System" {
 background #1168bd
 color #ffffff
 }
 element "Container" {
 background #438dd5
 color #ffffff
 }
 element "Component" {
 background #85bbf0
 color #000000
 }
 element "Externo" {
 background #8c8c8c
 color #ffffff
 }
 element "BaseDatos" {
 shape Cylinder
 }
 element "Cola" {
 shape Pipe
 }
 element "Infrastructure Node" {
 background #ffffff
 color #000000
 }
 relationship "Relationship" {
 fontSize 20
 }
 }
 }
}
