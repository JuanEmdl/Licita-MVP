# Alineación del MVP con el Documento de Trabajo de Grado II (2026)

Contraste del código del repositorio (rama `feature/roles-sesiones-vigilancia`, sin commitear,
2026-10-24) con `Documento_TrabajoGradoII_2026.pdf`. Se revisaron el catálogo de requisitos
funcionales (Tabla 37), los no funcionales (Tablas 8 y 50), los escenarios ASR (Tabla 57), las
decisiones arquitectónicas (Tabla 60), la API (Tabla 45), la cola (Tabla 46), la matriz de acceso
(Tablas 27 y 61), las pantallas (Tabla 28), la máquina de estados (Figura 15 y Tabla 18), la deuda
técnica (Tabla 23) y las funciones de aptitud (Tabla 33).

**Leyenda:** ✅ cumple · 🟡 parcial o con diferencias · ❌ no implementado.
"Medido" quiere decir que existe una prueba automatizada que lo verifica.

## Resumen

| Grupo | ✅ | 🟡 | ❌ |
|---|---|---|---|
| RF de prioridad **Debe** (31) | 31 | 0 | 0 |
| RF de prioridad **Debería** (10) | 10 | 0 | 0 |
| RF de prioridad **Podría** (2) | 2 | 0 | 0 |
| **Total RF (43)** | **43** | **0** | **0** |

El MVP cubre el **flujo central de punta a punta**: sesión y roles, portafolio versionado,
sincronización con SECOP II, búsqueda, perfiles, seguimiento y novedades, expediente documental
con carga manual, extracción con página de origen, compuerta humana, evaluación, puntaje
determinista, recomendación, informe PDF sellado, bitácora, decisión comercial y notificaciones
por aplicación y correo, carpetas, notas, responsable, exportación a CSV e inicio de sesión con
OpenID Connect. El código cubre los 43 RF (OIDC verificado con el App Registration real), la
infraestructura como código está escrita (`infra/terraform`, sin aplicar) y la canalización ejecuta
pruebas, funciones de aptitud y análisis de seguridad. Ninguno de los 10 RNF está medido todavía con
su umbral, porque eso requiere crear el ambiente de pruebas (DT-04), como reconoce el propio documento.

**Estado al 2026-10-25 (cierre de los pendientes que no son RF):** el código ya no contradice al
documento en ningún punto que no sea una decisión registrada abajo. Lo que queda son **correcciones
del documento** (sección final) y **mediciones** que solo se pueden hacer con el ambiente de pruebas
desplegado (ver «Lo que no se resuelve desde el código»).

## Diferencias que conviene resolver antes de la sustentación

Estas no son funciones faltantes, sino puntos donde **el código contradice lo que dice el
documento**:

1. ✅ *Resuelta el 2026-10-24: la matriz sigue la Tabla 61 y cada rol abre en su pantalla de la
   Tabla 27.* **El administrador tenía todos los permisos** (`src/shared/roles.py`). Las Tablas 27 y 61 dicen
   que el administrador no tiene acceso a la revisión de requisitos ni a la decisión comercial, y
   que solo consulta análisis y resultados. Hoy puede aprobar requisitos, solicitar análisis y
   registrar decisiones, lo que rompe la segregación de funciones.
2. ✅ *Resuelta siguiendo la Tabla 61: el Gerente puede solicitar análisis. Falta corregir la
   Tabla 45 del documento, que asigna `POST /analisis` solo al Analista.* **El Gerente no podía
   solicitar análisis.** La Tabla 61 dice que sí puede ("C, A"; "el gerente
   puede solicitar, no aprobar requisitos"), pero la Tabla 45 asigna `POST /analisis` solo al
   Analista. **El documento se contradice**: hay que decidir cuál vale. El código sigue la Tabla 45.
3. ✅ *Resuelta el 2026-10-25: `AUTH_MODE=oidc` con la interfaz como cliente confidencial (bloque G);
   el modo local queda como alternativa para pruebas.* **Autenticación local en lugar de OIDC** (DA-10, RF-005, Tabla 28). La API admite `oidc`, pero
   la interfaz solo funciona con `AUTH_MODE=local` (usuarios y contraseñas propios). Esto
   contradice RN-02 ("el usuario no define su credencial… se establece en el proveedor de
   identidad") y la pantalla de inicio de sesión descrita. Si se mantiene, necesita un registro de
   decisión (ADR) que lo justifique para el MVP.
4. 🟡 *Decisión pendiente del documento: el código conserva el historial a propósito.* **Decisión comercial.** La Tabla 45 especifica `POST /oportunidades/{id}/decision` con 409
   "decisión ya registrada" (una sola decisión). El código usa `POST /resultados/{tarea_id}/decision`
   y conserva un historial de varias decisiones. Hay que alinear el documento o el código.
5. ✅ *Resuelta el 2026-10-25: `GET /analisis/{id}` con `etapa_actual` y `etapas_cerradas` leídas del
   checkpoint, y `PUT /analisis/{id}/requisitos` con `aprobar` (200 borrador guardado, 202 flujo
   reanudado, 409, 422). `/estado` y `POST /aprobacion` quedan como alias marcados obsoletos.*
   **Contrato de la API (Tabla 45)**, parcialmente resuelto. Ya existen `POST /portafolio/versiones`,
   `PUT /reglas-puntaje` (422 si no suman 100) y `forzar_nuevo` con 409 reutilizable. Faltan
   `GET /analisis/{id}` con `etapaActual` y `etapasCerradas` (hoy `GET /analisis/{id}/estado`) y
   `PUT /requisitos` con borrador (hoy `POST /aprobacion`).
6. 🟡 *Solo falta corregir el documento (snake_case, una sola cola, sin `oportunidad.novedad`).* **Contrato de la cola (Tabla 46)**, parcialmente resuelto. `analisis.solicitado` (con las versiones),
   `analisis.reanudar` y `portafolio.indexar` ya existen. Las novedades se registran en
   `novedades_proceso` y llegan al notificador por la tabla `notificaciones` (bandeja de salida
   persistente), no por la cola: el notificador es un componente del mismo trabajador (Figura 11).
   Los campos van en snake_case (`reglas_version`), no en camelCase como en la tabla.
7. ✅ *Resuelta el 2026-10-25: fragmentos (al extraer) y requisitos (al evaluar) en paralelo con
   `ANALISIS_PARALELISMO` (4 por defecto), con el mismo resultado que en serie.* **Fragmentos en serie.** El apartado 2.12 dice que RNF-001 "obliga a paralelizar el procesamiento
   de fragmentos". El nodo `extrayendo` del grafo los recorre uno por uno.
8. 🟡 *Corrección del documento.* **La Tabla 30 (estado de implementación) está desactualizada**: marca el motor de puntaje y la
   bitácora como "Pendiente" y la interfaz como "Diseñada", cuando ya están construidos. Además, el
   documento no menciona lo que se agregó en el código: pantalla de Seguimiento, Diagnóstico de
   servicios, modo de autenticación local y evaluación del extractor.
9. 🟡 *Corrección del documento.* **Stack (Tabla 58):** el documento declara NiceGUI "serie 2.x"; el proyecto usa 3.18.

## Requisitos funcionales (Tabla 37)

### Acceso y sesión
| RF | Prioridad | Estado | Evidencia o brecha |
|---|---|---|---|
| RF-001 | Debe | ✅ | `POST /usuarios/`, pantalla Usuarios. Medido (`tests/unit/test_identidad.py`). |
| RF-002 | Debe | ✅ | El rol asigna los permisos de la Tabla 61; una prueba compara la matriz fila por fila (`test_matriz_de_roles_sigue_la_tabla_61`). |
| RF-003 | Debe | ✅ | `PATCH /usuarios/{id}` con `activo`. |
| RF-004 | Debe | ✅ | Corta la sesión abierta al instante y queda en la bitácora con el antes y el después (Tabla 61). Medido. |
| RF-005 | Debe | ✅ | OpenID Connect (código con PKCE, cliente confidencial, nonce y state); la API valida el id_token y exige usuario registrado y habilitado; credenciales inválidas rechazadas. Medido con un proveedor simulado; falta la prueba con el App Registration real. |
| RF-006 | Debe | ✅ | `POST /auth/logout`. Medido. |
| RF-007 | Debe | ✅ | `SESION_INACTIVIDAD_MIN`, aviso previo en la interfaz. Medido. |

### Portafolio de capacidades
| RF | Prioridad | Estado | Evidencia o brecha |
|---|---|---|---|
| RF-008 | Debe | ✅ | `POST /portafolio/`, `scripts.cargar_portafolio`, pantalla Portafolio. |
| RF-009 | Debe | ✅ | Cada cambio publica una versión completa; la anterior queda como histórico (RN-03). La tarea fija la versión y el evaluador busca solo en ella. |
| RF-010 | Debería | ✅ | Las capacidades sin cambios conservan su vector (huella de contenido); el trabajador indexa solo lo nuevo o modificado (`portafolio.indexar`), de forma repetible. |

### Monitoreo de oportunidades
| RF | Prioridad | Estado | Evidencia o brecha |
|---|---|---|---|
| RF-011 | Debe | ✅ | Metadatos (`p6dx-8zbt`) y lista de documentos (`dmgg-8hin`) de Datos Abiertos; cada archivo se pide a su enlace publicado y el que no se obtiene queda como faltante con el motivo. SECOP II responde 403 a la descarga automática: en la práctica todos pasan por la carga manual (corrección pendiente del documento). |
| RF-012 | Debe | ✅ | Tabla `oportunidades` sin duplicados, con fuente, identificador de origen y última actualización exitosa; cada barrido queda en `sincronizaciones` y la falla de la fuente muestra los datos previos con su fecha (HU-04 CA-04). Medido. |
| RF-013 | Debería | ✅ | Palabras clave sobre nombre y objeto, sin tildes ni mayúsculas. Medido. |
| RF-014 | Debería | ✅ | Entidad, departamento, ciudad, modalidad, cuantía, fechas de publicación y cierre, y estado. Medido. |
| RF-015 | Debería | ✅ | `/perfiles` con alcance por propietario (Tabla 61); el barrido los evalúa. Medido. |
| RF-016 | Debería | ✅ | Canal (aplicación, o correo y aplicación) y frecuencia (inmediata o resumen diario) por usuario. Medido. |
| RF-017 | Debería | ✅ | Aviso por cada oportunidad nueva que coincide con un perfil activo, con proceso, entidad y fecha de cierre; una sola vez por destinatario; en la aplicación y por correo SMTP. Medido. |
| RF-018 | Debe | ✅ | Seguimiento por usuario (`PUT/DELETE /oportunidades/{id}/seguimiento`). Medido. |
| RF-019 | Debe | ✅ | Detector de cambios de estado, fechas y documentos de los procesos seguidos; los requisitos se infieren de documentos nuevos (adendas, pliegos) porque Datos Abiertos no los publica, y se marca el análisis afectado. Medido. |
| RF-020 | Debería | ✅ | Cada novedad de un proceso seguido llega a sus seguidores según su canal y frecuencia, con resumen diario consolidado. Medido. |
| RF-021 | Debe | ✅ | Expediente con nombre, versión, procedencia, fechas, huella y estado; faltantes e ilegibles explícitos (HU-02 CA-02 y CA-03). Medido. |
| RF-022 | Debe | ✅ | Carga de PDF, DOCX, XLSX o TXT con procedencia, versión e historial; auditada. Medido. |

### Procesamiento y extracción documental
| RF | Prioridad | Estado | Evidencia o brecha |
|---|---|---|---|
| RF-023 | Debe | ✅ | Fragmentos con documento, versión, procedencia, páginas y sección; tablas sin partir aunque crucen de página; descarte de fragmentos sin referencia; referencia del requisito completada con documento y página. Medido. |
| RF-024 | Debe | ✅ | Guardia documental y separación sistema/datos en los prompts. Medido (17 casos; ASR-10 pide 50). |
| RF-025 | Debe | ✅ | `POST /analisis/` responde 202 con `tarea_id` y encola en Service Bus. |
| RF-026 | Debe | ✅ | `GET /analisis/{id}/estado` con el motivo de la falla. |
| RF-027 | Debería | ✅ | Reintentos con espera exponencial solo ante fallas transitorias; avance conservado en checkpoints. |
| RF-028 | Debe | ✅ | Tokens por invocación en `consumo_tokens`; la pasarela no invoca con la cuota agotada, las solicitudes nuevas reciben 429 y las tareas en curso quedan Suspendidas hasta que el administrador amplía la cuota (RN-10). |
| RF-029 | Debe | ✅ | Salida estructurada con los cinco campos. Evaluado: 100 % encontrados, estabilidad 100 % (prompt 2.1.0; la 2.2.0 solo cambia la descripción de la entrada; volver a evaluarla es opcional y consume tokens). |
| RF-030 | Debe | ✅ | Revisión con edición, alta y baja; borrador guardado en el checkpoint (a mano y cada 20 s mientras se edita) que sobrevive a la caducidad de la sesión (CU-05 A1 y E1); la aprobación sella la lista. Tras una adenda, solo los requisitos afectados vuelven a revisión (HU-06 CA-03). Medido. |

### Evaluación y puntaje
| RF | Prioridad | Estado | Evidencia o brecha |
|---|---|---|---|
| RF-031 | Debe | ✅ | Cuatro estados, evidencia `[P-n]` obligatoria y degradación determinista si no cita. Medido. |
| RF-032 | Debe | ✅ | Pantalla y `PUT /reglas-puntaje`: pesos por categoría (suman 100) y umbrales, con doble control (propone el Administrador, confirma el Gerente). |
| RF-033 | Debe | ✅ | Versiones Propuesta → Vigente → Histórica; la tarea fija la vigente al aceptarse (RN-06) y el resultado, el informe y Resultados la declaran. |
| RF-034 | Debe | ✅ | Puntaje 0-100 con aporte y peso efectivo por categoría. Medido. |
| RF-035 | Debe | ✅ | Categoría por reglas (RN-05, RN-07) y justificación redactada por el modelo. |
| RF-036 | Debería | ✅ | 409 con la tarea previa, su fecha y su resultado si coinciden proceso, pliego y versiones; `forzar_nuevo` lo repite (RN-09). La vigencia de la ficha de SECOP no se compara: solo el pliego aportado. |

### Reporte y gestión comercial
| RF | Prioridad | Estado | Evidencia o brecha |
|---|---|---|---|
| RF-037 | Debe | ✅ | PDF con dictámenes, evidencia, puntaje, recomendación, versiones, intervenciones humanas, documentos faltantes e incertidumbres (HU-10); emisión atómica con su huella (Tabla 19) y verificación por la API. |
| RF-038 | Debería | ✅ | Tablero de Resultados filtrable por recomendación y decisión; el estado de la tarea está en Seguimiento. |
| RF-039 | Debe | ✅ | Continuar, descartar o solicitar información, con fecha, autor y justificación, auditado. Ver diferencia 4. |
| RF-040 | Podría | ✅ | Carpetas propias de cada usuario, notas con autor y responsable asignado a un analista activo, auditado y avisado. Medido. |
| RF-041 | Podría | ✅ | CSV de las seleccionadas o de todas las filtradas, con las carpetas propias y auditado; ASR-15 medido (100 registros en menos de 2 s). |

### Auditoría y observabilidad
| RF | Prioridad | Estado | Evidencia o brecha |
|---|---|---|---|
| RF-042 | Debe | ✅ | Eventos de análisis, informe, decisión, reglas, portafolio, cuota, identidad, 403 y vigilancia, con autor, fecha, tarea y valores modificados; solo anexado en la base; consulta y verificación para Gerente y Administrador. |
| RF-043 | Debe | ✅ | OpenTelemetry hacia Azure Monitor en las cuatro unidades: traza por tarea con un span por etapa y por llamada al modelo (modelo, duración, resultado), métricas de la Tabla 49, incluida la longitud de la cola (en espera y fallidos), y contexto propagado de la API al trabajador. Alertas de la Tabla 49 en `infra/terraform/monitoreo.tf`. Medido. |

## Requisitos no funcionales y escenarios ASR

| RNF / ASR | Estado del mecanismo | Medido con su umbral |
|---|---|---|
| RNF-001 / ASR-01 (≤ 10 min p90) | ✅ Cola, trabajador y fragmentos en paralelo (`ANALISIS_PARALELISMO`). | No. La prueba existe (`tests/carga/locustfile.py`, FF-01) y corre en el ambiente de pruebas. |
| RNF-002 / ASR-02 (10 concurrentes) | ✅ Cola durable, trabajador sin estado y escalado por longitud de cola (Terraform). | No. La misma prueba de carga usa 10 analistas concurrentes. |
| RNF-003 / ASR-03 (≥ 98 % de 500 esquemas) | 🟡 Adaptador con capa anticorrupción. | No hay suite de esquemas históricos. |
| RNF-004 / ASR-04 (RTO 4 h, RPO 12 h) | 🟡 Checkpoints en PostgreSQL y reanudación probada. | Sin respaldo continuo ni simulacro. |
| RNF-005 / ASR-05 (100 % protegido) | ✅ Anonimización en la pasarela y telemetría sin contenido; en Terraform, secretos en Key Vault leídos con identidad administrada, PostgreSQL sin acceso público y TLS 1.2 (C-08, C-09). | Parcial: prueba de que ningún dato protegido llega al proveedor; el cifrado se inspecciona en el ambiente. |
| RNF-006 / ASR-06 (100 % alteraciones detectadas) | ✅ Huella SHA-256 del PDF verificable, bitácora encadenada, disparadores que impiden UPDATE, DELETE y TRUNCATE, y copia del informe en Blob Storage con política de inmutabilidad (`ALMACEN_INFORMES_URL`, DA-06). | Sí: integración que altera el PDF y la bitácora y comprueba que se detecta. |
| RNF-007 / ASR-07 (0 % caídas del núcleo) | ✅ Reintentos, disyuntor, mensaje devuelto a la cola que continúa desde la última etapa cerrada y paso a mensajes fallidos con aviso en la tarea. | Parcial: pruebas unitarias con 429 simulados; falta la inyección de fallas en el ambiente de pruebas. |
| RNF-008 / ASR-08 (0 archivos para escalar) | ✅ Trabajador sin estado; se escala con réplicas. | No. |
| RNF-009 / ASR-09 (100 % rechazados) | ✅ `requiere_permiso` en cada ruta. | Sí: FF-05 arma la suite con todas las rutas de la API, 225 combinaciones rol-operación (rechazos de punta a punta y permisos), más `tests/asr`. |
| RNF-010 (0 sesiones sin vigencia) | ✅ Las tres causas de pérdida de vigencia. | Sí (`test_identidad.py`). |
| ASR-10 (inyección) | ✅ Guardia más prompts. | 17 casos de 50. |
| ASR-11 (202 en ≤ 1 s) | ✅ | Funcional; sin medir el percentil. |
| ASR-12 (compuerta humana) | ✅ El grafo se detiene antes de `evaluando`. | Sí (`test_asr12_human_gate.py`). |
| ASR-13 (cuota) | ✅ | Sí: 0 invocaciones con la cuota agotada (unitaria) y 429 en PostgreSQL (integración). |

## Decisiones arquitectónicas (Tabla 60)

| DA | Estado | Comentario |
|---|---|---|
| DA-01 web-cola-trabajador | ✅ | API, trabajadores de análisis y vigilancia, interfaz. |
| DA-02 puertos y adaptadores | ✅ | Adaptador SECOP con capa anticorrupción; pasarela LLM; publicador de cola. |
| DA-03 LangGraph con checkpoints | ✅ | Los nodos coinciden con los estados de la Figura 15. |
| DA-04 Service Bus con dead-letter | ✅ | `abandon` y `dead_letter` en `worker_analysis/main.py`. |
| DA-05 una base PostgreSQL con pgvector | ✅ | |
| DA-06 almacenamiento inmutable y huella | ✅ | Huella verificable, emisión única, bitácora de solo anexado y copia en Blob Storage con política de inmutabilidad (`src/shared/almacen_informes.py`, `infra/terraform/main.tf`); un informe emitido no se reemplaza. |
| DA-07 pasarela única | ✅ | Única puerta al modelo (FF-03), también para los embeddings: cuota, anonimización, reintentos, disyuntor y telemetría. |
| DA-08 guardia y agentes sin herramientas | ✅ | |
| DA-09 puntaje determinista | ✅ | El motor no importa nada de inferencia (FF-04 se cumple). |
| DA-10 OIDC y roles | ✅ | OIDC con la interfaz como cliente confidencial y roles administrados en Licita (diferencia 3 resuelta). |
| DA-11 una instancia por fábrica | ✅ | |
| DA-12 despliegue en Azure | ✅ | `infra/terraform` (red, PostgreSQL, Service Bus, Storage inmutable, Key Vault, Azure OpenAI, cuatro unidades en Container Apps y alertas) y canalización que lo aplica. Escrito, sin aplicar ni validar con `terraform validate` (no hay Terraform en la máquina de desarrollo). |
| DA-13 todo en Python | ✅ | NiceGUI 3.18 (el documento dice 2.x). |
| DA-14 reglas versionadas (propuesta) | ✅ | Implementada; en el documento debería pasar de Propuesta a Aceptada. |

## Pantallas (Tabla 28)

| Pantalla | Estado |
|---|---|
| Inicio de sesión | ✅ Con el proveedor de identidad (sin registro ni contraseña local) y, como alternativa, con usuarios locales. |
| Sesión caducada | ✅ Vuelve al inicio de sesión con el motivo. |
| Portafolio | ✅ Versión vigente, edición, retiro e historial. |
| Vigilancia | ✅ Alertas reales, radicación de procesos, solicitud manual y última sincronización. |
| Tablero de oportunidades | ✅ Filtros, seguimiento, novedades, expediente y análisis (RF-013, RF-014, RF-018, RF-019). Perfiles en su propia pantalla. |
| Revisión de requisitos | ✅ Con borrador y columna «Revisión» tras una adenda (HU-06 CA-03). |
| Detalle de la evaluación | ✅ En Resultados: dictamen por requisito con evidencia y justificación, aporte por categoría, puntaje, recomendación y versiones de reglas y portafolio. |
| Resultados y decisiones | ✅ |
| Informe de viabilidad | ✅ Vista previa, huella verificada y descarga del PDF. |
| Administración (DT-01) | ✅ Usuarios y Reglas del puntaje. |

## Canalización y funciones de aptitud (Tabla 33)

`azure-pipelines.yml` corre en cada solicitud de incorporación y en cada integración a `main`; FF-07
corre además cada semana. `azure-pipelines-carga.yml` ejecuta FF-01 al cierre de sprint.

| FF | Estado | Cómo se mide en el código |
|---|---|---|
| FF-01 | ✅ escrita | `tests/carga/locustfile.py`: 10 analistas, falla si el p90 supera 10 min. Requiere el ambiente de pruebas. |
| FF-02 | ✅ | `tests/aptitud/test_dependencias.py`: esquemas, puntaje y procesamiento documental no importan adaptadores, base de datos ni clientes externos. |
| FF-03 | ✅ | Solo `llm_gateway` importa `openai` o `langchain_openai`. |
| FF-04 | ✅ | El motor de puntaje solo usa la biblioteca estándar, pydantic y los esquemas. Al escribirla apareció una dependencia real (los pesos iniciales venían del repositorio de reglas) y se corrigió. |
| FF-05 | ✅ | `tests/aptitud/test_ff05_rol_operacion.py`: 225 combinaciones generadas desde las rutas de la API. |
| FF-06 | ✅ | `tests/aptitud/test_ff06_maquina_estados.py`: la máquina de estados del núcleo rechaza las cuatro transiciones de la Tabla 18; más `tests/asr/test_asr12_human_gate.py`. |
| FF-07 | ✅ | Bandit (severidad alta; hoy sin hallazgos, tampoco de severidad media tras endurecer la lectura de DOCX y XLSX) y pip-audit (sin vulnerabilidades conocidas). |
| FF-08 | ✅ | `tests/aptitud/test_ff08_idempotencia.py`: cada mensaje repetido con la misma clave no duplica extracción, dictámenes, informe ni bitácora. |

La cobertura del dominio (esquemas, puntaje, procesamiento, orquestador y núcleo) es 97 %; la canalización
exige 90 %.

## Prioridad sugerida para cerrar el MVP

1. ~~Alinear la matriz de roles con la Tabla 61~~ (hecho). Queda corregir la Tabla 45 del documento.
2. **Registrar en el documento las desviaciones** conscientes: autenticación local (ADR), historial
   de decisiones, contrato de la API y la Tabla 30 actualizada.
3. ~~RF-032, RF-033, RF-009, RF-010 y RF-036~~ (hecho, bloque A).
4. ~~RF-028 / ASR-13, ASR-05, ASR-07 y RF-043~~ (hecho, bloque B). Queda el cifrado y Key Vault con la infraestructura.
5. ~~RF-037 y RF-042~~ (hecho, bloque C). El almacenamiento en Blob Storage inmutable queda con la infraestructura.
7. ~~Monitoreo y expediente (RF-011 a RF-015, RF-018, RF-019, RF-021 a RF-023)~~ (hecho, bloque D).
   Queda HU-06 CA-03 completo: hoy la novedad marca el análisis afectado, pero no devuelve a revisión
   solo los requisitos que cambió la adenda.
9. ~~Carpetas, notas, responsable y CSV (RF-040, RF-041)~~ (hecho, bloque F).
8. ~~**Canalización** con pruebas y análisis de seguridad (FF-02 a FF-07) y Terraform (DT-06)~~ (hecho,
   2026-10-25). Falta aplicarlo para tener el ambiente de pruebas y medir los RNF.

## Correcciones pendientes del documento (para la pasada final)

Puntos donde el código ya sigue una regla del documento y otra parte del mismo documento la contradice:

- **Tabla 45:** `POST /analisis` solo para el Analista; la Tabla 61 lo permite también al Gerente (el código sigue la Tabla 61).
- **Tabla 61, fila Reglas del puntaje:** el Gerente aparece solo con «C», pero el control adicional dice que confirma la publicación; el código le da `reglas:confirmar`.
- **Tabla 60 y MADR de DA-14:** cambiar el estado de Propuesta a Aceptada.
- **Tabla 23, DT-01:** la pantalla de usuarios y reglas ya existe.
- **Tabla 46:** los campos van en snake_case en el código, y existe un mensaje más, `analisis.continuar` (Suspendida → Evaluando cuando vuelve a haber cuota).
- **RN-10 y Tabla 61:** el documento dice que la cuota la amplía «el responsable autorizado» (Gerencia Financiera), pero no hay ese rol; el código se lo asigna al Administrador (`cuota:ampliar`).
- **Tabla 49:** la métrica de longitud de la cola no está implementada; requiere consultar Service Bus desde la telemetría.
- **RF-011 y Tabla 16:** Datos Abiertos publica la lista y el enlace de los documentos (`dmgg-8hin`), pero SECOP II responde 403 a la descarga automática. El documento debe decir que los archivos se obtienen por carga manual (RF-022) y que el sistema identifica cuáles faltan.
- **RF-019:** Datos Abiertos no publica los requisitos como datos; el cambio de requisitos se detecta por la publicación de documentos que los modifican (adendas, pliegos, anexos técnicos).
- **Tabla 61, perfiles:** Gerente «C» y Administrador «C, E» con alcance «solo los perfiles que el propio usuario creó», pero ninguno puede crearlos; el código lo aplica literalmente. En la misma fila, el Gerente no puede configurar el canal ni la frecuencia de sus avisos (solo «C»).
- **Tabla 46:** `oportunidad.novedad` no viaja por la cola: el notificador está en el mismo trabajador de vigilancia (Figura 11) y recibe las novedades por la tabla `notificaciones`, que además evita repetir un aviso. Conviene describirlo así o quitar el mensaje de la tabla.
- **Tabla 47:** agregar `notificaciones` y `preferencias_notificacion` (correo del destinatario: dato personal, Ley 1581).
- **RF-016:** el documento no enumera los canales; el código ofrece aplicación y correo, que son los dos que aparecen en la arquitectura (Tabla 16 y Figura 11).
- **Figura 16 y Tabla 47:** faltan las entidades nuevas (`oportunidades`, `seguimientos_proceso`, `novedades_proceso`, `documentos_expediente`, `perfiles_busqueda`, `coincidencias_perfil`, `sincronizaciones`).
- **Tabla 58:** agregar `pypdf` (texto por página de los PDF del expediente).
- **DA-10 y RF-002:** dejar explícito que el proveedor autentica y que el rol y el estado se administran en Licita (no con roles de aplicación de Entra ID), y que la API abre una sesión propia tras validar el id_token para cumplir RNF-010 y RF-004 (ADR).
- **Tabla 45:** agregar `POST /auth/oidc` (canje del id_token por la sesión de Licita).
- **RN-02 y Tabla 28:** el código admite además un modo combinado (`AUTH_MODE=local` con el App Registration), en el que conviven la cuenta institucional y los usuarios locales con contraseña. Si se usa en la entrega, el documento debe declararlo como excepción a RN-02 (por ejemplo, cuentas de servicio o usuarios externos sin cuenta institucional); `AUTH_MODE=oidc` cumple RN-02 sin excepciones.
- **RF-040 y Tabla 61:** el documento no dice quién ve las notas ni a quién se asigna el responsable. El código deja las notas a la vista de quien consulta la oportunidad (solo el autor las borra) y solo permite asignar analistas comerciales activos, porque el responsable gestiona el expediente.
- **Tabla 61, carpetas y exportación:** «quitar una oportunidad de la carpeta» se trató como edición (E), no como borrado (B): el gerente puede hacerlo; borrar la carpeta queda solo para el analista.
- **ASR-15:** la exportación vive en `/resultados/oportunidades.csv` (módulo de resultados), con separador punto y coma por la configuración regional de Excel en Colombia.
- **Tabla 45, nombres:** el código usa snake_case en toda la API (`tarea_id`, `licitacion_url`, `contenido_pliego`, `forzar_nuevo`, `etapa_actual`, `etapas_cerradas`); la Tabla 45 los escribe en camelCase. `GET /analisis/{id}` devuelve además `etapa_actual = esperando_revision` en la compuerta humana.
- **Tabla 45, decisión comercial (diferencia 4):** el código usa `POST /resultados/{tarea_id}/decision` y conserva el historial (por ejemplo, «Solicitar información» y luego «Continuar»), en lugar de `POST /oportunidades/{id}/decision` con 409 «decisión ya registrada». Conviene describir el historial en el documento (es más trazable y el tablero muestra la última); si se prefiere la regla de una sola decisión, es un cambio pequeño en el código.
- **Tabla 46 y Anexo G:** hay una sola cola (`analisis-licitaciones`) y el tipo de trabajo viaja en el mensaje (`tipo_tarea`); el Anexo G declara tres colas. Las entregas antes de pasar a fallidos son 10 (`SERVICE_BUS_MAX_ENTREGAS`), no tres.
- **Anexo G, en general:** `infra/terraform` sigue la estructura del anexo, pero lo corrige para que funcione con la aplicación. Las variables de entorno son las que lee el código (`DB_CONNECTION_STRING`, `SERVICE_BUS_CONNECTION_STRING`, etc., no `PG_HOST` ni `SERVICEBUS_FQDN`) y los secretos llegan por referencia a Key Vault. Hay cuatro imágenes, porque la vigilancia tiene la suya. Hay red virtual con subred delegada y DNS privado: con el acceso público desactivado, el anexo dejaba PostgreSQL inalcanzable. El expediente usa un recurso compartido de Azure Files en lugar del contenedor `pliegos`. La afinidad de sesión se fija con la CLI, porque el proveedor no la expone. Se agregaron `monitoreo.tf` (alertas) y nombres con sufijo aleatorio para los recursos que deben ser únicos. El anexo debería transcribir esta versión.
- **Tabla 29:** agregar `monitoreo.tf`; el script de arranque está en `infra/terraform/bootstrap/crear_backend.sh`; `variables.tf` tiene más de los catorce parámetros (modelos, identidad, correo, alertas, registro).
- **Tabla 30:** todos los frentes están construidos; la infraestructura como código está escrita y sin aplicar; la canalización está escrita (pruebas, aptitud, seguridad, construcción y despliegue con aprobación).
- **Tablas 31 y 33:** FF-05 se genera desde las rutas (225 combinaciones, más de las 200 de la Tabla 48); la cobertura acordada del dominio es 90 % (hoy 97 %); Bandit detiene la canalización con severidad alta y pip-audit con cualquier vulnerabilidad conocida (no informa severidad).
- **Tabla 49:** las alertas implementadas son tiempo de análisis (p90), longitud de la cola, apertura del disyuntor (se alerta al abrirse, no a los 5 minutos) y suspensión por inyección. El 80 % de la cuota lo avisa la propia aplicación (`CUOTA_ALERTA_PORCENTAJE`). Los 403 por usuario se consultan en la bitácora, porque la métrica no lleva datos personales (ASR-05).
- **Tabla 58:** agregar pytest-cov 7.1, Bandit 1.9.4, pip-audit 2.10.1, Locust 2.47 (solo en la canalización de carga) y Terraform 1.9.8 con azurerm 4.x.
- **HU-06 CA-03:** la regla es determinista. Se compara el texto de cada documento con el del análisis aprobado; un requisito queda afectado si cambió el texto de su numeral, si una adenda cita su numeral (o el capítulo que lo contiene) o si su documento se retiró; una adenda que no cita numerales devuelve toda la lista. La marca se aplica al solicitar el análisis nuevo, que pide el analista (consume tokens); la novedad del proceso se lo indica.
- **Apartado 2.12 y RNF-001:** el paralelismo es un parámetro (`ANALISIS_PARALELISMO`, 4 por defecto) porque concentra el consumo de la cuota.
- **DA-06 y C-03:** el periodo de inmutabilidad de los informes es de 90 días (Terraform); el informe también se escribe en un directorio temporal del contenedor.

## Cierre del capítulo 4 (2026-10-25)

- Núcleo de dominio explícito: puertos de la Figura 12 y máquina de estados de la Figura 15
  (`src/worker_analysis/nucleo`).
- Tabla 24 medida con `scripts/metricas_acoplamiento.py`.
- Terraform validado (no aplicado); estrategia de ramas registrada (`CONTRIBUTING.md`).
- Las instrucciones para actualizar el documento están en `ACTUALIZACION_DOCUMENTO_PARA_CLAUDE_CHAT.md`.

## Lo que no se resuelve desde el código

Estas partes del documento requieren el ambiente de pruebas desplegado o datos que no están en el
repositorio. No son contradicciones: el capítulo 5 ya las declara abiertas.

1. **Aplicar Terraform** en la suscripción (crear el estado remoto con el script de arranque y
   configurar el grupo de variables de la canalización). `terraform validate` ya pasa.
2. **Medir los RNF con su umbral:** FF-01 y ASR-02 (Locust), ASR-04 (simulacro de caída y
   restauración), ASR-07 (inyección de fallas del proveedor), ASR-11 (percentil del 202) y la
   inspección de cifrado.
3. **ASR-10:** la suite adversaria tiene 17 casos y el documento pide 50 pliegos.
4. **ASR-03:** falta la suite de 500 esquemas históricos de SECOP II para el adaptador.
5. **RF-029 (opcional):** volver a evaluar el extractor con las instrucciones 2.2.0.
