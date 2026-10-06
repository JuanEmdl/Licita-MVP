from nicegui import ui
import asyncio

from tema import (
    TONOS,
    banda,
    boton,
    cabecera_seccion,
    cargar_tema,
    etiqueta,
    ficha_icono,
    kpi,
    medidor,
    tarjeta,
)

# --- Mock Data for the MVP UI ---
mock_portafolio = [
    {"id": 1, "tecnologia": "Python", "categoria": "Desarrollo", "descripcion": "Experiencia en 3 proyectos de backend con FastAPI."},
    {"id": 2, "tecnologia": "Azure", "categoria": "Infraestructura", "descripcion": "Despliegue de arquitecturas cloud nativas."}
]

mock_tareas_revision = [
    {"id": "tarea_SECOP-2026-001", "licitacion": "SECOP-2026-001 - Desarrollo de Software a Medida"}
]

mock_requisitos_extraidos = [
    {"id_interno": "REQ-1", "categoria": "Técnico", "descripcion": "Desarrollo en Python/FastAPI", "criterio": "Experiencia comprobable", "es_habilitante": True, "puntaje_maximo": 0},
    {"id_interno": "REQ-2", "categoria": "Experiencia", "descripcion": "3 proyectos similares en el Estado", "criterio": "Certificaciones", "es_habilitante": False, "puntaje_maximo": 30}
]

mock_tablero = [
    {"id": "SECOP-2026-001", "entidad": "MinTIC", "estado": "Finalizada", "puntaje": 85, "recomendacion": "Ofertar", "decision": "Pendiente"},
    {"id": "SECOP-2026-002", "entidad": "DIAN", "estado": "Finalizada", "puntaje": 45, "recomendacion": "No ofertar", "decision": "Descartada"}
]

CATEGORIAS = ['Desarrollo', 'Infraestructura', 'Experiencia', 'Certificación']

# Color por categoria del portafolio, para que la tabla se lea de un vistazo.
TONO_CATEGORIA = {
    'Desarrollo': 'azul',
    'Infraestructura': 'violeta',
    'Experiencia': 'verde',
    'Certificación': 'ambar',
}


# --- UI Components ---

def show_portafolio():
    with banda(
        'Gestión del portafolio de capacidades',
        'Registra las tecnologías y casos de éxito que sirven como base de conocimiento para la '
        'evaluación. Cada registro se vectoriza en pgvector.',
        'EP-01 · Analista comercial',
    ):
        boton('Exportar', lambda: ui.notify('Portafolio exportado.', type='info'),
              'download', 'banda')

    with ui.row().classes('w-full gap-3'):
        kpi(str(len(mock_portafolio)), 'Capacidades registradas', 'Base de conocimiento activa',
            'azul', 'inventory_2')
        kpi('4', 'Categorías cubiertas', 'Desarrollo, infraestructura, experiencia', 'violeta',
            'category')
        kpi('pgvector', 'Índice semántico', 'Sincronizado', 'verde', 'hub')

    with tarjeta('azul'):
        cabecera_seccion('Agregar nueva capacidad',
                         'El texto de la descripción es lo que alimenta la búsqueda semántica.',
                         'add_circle', 'azul')
        with ui.row().classes('w-full items-start gap-3'):
            tec = ui.input('Tecnología').props('outlined dense').classes('flex-1')
            cat = ui.select(CATEGORIAS, label='Categoría').props('outlined dense').classes('flex-1')
            desc = ui.input('Descripción (caso de éxito o detalle)').props('outlined dense').classes('flex-[2]')

            def add_item():
                if tec.value and cat.value and desc.value:
                    mock_portafolio.append({
                        "id": len(mock_portafolio) + 1,
                        "tecnologia": tec.value, "categoria": cat.value, "descripcion": desc.value
                    })
                    table.update()
                    tec.value = ''; cat.value = ''; desc.value = ''
                    ui.notify('Capacidad guardada y vectorizada (pgvector).', type='positive')
                else:
                    ui.notify('Completa los tres campos antes de guardar.', type='warning')

            boton('Guardar', add_item, 'save', 'primario')

    with tarjeta('violeta'):
        cabecera_seccion('Capacidades acreditadas',
                         f'{len(mock_portafolio)} registros contrastables contra cada licitación.',
                         'verified', 'violeta')
        columns = [
            {'name': 'id', 'label': 'ID', 'field': 'id', 'align': 'left'},
            {'name': 'tecnologia', 'label': 'Tecnología', 'field': 'tecnologia', 'align': 'left', 'sortable': True},
            {'name': 'categoria', 'label': 'Categoría', 'field': 'categoria', 'align': 'left', 'sortable': True},
            {'name': 'descripcion', 'label': 'Descripción', 'field': 'descripcion', 'align': 'left'},
        ]
        table = ui.table(columns=columns, rows=mock_portafolio, row_key='id').props(
            'flat dense wrap-cells'
        ).classes('w-full')
        table.add_slot('body-cell-categoria', _ranura_categoria())
        table.add_slot(
            'body-cell-tecnologia',
            '<q-td :props="props"><span style="font-weight:500;color:#0F172A">{{ props.value }}'
            '</span></q-td>',
        )


def _ranura_categoria() -> str:
    """Pinta la categoria con el tono que le corresponde en TONO_CATEGORIA."""
    reglas = ','.join(
        f"'{cat}':'background:{TONOS[t][0]};color:{TONOS[t][1]};border-color:{TONOS[t][2]}'"
        for cat, t in TONO_CATEGORIA.items()
    )
    return f'''
    <q-td :props="props">
      <span class="tag" :style="{{{reglas}}}[props.value]">{{{{ props.value }}}}</span>
    </q-td>
    '''


def show_vigilancia():
    with banda(
        'Vigilancia de oportunidades SECOP II',
        'El trabajador de vigilancia barre SECOP II y contrasta cada proceso nuevo contra el '
        'perfil del portafolio vigente.',
        'EP-02 · Analista comercial',
    ):
        boton('Configurar barrido', lambda: ui.notify('Configuración del barrido programado.'),
              'tune', 'banda')

    with ui.row().classes('w-full gap-3'):
        kpi('1', 'Alertas sin revisar', 'Detectada en el último barrido', 'ambar',
            'notifications_active')
        kpi('3', 'Análisis en cola', '1 en ejecución · 2 en espera', 'azul', 'pending_actions')
        kpi('18:00', 'Próximo barrido', 'Programado para hoy', 'violeta', 'schedule')

    with ui.row().classes('w-full gap-4 items-start'):

        with ui.column().classes('flex-[3] gap-4 min-w-[360px]'):
            with tarjeta('ambar'):
                cabecera_seccion('Alertas automatizadas',
                                 'Coincidencias del barrido contra el perfil tecnológico.',
                                 'notifications_active', 'ambar')
                with ui.column().classes('w-full gap-2 p-4').style(
                    'background:#FFFBEB;border:1px solid #FDE68A;border-left:4px solid #D97706;'
                    'border-radius:9px'
                ):
                    with ui.row().classes('w-full items-center justify-between gap-3'):
                        ui.html(
                            '<span style="font-weight:600;color:#92400E;font-size:0.88rem">'
                            'Nueva licitación detectada · SECOP-2026-003</span>'
                        )
                        etiqueta('Alta afinidad', 'ambar')
                    ui.html(
                        '<span style="font-size:0.82rem;color:#B45309">Desarrollo de plataforma '
                        'transaccional.</span>'
                    )
                    with ui.row().classes('gap-2 pt-1'):
                        boton('Solicitar análisis',
                              lambda: ui.notify('Análisis encolado...', type='info'),
                              'play_arrow', 'primario')
                        boton('Descartar',
                              lambda: ui.notify('Alerta descartada del barrido.'),
                              'close', 'claro')

        with ui.column().classes('flex-[2] gap-4 min-w-[300px]'):
            with tarjeta('azul'):
                cabecera_seccion('Solicitud manual',
                                 'Radica un proceso que el barrido no haya detectado.',
                                 'add_link', 'azul')
                secop_id = ui.input(
                    'ID de proceso SECOP II', placeholder='Ej: SECOP-2026-001',
                ).props('outlined dense').classes('w-full')

                async def request_analysis():
                    if secop_id.value:
                        ui.notify('Enviando solicitud a la API (ASR-11)...', type='info')
                        await asyncio.sleep(1)  # Simula latencia API
                        ui.notify(f'Tarea aceptada. ID: tarea_{secop_id.value}', type='positive')
                        secop_id.value = ''
                    else:
                        ui.notify('Indica el ID del proceso.', type='warning')

                boton('Iniciar análisis', request_analysis, 'rocket_launch',
                      'primario').classes('w-full')

                with ui.row().classes('w-full items-center gap-2 pt-2').style(
                    'border-top:1px solid #E2E8F2'
                ):
                    ficha_icono('lock', 'verde', '14px')
                    ui.html(
                        '<span class="meta">La API valida el rol antes de encolar la tarea.</span>'
                    )


def show_analisis():
    with banda(
        'Revisión de requisitos extraídos',
        'El orquestador de LangGraph se detiene aquí. Revisa, edita o agrega requisitos antes de '
        'que el Agente Evaluador proceda.',
        'EP-03 · ASR-12 · Compuerta humana',
    ):
        etiqueta('Flujo suspendido', 'ambar')

    with ui.row().classes('w-full items-start gap-3 p-4').style(
        'background:#FFFBEB;border:1px solid #FDE68A;border-left:4px solid #D97706;border-radius:10px'
    ):
        ficha_icono('pan_tool', 'ambar')
        with ui.column().classes('gap-0.5 flex-1'):
            ui.html(
                '<span style="font-weight:600;color:#92400E;font-size:0.86rem">El StateGraph '
                'espera tu confirmación</span>'
            )
            ui.html(
                '<span style="font-size:0.78rem;color:#B45309;line-height:1.45">Ningún agente de '
                'evaluación corre con requisitos sin validar: un criterio mal leído arrastra el '
                'error hasta la recomendación final y el informe firmado.</span>'
            )

    with ui.row().classes('w-full gap-3'):
        kpi(str(len(mock_requisitos_extraidos)), 'Requisitos extraídos', 'Por el agente LLM',
            'azul', 'fact_check')
        kpi('1', 'Habilitante', 'Su incumplimiento descalifica', 'rojo', 'gpp_maybe')
        kpi('30', 'Puntaje ponderable', 'Suma de criterios con peso', 'verde', 'scoreboard')

    with tarjeta('ambar'):
        with ui.row().classes('w-full items-end justify-between gap-4'):
            cabecera_seccion('Lista extraída del expediente',
                             'Doble clic sobre una celda para corregirla (RF-030).',
                             'edit_note', 'ambar')
            tarea_sel = ui.select(
                {t['id']: t['licitacion'] for t in mock_tareas_revision},
                label='Tarea en espera',
            ).props('outlined dense').classes('min-w-[340px]')

        # Usamos aggrid para permitir edición directa en la tabla (RF-030)
        grid_options = {
            'columnDefs': [
                {'field': 'id_interno', 'headerName': 'ID', 'editable': False, 'width': 100},
                {'field': 'categoria', 'headerName': 'Categoría', 'editable': True, 'width': 150, 'cellEditor': 'agSelectCellEditor', 'cellEditorParams': {'values': ['Técnico', 'Financiero', 'Experiencia']}},
                {'field': 'descripcion', 'headerName': 'Descripción', 'editable': True, 'flex': 1},
                {'field': 'es_habilitante', 'headerName': 'Habilitante', 'editable': True, 'cellEditor': 'agCheckboxCellEditor', 'width': 120},
                {'field': 'puntaje_maximo', 'headerName': 'Puntaje Máx.', 'editable': True, 'width': 120},
            ],
            'rowData': mock_requisitos_extraidos,
            'rowSelection': 'single',
        }

        aggrid = ui.aggrid(grid_options).classes('h-64 w-full')

        def add_row():
            new_req = {"id_interno": f"REQ-{len(mock_requisitos_extraidos)+1}", "categoria": "Técnico", "descripcion": "Nuevo requisito...", "es_habilitante": False, "puntaje_maximo": 0}
            mock_requisitos_extraidos.append(new_req)
            aggrid.update()

        def approve_and_resume():
            if not tarea_sel.value:
                ui.notify('Selecciona una tarea primero.', type='warning')
                return
            ui.notify(
                f'Lista aprobada. Reanudando StateGraph desde checkpoint en Postgres para la '
                f'tarea {tarea_sel.value}...', type='positive',
            )
            # Limpiar selección simulando que la tarea avanzó
            tarea_sel.value = None

        with ui.row().classes('w-full items-center justify-between gap-3 pt-1'):
            boton('Añadir requisito', add_row, 'add', 'claro')
            with ui.row().classes('items-center gap-3'):
                ui.html(
                    '<span class="meta">Al aprobar, la lista se sella y el grafo reanuda desde '
                    'su checkpoint.</span>'
                )
                boton('Aprobar y continuar evaluación', approve_and_resume, 'check_circle', 'exito')


def show_resultados():
    ofertar = sum(1 for r in mock_tablero if r['recomendacion'] == 'Ofertar')
    pendientes = sum(1 for r in mock_tablero if r['decision'] == 'Pendiente')
    promedio = round(sum(r['puntaje'] for r in mock_tablero) / len(mock_tablero)) if mock_tablero else 0

    with banda(
        'Tablero de resultados y decisiones',
        'Embudo comercial con el puntaje que calculó el sistema, la sugerencia automática y la '
        'decisión que registra el gerente.',
        'EP-04 · EP-05 · Gerente comercial',
    ):
        boton('Exportar embudo', lambda: ui.notify('Embudo exportado.', type='info'),
              'download', 'banda')

    with ui.row().classes('w-full gap-3'):
        kpi(str(len(mock_tablero)), 'Licitaciones analizadas', 'Con informe emitido', 'azul',
            'analytics')
        kpi(str(ofertar), 'Sugeridas para ofertar', 'Por encima del umbral', 'verde', 'trending_up')
        kpi(str(pendientes), 'Decisiones pendientes', 'Esperan al gerente', 'ambar', 'how_to_vote')
        kpi(str(promedio), 'Puntaje promedio', 'Sobre 100 puntos', 'violeta', 'speed')

    with tarjeta('verde'):
        cabecera_seccion('Embudo comercial',
                         'El puntaje agrega el cumplimiento ponderado de cada requisito.',
                         'dashboard', 'verde')

        columns = [
            {'name': 'id', 'label': 'Licitación', 'field': 'id', 'align': 'left', 'sortable': True},
            {'name': 'entidad', 'label': 'Entidad', 'field': 'entidad', 'align': 'left', 'sortable': True},
            {'name': 'estado', 'label': 'Estado Análisis', 'field': 'estado', 'align': 'left'},
            {'name': 'puntaje', 'label': 'Puntaje', 'field': 'puntaje', 'align': 'left', 'sortable': True},
            {'name': 'recomendacion', 'label': 'Sugerencia IA', 'field': 'recomendacion', 'align': 'left'},
            {'name': 'decision', 'label': 'Decisión Comercial', 'field': 'decision', 'align': 'left'},
            {'name': 'acciones', 'label': 'Acciones', 'field': 'acciones', 'align': 'right'}
        ]

        with ui.table(columns=columns, rows=mock_tablero, row_key='id').props(
            'flat dense wrap-cells'
        ).classes('w-full') as table:
            table.add_slot('body-cell-id', '''
                <q-td :props="props">
                    <span style="font-weight:500;color:#0F172A">{{ props.value }}</span>
                </q-td>
            ''')
            table.add_slot('body-cell-estado', '''
                <q-td :props="props">
                    <span class="tag" style="background:#EFF4FF;color:#1D4ED8;border-color:#C7D7FE">
                        <span class="punto" style="background:#1D4ED8"></span>{{ props.value }}
                    </span>
                </q-td>
            ''')
            table.add_slot('body-cell-puntaje', '''
                <q-td :props="props">
                    <div style="display:flex;align-items:center;gap:10px">
                        <span style="font-weight:700;font-size:0.85rem;min-width:22px;
                            color:#0F172A">{{ props.value }}</span>
                        <div class="medidor" style="width:80px">
                            <span :style="'width:' + props.value + '%;background:' +
                                (props.value >= 70 ? '#047857' :
                                (props.value >= 50 ? '#B45309' : '#C01048'))"></span>
                        </div>
                    </div>
                </q-td>
            ''')
            table.add_slot('body-cell-recomendacion', '''
                <q-td :props="props">
                    <span class="tag" :style="props.value === 'Ofertar'
                        ? 'background:#ECFDF5;color:#047857;border-color:#A7F3D0'
                        : (props.value === 'No ofertar'
                            ? 'background:#FFF1F3;color:#C01048;border-color:#FECDD6'
                            : 'background:#FFFBEB;color:#B45309;border-color:#FDE68A')">
                        <span class="punto" :style="'background:' + (props.value === 'Ofertar'
                            ? '#047857' : (props.value === 'No ofertar' ? '#C01048' : '#B45309'))">
                        </span>{{ props.value }}
                    </span>
                </q-td>
            ''')
            table.add_slot('body-cell-decision', '''
                <q-td :props="props">
                    <span class="tag" :style="props.value === 'Pendiente'
                        ? 'background:#FFFBEB;color:#B45309;border-color:#FDE68A'
                        : (props.value === 'Ofertar'
                            ? 'background:#ECFDF5;color:#047857;border-color:#A7F3D0'
                            : 'background:#F1F5F9;color:#475569;border-color:#DFE5EF')">
                        {{ props.value }}
                    </span>
                </q-td>
            ''')
            table.add_slot('body-cell-acciones', '''
                <q-td :props="props" class="text-right">
                    <q-btn flat dense round icon="picture_as_pdf" color="primary"
                           @click="$parent.$emit('download', props.row.id)">
                        <q-tooltip>Descargar informe (inmutable SHA-256)</q-tooltip>
                    </q-btn>
                    <q-btn flat dense round icon="gavel" color="deep-purple"
                           @click="$parent.$emit('decide', props.row.id)">
                        <q-tooltip>Registrar decisión</q-tooltip>
                    </q-btn>
                </q-td>
            ''')

            # Event handlers for the custom slots
            table.on('download', lambda e: ui.notify(
                f'Descargando informe certificado de Azure Blob Storage para {e.args}...',
                type='info',
            ))

            async def registrar_decision(e):
                row_id = e.args
                fila = next((r for r in mock_tablero if r['id'] == row_id), None)

                with ui.dialog() as dialog, ui.column().classes('tarjeta gap-4 p-6 min-w-[460px]'):
                    cabecera_seccion(f'Registrar decisión · {row_id}',
                                     'Queda en la bitácora junto al informe sellado.',
                                     'gavel', 'violeta')
                    if fila:
                        with ui.row().classes('w-full items-center gap-4 p-4').style(
                            'background:#F4F6FB;border:1px solid #E2E8F2;border-radius:9px'
                        ):
                            with ui.column().classes('gap-0'):
                                ui.html('<span class="rotulo">Puntaje</span>')
                                ui.html(
                                    f'<span style="font-size:1.5rem;font-weight:700">'
                                    f'{fila["puntaje"]}</span>'
                                )
                            with ui.column().classes('gap-1 flex-1'):
                                ui.html('<span class="rotulo">Sugerencia del sistema</span>')
                                etiqueta(
                                    fila['recomendacion'],
                                    'verde' if fila['recomendacion'] == 'Ofertar' else 'rojo',
                                )
                                medidor(
                                    fila['puntaje'],
                                    'verde' if fila['puntaje'] >= 70 else 'rojo',
                                )

                    decision = ui.select(['Ofertar', 'No Ofertar'], value='Ofertar',
                                         label='Decisión comercial').props('outlined dense').classes('w-full')
                    justificacion = ui.textarea(
                        'Justificación',
                        placeholder='Obligatoria si la decisión se aparta de la sugerencia.',
                    ).props('outlined dense rows=3').classes('w-full')

                    with ui.row().classes('w-full justify-end gap-2'):
                        boton('Cancelar', lambda: dialog.submit(None), '', 'claro')
                        boton('Guardar',
                              lambda: dialog.submit({'decision': decision.value,
                                                     'j': justificacion.value}),
                              'check', 'primario')

                result = await dialog
                if result:
                    for row in mock_tablero:
                        if row['id'] == row_id:
                            row['decision'] = result['decision']
                    table.update()
                    ui.notify('Decisión registrada con éxito.', type='positive')

            table.on('decide', registrar_decision)


# --- Layout and Page Registration ---

@ui.page('/')
def index():
    # DA-10 y RF-002: La sesión y autorización se manejan desde la API,
    # pero la UI refleja el rol del usuario conectado.
    cargar_tema()

    with ui.header().props('flat bordered=false').classes(
        'items-center justify-between px-7 h-16'
    ).style('background:#FFFFFF;border-bottom:1px solid #E2E8F2'):
        ui.html(
            '<div style="display:flex;align-items:center;gap:8px;background:#F4F6FB;'
            'border:1px solid #E2E8F2;border-radius:7px;padding:7px 12px;min-width:300px">'
            '<span class="material-icons" style="font-size:17px;color:#2563EB">search</span>'
            '<span style="font-size:0.8rem;color:#64748B">Buscar licitación, entidad u objeto</span>'
            '</div>'
        )
        with ui.row().classes('items-center gap-4'):
            ui.html(
                '<span class="tag" style="background:#ECFDF5;color:#047857;border-color:#A7F3D0">'
                '<span class="punto" style="background:#059669"></span>Orquestador activo</span>'
            )
            with ui.column().classes('gap-0 items-end'):
                ui.html('<span style="font-size:0.8rem;font-weight:500">Juan</span>')
                ui.html('<span class="meta">Gerente / Analista comercial</span>')
            ui.html(
                '<div style="width:33px;height:33px;border-radius:9px;'
                'background:linear-gradient(135deg,#2563EB,#4338CA);color:#FFFFFF;display:flex;'
                'align-items:center;justify-content:center;font-size:0.76rem;font-weight:600">J</div>'
            )
            ui.button(
                on_click=lambda: ui.notify('Cerrando sesión (OIDC)...'),
            ).props('flat dense round icon=logout color=grey-7').tooltip('Salir')

    with ui.left_drawer(value=True, bordered=False).props(':width=244 :breakpoint=0').classes(
        'px-3 py-5 flex flex-col h-full'
    ).style('background:linear-gradient(176deg,#1B2C5A 0%,#111C3A 48%,#0D1530 100%)'):
        with ui.row().classes('items-center gap-2.5 px-2 pb-5'):
            ui.html(
                '<div style="width:30px;height:30px;border-radius:9px;'
                'background:linear-gradient(135deg,#60A5FA,#2563EB);display:flex;'
                'align-items:center;justify-content:center;'
                'box-shadow:0 4px 10px -3px rgba(37,99,235,0.7)">'
                '<span class="material-icons" style="font-size:16px;color:#FFFFFF">diamond</span>'
                '</div>'
            )
            with ui.column().classes('gap-0'):
                ui.html('<span style="color:#FFFFFF;font-weight:600;font-size:0.9rem">Licita</span>')
                ui.html('<span class="riel-rotulo">MVP multi-agente</span>')

        ui.html('<span class="riel-rotulo" style="padding:0 10px">Operación</span>')
        with ui.tabs().classes('hidden') as tabs:
            tab1 = ui.tab('Portafolio')
            tab2 = ui.tab('Vigilancia')
            tab3 = ui.tab('Revisión Requisitos')
            tab4 = ui.tab('Resultados')

        entradas = [
            ('Portafolio', 'inventory_2'),
            ('Vigilancia', 'radar'),
            ('Revisión Requisitos', 'fact_check'),
            ('Resultados', 'dashboard'),
        ]
        activo = {'nombre': 'Portafolio'}

        def seleccionar(nombre: str) -> None:
            activo['nombre'] = nombre
            tabs.set_value(nombre)
            riel.refresh()

        @ui.refreshable
        def riel() -> None:
            for nombre, icono in entradas:
                clase = 'riel-item activo' if activo['nombre'] == nombre else 'riel-item'
                with ui.element('div').classes(clase).on(
                    'click', lambda n=nombre: seleccionar(n)
                ):
                    ui.html(
                        f'<span class="material-icons" style="font-size:18px">{icono}</span>'
                    )
                    ui.html(f'<span>{nombre}</span>')

        with ui.column().classes('w-full gap-0 mt-2'):
            riel()

        ui.element('div').classes('flex-grow')
        with ui.column().classes('w-full gap-2 p-3.5').style(
            'background:linear-gradient(140deg,rgba(96,165,250,0.18),rgba(124,58,237,0.16));'
            'border:1px solid rgba(147,180,253,0.26);border-radius:10px'
        ):
            ui.html(
                '<div style="display:flex;align-items:center;gap:7px">'
                '<span class="material-icons" style="font-size:15px;color:#93B4FD">account_tree</span>'
                '<span class="riel-rotulo" style="color:#A9C5FF">Grafo de agentes</span></div>'
            )
            with ui.row().classes('items-center justify-between w-full'):
                ui.html('<span style="color:#E8EDF8;font-size:0.76rem">1 tarea en curso</span>')
                ui.html(
                    '<span class="tag" style="background:rgba(217,119,6,0.26);color:#FCD34D;'
                    'border-color:rgba(252,211,77,0.32)">1 en compuerta</span>'
                )
            ui.html(
                '<span style="color:#8FA3C7;font-size:0.7rem;line-height:1.45">El StateGraph '
                'retuvo SECOP-2026-001 en el nodo de revisión humana.</span>'
            )

    with ui.tab_panels(tabs, value=tab1).classes('w-full bg-transparent'):
        for tab, vista in ((tab1, show_portafolio), (tab2, show_vigilancia),
                           (tab3, show_analisis), (tab4, show_resultados)):
            with ui.tab_panel(tab).classes('bg-transparent px-0'):
                with ui.column().classes('w-full max-w-[1280px] mx-auto px-8 py-7 gap-5'):
                    vista()


if __name__ in {"__main__", "__mp_main__"}:
    # Puerto por defecto 8080 configurado en docker-compose
    ui.run(title="MVP Licitaciones", port=8080, language="es")
