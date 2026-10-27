# Segunda pasada sobre el documento: lo que quedó pendiente

**Para la persona que lo usa:** en el mismo chat de Claude donde se hizo la primera actualización (o
en uno nuevo, adjuntando también `ACTUALIZACION_DOCUMENTO_PARA_CLAUDE_CHAT.md` y el Word actual),
adjunta este archivo y escribe: *«Aplica esta segunda pasada al documento y entrégame el Word
actualizado con el registro de cambios»*.

---

## 0. Para Claude: contexto

La primera pasada quedó bien en lo grueso. El capítulo 4 está reestructurado y correcto, el Anexo G
trae el Terraform validado, el Anexo H existe, el capítulo 5 no se tocó y los anexos empiezan en la
página 94 (el límite es 101). Esta revisión se hizo contra el PDF de la versión actual (183 páginas),
página por página, y encontró lo siguiente sin aplicar. **Las páginas citadas son las de ese PDF.**
Valen las mismas reglas de la sección 0.1 del archivo de instrucciones original: no inventar datos,
mantener el estilo, renumerar y actualizar referencias, y no escribir el capítulo 5, las conclusiones
ni las recomendaciones.

Al terminar, entrega el registro de cambios y confirma la página en que empiezan los anexos.

---

## 1. Errores en el capítulo 4 (pocos, pero visibles)

1. **Tabla 19 (p. 83):** la ubicación de la pasarela es `src/worker_analysis/llm_gateway`, no
   `src/worker_analysis/pasarela`.
2. **«Identificador de token» (p. 84, apartado 4.3, y Tabla 22, DV-07, p. 87; también en H.4):** el
   término correcto es «token de identidad (id_token)». En 4.3: «la API valida el token de identidad
   y abre a continuación una sesión propia…». En DV-07: «Tras validar el token de identidad, la API
   abre una sesión propia del sistema».
3. **Figura 18 (p. 81):** la nota dice «cajas azules para pantallas construidas», pero la imagen sigue
   siendo el mapa anterior, con la caja punteada de la pantalla pendiente. Si no puedes reemplazar la
   imagen, deja `[POR COMPLETAR: actualizar la imagen del mapa de navegación sin la caja punteada]` y
   regístralo.

---

## 2. Numeración de tablas e índices

1. **La tabla del apartado 3.11 (p. 55) tiene el título «Tabla 64. Decisiones arquitectónicas
   adoptadas y fuentes que las respaldan».** Debe ser la **Tabla 12**: así figura en la lista de
   tablas y es la que falta en la secuencia (hoy la numeración salta de la 11 a la 13). Corrige
   también las referencias en el texto que la llaman «Tabla 64»: p. 46 (en la Tabla 10), p. 54 y
   p. 55.
2. **En el Anexo E hay otra «Tabla 64. Decisiones arquitectónicas adoptadas» (p. 155)** que repite
   la Tabla 12 del cuerpo y la Tabla 52 del mismo anexo. **Elimínala** y quita su entrada de la
   lista de tablas. Si alguna referencia la cita, apúntala a la Tabla 52.
3. **El índice de contenido (pp. 6 a 8) no se regeneró:** conserva la estructura vieja (por ejemplo
   «2.2 ÉPICAS DEL SISTEMA», «3.15 RESULTADO PARCIAL…», «1.4 DISEÑO METODOLÓGICO» repetido) y no
   lista los capítulos 4 y 5. Regenéralo desde los títulos reales: 1.1 a 1.6, 2.1 a 2.13, 3.1 a
   3.38, 4.1 a 4.6, 5.1 a 5.3, 6, 7, Bibliografía y Anexos. Actualiza también los números de
   página de las listas de tablas, figuras y anexos (en Word: actualizar los campos).
4. **Capítulo 5, p. 88 (solo la referencia, no el texto):** «la Tabla 49 del apartado 3.24 asocia
   cada ASR con la prueba» debe decir **apartado 3.37** (Correspondencias y trazabilidad).

---

## 3. Párrafos gemelos que siguen en el documento

En cada caso la misma idea aparece dos veces seguidas. Conserva el párrafo que remite al Anexo E (o
el más completo) y fusiona en él lo que solo tenga el otro.

| Apartado | Página | Idea repetida |
|---|---|---|
| 2.4 Casos de uso | 34 | «No todos los casos pesan igual. La Tabla 26 especifica…» y «La especificación de esos cuatro casos… ocupa más espacio del que admite el cuerpo…» |
| 3.9 Catálogo de patrones | 52-53 | «Los doce patrones aplicados… se presentan en la Tabla 36» y el párrafo siguiente que vuelve a presentarlos antes de hablar de la pasarela |
| 3.11 Decisiones arquitectónicas | 55 | «La Tabla 64 enumera las catorce decisiones tomadas. Cada una se registra en formato MADR…» y «La Tabla 64 enumera las catorce decisiones tomadas y, para cada una, la fuente…» |
| 3.13 Registro MADR | 57 | «Trece decisiones están aceptadas y una, DA-14, queda como propuesta…» aparece dos veces (además debe corregirse, ver sección 4) |
| 3.28 Infraestructura | 72-73 | «El dimensionamiento inicial se deriva de las cifras de los requisitos… La Tabla 55 relaciona…» y «El dimensionamiento de partida… se presenta en la Tabla 55 del Anexo E…» |
| 3.29 Observabilidad | 74-75 | «Todas se emiten con OpenTelemetry desde las cuatro unidades y se correlacionan por el identificador de tarea…» (dos veces) |
| 3.30 Stack tecnológico | 75 | «Dos filas quedan abiertas a propósito…» (dos veces; además debe corregirse, ver sección 4) |
| 3.33 Controles de seguridad | 77 | «Diez son preventivos y se verifican en la canalización…» (dos veces) |
| 3.34 Evaluación (ATAM) | 77 | «Los dos puntos de compromiso que más condicionan el diseño comparten raíz…» (dos veces) |
| 3.35 Deuda técnica | 78 | «Los valores se medirán sobre el código en el tercer objetivo…» seguido de «El acoplamiento se midió sobre el código…»: elimina la primera frase, que ya no es cierta |

---

## 4. Correcciones de los capítulos 1 a 3 que no se aplicaron

1. **1.6, Fase 4 (p. 27):** «herramientas de monitoreo de telemetría correlacionada por tarea por
   definir» pasa a «OpenTelemetry con Azure Monitor para la telemetría correlacionada por tarea».
2. **3.13 (p. 57):** DA-14 ya no es propuesta: «Las catorce decisiones están aceptadas. DA-14 se
   implementó como reglas versionadas con doble control; sus valores siguen siendo provisionales hasta
   que el comité comercial apruebe las ponderaciones (DT-02)». Corrige igual la columna de estado de
   DA-14 en la Tabla 35 (p. 137) y en la Tabla 52 (pp. 148-149) si dice «Propuesta».
3. **3.22 Máquina de estados (pp. 66-68):** falta el párrafo de la sección 5, punto 3, del archivo
   original. Agrégalo después del párrafo de la Tabla 15:
   > La máquina se implementó como una pieza separada del orquestador, en el núcleo de dominio, y la
   > función de aptitud FF-06 verifica que rechace las cuatro transiciones de la Tabla 15. La
   > implementación precisó dos transiciones de la Figura 15: Fallida se alcanza desde cualquier
   > etapa cuando se agotan los reintentos, y una suspensión por cuota continúa en la etapa que quedó
   > pendiente, sea la extracción o la evaluación; una suspensión por sospecha de inyección no se
   > continúa, sino que se solicita un análisis nuevo. El registro de tareas conserva un estado
   > resumido y la etapa precisa se consulta en la API (`etapa_actual` y `etapas_cerradas`).
4. **3.23 Modelo de datos (p. 68):** agrega al final del párrafo: «El modelo construido tiene
   veinticinco tablas; la Figura 16 muestra las del núcleo del análisis y el Anexo H (apartado H.3)
   reúne todas con su propósito».
5. **3.29 Observabilidad (pp. 74-75):** además de quitar el gemelo, agrega: «Las nueve señales están
   instrumentadas, incluida la longitud de la cola. Las alertas de tiempo de análisis, longitud de la
   cola, apertura del disyuntor y suspensión por inyección están declaradas en la infraestructura
   como código; el aviso del 80 % de la cuota lo emite la propia aplicación, y los rechazos 403 por
   usuario se consultan en la bitácora, porque la telemetría no lleva datos personales (ASR-05)».
6. **3.30 Stack (p. 75):** el párrafo dice que el proveedor de identidad «se mantiene genérico». Ya
   no: «El proveedor de identidad es Microsoft Entra ID por OpenID Connect; la arquitectura sigue
   comprometiendo el protocolo y no el producto, de modo que otra fábrica puede usar su propio
   proveedor. Las versiones exactas se fijan en el archivo de dependencias del repositorio y la
   canalización las verifica». Quita «dos filas quedan abiertas a propósito».
7. **3.38 Resultado parcial (p. 80):** no se actualizó. Reemplaza el segundo párrafo («Quedan
   pendientes que no alteran el estilo…») por:
   > Los pendientes que este capítulo dejó abiertos se cerraron en la implementación: la matriz de
   > roles opera según la Tabla 53; las ponderaciones de ASR-14 se versionan con doble control y
   > siguen con valores provisionales (DT-02); el proveedor de identidad y los modelos de lenguaje se
   > fijaron en el tercer objetivo, como describe el capítulo 4. Solo la región de Azure sigue abierta,
   > porque depende de la política de transferencia internacional de datos.

   Y el tercer párrafo («Con las decisiones de arquitectura justificadas… las maquetas se diseñarán…»)
   por una sola frase: «Con la arquitectura justificada, el capítulo siguiente describe lo que se
   construyó sobre ella».

---

## 5. Tablas del Anexo E que siguen con el contenido anterior

1. **Tabla 37, Operaciones principales de la API (p. 137):** sigue con la versión original (nombres
   en camelCase, `POST /analisis` solo para el Analista, `POST /oportunidades/{id}/decision` con 409).
   **Reemplázala completa** por la tabla de la sección 7.3 del archivo de instrucciones original,
   con su nota al pie.
2. **Tabla 38, Contrato de la cola (p. 138):** sigue igual. Reemplázala por:

   | Mensaje | Emisor | Consumidor | Carga útil | Entrega y repetición |
   |---|---|---|---|---|
   | analisis.solicitado | API | Trabajador de análisis | { tarea_id, licitacion_url, contenido_pliego, reglas_version, portafolio_version } | Idempotente por tarea: un mensaje repetido continúa desde el último checkpoint |
   | analisis.reanudar | API | Trabajador de análisis | { tarea_id } | Idempotente por tarea y etapa: sin lista aprobada no avanza |
   | analisis.continuar | API | Trabajador de análisis | { tarea_id } | Solo para una tarea suspendida por cuota, cuando vuelve a haber cuota |
   | portafolio.indexar | API | Trabajador de análisis | { portafolio_version } | Reindexación incremental, repetible sin efectos |

   Nota bajo la tabla: «Todos los mensajes viajan por una sola cola (`analisis-licitaciones`) con el
   tipo en el campo `tipo_tarea` y el contexto de traza; tras diez entregas fallidas pasan a la cola de
   mensajes fallidos y la tarea queda Fallida con el motivo. Las novedades de los procesos seguidos no
   viajan por la cola: el notificador, que está en el mismo trabajador de vigilancia, las lee de la
   bandeja persistente `notificaciones`, que evita avisos repetidos (DV-05)».
3. **Tabla 39, Diccionario de datos (p. 138):** agrega dos filas:
   `preferencias_notificacion | usuario | text | Sí | Correo institucional del usuario; identifica sus
   preferencias de canal y frecuencia. | Alta: dato personal sujeto a la Ley 1581 de 2012. | RF-016` y
   `notificaciones | destinatario | text | Sí | Correo del usuario que recibe el aviso. | Alta: dato
   personal sujeto a la Ley 1581 de 2012. | RF-017, RF-020`.
4. **Tabla 50, Stack (p. 147):** hay un error y varias versiones viejas:
   - **«Locust 3.18» es un error** (es la versión de NiceGUI): debe decir **Locust 2.47**.
   - FastAPI 0.143 con Uvicorn 0.54; LangGraph 1.2 con psycopg 3.3; pgvector 0.3 en el cliente y
     SQLAlchemy 2.1; OpenTelemetry 1.45; pytest 9.1 con pytest-cov 7.1; Bandit 1.9.4 y pip-audit
     2.10.1.
   - En «Modelos de lenguaje», agrega en la versión: gpt-5-mini y text-embedding-3-small.
   - «Almacenamiento de objetos»: Blob Storage para los informes con inmutabilidad; agrega una fila
     «Almacenamiento de archivos: Azure Files, expediente documental, DA-12».
   - Agrega una fila «Infraestructura como código: Terraform, 1.9.8 con azurerm 4.81, declara los
     tres ambientes, MPL 2.0 (proveedor) y BUSL 1.1 (Terraform), DA-12» y otra «Lectura de
     documentos: pypdf 6.21, texto por página de los PDF del expediente, BSD, RF-023».
5. **Tabla 58, Deuda técnica (p. 152):** sigue igual que antes. Debe quedar:
   - DT-01: **Resuelta**: las pantallas de Usuarios y de Reglas del puntaje están construidas.
   - DT-02, DT-03, DT-04 y DT-05: sin cambios (vigentes).
   - DT-06: **Resuelta en lo escrito**: el código de Terraform está validado; su aplicación depende de
     DT-04.
   - **DT-07 (nueva):** la salida con dirección IP fija no está implementada (DV-10). Impacto bajo.
     Consecuencia: una fuente externa que exija lista de IP permitidas no podría reconocer el origen.
     Se resuelve si alguna fuente lo exige. Responsable: equipo técnico.
   - **DT-08 (nueva):** las suites de ASR-10 (17 de 50 casos) y de ASR-03 (sin los 500 esquemas
     históricos) están incompletas. Impacto medio. Consecuencia: esos dos escenarios no pueden
     declararse medidos. Se resuelve en el cuarto objetivo. Responsable: equipo técnico.

   El texto de la p. 78 dice «Dos entradas quedaron resueltas durante l[a implementación]»; con este
   cambio la tabla lo respalda.
6. **Tabla 59, Acoplamiento (p. 152):** sigue con los valores esperados. Cambia el título a
   «Acoplamiento esperado y medido por agrupación de módulos» y deja estas columnas: Agrupación |
   Esperado (Ca, Ce, I, A) | Medido (Ca, Ce, I, A) | Lectura.

   | Agrupación | Esperado | Medido | Lectura |
   |---|---|---|---|
   | Núcleo de dominio | Ca alta, Ce baja, I baja, A alta | Ca 7, Ce 0, I 0,00, A 0,27 | Estable como se esperaba; menos abstracto porque en Python los puertos son protocolos estructurales y el dominio usa modelos de datos concretos. |
   | Adaptadores de integración | Ca baja, Ce alta, I alta, A baja | Ca 22, Ce 10, I 0,31, A 0,00 | Más estables de lo previsto: la API y los trabajadores comparten los repositorios sobre una sola base (DA-05). |
   | Módulos de la API | Media en todo, A baja | Ca 2, Ce 21, I 0,91, A 0,00 | Son hojas que absorben el cambio externo, como corresponde a la capa más externa. |
   | Motor de puntaje | Ca baja, Ce baja, I baja, A media | Ca 2, Ce 1, I 0,33, A 0,00 | Aislado: solo depende de los esquemas de dominio (FF-04). |

   Nota: «Medido con `scripts/metricas_acoplamiento.py` sobre el código del MVP. Ca: módulos que
   dependen de la agrupación; Ce: módulos de los que ella depende; I = Ce/(Ca+Ce); A: proporción de
   clases abstractas».
7. **Tabla 60, Trazabilidad (p. 153):** en la columna de prueba de «Seguir el estado del embudo
   comercial», «Suite de 200 pruebas de rol y operación» pasa a «Suite de 225 combinaciones de rol y
   operación (FF-05)».
8. **Tabla 40, Controles (p. 139):** en la evidencia de C-01, menciona FF-05 junto a las 225
   combinaciones si no aparece.
9. **Tabla 27, HU-06 CA-03 (p. 126):** el «Entonces» sigue con el texto original. Cámbialo por: «el
   sistema marca como pendientes de revisión solo los requisitos cuyo numeral cambió, que la adenda
   cita o cuyo documento se retiró; los demás conservan la aprobación y sus correcciones; una adenda
   que no cita numerales devuelve toda la lista a revisión».

---

## 6. Lo que queda abierto a propósito

- `[POR COMPLETAR: capturas…]` en el Anexo F (p. 156) y la figura de capturas reales del capítulo 4:
  las agrega la persona usuaria.
- El capítulo 5, las conclusiones y las recomendaciones se escriben después.

## 7. Lista de verificación de esta pasada

- [ ] Ninguna tabla se llama «Tabla 64» en el cuerpo y la secuencia de tablas no tiene huecos ni repetidas.
- [ ] El índice de contenido lista los capítulos 4 y 5 con sus apartados y páginas reales.
- [ ] No quedan los gemelos de la sección 3.
- [ ] No queda «genérico», «por definir», «Locust 3.18», «identificador de token», «se medirán», «DT-06 No hay» ni «queda como propuesta».
- [ ] Las Tablas 37, 38, 39, 50, 58, 59 y 60 tienen el contenido nuevo.
- [ ] Los anexos empiezan en la página ___ (101 o menos).
