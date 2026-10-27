"""
Trazabilidad de los 38 escenarios de aceptación (Tabla 27) con las pruebas que los verifican.

Cada escenario lista las pruebas automatizadas que lo cubren ("archivo::función"). Si una parte
del criterio solo se observa en la pantalla, "interfaz" dice qué revisa el analista; si el sistema
no cumple el criterio tal como está escrito, "brecha" lo explica. test_matriz_gherkin.py impide que
la matriz quede desactualizada y scripts/matriz_aceptacion.py la ejecuta y genera el reporte.
"""

U = "tests/unit/"
I = "tests/integration/test_flujo_postgres.py::"
A12 = "tests/asr/test_asr12_human_gate.py::"
FF06 = "tests/aptitud/test_ff06_maquina_estados.py::"

ESCENARIOS = {
    "HU-01 CA-01": {
        "titulo": "Registrar el portafolio por primera vez crea la versión 1",
        "pruebas": [U + "test_reglas_y_versiones.py::test_publicar_crea_version_vigente_y_conserva_la_anterior",
                    U + "test_reglas_y_versiones.py::test_api_portafolio_publica_e_indexa"],
    },
    "HU-01 CA-02": {
        "titulo": "Actualizar el portafolio crea la versión 2 y conserva la 1 para los análisis emitidos",
        "pruebas": [U + "test_reglas_y_versiones.py::test_publicar_crea_version_vigente_y_conserva_la_anterior",
                    U + "test_reglas_y_versiones.py::test_solo_se_indexa_lo_nuevo_o_modificado",
                    I + "test_reglas_y_portafolio_versionados_en_postgres"],
    },
    "HU-01 CA-03": {
        "titulo": "Un usuario sin permiso no registra portafolio y el intento queda auditado",
        "pruebas": [U + "test_identidad.py::test_api_aplica_la_matriz_de_roles",
                    U + "test_identidad.py::test_api_el_acceso_denegado_queda_en_la_bitacora",
                    "tests/aptitud/test_ff05_rol_operacion.py::test_ff05_el_rol_sin_permiso_recibe_403"],
    },
    "HU-01 CA-04": {
        "titulo": "Un archivo de más de 25 MB o que no es PDF ni DOCX no se carga como portafolio",
        "pruebas": [],
        "brecha": ("El portafolio se registra como capacidades estructuradas (formulario, API o JSON), no como "
                   "un archivo PDF o DOCX; el límite de 25 MB y los formatos existen solo para el expediente "
                   "(prueba test_la_carga_manual_rechaza_formatos_y_tamanos_no_admitidos)."),
    },
    "HU-02 CA-01": {
        "titulo": "Registrar un proceso vigente recupera sus datos y su expediente",
        "pruebas": [U + "test_monitoreo.py::test_radicar_recupera_metadatos_y_documentos_o_rechaza_el_enlace",
                    U + "test_monitoreo.py::test_documento_descargado_queda_disponible_con_huella",
                    I + "test_radicacion_expediente_y_analisis_con_documentos"],
        "nota": "SECOP II responde 403 a la descarga automática (DV-01): los documentos se cargan a mano.",
    },
    "HU-02 CA-02": {
        "titulo": "Un anexo no disponible se lista como faltante y el analista decide",
        "pruebas": [U + "test_monitoreo.py::test_lo_que_la_fuente_no_entrega_queda_como_faltante_con_su_motivo"],
    },
    "HU-02 CA-03": {
        "titulo": "Cada documento muestra nombre, versión, procedencia y fecha; el ilegible queda listado",
        "pruebas": [U + "test_monitoreo.py::test_carga_manual_registra_procedencia_y_version",
                    U + "test_monitoreo.py::test_formato_no_admitido_o_sin_texto_es_ilegible",
                    U + "test_monitoreo.py::test_api_expediente_respeta_la_tabla_61"],
    },
    "HU-02 CA-04": {
        "titulo": "Un enlace que no corresponde a un proceso se rechaza sin crear tarea",
        "pruebas": [U + "test_monitoreo.py::test_radicar_recupera_metadatos_y_documentos_o_rechaza_el_enlace",
                    I + "test_tarea_inexistente_y_entrada_invalida"],
    },
    "HU-03 CA-01": {
        "titulo": "Todos los habilitantes cumplen: se recomienda ofertar con justificación",
        "pruebas": ["tests/test_recomendador.py::test_umbrales",
                    U + "test_prompts_y_agentes.py::test_recomendador_envia_texto_del_requisito_y_umbrales"],
    },
    "HU-03 CA-02": {
        "titulo": "Un habilitante que no cumple impide recomendar ofertar aunque el puntaje sea alto",
        "pruebas": ["tests/test_recomendador.py::test_no_cumple_prevalece_sobre_no_verificable_sin_importar_el_orden"],
    },
    "HU-03 CA-03": {
        "titulo": "Habilitantes no verificables llevan a solicitar revisión",
        "pruebas": ["tests/test_recomendador.py::test_habilitante_no_verificable_pide_revision",
                    U + "test_prompts_y_agentes.py::test_habilitante_parcial_exige_revision_aunque_el_puntaje_sea_alto"],
    },
    "HU-03 CA-04": {
        "titulo": "Una tarea en error no muestra recomendación e informa estado y fecha",
        "pruebas": [A12 + "test_error_queda_registrado_en_la_tarea"],
        "interfaz": "La oportunidad muestra el estado Fallida y la fecha del último intento.",
    },
    "HU-04 CA-01": {
        "titulo": "Un proceso nuevo que coincide con un perfil se notifica",
        "pruebas": [U + "test_monitoreo.py::test_un_proceso_coincide_con_un_perfil_segun_todos_sus_criterios",
                    U + "test_notificaciones.py::test_una_oportunidad_se_avisa_una_vez_con_proceso_entidad_y_cierre"],
    },
    "HU-04 CA-02": {
        "titulo": "Un proceso ya notificado no se vuelve a notificar por el mismo canal",
        "pruebas": [U + "test_monitoreo.py::test_un_proceso_coincide_una_sola_vez_con_cada_perfil",
                    U + "test_notificaciones.py::test_frecuencia_inmediata_envia_cada_aviso_una_vez"],
    },
    "HU-04 CA-03": {
        "titulo": "El resumen diario llega en un único envío consolidado",
        "pruebas": [U + "test_notificaciones.py::test_resumen_diario_un_solo_envio_consolidado_al_dia"],
    },
    "HU-04 CA-04": {
        "titulo": "Con la fuente caída se muestran los datos previos, la advertencia y la última sincronización",
        "pruebas": [U + "test_monitoreo.py::test_con_la_fuente_caida_se_avisa_y_se_muestra_la_ultima_sincronizacion_exitosa"],
    },
    "HU-05 CA-01": {
        "titulo": "El extractor entrega cada requisito con identificador, texto, categoría, condición y referencia",
        "pruebas": [U + "test_evaluar_extractor.py::test_corrida_correcta",
                    "tests/test_orquestador.py::test_extraccion_asigna_ids_unicos_entre_fragmentos",
                    U + "test_paralelismo_y_cola.py::test_extraccion_en_paralelo_da_lo_mismo_que_en_serie"],
        "nota": "La medición sobre pliegos reales de 46 a 134 páginas está en scripts/evaluar_corpus.py.",
    },
    "HU-05 CA-02": {
        "titulo": "Una tabla financiera de dos páginas queda asociada al título de su sección",
        "pruebas": [U + "test_monitoreo.py::test_la_tabla_no_se_parte_aunque_el_fragmento_se_llene",
                    U + "test_monitoreo.py::test_cada_fragmento_conserva_documento_version_pagina_y_seccion"],
    },
    "HU-05 CA-03": {
        "titulo": "Un requisito ambiguo se señala como incierto y va a revisión sin evaluarse",
        "pruebas": [A12 + "test_el_grafo_se_detiene_antes_de_evaluar"],
        "brecha": ("El requisito extraído no tiene una marca de incertidumbre. Lo que sí se cumple es que toda la "
                   "lista, ambigua o no, pasa por la revisión del analista antes de cualquier evaluación."),
    },
    "HU-05 CA-04": {
        "titulo": "Un fragmento sin referencia se descarta y el descarte queda en la traza",
        "pruebas": [U + "test_monitoreo.py::test_sin_marcas_se_comporta_como_antes_y_sin_referencia_se_descarta"],
    },
    "HU-06 CA-01": {
        "titulo": "La corrección del analista se aprueba y se conserva el valor generado por la IA",
        "pruebas": [A12 + "test_aprobacion_y_reanudacion_evalua_solo_la_lista_aprobada",
                    U + "test_revision_requisitos.py::test_put_requisitos_borrador_y_aprobacion",
                    I + "test_flujo_completo_con_compuerta_humana"],
    },
    "HU-06 CA-02": {
        "titulo": "Un requisito agregado a mano queda marcado como intervención humana con autor y fecha",
        "pruebas": [U + "test_informe_y_bitacora.py::test_el_informe_es_un_pdf_con_todo_lo_que_exige_rf_037",
                    I + "test_flujo_completo_con_compuerta_humana"],
    },
    "HU-06 CA-03": {
        "titulo": "Una adenda devuelve a revisión solo los requisitos afectados",
        "pruebas": [U + "test_revision_requisitos.py::test_adenda_devuelve_a_revision_solo_lo_afectado",
                    U + "test_revision_requisitos.py::test_version_nueva_solo_devuelve_a_revision_el_numeral_que_cambio"],
    },
    "HU-06 CA-04": {
        "titulo": "No se evalúa una lista que el analista no ha aprobado",
        "pruebas": [FF06 + "test_no_se_evalua_sin_aprobacion", FF06 + "test_reanudar_sin_aprobacion_no_evalua",
                    A12 + "test_reanudar_sin_aprobacion_no_avanza_dos_veces"],
    },
    "HU-07 CA-01": {
        "titulo": "Cada requisito aprobado tiene un dictamen con evidencia y justificación",
        "pruebas": [A12 + "test_aprobacion_y_reanudacion_evalua_solo_la_lista_aprobada",
                    I + "test_flujo_completo_con_compuerta_humana"],
        "nota": "La exactitud de los dictámenes sobre pliegos reales está en scripts/evaluar_corpus.py.",
    },
    "HU-07 CA-02": {
        "titulo": "Un dictamen Cumple o Cumple parcialmente muestra el extracto del portafolio",
        "pruebas": [U + "test_prompts_y_agentes.py::test_cumple_citando_registro_recuperado_se_conserva",
                    U + "test_prompts_y_agentes.py::test_cumple_sin_cita_valida_se_degrada"],
        "interfaz": "El diálogo «Detalle de la evaluación» muestra la evidencia citada.",
    },
    "HU-07 CA-03": {
        "titulo": "Sin información en el portafolio el dictamen es No verificable y nunca No cumple",
        "pruebas": [U + "test_prompts_y_agentes.py::test_sin_evidencia_es_no_verificable_sin_llamar_al_modelo",
                    U + "test_prompts_y_agentes.py::test_no_verificable_del_modelo_no_se_altera"],
    },
    "HU-08 CA-01": {
        "titulo": "El puntaje va de 0 a 100 con el aporte de cada categoría",
        "pruebas": ["tests/test_motor_puntaje.py::test_puntaje_perfecto",
                    "tests/test_motor_puntaje.py::test_redistribucion_proporcional",
                    U + "test_reglas_y_versiones.py::test_el_motor_usa_los_pesos_de_la_version"],
    },
    "HU-08 CA-02": {
        "titulo": "Sin requisitos financieros la categoría no aplica y no reduce el resultado",
        "pruebas": ["tests/test_motor_puntaje.py::test_categoria_ausente_no_regala_puntos",
                    "tests/test_motor_puntaje.py::test_cumplimiento_parcial_redistribuye_categorias_ausentes"],
    },
    "HU-08 CA-03": {
        "titulo": "Los No verificable se contabilizan aparte y no como incumplimiento",
        "pruebas": [],
        "brecha": ("El motor asigna 0 puntos a un No verificable, igual que a un No cumple, y el desglose no los "
                   "cuenta aparte (el comentario de motor.py dice lo contrario del criterio). Sí se diferencian "
                   "en la recomendación (piden revisión) y en el informe (incertidumbres)."),
    },
    "HU-08 CA-04": {
        "titulo": "Un análisis conserva su puntaje y la versión de reglas con que se calculó",
        "pruebas": [U + "test_reglas_y_versiones.py::test_el_grafo_aplica_la_version_fijada_por_la_tarea",
                    U + "test_reglas_y_versiones.py::test_api_reutiliza_un_analisis_vigente"],
    },
    "HU-09 CA-01": {
        "titulo": "El informe PDF trae puntaje, recomendación y dictamen de cada requisito",
        "pruebas": [U + "test_informe_y_bitacora.py::test_el_informe_es_un_pdf_con_todo_lo_que_exige_rf_037",
                    "tests/test_orquestador.py::test_generar_informe"],
    },
    "HU-09 CA-02": {
        "titulo": "El informe señala documentos faltantes, incertidumbres e intervenciones humanas",
        "pruebas": [U + "test_monitoreo.py::test_el_analisis_usa_el_expediente_y_el_informe_lo_declara",
                    U + "test_informe_y_bitacora.py::test_el_informe_es_un_pdf_con_todo_lo_que_exige_rf_037"],
    },
    "HU-09 CA-03": {
        "titulo": "No se genera informe de un análisis en proceso",
        "pruebas": ["tests/test_orquestador.py::test_no_se_genera_informe_sin_puntaje",
                    FF06 + "test_no_se_genera_informe_sin_puntaje"],
    },
    "HU-10 CA-01": {
        "titulo": "El tablero muestra estado, puntaje, recomendación y decisión en campos distintos",
        "pruebas": [U + "test_decisiones.py::test_tablero_filtra_por_recomendacion_y_decision"],
        "interfaz": "Cada fila del tablero muestra las columnas en campos separados.",
    },
    "HU-10 CA-02": {
        "titulo": "Ordenar por puntaje descendente pone primero la de mayor puntaje",
        "pruebas": [],
        "interfaz": "La columna Puntaje del tablero es ordenable (sortable); se verifica con cinco oportunidades.",
    },
    "HU-10 CA-03": {
        "titulo": "Una oportunidad no autorizada para el rol no aparece en el tablero",
        "pruebas": [U + "test_identidad.py::test_api_aplica_la_matriz_de_roles",
                    "tests/aptitud/test_ff05_rol_operacion.py::test_ff05_el_rol_sin_permiso_recibe_403"],
        "interfaz": "Con un rol sin acceso, la oportunidad no aparece ni en el listado ni en los filtros.",
    },
    "HU-10 CA-04": {
        "titulo": "Una tarea fallida aparece marcada, sin puntaje y con la fecha del último intento",
        "pruebas": [A12 + "test_error_queda_registrado_en_la_tarea"],
        "interfaz": "La fila muestra Fallida, sin puntaje, y la fecha del último intento.",
    },
}
