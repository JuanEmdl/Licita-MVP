# Actualización del Documento de Trabajo de Grado II: capítulos 1 a 4 y anexos

**Para la persona que lo usa:** abre un chat nuevo con Claude, adjunta este archivo y la última
versión del documento en Word (`.docx`), y escribe: *«Lee completo el archivo de instrucciones y
aplica los cambios al documento adjunto. Entrégame el documento actualizado y el registro de
cambios»*. El apéndice A de este archivo trae el código Terraform validado para el Anexo G.
Las capturas de la interfaz real (sección 6.3) las tomas tú; Claude deja el espacio y el título.

---

## 0. Para Claude: qué se te pide

Eres el editor del documento de trabajo de grado *«Sistema multi-agente para la evaluación
estratégica de licitaciones públicas en fábricas de software colombianas»* (Universidad Católica
de Colombia, 2026). El MVP ya está implementado. Tu tarea es **actualizar los capítulos 1 a 4, las
listas y los anexos** para que el documento diga lo que el sistema hace, con los datos de este
archivo, que vienen verificados contra el código, las pruebas y la ejecución.

### 0.1 Reglas que no se negocian

1. **Límite de páginas.** El cuerpo, desde la portada hasta la bibliografía, **no puede pasar de
   100 páginas antes de los anexos**. Además falta escribir el capítulo 5 (evaluación, cuarto
   objetivo específico), las conclusiones y las recomendaciones. Por eso los capítulos 1 a 4 deben
   **quedar más cortos que hoy** (presupuesto en la sección 2). Todo detalle extenso va a un
   anexo y el cuerpo lo referencia con una frase como «El detalle se presenta en el Anexo H».
2. **No escribas el capítulo 5, las conclusiones ni las recomendaciones.** No toques su texto
   actual, salvo para renumerar referencias cruzadas. La sección 9 de este archivo trae insumos
   para cuando se escriban; no los apliques ahora.
3. **No inventes datos.** Cifras, versiones, fechas, nombres de archivo y resultados salen solo de
   este archivo o del propio documento. Si algo falta, deja una marca visible `[POR COMPLETAR: …]`
   y regístralo en el informe final.
4. **Respeta el estilo del documento:** español formal, impersonal («se construyó», «el sistema
   valida»), párrafos que justifican y no enumeran, títulos de tabla «Tabla N. Título» encima y
   «Fuente: elaboración propia.» debajo, figuras con «Notación…» y «Fuente…», citas numéricas
   `[n]` existentes sin renumerar la bibliografía. No uses viñetas donde el documento usa prosa.
5. **Numeración y referencias.** Al mover, agregar o quitar tablas, figuras o anexos, renumera en
   orden de aparición y actualiza **todas** las referencias cruzadas, el índice de contenido, la
   lista de tablas, la lista de figuras y la lista de anexos (hoy están desactualizados: la tabla
   de contenido lista apartados del capítulo 3 que ya no existen con esos números).
6. **Código en el cuerpo: ninguno.** Rutas de archivo solo cuando sirvan de evidencia (por ejemplo
   `tests/aptitud`), en fuente monoespaciada y sin abusar.
7. **Entrega:** el documento actualizado y un **registro de cambios** con: apartado, página antes y
   después, qué cambió y por qué (citando la sección de este archivo), y el **número de página en
   que empiezan los anexos** al final. Si no logras el presupuesto, dilo y propone qué más mover.

### 0.2 Estado del sistema en una frase (para orientar la redacción)

Los 43 requisitos funcionales están implementados y verificados con pruebas automatizadas; la
arquitectura se construyó como se diseñó, con desviaciones registradas y justificadas; la
infraestructura como código está escrita y validada, pero **no aplicada**; la canalización ejecuta
pruebas, funciones de aptitud y análisis de seguridad; la medición de los requisitos no funcionales
con sus umbrales queda para el capítulo 5 porque requiere el ambiente de pruebas en Azure.

---

## 1. Hechos verificados del MVP (fuente única para redactar)

| Tema | Dato verificado |
|---|---|
| Código | Python 3.12. Líneas no vacías: API 2.703; trabajador de análisis 3.111; trabajador de vigilancia 970; interfaz 3.501; código compartido 3.192 (≈13.500 en total). |
| API | 82 operaciones REST: 75 protegidas por permiso de rol y 7 de sesión o públicas (salud, inicio y cierre de sesión, OIDC, perfil propio). |
| Datos | PostgreSQL 16 con pgvector; 25 tablas (además de las de checkpoints de LangGraph). |
| Interfaz | NiceGUI 3.18 (no 2.x). Pantallas: Portafolio, Vigilancia, Oportunidades (con expediente, seguimiento, carpetas, notas, responsable y exportación CSV), Perfiles de búsqueda, Seguimiento de análisis, Revisión de requisitos, Resultados (con Detalle de la evaluación, Informe y decisión), Reglas del puntaje, Bitácora y Usuarios (con Diagnóstico de servicios y cuota). Campana de notificaciones en todas. |
| Identidad | OpenID Connect con Microsoft Entra ID: la interfaz es cliente confidencial (flujo de código con PKCE, `state` y `nonce`); la API valida el id_token y abre una **sesión propia de Licita** (inactividad, cierre y corte inmediato al deshabilitar). El rol y el estado se administran en Licita, no en Entra ID. Verificado con el App Registration real de la universidad. Existe además un modo local con usuario y contraseña, solo para demostraciones. |
| Modelos | Azure OpenAI (Azure AI Foundry) con **gpt-5-mini** para extracción, evaluación y redacción, y **text-embedding-3-small** (1536 dimensiones) para el portafolio. Toda invocación pasa por la pasarela (cuota de tokens, anonimización, reintentos, disyuntor y telemetría). |
| Evaluación del extractor | Script `scripts/evaluar_extractor.py`, 3 casos (pliego de ejemplo, ficha de SECOP con ruido y pliego largo de dos fragmentos) × 5 corridas con gpt-5-mini. Instrucciones 2.0.0: 86,5 % de requisitos encontrados, estabilidad 46,7 %, 4,5 requisitos espurios por corrida. Instrucciones 2.1.0: 100 % encontrados, estabilidad entre 93,3 % y 100 %, entre 0 y 0,4 espurios por corrida. **No se hizo una comparación entre modelos**: se comparó la versión de las instrucciones sobre un mismo modelo. |
| SECOP II | Datos Abiertos: procesos (`p6dx-8zbt`) y documentos (`dmgg-8hin`). Barrido real de 500 procesos. SECOP II responde **403** a la descarga automática de los archivos: el sistema lista los documentos, los marca como faltantes con el motivo y el analista los carga a mano (RF-022). |
| Paralelismo | Fragmentos (extracción) y requisitos (evaluación) en paralelo, 4 llamadas simultáneas por defecto (`ANALISIS_PARALELISMO`), con el mismo resultado que en serie. |
| Informe | PDF sellado con huella SHA-256, emisión atómica con la bitácora, verificación por la API y copia en Blob Storage con política de inmutabilidad (90 días). |
| Bitácora | Encadenada por huellas; disparadores en PostgreSQL impiden UPDATE, DELETE y TRUNCATE. |
| Pruebas | 590 pruebas automatizadas (577 sin base de datos + 13 de integración contra PostgreSQL), todas en verde. Cobertura: 97 % en el núcleo de dominio, 60 % en todo el código (la interfaz pesa en el total). |
| Funciones de aptitud | FF-02 a FF-06 y FF-08 automatizadas en `tests/aptitud`; FF-05 genera 225 combinaciones rol-operación desde las rutas reales; FF-01 escrita con Locust (requiere el ambiente de pruebas); FF-07 con Bandit y pip-audit. |
| Seguridad estática | Bandit: 0 hallazgos de severidad media o alta (uno real de severidad media se corrigió: el análisis de XML de DOCX y XLSX cargados ahora rechaza DTD y entidades). pip-audit: 0 vulnerabilidades conocidas. |
| Infraestructura | Terraform 1.9.8 con azurerm 4.81: `terraform validate` exitoso y formato verificado. **No se ha aplicado** en la suscripción (crédito agotado, ver Tabla 21). |
| Canalización | Azure DevOps: pruebas con PostgreSQL de servicio, cobertura mínima del dominio (90 %), funciones de aptitud, validación de Terraform, Bandit y pip-audit en cada solicitud de incorporación y cada integración a `main` y `develop`; FF-07 también semanal; construcción de las cuatro imágenes con `az acr build`; despliegue con Terraform en pruebas y, con aprobación manual, en producción. FF-01 en una canalización aparte al cierre de sprint. |
| Repositorio | Azure Repos. Ramas `main` y `develop` protegidas, ramas `feature/*` y `fix/*`; solicitud de incorporación con aprobación del otro integrante (el voto del autor no cuenta), canalización en verde, comentarios resueltos y vínculo con la historia; fusión por *squash*. Políticas en `infra/devops/politicas_rama.sh`, guía en `CONTRIBUTING.md`, plantilla de solicitud con la definición de terminado. |
| Métricas de Martin (Tabla 24 medida) | Núcleo de dominio: Ca 7, Ce 0, I 0,00, A 0,27. Adaptadores de integración: Ca 22, Ce 10, I 0,31, A 0,00. Módulos de la API: Ca 2, Ce 21, I 0,91, A 0,00. Motor de puntaje: Ca 2, Ce 1, I 0,33, A 0,00. Script reproducible: `scripts/metricas_acoplamiento.py`. |
| Núcleo de dominio explícito | `src/worker_analysis/nucleo`: los puertos de la Figura 12 como protocolos (modelo de lenguaje, expediente, almacén de documentos, cola, registro de informes, auditoría) y la máquina de estados de la Figura 15 con las prohibiciones de la Tabla 18; una prueba verifica que cada adaptador cumple su puerto. |

### 1.1 Desviaciones del diseño durante la implementación (deben quedar registradas)

| Id | Desviación | Razón |
|---|---|---|
| DV-01 | Los documentos del pliego se cargan a mano. | SECOP II responde 403 a la descarga automática; Datos Abiertos sí publica la lista y el enlace de cada documento. |
| DV-02 | Los requisitos cambiados se detectan por la publicación de documentos (adendas, pliegos, anexos). | Datos Abiertos no publica los requisitos como datos estructurados. |
| DV-03 | Tras una adenda solo vuelven a revisión los requisitos afectados (HU-06 CA-03), con una regla determinista por numerales. | Evita repetir toda la revisión; ante la duda marca el requisito. |
| DV-04 | Una sola cola de trabajos con el tipo en el mensaje, en lugar de tres colas. | Menos recursos y la misma garantía de entrega e idempotencia. |
| DV-05 | Las novedades no viajan por la cola: el notificador está en el mismo trabajador de vigilancia y lee una bandeja persistente (tabla `notificaciones`) que evita avisos repetidos. | Coherente con la Figura 11. |
| DV-06 | La decisión comercial conserva historial (por ejemplo, «Solicitar información» y luego «Continuar») en `POST /resultados/{tarea_id}/decision`, en lugar de una sola decisión con 409. | Trazabilidad ante el comité; el tablero muestra la última. |
| DV-07 | Tras validar el id_token, la API abre una sesión propia de Licita. | Sin ella no se cumplen RNF-010 ni RF-004 (corte inmediato al deshabilitar). |
| DV-08 | Service Bus nivel Standard con acceso público autenticado (SAS y TLS), no por punto de conexión privado. | Los puntos de conexión privados de Service Bus exigen el nivel Premium, fuera del presupuesto. |
| DV-09 | Key Vault y Storage restringidos por punto de conexión de servicio de la subred de aplicaciones (no puntos de conexión privados); PostgreSQL sí es privado (subred delegada y DNS privado). | Costo; la restricción de red se activa en producción. |
| DV-10 | No se implementó la salida con dirección IP fija. | Requiere NAT Gateway (costo fijo mensual); queda como deuda técnica. |
| DV-11 | El expediente vive en un recurso compartido de Azure Files; Blob Storage guarda solo los informes inmutables. | La API, el trabajador y la vigilancia comparten los archivos cargados. |
| DV-12 | Los cambios de esquema son sentencias aditivas e idempotentes (`ADD COLUMN IF NOT EXISTS`), no migraciones reversibles. | Nunca se borra ni renombra una columna, así que no hay nada que revertir. |
| DV-13 | La evaluación del extractor comparó versiones de instrucciones, no modelos. | Se fijó gpt-5-mini por disponibilidad en la suscripción y salida estructurada. |

---

## 2. Presupuesto de páginas

**Situación actual (PDF de la última versión):** el cuerpo llega a la página 96 y los anexos empiezan
en la 97. Las páginas **83 y 90 están en blanco** (saltos antes de los capítulos 4 y 5). El
capítulo 3 ocupa las páginas 43 a 82 (40 páginas), el capítulo 4 las 84 a 89 y el capítulo 5 las 91
a 93; las conclusiones y recomendaciones (94 y 95) son plantillas.

**Meta:** que el capítulo 4 termine **a más tardar en la página 84**, para dejar unas 16 páginas al
capítulo 5 (que hoy solo tiene el plan), las conclusiones, las recomendaciones y la bibliografía.

**Ahorros a aplicar, en este orden** (estimaciones; verifica el resultado real):

| # | Acción | Ahorro aprox. |
|---|---|---|
| 1 | Quitar las dos páginas en blanco (83 y 90): los capítulos empiezan en página nueva sin hoja vacía. | 2 |
| 2 | Eliminar los **párrafos gemelos** (sección 3.1 de este archivo). | 2,5 |
| 3 | Mover las Tablas 20, 21 y 22 (dimensionamiento, crédito e inventario de costos) al Anexo E y dejar un párrafo con la cifra total y el riesgo del crédito. | 2,5 |
| 4 | Mover la Tabla 26 (matriz de trazabilidad) al Anexo E y dejar el párrafo de las exclusiones. | 1,5 |
| 5 | Mover las Tablas 23 y 24 (deuda técnica y acoplamiento) al Anexo E con un párrafo que resuma la deuda vigente y las métricas medidas. | 1,5 |
| 6 | Mover la Tabla 14 (marcos de interfaz web) al Anexo E. | 0,8 |
| 7 | Dejar las Figuras 18 y 19 solo en el Anexo C (ya están ampliadas allí) y conservar en el cuerpo el texto de las tres reglas de tráfico. | 1 |
| 8 | Capítulo 4: la Figura 21 (panel de maquetas) y el texto del prototipo pasan al Anexo F; el cuerpo describe la interfaz construida (sección 6). | 1,5 |

Con esto los capítulos 1 a 4 bajan unas 13 páginas y el capítulo 4 nuevo cabe en unas 7.
**No recortes el capítulo 2 ni las decisiones arquitectónicas (3.7 a 3.13):** son el núcleo de los
objetivos 1 y 2.

---

## 3. Correcciones transversales (aplicar en todo el documento)

### 3.1 Párrafos gemelos

Cuando una tabla se movió al Anexo E se agregó un párrafo nuevo que la resume, pero el párrafo
anterior se quedó, de modo que la misma idea se dice dos veces seguidas. **Conserva el que menciona
el anexo** y fusiona en él cualquier dato que solo esté en el otro. Casos detectados:

| Apartado | Página | Idea repetida |
|---|---|---|
| 2.8 Criterios de aceptación y verificación INVEST | 37 | «Las diez historias superaron la revisión INVEST…» / «La Tabla 36 deja constancia…» |
| 2.10 Reglas de negocio | 38 | «Dos reglas no admiten excepción…» (RN-04 y RN-08) |
| 3.5 Escenarios de atributos de calidad | 47-48 | Los quince escenarios y la explicación de la medida |
| 3.20 Contratos de las interfaces | 64 | «Los códigos de error no son decoración…» y «Todo mensaje declara su versión…» (dos veces cada uno) |
| 3.24 Diccionario de datos | 68 | Párrafo del Anexo E y párrafo de la anonimización |
| 3.29 Plan de observabilidad | 74 | «Todas las señales se emiten con OpenTelemetry…» |
| 3.30 Stack tecnológico | 74-75 | El resumen del stack y «Dos filas quedan abiertas a propósito» |
| 3.32 Análisis de amenazas | 76 | «Las dos amenazas de nivel alto con mayor probabilidad…» |
| 3.33 Controles de seguridad | 76 | «Diez de los trece controles son preventivos…» |
| 3.34 Evaluación de la arquitectura | 77 | «Los dos puntos de compromiso…» y «ninguno obliga a revisar el estilo…» |
| 3.37 Correspondencias y trazabilidad | 79 | La regla de correspondencia de la Tabla 57 |
| 3.28 Infraestructura | 74 | La última frase («El inventario detallado… queda pendiente hasta fijar la región») contradice la Tabla 22, que ya existe: elimínala. |

### 3.2 Sustituciones de términos y datos

| Dónde aparezca | Cambiar por |
|---|---|
| NiceGUI «serie 2.x» | NiceGUI 3.18 |
| «proveedor de identidad genérico», «se mantiene genérico», «por definir» (identidad) | Microsoft Entra ID mediante OpenID Connect (el diseño sigue comprometiendo el protocolo y no el producto: otra fábrica puede usar otro proveedor OIDC) |
| «GPT-4o mini» o modelo «por definir» | gpt-5-mini (Azure OpenAI) y text-embedding-3-small |
| Que el sistema «descarga» los documentos de SECOP II | Que el sistema obtiene la lista y el enlace de los documentos de Datos Abiertos, marca como faltantes los que SECOP II no entrega (403) y el analista los carga |
| «suite de doscientas pruebas de rol y operación» | Suite de 225 combinaciones rol-operación generada a partir de las rutas de la API (FF-05) |
| «tres colas» (análisis, reanudación, indexación) | Una cola de trabajos, con el tipo de trabajo en cada mensaje |
| «la selección del proveedor de identidad y de los modelos se hará en el tercer objetivo» | Lo que se seleccionó y cómo (sección 1) |

---

## 4. Capítulos 1 y 2

1. **1.6 Diseño metodológico, Fase 3 (p. 26-27).** Donde dice «pipelines de integración continua
   para la automatización de pruebas de seguridad estática», agrega en una frase: la canalización
   ejecuta además pruebas, funciones de aptitud y validación de la infraestructura como código.
2. **Tabla 2 (p. 28):** la práctica «Integración continua con seguridad» ya tiene evidencia
   concreta: políticas de rama de `main` y `develop` y la canalización `azure-pipelines.yml`.
3. **Párrafo posterior a la Tabla 3 (p. 29):** «Ninguna historia ha cerrado todavía los cinco
   criterios…». Reescríbelo así: las diez historias tienen sus pruebas automatizadas en verde y
   la revisión por pares se aplica con las políticas de rama, pero ninguna cierra todavía «versión
   desplegada en el ambiente de pruebas» ni «aceptación registrada», porque dependen del cuarto
   objetivo. El tablero conserva ese estado sin maquillarlo.
4. **2.12 Requisitos no funcionales (p. 40):** la frase de que RNF-001 «obliga a paralelizar el
   procesamiento de fragmentos» se conserva; agrega que el grado de paralelismo es un parámetro
   porque concentra el consumo de la cuota (ASR-13).
5. **Requisitos en el Anexo E (Tabla 37):** ajusta la redacción de RF-011 («obtener la lista de
   documentos publicados y su enlace; el que no se pueda obtener queda como faltante con el motivo
   para su carga manual») y de RF-019 (el cambio de requisitos se detecta por la publicación de
   documentos que los modifican: adendas, pliegos, anexos técnicos). RF-016: los canales son
   aplicación y correo, con frecuencia inmediata o resumen diario.
6. **Reglas de negocio (Tabla 38):** en RN-10, «el responsable autorizado» que amplía la cuota es el
   Administrador del Sistema (no existe un rol de Gerencia Financiera en el sistema). En RN-02,
   agrega que el modo local con contraseña existe solo para demostraciones y no se usa en pruebas
   ni en producción.
7. **Tabla 35, HU-06 CA-03:** el «Entonces» queda: «el sistema marca como pendientes de revisión
   solo los requisitos cuyo numeral cambió, que la adenda cita o cuyo documento se retiró; los demás
   conservan la aprobación y sus correcciones. Una adenda que no cita numerales devuelve toda la
   lista a revisión».

---

## 5. Capítulo 3

1. **3.17, Tabla 17 (p. 60):** en «Cola de trabajos», una sola cola con el tipo de trabajo en el
   mensaje. En «Almacén de documentos», separa: Blob Storage con política de inmutabilidad para los
   informes emitidos y Azure Files para el expediente documental (DV-11).
2. **3.20 Contratos (p. 64):** además de quitar los gemelos, deja dicho que la API usa nombres en
   snake_case y que las rutas reemplazadas se conservan como alias marcados obsoletos mientras haya
   clientes que las usen.
3. **3.22 Máquina de estados (p. 66-67):** agrega un párrafo corto: la máquina se implementó como
   pieza separada del orquestador (`MaquinaEstados` en el núcleo de dominio), con las cuatro
   prohibiciones de la Tabla 18 verificadas por FF-06. Registra dos diferencias con la Figura 15:
   Fallida se alcanza desde cualquier etapa cuando se agotan los reintentos, y una suspensión por
   cuota continúa en la etapa que quedó pendiente (Extrayendo o Evaluando); la suspensión por
   inyección no se continúa, se solicita un análisis nuevo. El registro de tareas guarda un estado
   resumido (Recibida, En proceso, Esperando revisión, Evaluando, Suspendida, Fallida, Finalizada) y
   la etapa fina se consulta en `GET /analisis/{id}` (`etapa_actual`, `etapas_cerradas`).
   Corrige la Figura 15 (y la C.15) o agrega esas dos transiciones en su nota.
4. **3.19 Diagrama de clases (p. 63):** agrega una frase: los puertos de la Figura 12 existen en el
   código como protocolos y una prueba verifica que cada adaptador los cumple. El puerto de
   repositorio se reparte entre el checkpointer de LangGraph y el registro de informes.
5. **3.23 Modelo de datos y 3.24 Diccionario (p. 67-68):** la Figura 16 debe incluir las entidades
   agregadas: `oportunidades`, `seguimientos_proceso`, `novedades_proceso`, `documentos_expediente`,
   `perfiles_busqueda`, `coincidencias_perfil`, `sincronizaciones`, `notificaciones`,
   `preferencias_notificacion`, `carpetas`, `notas_oportunidad`, `decisiones_comerciales`,
   `informes_emitidos`, `consumo_tokens`, `sesiones` y `usuarios`. Si regenerarla no es posible,
   agrega en la nota que el modelo completo de 25 tablas está en el Anexo H. En la Tabla 47 agrega
   `preferencias_notificacion.usuario` y `notificaciones.destinatario` (alta: correo, dato personal, Ley 1581).
6. **3.26 Vista de despliegue (p. 69-70):** «Azure Blob Storage conserva pliegos e informes» pasa a
   «Blob Storage conserva los informes con política de inmutabilidad y Azure Files, el expediente
   documental». La región sigue siendo un parámetro (`eastus2` en los archivos de Terraform) mientras
   se decide la transferencia internacional de datos.
7. **3.27 Topología (p. 70-71):** corrige la regla «entre segmentos» con DV-08, DV-09 y DV-10:
   PostgreSQL es privado (subred delegada y DNS privado); Key Vault y Storage se restringen a la
   subred de aplicaciones en producción; Service Bus usa TLS y credencial de acceso compartido porque
   el punto de conexión privado exige el nivel Premium; la salida con IP fija queda como deuda técnica.
8. **3.28 Infraestructura (p. 71-74):** aplica el ahorro 3 de la sección 2. En la tabla que pase al
   anexo: el modelo es gpt-5-mini, no GPT-4o mini, así que la fila de Azure OpenAI debe recalcularse
   con las tarifas vigentes de gpt-5-mini; agrega Azure Files (expediente) y la red virtual (sin
   costo). **No inventes tarifas:** si no puedes verificarlas, deja `[POR COMPLETAR: tarifa
   gpt-5-mini]` y conserva el resto.
9. **3.29 Observabilidad (p. 74):** las nueve señales están instrumentadas, incluida la longitud de la
   cola (en espera y fallidos). Las alertas de la Tabla 49 están declaradas en Terraform
   (`monitoreo.tf`) para tiempo de análisis (p90), longitud de la cola, apertura del disyuntor y
   suspensión por inyección; el 80 % de la cuota lo avisa la propia aplicación; los 403 por usuario
   se consultan en la bitácora porque la telemetría no lleva datos personales (ASR-05).
10. **3.30 Stack (p. 74-75):** NiceGUI 3.18; cierra las dos «filas abiertas»: identidad = Entra ID por
    OIDC; versiones fijadas en `requirements.txt` y verificadas por la canalización.
11. **3.31 Matriz de acceso (p. 75):** cambia la suite de doscientas pruebas por la de 225
    combinaciones (FF-05). En la Tabla 61, ver sección 7.2.
12. **3.33 Controles (p. 76):** la evidencia de C-01 es la suite FF-05; la de C-03, el contenedor
    inmutable; la de C-08, Key Vault con identidad administrada y TLS 1.2; la de C-09, DV-08 a DV-10.
13. **3.35 Deuda técnica (p. 77-78):** actualiza la Tabla 23 (y muévela al anexo según el ahorro 5):
    DT-01 **resuelta** (pantallas de Usuarios y Reglas del puntaje); DT-02 vigente (las ponderaciones
    siguen con valores provisionales hasta que el comité las apruebe, aunque ya se versionan con doble
    control); DT-03 vigente; DT-04 vigente (sin crédito para el ambiente de pruebas); DT-05 vigente;
    DT-06 **resuelta** (Terraform escrito y validado; falta aplicarlo, que depende de DT-04). Agrega
    **DT-07**: salida con IP fija no implementada (DV-10), impacto bajo, se resuelve si una fuente
    exige lista de IP permitidas. Agrega **DT-08**: suites de ASR-10 (17 de 50 casos) y ASR-03
    (sin la suite de 500 esquemas), impacto medio, se resuelven en el cuarto objetivo.
    En la Tabla 24 reemplaza lo esperado por lo **medido** (sección 1) con esta lectura: el núcleo es
    estable como se esperaba (I = 0) pero menos abstracto (A = 0,27), porque en Python los puertos son
    protocolos estructurales y el dominio usa modelos de datos concretos; los adaptadores resultaron
    más estables que lo previsto (I = 0,31) porque la API y los trabajadores comparten los
    repositorios sobre una sola base (DA-05); los módulos de la API son hojas (I = 0,91), lo esperado
    para la capa que absorbe el cambio externo; el motor de puntaje sigue aislado (depende solo de los
    esquemas, FF-04). Cambia «Los valores se medirán sobre el código en el tercer objetivo» por la
    referencia al script.
14. **3.36 Gobernanza, Tabla 25 (p. 79):** «Cambio en un modelo de datos: script de migración
    reversible» pasa a «sentencia aditiva e idempotente revisada por pares» (DV-12). Agrega que el
    procedimiento se aplica con las políticas de rama de Azure Repos (`CONTRIBUTING.md`).
15. **3.38 Resultado parcial (p. 81-82):** el párrafo de pendientes queda superado. Reemplázalo por:
    la matriz de roles se implementó según la Tabla 61; las ponderaciones de ASR-14 se versionan con
    doble control y operan con valores provisionales (DT-02); la región sigue abierta; el proveedor de
    identidad (Entra ID) y los modelos (gpt-5-mini, text-embedding-3-small) se fijaron en el tercer
    objetivo (capítulo 4). El último párrafo (interfaz y maquetas) se recorta a una frase que da paso
    al capítulo 4.

---

## 6. Capítulo 4: reestructuración

El capítulo actual describe sobre todo el diseño de la interfaz (mapa y maquetas), y la
implementación queda «para los apartados siguientes». Ahora debe contar **qué se construyó, cómo se
verificó y qué se desvió**, en unas 7 páginas, con el detalle en anexos. Estructura propuesta:

| Apartado | Contenido | Extensión |
|---|---|---|
| Introducción del capítulo | Conserva el primer párrafo. Reemplaza el segundo: el capítulo recorre la interfaz construida, los componentes y las integraciones, la seguridad en la canalización, la infraestructura como código y el estado final con sus desviaciones. | ½ p. |
| 4.1 Interfaz de usuario | Conserva la Figura 20 y la Tabla 27 actualizadas (sección 6.1). Un párrafo: la interfaz se construyó en NiceGUI sobre el sistema visual del prototipo; las maquetas y los supuestos de usabilidad pasan al Anexo F, y los supuestos se comprueban en el capítulo 5. Tabla 28 actualizada (sección 6.2) y una figura con capturas reales (sección 6.3). | 2 p. |
| 4.2 Componentes y flujo del análisis | Un párrafo por unidad de despliegue (sección 6.4) y una tabla corta «componente → ubicación en el código → requisitos → decisión». Detalle en el Anexo H. | 1½ p. |
| 4.3 Integración con las fuentes de datos y los modelos | SECOP II (DV-01, DV-02), Azure OpenAI a través de la pasarela, selección del modelo y evaluación del extractor (sección 1 y DV-13), Entra ID (DV-07). | 1 p. |
| 4.4 Seguridad desde el código y canalización | Repositorio y ramas, canalización, funciones de aptitud y análisis de seguridad (sección 6.5). Tabla 33 resumida o referenciada. | 1 p. |
| 4.5 Aprovisionamiento con Terraform | El texto actual del 4.3, corregido (sección 6.6), con la Tabla 29 actualizada. | 1 p. |
| 4.6 Estado de la implementación y desviaciones | Tabla 30 nueva (sección 6.7) y una tabla de desviaciones con DV-01 a DV-13 en una línea cada una; la justificación completa va al Anexo H. | 1 p. |

### 6.1 Figura 20 y Tabla 27

- Figura 20: la caja punteada de «pantalla pendiente» (administración) ya no aplica. Si no puedes
  editar la imagen, corrige la nota: todas las pantallas del mapa están construidas.
- Elimina el párrafo «La pantalla de administración de usuarios, roles y reglas queda sin maquetar…».
- Tabla 27, pantallas accesibles por rol (real):
  - **Analista Comercial**, inicio en Portafolio: Portafolio, Vigilancia, Oportunidades, Perfiles de
    búsqueda, Seguimiento, Revisión de requisitos, Resultados, Reglas del puntaje (consulta).
  - **Gerente Comercial**, inicio en Resultados: Portafolio (consulta), Vigilancia, Oportunidades,
    Perfiles (consulta), Seguimiento, Resultados con decisión comercial, Reglas del puntaje
    (confirma o rechaza versiones), Bitácora. Puede solicitar análisis, no aprobar requisitos.
  - **Administrador del Sistema**, inicio en Usuarios: Usuarios con Diagnóstico de servicios y
    ampliación de la cuota de tokens, Reglas del puntaje (propone versiones), Bitácora y consulta del
    resto; sin revisión de requisitos ni decisión comercial.

### 6.2 Tabla 28 (pantallas)

La tabla pasa de «Pantallas del prototipo» a «Pantallas implementadas y requisitos que
materializan». Ajustes por fila:

- **Inicio de sesión:** Entra ID por OIDC (DV-07); en demostraciones puede habilitarse además el
  inicio con correo y contraseña.
- **Sesión caducada:** la revisión de requisitos se guarda como borrador en la API, a mano y cada
  20 segundos mientras se edita, y sobrevive a la caducidad (CU-05 A1 y E1).
- **Vigilancia:** alertas del barrido real de SECOP II con afinidad frente al portafolio y fecha de la
  última sincronización exitosa.
- **Tablero de oportunidades:** suma el expediente documental con carga manual y versiones,
  seguimiento y novedades, carpetas propias, notas, responsable y exportación a CSV (RF-040, RF-041).
- **Revisión de requisitos:** suma el borrador y, tras una adenda, la columna «Revisión» que separa lo
  que conserva la aprobación de lo que vuelve a revisión (HU-06 CA-03).
- **Detalle de la evaluación:** se abre desde Resultados; muestra dictamen, evidencia y
  justificación por requisito, aporte por categoría y versiones de reglas y portafolio.
- Filas nuevas, en una línea cada una: **Perfiles de búsqueda** (RF-015, RF-017), **Seguimiento de
  análisis** (estado y etapa de cada tarea, continuar una tarea suspendida por cuota; RF-026),
  **Reglas del puntaje** (RF-032, RF-033, doble control), **Bitácora** (RF-042, verificación de la
  cadena), **Usuarios y Diagnóstico** (RF-001 a RF-004, RF-028), **Notificaciones** (RF-016,
  RF-017, RF-020).
- Elimina el párrafo del prototipo de fidelidad media y los cuatro supuestos de usabilidad del
  cuerpo: van al Anexo F con una frase que diga que se comprueban en el capítulo 5.

### 6.3 Capturas de la interfaz real (las toma la persona usuaria)

Deja una figura con un panel de capturas reales, titulada «Figura N. Pantallas implementadas del
MVP», con la nota «Capturas de la aplicación en ejecución con datos de prueba». Marca
`[POR COMPLETAR: capturas]` y lista las sugeridas: Revisión de requisitos con borrador y columna
«Revisión», Detalle de la evaluación, Oportunidades con el expediente, Resultados con la decisión,
Reglas del puntaje e inicio de sesión con Entra ID. Las capturas en tamaño completo van al Anexo F,
junto a las maquetas.

### 6.4 Texto base para 4.2 (redáctalo en prosa, sin perder datos)

- **API de aplicación (FastAPI):** 82 operaciones; el filtro de autenticación y autorización resuelve
  en el servidor el permiso de cada una (Tabla 61); responde 202 con el identificador de la tarea y
  encola el trabajo (ASR-11); 409 cuando ya existe un análisis vigente reutilizable (RF-036); 429 con
  la cuota agotada (RN-10).
- **Trabajador de análisis (LangGraph):** grafo con las etapas de la Figura 15 y checkpoints en
  PostgreSQL; guardia documental antes de cualquier llamada al modelo (ASR-10); segmentador que
  conserva documento, versión, página y sección y no parte tablas (RF-023); extractor y evaluador sin
  herramientas, con salida validada contra esquema (DA-08); compuerta humana antes de evaluar
  (ASR-12); motor de puntaje determinista con reglas versionadas (DA-09); recomendación por reglas
  con justificación redactada por el modelo; informe PDF sellado con huella y emisión atómica
  (ASR-06). Fragmentos y requisitos en paralelo. Reintentos con espera exponencial, disyuntor y paso
  a mensajes fallidos con aviso (ASR-07).
- **Trabajador de vigilancia:** sincronización con Datos Abiertos sin duplicados y registro de cada
  barrido; perfiles de búsqueda; detector de novedades de los procesos seguidos; notificador por
  aplicación y correo, inmediato o resumen diario.
- **Pasarela de modelos (DA-07):** única puerta al proveedor, también para los embeddings: cuota de
  tokens por periodo, anonimización de datos protegidos antes de salir (ASR-05), reintentos,
  disyuntor y telemetría sin contenido.
- **Datos:** 25 tablas en PostgreSQL con pgvector; bitácora encadenada de solo anexado.
- **Núcleo de dominio:** puertos y máquina de estados explícitos (sección 1).

### 6.5 Texto base para 4.4

Repositorio en Azure Repos con ramas protegidas y solicitud de incorporación obligatoria (sección 1,
fila «Repositorio»). La canalización de cada solicitud ejecuta las 590 pruebas (incluidas las 13 de
integración contra un PostgreSQL de servicio), exige 90 % de cobertura en el núcleo de dominio (hoy
97 %), corre las funciones de aptitud FF-02 a FF-06 y FF-08, valida y da formato a Terraform, y
analiza el código con Bandit y las dependencias con pip-audit (sin hallazgos). Dos hallazgos reales
salieron de esas comprobaciones y se corrigieron: FF-04 detectó que el motor de puntaje dependía del
repositorio de reglas (y de la base de datos) para leer los pesos iniciales, y Bandit detectó que la
lectura de DOCX y XLSX cargados aceptaba entidades XML. Ese es el argumento: las reglas de
arquitectura y seguridad no dependen de la memoria de quien revisa.

### 6.6 Correcciones al apartado de Terraform (hoy 4.3) y a la Tabla 29

- Versión: Terraform 1.6 o superior en el texto; la canalización usa 1.9.8 y el proveedor azurerm
  4.81. Validado con `terraform validate`; **no se ha aplicado** por falta de crédito (DT-04).
- Tabla 29: agrega `monitoreo.tf` (alertas de la Tabla 49 y grupo de acción) y
  `bootstrap/crear_backend.sh` (estado remoto; el texto ya lo menciona). `variables.tf` tiene más de
  catorce parámetros (también modelos, identidad, correo, alertas y registro de contenedores): quita
  el número o cámbialo por «parámetros agrupados por servicio».
- `main.tf`: agrega la red virtual con las dos subredes y el DNS privado de PostgreSQL, el recurso de
  Azure Files del expediente y los secretos en Key Vault leídos por referencia desde las aplicaciones.
- `apps.tf`: **cuatro** imágenes (la vigilancia tiene la suya), afinidad de sesión de la interfaz
  fijada con la CLI porque el proveedor no la expone, y escalado del trabajador por la longitud de la
  única cola.
- Entornos: `dev` con `AUTH_MODE=local` y sin Azure OpenAI propio; `pruebas` y `prod` con OIDC;
  `prod` con Key Vault y Storage restringidos a la red virtual.

### 6.7 Tabla 30 nueva: «Estado de los frentes de implementación del MVP»

| Frente | Estado | Evidencia |
|---|---|---|
| Interfaz de usuario | Construida | Diez pantallas y dos vistas de detalle en NiceGUI (Tabla 28). |
| Agentes y orquestador | Construido | Grafo con checkpoints, compuerta humana, extractor y evaluador; evaluación del extractor (100 % de requisitos encontrados). |
| Integración con SECOP II | Construida | Barrido real de 500 procesos; documentos faltantes por 403 con carga manual. |
| Motor de puntaje y reportes | Construido | Reglas versionadas con doble control; informe PDF sellado; bitácora encadenada. |
| Identidad | Construida | OIDC con Entra ID verificado con el App Registration real. |
| Infraestructura como código | Escrita y validada, sin aplicar | `infra/terraform`; aplicación pendiente del crédito (DT-04). |
| Canalización de construcción y despliegue | Construida | `azure-pipelines.yml` y `azure-pipelines-carga.yml`. |
| Repositorio y estrategia de ramas | Registrada | `CONTRIBUTING.md`, políticas de rama y plantilla de solicitud. |

Reemplaza el párrafo posterior: el único frente que condiciona al cuarto objetivo es la aplicación de
la infraestructura, que depende del crédito de la suscripción (DT-04 y riesgo R-05).

---

## 7. Anexos

### 7.1 Anexo E: tablas que se corrigen

- **Tabla 43 (MADR) y Tabla 60:** DA-14 pasa de *Propuesta* a *Aceptada*. DA-06, DA-10 y DA-12 quedan
  implementadas. Si el formato lo permite, agrega una nota que remita a las desviaciones DV-01 a DV-13
  del Anexo H.
- **Tabla 45 (API):** reemplázala por la tabla de la sección 7.3 (nombres en snake_case y rutas
  reales).
- **Tabla 46 (cola):** una sola cola, `analisis-licitaciones`; mensajes `analisis.solicitado`
  {tarea_id, licitacion_url, contenido_pliego, reglas_version, portafolio_version},
  `analisis.reanudar` {tarea_id}, `analisis.continuar` {tarea_id} (Suspendida por cuota → etapa
  pendiente) y `portafolio.indexar` {portafolio_version}; todos con `tipo_tarea` y el contexto de
  traza. Idempotentes por tarea y etapa (FF-08); hasta 10 entregas y luego cola de mensajes
  fallidos. `oportunidad.novedad` sale de la tabla (DV-05) o queda con la nota de que viaja por la
  bandeja persistente `notificaciones`.
- **Tabla 47:** agrega `preferencias_notificacion.usuario` y `notificaciones.destinatario` (alta: correo, dato personal, Ley 1581).
- **Tabla 48:** evidencias de C-01, C-03, C-08 y C-09 según el punto 12 del capítulo 3.
- **Tabla 49:** columna de umbral sin cambios; agrega una columna o una nota «Implementación»: las
  señales existen en el código y las alertas en `monitoreo.tf`, con las tres salvedades del punto 9
  del capítulo 3.
- **Tabla 58 (stack):** NiceGUI 3.18; FastAPI 0.143; LangGraph 1.2; SQLAlchemy 2.1; psycopg 3.3;
  pgvector 0.3 (cliente); pypdf 6.21 (texto por página del expediente, licencia BSD); OpenTelemetry
  1.45; pytest 9.1 con pytest-cov 7.1; Bandit 1.9.4; pip-audit 2.10.1; Locust 2.47 (solo en la
  canalización de carga); Terraform 1.9.8 con azurerm 4.81; identidad: Microsoft Entra ID (OIDC);
  modelos: gpt-5-mini y text-embedding-3-small en Azure OpenAI; almacenamiento: Blob Storage
  (informes) y Azure Files (expediente).
- **Tabla 61 (matriz de acceso):** cambios que el código ya aplica:
  - *Reglas del puntaje:* Gerente «C» pasa a «C y confirma o rechaza versiones» (el control
    adicional ya lo dice).
  - *Perfiles de búsqueda y notificaciones:* el Gerente consulta sus avisos pero no crea perfiles ni
    cambia canal o frecuencia; el Administrador edita sus perfiles y su canal. Aclara en el alcance
    que cada quien solo ve lo propio.
  - *Cuota de inferencia (RN-10):* agrega la fila: Administrador amplía la cuota; los demás no tienen
    acceso.
  - *Carga manual de documentos:* el Gerente no tiene acceso al expediente; el Administrador lo
    consulta.
  - *Carpetas y exportación:* quitar una oportunidad de una carpeta es edición (el Gerente puede);
    borrar la carpeta, solo el Analista. Las notas las ve quien consulta la oportunidad y solo su
    autor las borra; el responsable se elige entre analistas activos.
  - *Solicitud de análisis:* sin cambio (el Gerente puede solicitar); corrige la Tabla 45, que se la
    asignaba solo al Analista.

### 7.2 Anexo F

Conserva las maquetas (son el diseño del segundo objetivo) y cambia el título a «Maquetas y capturas
de la interfaz». Mueve aquí el texto del prototipo y los cuatro supuestos de usabilidad que salen del
capítulo 4 y deja `[POR COMPLETAR: capturas en tamaño completo]` para las capturas reales.

### 7.3 Tabla 45 nueva: operaciones principales de la API

| Operación | Rol autorizado | Entrada | Respuesta correcta | Errores previstos | Traza |
|---|---|---|---|---|---|
| POST /analisis/ | Analista, Gerente | { licitacion_url, contenido_pliego, forzar_nuevo } | 202 { tarea_id } | 401; 403; 409 análisis vigente reutilizable; 422; 429 cuota agotada | CU-03, RF-025, RF-036 |
| GET /analisis/{tarea_id} | Los tres roles | — | 200 { estado, etapa_actual, etapas_cerradas, puntaje, recomendacion, … } | 401; 403; 404 | CU-04, RF-026 |
| GET /analisis/{tarea_id}/requisitos | Los tres roles | — | 200 { requisitos (borrador o extraídos), extraidos, borrador, revision } | 401; 403; 404; 409 la tarea no espera revisión | CU-05, RF-029 |
| PUT /analisis/{tarea_id}/requisitos | Analista | { requisitos[], aprobar } | 200 borrador guardado o 202 flujo reanudado | 401; 403; 409 no espera revisión o lista ya aprobada; 422 esquema inválido | CU-05, RF-030 |
| GET /analisis/{tarea_id}/resultado | Los tres roles | — | 200 con puntaje, desglose, dictámenes y versiones | 401; 403; 404; 409 sin resultado | CU-06, RF-031 a RF-035 |
| GET /analisis/{tarea_id}/informe | Los tres roles | — | 200 PDF con la huella SHA-256 en la cabecera | 401; 403; 404 informe no emitido | CU-07, RF-037 |
| GET /analisis/{tarea_id}/informe/verificacion | Los tres roles | — | 200 { huella_registrada, huella_actual, coincide } | 401; 403; 404 | ASR-06 |
| POST /resultados/{tarea_id}/decision | Gerente | { decision, justificacion } | 201 decisión registrada (conserva historial) | 401; 403; 404; 409 tarea no finalizada; 422 justificación faltante | CU-08, RF-039 |
| POST /portafolio/versiones | Analista | { capacidades[] } | 201 con la versión creada | 401; 403; 422 esquema inválido | CU-01, RF-008, RF-009 |
| PUT /reglas-puntaje/ | Administrador (propone) | { ponderaciones, umbral_ofertar, umbral_revision, nota } | 201 versión propuesta | 401; 403; 422 las ponderaciones no suman 100 | CU-10, RF-032 |
| POST /reglas-puntaje/{version}/confirmar | Gerente (confirma) | — | 200 versión vigente; la anterior pasa a histórica | 401; 403; 404; 409 doble control (quien propone no confirma) | RF-033 |
| POST /auth/oidc | Público (canje) | { id_token, nonce } | 200 sesión de Licita | 401 token inválido; 403 usuario no registrado o deshabilitado | RF-005 |
| GET /resultados/oportunidades.csv | Los tres roles | filtros o selección | 200 archivo CSV | 401; 403 | RF-041 |

Nota bajo la tabla: «La API expone 82 operaciones; la lista completa con sus permisos se presenta en
el Anexo H. `GET /analisis/{tarea_id}/estado` y `POST /analisis/{tarea_id}/aprobacion` se conservan
como alias obsoletos de las dos operaciones nuevas».

### 7.4 Anexo G

Reemplaza el código por el del **apéndice A** de este archivo (es el que se validó). Actualiza el
párrafo introductorio: Terraform 1.6 o superior y proveedor azurerm 4.81; los comandos de
aplicación no cambian; el código está validado y formateado, y su aplicación queda pendiente del
crédito. Agrega G.9 `monitoreo.tf` y G.10 `bootstrap/crear_backend.sh`.

### 7.5 Anexo H nuevo: «Detalle de la implementación del MVP»

Crea este anexo (después del G) y referéncialo desde el capítulo 4. Contenido:

- **H.1 Estructura del repositorio:** la tabla de carpetas de `CONTRIBUTING.md` (sección 8).
- **H.2 Operaciones de la API:** las 82 rutas con método y roles (sección 8).
- **H.3 Modelo de datos:** las 25 tablas con una línea de propósito cada una (sección 8).
- **H.4 Desviaciones del diseño:** DV-01 a DV-13 con su razón completa (sección 1.1).
- **H.5 Inventario de pruebas y funciones de aptitud:** sección 9 (solo el inventario, sin resultados
  de medición de los RNF).
- **H.6 Evaluación del extractor:** la tabla de la sección 1 con los dos resultados por versión de
  instrucciones.

---

## 8. Datos para el Anexo H

### 8.1 Estructura del repositorio

| Carpeta | Contenido |
|---|---|
| `src/api` | API de aplicación: filtro de autenticación y autorización y módulos de identidad, portafolio, oportunidades, análisis, resultados, notificaciones, auditoría y consumo. |
| `src/worker_analysis` | Trabajador de análisis: núcleo de dominio (puertos y máquina de estados), orquestador, agentes, pasarela de modelos, procesamiento documental, motor de puntaje e informes. |
| `src/worker_vigilance` | Trabajador de vigilancia: sincronización con SECOP II, detector de novedades, perfiles y notificador. |
| `src/webui` | Interfaz web y cliente confidencial OIDC. |
| `src/shared` | Modelos, repositorios, configuración, roles, telemetría y esquemas de dominio. |
| `tests` | Pruebas unitarias, de escenarios arquitectónicos, de integración, funciones de aptitud y carga. |
| `infra/terraform`, `infra/devops` | Infraestructura como código y políticas de rama. |
| `docker`, `architecture`, `scripts`, `data` | Imágenes, diagramas C4, utilidades y datos de ejemplo y de evaluación. |

### 8.2 Operaciones de la API (método, ruta, roles: An Analista, Ge Gerente, Ad Administrador)

Análisis: GET /analisis/ (An, Ge, Ad); POST /analisis/ (An, Ge); GET /analisis/{tarea_id} (An, Ge,
Ad); GET /analisis/{tarea_id}/estado (An, Ge, Ad; obsoleta); GET y PUT /analisis/{tarea_id}/requisitos
(consulta los tres; PUT An); POST /analisis/{tarea_id}/aprobacion (An; obsoleta); POST
/analisis/{tarea_id}/continuar (An, Ge); GET /analisis/{tarea_id}/resultado, /informe,
/informe/texto e /informe/verificacion (An, Ge, Ad).
Resultados: GET /resultados/, /resultados/opciones y /resultados/oportunidades.csv (An, Ge, Ad); POST
/resultados/{tarea_id}/decision (Ge); GET /resultados/{tarea_id}/decisiones (An, Ge, Ad).
Oportunidades: GET /oportunidades/, /oportunidades/filtros y /oportunidades/{id_proceso} (An, Ge,
Ad); POST /oportunidades/ (An, radicar); GET /oportunidades/{id_proceso}/expediente y descarga de un
documento (An, Ad); POST .../expediente/actualizar y .../expediente/documentos (An); GET y POST
.../notas (consulta los tres; agrega An, Ge); DELETE .../notas/{nota_id} (An, autor); GET
.../novedades y POST .../novedades/revisadas (An, Ge, Ad); PUT .../responsable y GET
.../responsable/opciones (An, Ge); PUT y DELETE .../seguimiento (An).
Carpetas: GET /carpetas/ (An, Ge, Ad); POST /carpetas/, PUT /carpetas/{id}, POST
/carpetas/{id}/oportunidades y .../oportunidades/quitar (An, Ge); DELETE /carpetas/{id} (An).
Perfiles: GET /perfiles/ y /perfiles/coincidencias (An, Ge, Ad); POST /perfiles/ y DELETE
/perfiles/{id} (An); PUT /perfiles/{id} (An, Ad).
Portafolio: GET /portafolio/ y /portafolio/versiones (An, Ge, Ad); POST /portafolio/, POST
/portafolio/versiones y DELETE /portafolio/{id} (An); PUT /portafolio/{id} (An, Ad).
Reglas del puntaje: GET /reglas-puntaje/ y /reglas-puntaje/{version} (An, Ge, Ad); PUT
/reglas-puntaje/ (Ad, propone); POST /reglas-puntaje/{version}/confirmar y /rechazar (Ge).
Vigilancia: GET /vigilancia/alertas y /vigilancia/estado (An, Ge, Ad); POST
/vigilancia/alertas/{id_proceso}/analizar (An, Ge); POST .../descartar y POST /vigilancia/barrido (An).
Notificaciones: GET /notificaciones/, GET /notificaciones/preferencias, POST /notificaciones/leidas y
POST /notificaciones/{id}/leida (An, Ge, Ad); PUT /notificaciones/preferencias (An, Ad).
Administración: GET y POST /usuarios/, PATCH /usuarios/{id}, POST /usuarios/{id}/password, GET y POST
/consumo/ (ampliar) y GET /diagnostico (Ad); GET /usuarios/roles (con sesión).
Auditoría: GET /auditoria/ y /auditoria/verificacion (Ge, Ad).
Identidad: POST /auth/login, /auth/logout y /auth/oidc; GET /auth/yo y /auth/sesion (sesión
propia). Salud: GET /health (pública).

### 8.3 Las 25 tablas

`usuarios`, `sesiones` (identidad); `portafolio`, `portafolio_versiones` (portafolio versionado con
vector); `reglas_puntaje` (versiones con doble control); `licitaciones`, `tareas_analisis` (tareas
con versiones fijadas y huella de entrada); `informes_emitidos` (emisión única con huella);
`decisiones_comerciales` (historial); `bitacora_auditoria` (encadenada, solo anexado);
`consumo_tokens`, `cuotas_tokens` (cuota por periodo); `oportunidades`, `sincronizaciones`,
`alertas_oportunidad`, `seguimientos_proceso`, `novedades_proceso` (vigilancia);
`documentos_expediente` (expediente con versiones); `perfiles_busqueda`, `coincidencias_perfil`
(perfiles); `notificaciones`, `preferencias_notificacion` (avisos); `carpetas`,
`carpetas_oportunidades`, `notas_oportunidad` (organización). Los checkpoints del flujo los crea el
checkpointer de LangGraph en sus propias tablas.

---

## 9. Insumos para el capítulo 5 (no aplicar ahora)

Para cuando se escriba el capítulo 5. Sirven para no prometer de más en los capítulos 1 a 4:

| Elemento | Estado a la fecha |
|---|---|
| Nivel unitario e integración (Tabla 31) | 590 pruebas en verde; cobertura del dominio 97 %. |
| FF-02, FF-03, FF-04 | En verde (reglas de importación); FF-04 encontró y corrigió una dependencia real. |
| FF-05 | 225 combinaciones rol-operación en verde. |
| FF-06 | Máquina de estados con las cuatro prohibiciones de la Tabla 18 en verde. |
| FF-07 | Bandit y pip-audit sin hallazgos. |
| FF-08 | Idempotencia por mensaje repetido en verde. |
| FF-01, ASR-01, ASR-02 | Prueba de carga escrita (10 analistas, p90 ≤ 10 min); **sin ejecutar**: requiere el ambiente de pruebas. |
| ASR-04, ASR-07, ASR-11 | Mecanismos implementados y con pruebas unitarias; simulacro de caída, inyección de fallas y percentil del 202 **sin medir**. |
| ASR-03 | Sin la suite de 500 esquemas históricos. |
| ASR-10 | 17 casos adversarios de los 50 que pide el documento. |
| ASR-05, ASR-06, ASR-09, ASR-12, ASR-13 | Medidos con pruebas automatizadas (ver CAMBIOS.md y ALINEACION_DOCUMENTO.md del repositorio). |
| Supuestos de usabilidad (Anexo F) | Sin evaluar con participantes. |

---

## 10. Lista de verificación final (Claude la completa en su informe)

- [ ] Los anexos empiezan en la página ___ (debe ser 101 o menos).
- [ ] El capítulo 4 termina en la página ___ (meta: 84 o menos).
- [ ] No quedan párrafos gemelos de la sección 3.1.
- [ ] No queda «NiceGUI 2.x», «GPT-4o mini», «proveedor de identidad genérico», «tres colas» ni «suite de doscientas pruebas».
- [ ] Índice de contenido, listas de tablas, figuras y anexos regenerados y coherentes con la numeración.
- [ ] Todas las referencias cruzadas a tablas y figuras movidas apuntan al anexo correcto.
- [ ] Las marcas `[POR COMPLETAR: …]` están listadas en el informe.
- [ ] El capítulo 5, las conclusiones y las recomendaciones no se modificaron.

---

## Apéndice A. Código Terraform para el Anexo G

Transcríbelo tal cual en el Anexo G, un subapartado por archivo, en fuente monoespaciada.

### A.1 backend.tf

```hcl
# backend.tf - Estado remoto compartido por el equipo (apartado 4.3, Anexo G.1).
# La cuenta de almacenamiento del estado se crea una sola vez, fuera de este código,
# con bootstrap/crear_backend.sh: el estado no puede depender del propio estado.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "azurerm" {
    resource_group_name  = "rg-licita-tfstate"
    storage_account_name = "stlicitatfstate"
    container_name       = "tfstate"
    # La clave se pasa por entorno:
    # terraform init -backend-config="key=licita-dev.tfstate"
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
  }
  subscription_id = var.subscription_id
}
```

### A.2 variables.tf

```hcl
# variables.tf - Parámetros que cambian entre entornos (Anexo G.2).
# Los valores por entorno viven en entornos/*.tfvars; los secretos se pasan por la
# canalización (TF_VAR_*) y nunca se escriben en estos archivos.

variable "subscription_id" {
  description = "Identificador de la suscripción de Azure de la fábrica de software."
  type        = string
}

variable "entorno" {
  description = "Entorno de despliegue: dev, pruebas o prod."
  type        = string
  validation {
    condition     = contains(["dev", "pruebas", "prod"], var.entorno)
    error_message = "El entorno debe ser dev, pruebas o prod."
  }
}

variable "ubicacion" {
  description = "Región de Azure. Queda parametrizada porque depende de la política de transferencia de datos (Ley 1581 de 2012)."
  type        = string
}

variable "prefijo" {
  description = "Prefijo de nombres de recurso."
  type        = string
  default     = "licita"
}

variable "sku_postgres" {
  description = "Referencia de cómputo del servidor flexible de PostgreSQL."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "almacenamiento_postgres_mb" {
  description = "Almacenamiento aprovisionado para PostgreSQL, en megabytes."
  type        = number
  default     = 32768
}

variable "worker_replicas_min" {
  description = "Réplicas mínimas del trabajador de análisis. Cero permite escalar a cero fuera de uso."
  type        = number
  default     = 0
}

variable "worker_replicas_max" {
  description = "Réplicas máximas del trabajador de análisis."
  type        = number
  default     = 4
}

variable "longitud_cola_por_replica" {
  description = "Mensajes en cola que disparan una réplica adicional (regla KEDA, ASR-08)."
  type        = number
  default     = 5
}

variable "retencion_respaldo_dias" {
  description = "Días de retención del respaldo de PostgreSQL (RPO, ASR-04)."
  type        = number
  default     = 7
}

variable "desplegar_openai" {
  description = "Crea el recurso de Azure OpenAI. En dev suele quedar en false y se reutiliza el de pruebas."
  type        = bool
  default     = true
}

variable "imagen_api" {
  description = "Imagen del contenedor de la API, publicada por la canalización."
  type        = string
}

variable "imagen_web" {
  description = "Imagen del contenedor de la interfaz web."
  type        = string
}

variable "imagen_worker" {
  description = "Imagen del trabajador de análisis."
  type        = string
}

variable "imagen_vigilancia" {
  description = "Imagen del trabajador de vigilancia (docker/worker_vigilance.Dockerfile)."
  type        = string
}

variable "registro" {
  description = "Registro de contenedores existente donde la canalización publica las imágenes."
  type = object({
    nombre = string
    grupo  = string
  })
  default = {
    nombre = "acrlicitacioneslicita01"
    grupo  = "rg-licitaciones-mvp"
  }
}

variable "max_entregas_mensaje" {
  description = "Entregas de un mensaje antes de pasar a la cola de mensajes fallidos (SERVICE_BUS_MAX_ENTREGAS)."
  type        = number
  default     = 10
}

variable "acceso_publico_almacenes" {
  description = "Permite llegar a Key Vault y Storage desde fuera de la red virtual (necesario si la canalización aplica desde un agente hospedado). En prod va en false (C-09)."
  type        = bool
  default     = true
}

# --- Modelo de lenguaje (DA-07) ---

variable "modelo_chat" {
  description = "Despliegue del modelo de chat en Azure OpenAI (AZURE_OPENAI_DEPLOYMENT). La versión debe existir en la región."
  type = object({
    nombre    = string
    version   = string
    capacidad = number
  })
  default = {
    nombre    = "gpt-5-mini"
    version   = "2025-08-07"
    capacidad = 50
  }
}

variable "modelo_embeddings" {
  description = "Despliegue de embeddings (1536 dimensiones, AZURE_OPENAI_EMBEDDING_DEPLOYMENT)."
  type = object({
    nombre    = string
    version   = string
    capacidad = number
  })
  default = {
    nombre    = "text-embedding-3-small"
    version   = "1"
    capacidad = 50
  }
}

variable "azure_openai_endpoint" {
  description = "Endpoint de un Azure OpenAI existente cuando desplegar_openai = false."
  type        = string
  default     = ""
}

variable "azure_openai_clave" {
  description = "Clave del Azure OpenAI existente cuando desplegar_openai = false (TF_VAR_azure_openai_clave)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "cuota_tokens_periodo" {
  description = "Tokens permitidos por periodo mensual (RF-028, ASR-13). 0 = sin límite."
  type        = number
  default     = 5000000
}

# --- Identidad (DA-10) ---

variable "auth_mode" {
  description = "oidc en pruebas y producción (RN-02); local solo para demostraciones."
  type        = string
  default     = "oidc"
}

variable "oidc_authority" {
  description = "Autoridad del App Registration, p. ej. https://login.microsoftonline.com/<inquilino>/v2.0."
  type        = string
  default     = ""
}

variable "oidc_client_id" {
  description = "Id. de aplicación (cliente) del App Registration."
  type        = string
  default     = ""
}

variable "oidc_client_secret" {
  description = "Secreto del App Registration (TF_VAR_oidc_client_secret). Se guarda en Key Vault."
  type        = string
  default     = ""
  sensitive   = true
}

variable "admin_email" {
  description = "Correo institucional del primer administrador (ADMIN_EMAIL)."
  type        = string
  default     = ""
}

# --- Correo (RF-016, RF-017, RF-020) ---

variable "smtp" {
  description = "Servidor de correo para las notificaciones. Vacío: solo avisos en la aplicación."
  type = object({
    host      = string
    puerto    = number
    usuario   = string
    remitente = string
    seguridad = string
  })
  default = {
    host      = ""
    puerto    = 587
    usuario   = ""
    remitente = ""
    seguridad = "starttls"
  }
}

variable "smtp_clave" {
  description = "Contraseña del servidor de correo (TF_VAR_smtp_clave). Se guarda en Key Vault."
  type        = string
  default     = ""
  sensitive   = true
}

# --- Observabilidad (Tabla 49) ---

variable "correos_alertas" {
  description = "Correos del equipo técnico que reciben las alertas de la Tabla 49."
  type        = list(string)
  default     = []
}

variable "etiquetas" {
  description = "Etiquetas comunes a todos los recursos."
  type        = map(string)
  default = {
    proyecto = "licita-mvp-multiagente"
    origen   = "terraform"
  }
}
```

### A.3 main.tf

```hcl
# main.tf - Recursos del inventario de infraestructura del MVP (apartado 3.28, Anexo G.3).
#
# Diferencias con el Anexo G, para que la infraestructura coincida con el código:
# - Una sola cola (analisis-licitaciones): el tipo de trabajo viaja en el mensaje (Tabla 46).
# - Red virtual con subred delegada para PostgreSQL: con acceso público desactivado, el
#   servidor solo es alcanzable desde las Container Apps (C-09).
# - Los secretos se guardan en Key Vault y las Container Apps los leen por referencia con la
#   identidad administrada; el código los recibe como variables de entorno (ASR-05).
# - El expediente documental vive en un recurso compartido de Azure Files (lo escriben la API
#   y la vigilancia, lo lee el trabajador); los informes, en Blob Storage inmutable (DA-06).

locals {
  nombre     = "${var.prefijo}-${var.entorno}"
  nombre_san = replace("${var.prefijo}${var.entorno}", "-", "")
  # Sufijo para los nombres que deben ser únicos en todo Azure.
  unico     = random_string.sufijo.result
  etiquetas = merge(var.etiquetas, { entorno = var.entorno })
}

resource "random_string" "sufijo" {
  length  = 4
  upper   = false
  special = false
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.nombre}"
  location = var.ubicacion
  tags     = local.etiquetas
}

# --- Identidad administrada: evita credenciales en la configuración (ASR-05) ---

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  tags                = local.etiquetas
}

# --- Observabilidad (RF-043) ---

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.etiquetas
}

resource "azurerm_application_insights" "appi" {
  name                = "appi-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  workspace_id        = azurerm_log_analytics_workspace.logs.id
  application_type    = "web"
  tags                = local.etiquetas
}

# --- Red privada (C-09): las aplicaciones y la base de datos no se exponen ---

resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  address_space       = ["10.20.0.0/16"]
  tags                = local.etiquetas
}

resource "azurerm_subnet" "apps" {
  name                 = "snet-apps"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.20.0.0/23"]
  service_endpoints    = ["Microsoft.KeyVault", "Microsoft.Storage"]
  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.20.2.0/24"]
  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.etiquetas
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "vnet-${local.nombre}"
  resource_group_name   = azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
}

# --- Mensajería: cola de trabajos (DA-04, Tabla 46) ---

resource "azurerm_servicebus_namespace" "sb" {
  name                = "sb-${local.nombre}-${local.unico}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Standard"
  minimum_tls_version = "1.2"
  tags                = local.etiquetas
}

resource "azurerm_servicebus_queue" "trabajos" {
  name         = "analisis-licitaciones"
  namespace_id = azurerm_servicebus_namespace.sb.id
  # Agotadas las entregas, el mensaje pasa a la cola de mensajes fallidos (ASR-07, C-13).
  max_delivery_count                   = var.max_entregas_mensaje
  lock_duration                        = "PT5M"
  dead_lettering_on_message_expiration = true
}

# El código se conecta con cadena de conexión (azure-servicebus). Manage permite leer la
# longitud de la cola para la métrica de la Tabla 49 y para la regla de escalado.
resource "azurerm_servicebus_namespace_authorization_rule" "app" {
  name         = "licita-app"
  namespace_id = azurerm_servicebus_namespace.sb.id
  listen       = true
  send         = true
  manage       = true
}

# --- Persistencia: PostgreSQL con pgvector (DA-05) ---

resource "random_password" "pg" {
  length = 32
  # Solo caracteres que no hay que escapar en la cadena de conexión.
  special          = true
  override_special = "-_~"
}

resource "azurerm_postgresql_flexible_server" "pg" {
  name                          = "psql-${local.nombre}-${local.unico}"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  version                       = "16"
  sku_name                      = var.sku_postgres
  storage_mb                    = var.almacenamiento_postgres_mb
  backup_retention_days         = var.retencion_respaldo_dias
  administrator_login           = "licitaadmin"
  administrator_password        = random_password.pg.result
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  tags                          = local.etiquetas

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]

  lifecycle {
    # Azure elige la zona de disponibilidad; no se fuerza en cada plan.
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "db" {
  name      = "licita"
  server_id = azurerm_postgresql_flexible_server.pg.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# pgvector se habilita como extensión permitida del servidor.
resource "azurerm_postgresql_flexible_server_configuration" "extensiones" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.pg.id
  value     = "VECTOR,PGCRYPTO"
}

# --- Almacenamiento: expediente documental e informes inmutables (DA-06) ---

resource "azurerm_storage_account" "st" {
  name                            = substr("st${local.nombre_san}${local.unico}", 0, 24)
  resource_group_name             = azurerm_resource_group.rg.name
  location                        = azurerm_resource_group.rg.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  tags                            = local.etiquetas

  network_rules {
    default_action             = var.acceso_publico_almacenes ? "Allow" : "Deny"
    bypass                     = ["AzureServices"]
    virtual_network_subnet_ids = [azurerm_subnet.apps.id]
  }
}

resource "azurerm_storage_container" "informes" {
  name                  = "informes"
  storage_account_id    = azurerm_storage_account.st.id
  container_access_type = "private"
}

# Política de inmutabilidad de los informes emitidos (ASR-06, C-03): lo escrito no se
# modifica ni se borra durante el periodo. ALMACEN_INFORMES_URL apunta a este contenedor.
resource "azurerm_storage_container_immutability_policy" "informes" {
  storage_container_resource_manager_id = azurerm_storage_container.informes.id
  immutability_period_in_days           = 90
  protected_append_writes_all_enabled   = false
}

# Expediente documental (RF-021, RF-022): montado en /app/data/expedientes.
resource "azurerm_storage_share" "expedientes" {
  name               = "expedientes"
  storage_account_id = azurerm_storage_account.st.id
  quota              = 50
}

# --- Secretos y claves (ASR-05, C-08) ---

data "azurerm_client_config" "actual" {}

resource "azurerm_key_vault" "kv" {
  name                       = substr("kv-${local.nombre}-${local.unico}", 0, 24)
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  tenant_id                  = data.azurerm_client_config.actual.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = var.entorno == "prod"
  soft_delete_retention_days = 7
  tags                       = local.etiquetas

  network_acls {
    default_action             = var.acceso_publico_almacenes ? "Allow" : "Deny"
    bypass                     = "AzureServices"
    virtual_network_subnet_ids = [azurerm_subnet.apps.id]
  }
}

# Quien aplica Terraform (la canalización) escribe los secretos; la aplicación solo los lee.
resource "azurerm_role_assignment" "kv_escritura_despliegue" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.actual.object_id
}

resource "random_password" "sesion" {
  length  = 48
  special = false
}

locals {
  openai_endpoint = var.desplegar_openai ? azurerm_cognitive_account.openai[0].endpoint : var.azure_openai_endpoint
  openai_clave    = var.desplegar_openai ? azurerm_cognitive_account.openai[0].primary_access_key : var.azure_openai_clave

  # Nombre del secreto en Key Vault => valor. Los opcionales se crean solo si se configuraron;
  # la lista de nombres no depende de valores sensibles para poder usarla en for_each.
  valores_secretos = {
    "postgres-admin-password" = random_password.pg.result
    "db-conexion"             = "postgresql://licitaadmin:${random_password.pg.result}@${azurerm_postgresql_flexible_server.pg.fqdn}:5432/${azurerm_postgresql_flexible_server_database.db.name}?sslmode=require"
    "service-bus-conexion"    = azurerm_servicebus_namespace_authorization_rule.app.primary_connection_string
    "sesion-secreto"          = random_password.sesion.result
    "openai-clave"            = local.openai_clave
    "oidc-secreto"            = var.oidc_client_secret
    "smtp-clave"              = var.smtp_clave
  }
  nombres_secretos = concat(
    ["postgres-admin-password", "db-conexion", "service-bus-conexion", "sesion-secreto"],
    var.desplegar_openai || var.azure_openai_endpoint != "" ? ["openai-clave"] : [],
    var.oidc_client_id != "" ? ["oidc-secreto"] : [],
    var.smtp.host != "" ? ["smtp-clave"] : [],
  )
}

resource "azurerm_key_vault_secret" "secretos" {
  for_each     = toset(local.nombres_secretos)
  name         = each.value
  value        = local.valores_secretos[each.value]
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.kv_escritura_despliegue]
}

# --- Permisos de la identidad de la aplicación ---

resource "azurerm_role_assignment" "kv_lectura" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Sube los informes al contenedor inmutable (ALMACEN_INFORMES_URL) y los lee.
resource "azurerm_role_assignment" "storage_escritura" {
  scope                = azurerm_storage_container.informes.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

data "azurerm_container_registry" "acr" {
  name                = var.registro.nombre
  resource_group_name = var.registro.grupo
}

resource "azurerm_role_assignment" "acr_descarga" {
  scope                = data.azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# --- Inferencia (DA-07) ---

resource "azurerm_cognitive_account" "openai" {
  count                 = var.desplegar_openai ? 1 : 0
  name                  = "oai-${local.nombre}-${local.unico}"
  resource_group_name   = azurerm_resource_group.rg.name
  location              = azurerm_resource_group.rg.location
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "oai-${local.nombre}-${local.unico}"
  tags                  = local.etiquetas
}

resource "azurerm_cognitive_deployment" "chat" {
  count                = var.desplegar_openai ? 1 : 0
  name                 = var.modelo_chat.nombre
  cognitive_account_id = azurerm_cognitive_account.openai[0].id
  model {
    format  = "OpenAI"
    name    = var.modelo_chat.nombre
    version = var.modelo_chat.version
  }
  sku {
    name     = "GlobalStandard"
    capacity = var.modelo_chat.capacidad
  }
}

resource "azurerm_cognitive_deployment" "embeddings" {
  count                = var.desplegar_openai ? 1 : 0
  name                 = var.modelo_embeddings.nombre
  cognitive_account_id = azurerm_cognitive_account.openai[0].id
  model {
    format  = "OpenAI"
    name    = var.modelo_embeddings.nombre
    version = var.modelo_embeddings.version
  }
  sku {
    name     = "Standard"
    capacity = var.modelo_embeddings.capacidad
  }
  depends_on = [azurerm_cognitive_deployment.chat]
}
```

### A.4 apps.tf

```hcl
# apps.tf - Unidades de despliegue sobre Azure Container Apps (DA-01, DA-12, Anexo G.4).
# Las variables de entorno son las que lee src/shared/config; los secretos llegan por
# referencia a Key Vault con la identidad administrada (ASR-05).

resource "azurerm_container_app_environment" "env" {
  name                       = "cae-${local.nombre}"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  infrastructure_subnet_id   = azurerm_subnet.apps.id
  tags                       = local.etiquetas
}

# Expediente documental compartido por la API, el trabajador y la vigilancia.
resource "azurerm_container_app_environment_storage" "expedientes" {
  name                         = "expedientes"
  container_app_environment_id = azurerm_container_app_environment.env.id
  account_name                 = azurerm_storage_account.st.name
  share_name                   = azurerm_storage_share.expedientes.name
  access_key                   = azurerm_storage_account.st.primary_access_key
  access_mode                  = "ReadWrite"
}

locals {
  nombre_web = "ca-web-${var.entorno}"
  nombre_api = "ca-api-${var.entorno}"
  url_web    = "https://${local.nombre_web}.${azurerm_container_app_environment.env.default_domain}"
  # Dentro del entorno, una aplicación con ingreso interno se alcanza por su nombre.
  url_api = "http://${local.nombre_api}"

  variables_comunes = {
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.appi.connection_string
    AUTH_MODE                             = var.auth_mode
    OIDC_AUTHORITY                        = var.oidc_authority
    OIDC_CLIENT_ID                        = var.oidc_client_id
    ADMIN_EMAIL                           = var.admin_email
    WEBUI_URL                             = local.url_web
    UTC_OFFSET                            = "-5"
    # DefaultAzureCredential usa la identidad asignada por el usuario (almacén de informes).
    AZURE_CLIENT_ID = azurerm_user_assigned_identity.app.client_id
  }
  variables_backend = {
    SERVICE_BUS_QUEUE_NAME            = azurerm_servicebus_queue.trabajos.name
    SERVICE_BUS_MAX_ENTREGAS          = tostring(var.max_entregas_mensaje)
    AZURE_OPENAI_ENDPOINT             = local.openai_endpoint
    AZURE_OPENAI_DEPLOYMENT           = var.modelo_chat.nombre
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = var.modelo_embeddings.nombre
    CUOTA_TOKENS_PERIODO              = tostring(var.cuota_tokens_periodo)
    EXPEDIENTES_DIR                   = "/app/data/expedientes"
    INFORMES_DIR                      = "/app/data/informes"
    ALMACEN_INFORMES_URL              = "${azurerm_storage_account.st.primary_blob_endpoint}${azurerm_storage_container.informes.name}"
  }
  variables_correo = {
    SMTP_HOST      = var.smtp.host
    SMTP_PUERTO    = tostring(var.smtp.puerto)
    SMTP_USUARIO   = var.smtp.usuario
    SMTP_REMITENTE = var.smtp.remitente
    SMTP_SEGURIDAD = var.smtp.seguridad
  }

  # Variable de entorno => secreto de Key Vault, por unidad. Solo los que existen.
  secretos_por_app = {
    web        = { SESION_SECRETO = "sesion-secreto", OIDC_CLIENT_SECRET = "oidc-secreto" }
    api        = { DB_CONNECTION_STRING = "db-conexion", SERVICE_BUS_CONNECTION_STRING = "service-bus-conexion", SESION_SECRETO = "sesion-secreto", AZURE_OPENAI_API_KEY = "openai-clave", OIDC_CLIENT_SECRET = "oidc-secreto" }
    worker     = { DB_CONNECTION_STRING = "db-conexion", SERVICE_BUS_CONNECTION_STRING = "service-bus-conexion", AZURE_OPENAI_API_KEY = "openai-clave" }
    vigilancia = { DB_CONNECTION_STRING = "db-conexion", SMTP_CLAVE = "smtp-clave" }
  }
  secretos_app = { for app, mapa in local.secretos_por_app :
  app => { for variable, secreto in mapa : variable => secreto if contains(local.nombres_secretos, secreto) } }
}

# Interfaz web: afinidad de sesión porque NiceGUI guarda estado por usuario (DA-13).
resource "azurerm_container_app" "web" {
  name                         = local.nombre_web
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = local.etiquetas
  depends_on                   = [azurerm_role_assignment.kv_lectura, azurerm_role_assignment.acr_descarga]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = toset(values(local.secretos_app.web))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.app.id
      key_vault_secret_id = azurerm_key_vault_secret.secretos[secret.value].versionless_id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2
    container {
      name   = "web"
      image  = var.imagen_web
      cpu    = 0.25
      memory = "0.5Gi"
      dynamic "env" {
        for_each = merge(local.variables_comunes, { API_URL = local.url_api })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secretos_app.web
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }
}

# El proveedor azurerm no expone la afinidad de sesión del ingreso: se fija con la CLI,
# que la canalización ya usa, cada vez que se recrea la aplicación.
resource "terraform_data" "afinidad_web" {
  triggers_replace = azurerm_container_app.web.id
  provisioner "local-exec" {
    command = "az containerapp ingress sticky-sessions set --name ${azurerm_container_app.web.name} --resource-group ${azurerm_resource_group.rg.name} --affinity sticky"
  }
}

# API: siempre una réplica activa para sostener la respuesta 202 de ASR-11.
resource "azurerm_container_app" "api" {
  name                         = local.nombre_api
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = local.etiquetas
  depends_on                   = [azurerm_role_assignment.kv_lectura, azurerm_role_assignment.acr_descarga]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = toset(values(local.secretos_app.api))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.app.id
      key_vault_secret_id = azurerm_key_vault_secret.secretos[secret.value].versionless_id
    }
  }

  ingress {
    external_enabled = false
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 3
    container {
      name   = "api"
      image  = var.imagen_api
      cpu    = 0.5
      memory = "1Gi"
      dynamic "env" {
        for_each = merge(local.variables_comunes, local.variables_backend, { CORS_ORIGINS = local.url_web })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secretos_app.api
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      volume_mounts {
        name = "expedientes"
        path = "/app/data/expedientes"
      }
      volume_mounts {
        name = "informes"
        path = "/app/data/informes"
      }
    }
    volume {
      name         = "expedientes"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.expedientes.name
    }
    # Copia local de trabajo; el informe emitido vive en Blob Storage inmutable.
    volume {
      name         = "informes"
      storage_type = "EmptyDir"
    }
  }
}

# Trabajador de análisis: escala por longitud de cola, sin tocar código (ASR-08).
resource "azurerm_container_app" "worker" {
  name                         = "ca-worker-${var.entorno}"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = local.etiquetas
  depends_on                   = [azurerm_role_assignment.kv_lectura, azurerm_role_assignment.acr_descarga]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = toset(values(local.secretos_app.worker))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.app.id
      key_vault_secret_id = azurerm_key_vault_secret.secretos[secret.value].versionless_id
    }
  }

  template {
    min_replicas = var.worker_replicas_min
    max_replicas = var.worker_replicas_max

    container {
      name   = "worker"
      image  = var.imagen_worker
      cpu    = 1.0
      memory = "2Gi"
      dynamic "env" {
        for_each = merge(local.variables_comunes, local.variables_backend)
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secretos_app.worker
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      volume_mounts {
        name = "expedientes"
        path = "/app/data/expedientes"
      }
      volume_mounts {
        name = "informes"
        path = "/app/data/informes"
      }
    }
    volume {
      name         = "expedientes"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.expedientes.name
    }
    volume {
      name         = "informes"
      storage_type = "EmptyDir"
    }

    custom_scale_rule {
      name             = "cola-analisis"
      custom_rule_type = "azure-servicebus"
      metadata = {
        queueName    = azurerm_servicebus_queue.trabajos.name
        namespace    = azurerm_servicebus_namespace.sb.name
        messageCount = tostring(var.longitud_cola_por_replica)
      }
      authentication {
        secret_name       = "service-bus-conexion"
        trigger_parameter = "connection"
      }
    }
  }
}

# Trabajador de vigilancia: trabajo programado cada hora; cada ejecución hace un barrido,
# envía los avisos pendientes y termina (VIGILANCIA_INTERVALO_MIN=0).
resource "azurerm_container_app_job" "vigilancia" {
  name                         = "caj-vigilancia-${var.entorno}"
  resource_group_name          = azurerm_resource_group.rg.name
  location                     = azurerm_resource_group.rg.location
  container_app_environment_id = azurerm_container_app_environment.env.id
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 1
  tags                         = local.etiquetas
  depends_on                   = [azurerm_role_assignment.kv_lectura, azurerm_role_assignment.acr_descarga]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = toset(values(local.secretos_app.vigilancia))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.app.id
      key_vault_secret_id = azurerm_key_vault_secret.secretos[secret.value].versionless_id
    }
  }

  schedule_trigger_config {
    cron_expression          = "0 * * * *"
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "vigilancia"
      image  = var.imagen_vigilancia
      cpu    = 0.25
      memory = "0.5Gi"
      dynamic "env" {
        for_each = merge(local.variables_comunes, local.variables_correo, {
          EXPEDIENTES_DIR          = "/app/data/expedientes"
          VIGILANCIA_INTERVALO_MIN = "0"
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secretos_app.vigilancia
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      volume_mounts {
        name = "expedientes"
        path = "/app/data/expedientes"
      }
    }
    volume {
      name         = "expedientes"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.expedientes.name
    }
  }
}
```

### A.5 outputs.tf

```hcl
# outputs.tf - Valores que consume la canalización después de aplicar (Anexo G.5).

output "url_interfaz" {
  description = "URL pública de la interfaz web. Registrar <url>/auth/callback como URI de redirección en Entra ID."
  value       = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "servidor_postgres" {
  description = "Nombre completo del servidor de base de datos (solo alcanzable desde la red virtual)."
  value       = azurerm_postgresql_flexible_server.pg.fqdn
}

output "espacio_service_bus" {
  description = "Espacio de nombres de la cola de trabajos."
  value       = azurerm_servicebus_namespace.sb.name
}

output "identidad_aplicacion" {
  description = "Identificador de cliente de la identidad administrada."
  value       = azurerm_user_assigned_identity.app.client_id
}

output "almacen_informes" {
  description = "Contenedor inmutable de los informes emitidos (ALMACEN_INFORMES_URL)."
  value       = "${azurerm_storage_account.st.primary_blob_endpoint}${azurerm_storage_container.informes.name}"
}

output "key_vault" {
  description = "Almacén de secretos del entorno."
  value       = azurerm_key_vault.kv.vault_uri
}

output "aplicaciones" {
  description = "Nombres de las unidades de despliegue, para la canalización."
  value = {
    web        = azurerm_container_app.web.name
    api        = azurerm_container_app.api.name
    worker     = azurerm_container_app.worker.name
    vigilancia = azurerm_container_app_job.vigilancia.name
    grupo      = azurerm_resource_group.rg.name
  }
}
```

### A.6 entornos/dev.tfvars

```hcl
# Entorno de desarrollo (Anexo G.6): una réplica máxima del trabajador, sin Azure OpenAI
# propio (se reutiliza el de pruebas con TF_VAR_azure_openai_endpoint y _clave).
entorno                    = "dev"
ubicacion                  = "eastus2"
sku_postgres               = "B_Standard_B1ms"
almacenamiento_postgres_mb = 32768
worker_replicas_min        = 0
worker_replicas_max        = 1
retencion_respaldo_dias    = 7
desplegar_openai           = false
acceso_publico_almacenes   = true
auth_mode                  = "local"
imagen_api                 = "acrlicitacioneslicita01.azurecr.io/api:dev"
imagen_web                 = "acrlicitacioneslicita01.azurecr.io/webui:dev"
imagen_worker              = "acrlicitacioneslicita01.azurecr.io/worker-analisis:dev"
imagen_vigilancia          = "acrlicitacioneslicita01.azurecr.io/worker-vigilancia:dev"
```

### A.7 entornos/pruebas.tfvars

```hcl
# Entorno de pruebas (Anexo G.7): hasta cuatro réplicas, Azure OpenAI propio e imágenes
# candidatas a liberación. Se crea para cada campaña de pruebas y se destruye al terminar.
entorno                    = "pruebas"
ubicacion                  = "eastus2"
sku_postgres               = "B_Standard_B1ms"
almacenamiento_postgres_mb = 32768
worker_replicas_min        = 0
worker_replicas_max        = 4
retencion_respaldo_dias    = 7
desplegar_openai           = true
acceso_publico_almacenes   = true
auth_mode                  = "oidc"
imagen_api                 = "acrlicitacioneslicita01.azurecr.io/api:rc"
imagen_web                 = "acrlicitacioneslicita01.azurecr.io/webui:rc"
imagen_worker              = "acrlicitacioneslicita01.azurecr.io/worker-analisis:rc"
imagen_vigilancia          = "acrlicitacioneslicita01.azurecr.io/worker-vigilancia:rc"
```

### A.8 entornos/prod.tfvars

```hcl
# Entorno de producción (Anexo G.8): cómputo mayor, réplica mínima activa, más retención de
# respaldo e imágenes con versión fija. Key Vault y Storage solo desde la red virtual (C-09):
# la canalización aplica desde un agente con acceso a la red.
entorno                    = "prod"
ubicacion                  = "eastus2"
sku_postgres               = "B_Standard_B2s"
almacenamiento_postgres_mb = 65536
worker_replicas_min        = 1
worker_replicas_max        = 6
retencion_respaldo_dias    = 14
desplegar_openai           = true
acceso_publico_almacenes   = false
auth_mode                  = "oidc"
imagen_api                 = "acrlicitacioneslicita01.azurecr.io/api:1.0.0"
imagen_web                 = "acrlicitacioneslicita01.azurecr.io/webui:1.0.0"
imagen_worker              = "acrlicitacioneslicita01.azurecr.io/worker-analisis:1.0.0"
imagen_vigilancia          = "acrlicitacioneslicita01.azurecr.io/worker-vigilancia:1.0.0"
```

### A.9 monitoreo.tf

```hcl
# monitoreo.tf - Alertas de la Tabla 49 sobre la telemetría que exporta el código (RF-043).
# Las métricas llegan a Application Insights con el nombre que les da src/shared/telemetria.py
# (tabla customMetrics) y los spans de cada análisis, a la tabla dependencies.

resource "azurerm_monitor_action_group" "equipo" {
  name                = "ag-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  short_name          = "licita"
  tags                = local.etiquetas

  dynamic "email_receiver" {
    for_each = toset(var.correos_alertas)
    content {
      name                    = replace(email_receiver.value, "@", "-")
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
}

locals {
  # nombre => (descripción, consulta KQL, ventana, severidad). Una fila devuelta dispara la alerta.
  alertas = {
    tiempo-analisis = {
      descripcion = "ASR-01: percentil 90 del tiempo de análisis superior a 10 minutos en 30 minutos."
      ventana     = "PT30M"
      severidad   = 2
      consulta    = <<-KQL
        dependencies
        | where name == "analisis"
        | summarize p90 = percentile(duration, 90)
        | where p90 > 600000
      KQL
    }
    longitud-cola = {
      descripcion = "ASR-02, ASR-07: más de 20 mensajes en espera o cualquier mensaje en la cola de fallidos."
      ventana     = "PT5M"
      severidad   = 2
      consulta    = <<-KQL
        customMetrics
        | where name == "licita.cola.mensajes"
        | extend estado = tostring(customDimensions.estado)
        | summarize maximo = max(value) by estado
        | where (estado == "en_espera" and maximo > 20) or (estado == "fallidos" and maximo > 0)
      KQL
    }
    disyuntor = {
      descripcion = "ASR-07: el disyuntor del proveedor del modelo se abrió (la Tabla 49 alerta si sigue abierto 5 minutos)."
      ventana     = "PT5M"
      severidad   = 2
      consulta    = <<-KQL
        customMetrics
        | where name == "licita.llm.disyuntor.aperturas"
        | summarize aperturas = sum(valueSum)
        | where aperturas > 0
      KQL
    }
    suspension-inyeccion = {
      descripcion = "ASR-10: tarea suspendida por sospecha de inyección."
      ventana     = "PT5M"
      severidad   = 1
      consulta    = <<-KQL
        customMetrics
        | where name == "licita.analisis.suspendidas"
        | where tostring(customDimensions.causa) == "inyeccion"
        | summarize total = sum(valueSum)
        | where total > 0
      KQL
    }
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "tabla49" {
  for_each             = local.alertas
  name                 = "alerta-${each.key}-${local.nombre}"
  resource_group_name  = azurerm_resource_group.rg.name
  location             = azurerm_resource_group.rg.location
  description          = each.value.descripcion
  scopes               = [azurerm_application_insights.appi.id]
  evaluation_frequency = "PT5M"
  window_duration      = each.value.ventana
  severity             = each.value.severidad
  tags                 = local.etiquetas

  criteria {
    query                   = each.value.consulta
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.equipo.id]
  }
}
```

### A.10 bootstrap/crear_backend.sh

```bash
#!/usr/bin/env bash
# Crea, una sola vez, la cuenta de almacenamiento del estado de Terraform (apartado 4.3).
# Es el único recurso que no crea Terraform: el estado no puede depender del propio estado.
# Uso: az login && ./bootstrap/crear_backend.sh [región]
set -euo pipefail

UBICACION="${1:-eastus2}"
GRUPO="rg-licita-tfstate"
CUENTA="stlicitatfstate"

az group create --name "$GRUPO" --location "$UBICACION" --output none
az storage account create --name "$CUENTA" --resource-group "$GRUPO" --location "$UBICACION" \
  --sku Standard_LRS --min-tls-version TLS1_2 --allow-blob-public-access false --output none
# Versionado y borrado temporal: un estado dañado o borrado por error se recupera.
az storage account blob-service-properties update --account-name "$CUENTA" --resource-group "$GRUPO" \
  --enable-versioning true --enable-delete-retention true --delete-retention-days 30 --output none
az storage container create --name tfstate --account-name "$CUENTA" --auth-mode login --output none

echo "Estado remoto listo: $GRUPO / $CUENTA / tfstate"
```
