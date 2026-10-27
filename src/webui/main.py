import json
import logging
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

# Permite ejecutar "python src/webui/main.py" desde la raíz sin fijar PYTHONPATH:
# el script importa con la ruta completa (src.webui.tema).
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

import httpx
from dotenv import load_dotenv
from fastapi.responses import RedirectResponse
from nicegui import app, ui

if os.getenv("CARGAR_DOTENV", "1").strip() != "0":
    load_dotenv(_RAIZ / ".env")

# cliente_api lee API_URL y AUTH_MODE al importarse: va después de load_dotenv.
from src.shared.horas import texto_local
from src.shared.roles import PANTALLA_INICIAL, Permiso
from src.webui import cliente_api as api
from src.webui import oidc
from src.webui.cliente_api import API_URL, detalle_error, llamar_api, puede, usuario_actual
from src.webui.tema import (
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

logger = logging.getLogger("webui")

ESTADO_ESPERANDO_REVISION = "Esperando revisión"
CATEGORIAS_REQUISITO = ['tecnico', 'financiero', 'juridico', 'experiencia', 'personal']
ESTADOS_ACTIVOS = ('Recibida', 'En proceso', 'Evaluando')

# Tono de cada estado de una tarea de análisis.
TONO_ESTADO = {
    'Recibida': 'neutro',
    'En proceso': 'azul',
    'Esperando revisión': 'ambar',
    'Evaluando': 'violeta',
    'Finalizada': 'verde',
    'Suspendida': 'rojo',
    'Fallida': 'rojo',
}

# Decisión comercial humana (RF-039) y su tono en el tablero de resultados.
DECISIONES = ['Continuar', 'Descartar', 'Solicitar información']
TONO_DECISION = {
    'Pendiente': 'ambar',
    'Continuar': 'verde',
    'Descartar': 'neutro',
    'Solicitar información': 'azul',
}
# Decisión que corresponde a cada recomendación del sistema: se propone por defecto.
DECISION_SUGERIDA = {'Ofertar': 'Continuar', 'No ofertar': 'Descartar',
                     'Solicitar revisión': 'Solicitar información'}

CATEGORIAS = ['Desarrollo', 'Infraestructura', 'Experiencia', 'Certificación']

# Color por categoria del portafolio, para que la tabla se lea de un vistazo.
TONO_CATEGORIA = {
    'Desarrollo': 'azul',
    'Infraestructura': 'violeta',
    'Experiencia': 'verde',
    'Certificación': 'ambar',
}


def _ranura_tono(columna: str, tonos: dict[str, str], subtitulo: str | None = None) -> str:
    """Celda de tabla pintada con el tono que corresponde a su valor.
    subtitulo: campo de la fila que se muestra debajo, en letra pequeña, si tiene valor."""
    reglas = ','.join(
        f"'{valor}':'background:{TONOS[t][0]};color:{TONOS[t][1]};border-color:{TONOS[t][2]}'"
        for valor, t in tonos.items()
    )
    debajo = (
        f'''<div v-if="props.row.{subtitulo}" style="font-size:0.7rem;color:#64748B;margin-top:3px">
        {{{{ props.row.{subtitulo} }}}}</div>''' if subtitulo else ''
    )
    return f'''
    <q-td :props="props">
      <span class="tag" :style="{{{reglas}}}[props.value]">{{{{ props.value }}}}</span>{debajo}
    </q-td>
    '''


def _fecha_corta(iso: str | None) -> str:
    """Instante guardado en UTC, mostrado en la hora local (UTC_OFFSET)."""
    if not iso:
        return ''
    return texto_local(iso) or iso


def _pesos(valor: float | None) -> str:
    return f'${valor:,.0f}'.replace(',', '.') if valor else 'Sin dato'


class Contexto:
    """Enlaces entre pantallas de una misma página (navegar, abrir una tarea en revisión)."""

    def __init__(self):
        self.ir_a = lambda nombre: None
        self.abrir_revision = None  # async (tarea_id) -> None


# --- Portafolio ---

def show_portafolio(ctx: Contexto):
    capacidades: list[dict] = []
    versiones: list[dict] = []
    gestiona = puede(Permiso.PORTAFOLIO_GESTIONAR)
    edita = puede(Permiso.PORTAFOLIO_EDITAR)

    with banda(
        'Portafolio de capacidades',
        'Tecnologías, certificaciones y casos de éxito que el sistema usa como evidencia al '
        'evaluar cada licitación. Cada cambio publica una versión nueva; la anterior queda como '
        'histórico y los análisis conservan la versión con que se evaluaron.',
        'Analista comercial',
    ):
        pass

    @ui.refreshable
    def indicadores():
        vectorizados = sum(1 for c in capacidades if c.get('vectorizado'))
        vigente = next((v for v in versiones if v['vigente']), None)
        with ui.row().classes('w-full gap-3'):
            kpi(f"v{vigente['version']}" if vigente else '—', 'Versión vigente',
                f"Publicada por {vigente['creada_por']}" if vigente else 'Sin versiones publicadas',
                'azul', 'history')
            kpi(str(len(capacidades)), 'Capacidades registradas', 'En la versión vigente',
                'violeta', 'inventory_2')
            kpi(str(len({c['categoria'] for c in capacidades})), 'Categorías cubiertas',
                'Según los registros cargados', 'ambar', 'category')
            kpi(f'{vectorizados}/{len(capacidades)}', 'Con búsqueda semántica',
                'El resto se busca por texto', 'verde', 'hub')

    indicadores()

    async def cargar():
        try:
            r_caps = await llamar_api('GET', '/portafolio/', automatica=True)
            r_vers = await llamar_api('GET', '/portafolio/versiones', automatica=True)
        except httpx.HTTPError:
            ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
            return
        if r_caps.status_code != 200 or r_vers.status_code != 200:
            return
        capacidades[:] = r_caps.json()
        versiones[:] = r_vers.json()
        table.rows = capacidades
        table.update()
        tabla_versiones.rows = [{**v, 'creada_en': _fecha_corta(v.get('creada_en'))} for v in versiones]
        tabla_versiones.update()
        indicadores.refresh()

    def avisar_publicacion(response) -> None:
        resumen = response.json()
        pendientes = resumen.get('pendientes_de_indexar', 0)
        ui.notify(f"Versión {resumen['version']} publicada"
                  + (f'; {pendientes} capacidad(es) en indexación.' if pendientes else '.'),
                  type='positive')

    if gestiona:
        with tarjeta('azul'):
            cabecera_seccion('Agregar nueva capacidad',
                             'Escribe evidencia verificable: cifras, años, certificaciones y vigencia.',
                             'add_circle', 'azul')
            with ui.row().classes('w-full items-start gap-3'):
                tec = ui.input('Tecnología').props('outlined dense').classes('flex-1')
                cat = ui.select(CATEGORIAS, label='Categoría').props('outlined dense').classes('flex-1')
                desc = ui.input('Descripción (caso de éxito o detalle)').props('outlined dense').classes('flex-[2]')

                async def add_item():
                    if not (tec.value and cat.value and desc.value):
                        ui.notify('Completa los tres campos antes de guardar.', type='warning')
                        return
                    try:
                        response = await llamar_api('POST', '/portafolio/', json={
                            'tecnologia': tec.value, 'categoria': cat.value, 'descripcion': desc.value,
                        })
                    except httpx.HTTPError:
                        ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
                        return
                    if response.status_code != 201:
                        if response.status_code not in (401, 403):
                            ui.notify(f'No se guardó: {detalle_error(response)}', type='negative')
                        return
                    avisar_publicacion(response)
                    tec.value = ''; cat.value = None; desc.value = ''
                    await cargar()

                boton('Guardar', add_item, 'save', 'primario')

    with tarjeta('violeta'):
        with ui.row().classes('w-full items-end justify-between'):
            cabecera_seccion('Capacidades acreditadas',
                             'Registros de la versión vigente, contrastables contra cada licitación.',
                             'verified', 'violeta')
            boton('Actualizar', cargar, 'refresh', 'claro')
        columns = [
            {'name': 'tecnologia', 'label': 'Tecnología', 'field': 'tecnologia', 'align': 'left', 'sortable': True},
            {'name': 'categoria', 'label': 'Categoría', 'field': 'categoria', 'align': 'left', 'sortable': True},
            {'name': 'descripcion', 'label': 'Descripción', 'field': 'descripcion', 'align': 'left'},
        ]
        if edita or gestiona:
            columns.append({'name': 'acciones', 'label': '', 'field': 'id', 'align': 'right'})
        table = ui.table(columns=columns, rows=capacidades, row_key='id').props(
            'flat dense wrap-cells'
        ).classes('w-full')
        table.add_slot('body-cell-categoria', _ranura_tono('categoria', TONO_CATEGORIA))
        table.add_slot(
            'body-cell-tecnologia',
            '<q-td :props="props"><span style="font-weight:500;color:#0F172A">{{ props.value }}'
            '</span><span v-if="!props.row.vectorizado" style="font-size:0.7rem;color:#94A3B8">'
            ' · búsqueda por texto</span></q-td>',
        )
        botones = ''
        if edita:
            botones += '''<q-btn flat dense round icon="edit" color="primary"
                @click="$parent.$emit('editar', props.row.id)"><q-tooltip>Editar</q-tooltip></q-btn>'''
        if gestiona:
            botones += '''<q-btn flat dense round icon="delete_outline" color="grey-7"
                @click="$parent.$emit('retirar', props.row.id)"><q-tooltip>Retirar</q-tooltip></q-btn>'''
        if botones:
            table.add_slot('body-cell-acciones', f'<q-td :props="props" class="text-right">{botones}</q-td>')

        async def editar(e):
            fila = next((c for c in capacidades if c['id'] == e.args), None)
            if fila is None:
                return
            with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[520px]'):
                cabecera_seccion('Editar capacidad', 'Al guardar se publica una versión nueva del portafolio.',
                                 'edit', 'azul')
                n_tec = ui.input('Tecnología', value=fila['tecnologia']).props('outlined dense').classes('w-full')
                n_cat = ui.select(sorted(set(CATEGORIAS) | {fila['categoria']}), value=fila['categoria'],
                                  label='Categoría').props('outlined dense').classes('w-full')
                n_desc = ui.textarea('Descripción', value=fila['descripcion']).props(
                    'outlined dense rows=4').classes('w-full')
                with ui.row().classes('w-full justify-end gap-2'):
                    boton('Cancelar', lambda: dialogo.submit(None), '', 'claro')
                    boton('Publicar versión', lambda: dialogo.submit({
                        'tecnologia': n_tec.value, 'categoria': n_cat.value, 'descripcion': n_desc.value}),
                        'check', 'primario')
            datos = await dialogo
            if not datos:
                return
            response = await llamar_api('PUT', f"/portafolio/{fila['id']}", json=datos)
            if response.status_code == 200:
                avisar_publicacion(response)
                await cargar()
            elif response.status_code not in (401, 403):
                ui.notify(f'No se guardó: {detalle_error(response)}', type='negative')

        async def retirar(e):
            fila = next((c for c in capacidades if c['id'] == e.args), None)
            if fila is None:
                return
            with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[440px]'):
                cabecera_seccion(f"Retirar «{fila['tecnologia']}»",
                                 'Sale de la versión nueva; sigue disponible en las anteriores.',
                                 'delete_outline', 'rojo')
                with ui.row().classes('w-full justify-end gap-2'):
                    boton('Cancelar', lambda: dialogo.submit(False), '', 'claro')
                    boton('Retirar y publicar', lambda: dialogo.submit(True), 'check', 'primario')
            if not await dialogo:
                return
            response = await llamar_api('DELETE', f"/portafolio/{fila['id']}")
            if response.status_code == 200:
                avisar_publicacion(response)
                await cargar()
            elif response.status_code not in (401, 403):
                ui.notify(f'No se retiró: {detalle_error(response)}', type='negative')

        table.on('editar', editar)
        table.on('retirar', retirar)

    with tarjeta('neutro'):
        cabecera_seccion('Historial de versiones',
                         'Solo una versión está vigente; las anteriores se conservan para la trazabilidad.',
                         'history', 'neutro')
        columnas_v = [
            {'name': 'version', 'label': 'Versión', 'field': 'version', 'align': 'left'},
            {'name': 'descripcion_cambio', 'label': 'Cambio', 'field': 'descripcion_cambio', 'align': 'left'},
            {'name': 'creada_por', 'label': 'Publicada por', 'field': 'creada_por', 'align': 'left'},
            {'name': 'creada_en', 'label': 'Fecha', 'field': 'creada_en', 'align': 'left'},
            {'name': 'capacidades', 'label': 'Capacidades', 'field': 'capacidades', 'align': 'left'},
            {'name': 'ver', 'label': '', 'field': 'version', 'align': 'right'},
        ]
        tabla_versiones = ui.table(columns=columnas_v, rows=versiones, row_key='version').props(
            'flat dense wrap-cells').classes('w-full')
        tabla_versiones.add_slot('body-cell-version', '''
            <q-td :props="props"><span style="font-weight:600">v{{ props.value }}</span>
              <span v-if="props.row.vigente" class="tag" style="margin-left:6px;background:#ECFDF5;
                color:#047857;border-color:#A7F3D0">Vigente</span></q-td>''')
        tabla_versiones.add_slot('body-cell-creada_en', '''
            <q-td :props="props">{{ (props.value || '').slice(0, 16).replace('T', ' ') }}</q-td>''')
        tabla_versiones.add_slot('body-cell-capacidades', '''
            <q-td :props="props">{{ props.value }}
              <span style="font-size:0.7rem;color:#64748B">({{ props.row.vectorizadas }} con vector)</span></q-td>''')
        tabla_versiones.add_slot('body-cell-ver', '''
            <q-td :props="props" class="text-right"><q-btn flat dense round icon="visibility" color="primary"
              @click="$parent.$emit('ver', props.row.version)"><q-tooltip>Ver capacidades</q-tooltip></q-btn></q-td>''')

        async def ver_version(e):
            response = await llamar_api('GET', '/portafolio/', params={'version': e.args})
            if response.status_code != 200:
                return
            with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[640px]'):
                cabecera_seccion(f'Portafolio · versión {e.args}', 'Contenido tal como quedó publicado.',
                                 'inventory_2', 'violeta')
                ui.table(columns=[c for c in columns if c['name'] != 'acciones'], rows=response.json(),
                         row_key='id').props('flat dense wrap-cells').classes('w-full max-h-[60vh]')
                boton('Cerrar', dialogo.close, '', 'claro')
            dialogo.open()

        tabla_versiones.on('ver', ver_version)

    ui.timer(0.1, cargar, once=True)


# --- Reglas del puntaje ---

def show_reglas(ctx: Contexto):
    datos: dict = {'vigente': None, 'propuesta': None, 'historial': []}
    propone = puede(Permiso.REGLAS_PROPONER)
    confirma = puede(Permiso.REGLAS_CONFIRMAR)

    with banda(
        'Reglas del puntaje',
        'Pesos por categoría de requisitos y umbrales de la recomendación. Cada análisis usa la '
        'versión vigente al solicitarse y la conserva hasta el informe. Publicar una versión exige '
        'doble control: la propone el administrador y la confirma la gerencia comercial.',
        'Reglas versionadas',
    ):
        pass

    def resumen_reglas(regla: dict, tono: str) -> None:
        with ui.row().classes('w-full gap-6 items-start'):
            with ui.column().classes('gap-2 flex-[2] min-w-[280px]'):
                for categoria, peso in sorted(regla['pesos'].items(), key=lambda x: -x[1]):
                    with ui.row().classes('w-full items-center gap-3'):
                        ui.label(categoria.capitalize()).classes('text-sm w-28')
                        medidor(round(peso), tono)
                        ui.label(f'{peso:g} %').classes('text-sm font-semibold w-14 text-right')
            with ui.column().classes('gap-1 flex-1 min-w-[200px]'):
                ui.html('<span class="rotulo">Umbrales</span>')
                ui.label(f"Ofertar desde {regla['umbral_ofertar']:g} puntos")
                ui.label(f"Solicitar revisión desde {regla['umbral_revision']:g} puntos")
                ui.label(f"Propuesta por {regla['creado_por']}").classes('meta')
                if regla.get('confirmado_por'):
                    ui.label(f"Confirmada por {regla['confirmado_por']} · "
                             f"{_fecha_corta(regla.get('confirmado_en'))}").classes('meta')
                if regla.get('nota'):
                    ui.label(regla['nota']).classes('meta').style('white-space:pre-wrap')

    @ui.refreshable
    def vista():
        vigente, propuesta = datos['vigente'], datos['propuesta']
        with tarjeta('verde'):
            cabecera_seccion(f"Versión vigente · v{vigente['version']}" if vigente else 'Sin versión vigente',
                             'Rige para los análisis que se soliciten desde su confirmación.',
                             'verified', 'verde')
            if vigente:
                resumen_reglas(vigente, 'verde')

        if propuesta:
            with tarjeta('ambar'):
                cabecera_seccion(f"Propuesta pendiente · v{propuesta['version']}",
                                 'Espera la confirmación de la gerencia comercial.', 'pending_actions', 'ambar')
                resumen_reglas(propuesta, 'ambar')
                if confirma:
                    with ui.row().classes('w-full justify-end gap-2'):
                        boton('Rechazar', lambda: rechazar(propuesta['version']), 'close', 'claro')
                        boton('Confirmar y publicar', lambda: confirmar(propuesta['version']), 'check', 'exito')

        if propone and not propuesta:
            base = vigente or {'pesos': {}, 'umbral_ofertar': 80, 'umbral_revision': 50}
            with tarjeta('azul'):
                cabecera_seccion('Proponer una versión nueva',
                                 'Los pesos deben sumar 100. La gerencia comercial la confirmará.',
                                 'tune', 'azul')
                entradas = {}
                with ui.row().classes('w-full gap-3'):
                    for categoria in ('tecnico', 'experiencia', 'financiero', 'juridico', 'personal'):
                        entradas[categoria] = ui.number(
                            categoria.capitalize(), value=base['pesos'].get(categoria, 0), min=0, max=100,
                            suffix='%', on_change=lambda: suma.refresh(),
                        ).props('outlined dense').classes('w-32')

                @ui.refreshable
                def suma():
                    total = sum(float(e.value or 0) for e in entradas.values())
                    color = '#047857' if abs(total - 100) < 0.01 else '#C01048'
                    ui.html(f'<span style="font-weight:600;color:{color}">Suma: {total:g} %</span>')

                suma()
                with ui.row().classes('w-full gap-3 items-start'):
                    u_ofertar = ui.number('Umbral para ofertar', value=base['umbral_ofertar'], min=0, max=100) \
                        .props('outlined dense').classes('w-48')
                    u_revision = ui.number('Umbral para revisión', value=base['umbral_revision'], min=0, max=100) \
                        .props('outlined dense').classes('w-48')
                    nota = ui.input('Motivo del cambio').props('outlined dense').classes('flex-1')

                async def proponer():
                    cuerpo = {
                        'ponderaciones': {c: float(e.value or 0) for c, e in entradas.items()},
                        'umbral_ofertar': float(u_ofertar.value or 0),
                        'umbral_revision': float(u_revision.value or 0),
                        'nota': nota.value or None,
                    }
                    response = await llamar_api('PUT', '/reglas-puntaje/', json=cuerpo)
                    if response.status_code == 201:
                        ui.notify(f"Versión {response.json()['version']} propuesta. Falta la confirmación "
                                  'de la gerencia comercial.', type='positive')
                        await cargar()
                    elif response.status_code not in (401, 403):
                        ui.notify(f'No se propuso: {detalle_error(response)}', type='negative')

                with ui.row().classes('w-full justify-end'):
                    boton('Proponer versión', proponer, 'send', 'primario')

        with tarjeta('neutro'):
            cabecera_seccion('Historial', 'Todas las versiones, incluidas las rechazadas.', 'history', 'neutro')
            filas = [{**r, 'resumen': ' · '.join(f'{c} {p:g}' for c, p in sorted(r['pesos'].items())),
                      'umbrales': f"{r['umbral_ofertar']:g} / {r['umbral_revision']:g}",
                      'fecha': _fecha_corta(r.get('confirmado_en') or r.get('creado_en'))}
                     for r in datos['historial']]
            tabla = ui.table(columns=[
                {'name': 'version', 'label': 'Versión', 'field': 'version', 'align': 'left'},
                {'name': 'estado', 'label': 'Estado', 'field': 'estado', 'align': 'left'},
                {'name': 'resumen', 'label': 'Pesos', 'field': 'resumen', 'align': 'left'},
                {'name': 'umbrales', 'label': 'Ofertar / revisión', 'field': 'umbrales', 'align': 'left'},
                {'name': 'creado_por', 'label': 'Propuesta por', 'field': 'creado_por', 'align': 'left'},
                {'name': 'confirmado_por', 'label': 'Decidida por', 'field': 'confirmado_por', 'align': 'left'},
                {'name': 'fecha', 'label': 'Fecha', 'field': 'fecha', 'align': 'left'},
            ], rows=filas, row_key='version').props('flat dense wrap-cells').classes('w-full')
            tabla.add_slot('body-cell-estado', _ranura_tono('estado', {
                'Vigente': 'verde', 'Propuesta': 'ambar', 'Histórica': 'neutro', 'Rechazada': 'rojo'}))

    async def cargar():
        try:
            response = await llamar_api('GET', '/reglas-puntaje/', automatica=True)
        except httpx.HTTPError:
            ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
            return
        if response.status_code == 200:
            datos.update(response.json())
            vista.refresh()

    async def confirmar(version: int):
        response = await llamar_api('POST', f'/reglas-puntaje/{version}/confirmar')
        if response.status_code == 200:
            ui.notify(f'Versión {version} publicada: rige para los análisis nuevos.', type='positive')
            await cargar()
        elif response.status_code not in (401, 403):
            ui.notify(f'No se confirmó: {detalle_error(response)}', type='negative')

    async def rechazar(version: int):
        with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[440px]'):
            cabecera_seccion(f'Rechazar la versión {version}', 'El motivo queda en la bitácora.', 'close', 'rojo')
            motivo = ui.textarea('Motivo').props('outlined dense rows=3').classes('w-full')
            with ui.row().classes('w-full justify-end gap-2'):
                boton('Cancelar', lambda: dialogo.submit(None), '', 'claro')
                boton('Rechazar', lambda: dialogo.submit(motivo.value), 'check', 'primario')
        texto = await dialogo
        if not texto:
            return
        response = await llamar_api('POST', f'/reglas-puntaje/{version}/rechazar', json={'motivo': texto})
        if response.status_code == 200:
            ui.notify(f'Versión {version} rechazada.')
            await cargar()
        elif response.status_code not in (401, 403):
            ui.notify(f'No se rechazó: {detalle_error(response)}', type='negative')

    vista()
    ui.timer(0.1, cargar, once=True)


# --- Vigilancia ---

async def solicitar_analisis(ctx: Contexto, ruta: str, cuerpo: dict | None = None) -> httpx.Response | None:
    """
    Solicita un análisis. Si la API responde 409 porque ya existe uno vigente con la misma
    entrada y versiones (RF-036), ofrece ver su resultado o analizar de nuevo.
    Devuelve la respuesta final, o None si el usuario no quiso repetir el análisis.
    """
    def enviar(forzar: bool):
        if cuerpo is None:
            return llamar_api('POST', ruta, params={'forzar_nuevo': 'true'} if forzar else None)
        return llamar_api('POST', ruta, json={**cuerpo, 'forzar_nuevo': forzar})

    response = await enviar(False)
    if response.status_code != 409 or not isinstance(response.json().get('detail'), dict):
        return response
    previo = response.json()['detail']
    with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[480px]'):
        cabecera_seccion('Ya hay un análisis vigente', previo['mensaje'], 'published_with_changes', 'ambar')
        if previo.get('recomendacion'):
            with ui.row().classes('items-center gap-3'):
                etiqueta(previo['recomendacion'], 'azul')
                ui.label(f"Puntaje {round(previo.get('puntaje') or 0)} · tarea {previo['tarea_id'][:8]}") \
                    .classes('meta')
        with ui.row().classes('w-full justify-end gap-2'):
            boton('Cancelar', lambda: dialogo.submit(None), '', 'claro')
            boton('Ver resultado', lambda: dialogo.submit('ver'), 'dashboard', 'claro')
            boton('Analizar de nuevo', lambda: dialogo.submit('nuevo'), 'refresh', 'primario')
    eleccion = await dialogo
    if eleccion == 'ver':
        ctx.ir_a('Resultados')
    if eleccion != 'nuevo':
        return None
    return await enviar(True)



def show_vigilancia(ctx: Contexto):
    alertas: list[dict] = []
    estado: dict = {}
    gestiona = puede(Permiso.VIGILANCIA_GESTIONAR)
    solicita = puede(Permiso.ANALISIS_SOLICITAR)

    with banda(
        'Vigilancia de oportunidades SECOP II',
        'Lectura automática de los procesos publicados en SECOP II: cada proceso se contrasta '
        'con el portafolio y los afines quedan como alerta.',
        'Analista comercial',
    ):
        if gestiona:
            boton('Ejecutar barrido ahora', lambda: barrer(), 'radar', 'banda')

    @ui.refreshable
    def indicadores():
        nuevas = [a for a in alertas if a['estado'] == 'Nueva']
        en_analisis = sum(1 for a in alertas if a['estado'] == 'En análisis')
        ultimo = estado.get('ultimo_barrido') or {}
        # La sincronización persistida incluye los barridos del trabajador programado (HU-04 CA-04).
        sincronizacion = (estado.get('sincronizacion') or {}).get('ultima') or {}
        if estado.get('en_curso'):
            nota_barrido, valor_barrido = 'Consultando SECOP II…', 'En curso'
        elif ultimo.get('estado') == 'completado':
            valor_barrido = _fecha_corta(ultimo.get('fin'))[11:] or '—'
            nota_barrido = (f"{ultimo.get('procesos_revisados', 0)} procesos revisados · "
                            f"{ultimo.get('alertas_nuevas', 0)} alertas nuevas")
        elif ultimo.get('estado') == 'fallido':
            valor_barrido, nota_barrido = 'Falló', ultimo.get('mensaje', '')[:80]
        elif sincronizacion.get('estado') == 'Exitosa':
            valor_barrido = _fecha_corta(sincronizacion.get('fin'))[5:] or '—'
            nota_barrido = (f"{sincronizacion.get('procesos', 0)} procesos · "
                            f"{sincronizacion.get('novedades', 0)} novedades")
        elif sincronizacion.get('estado') == 'Fallida':
            valor_barrido, nota_barrido = 'Falló', (sincronizacion.get('mensaje') or '')[:80]
        else:
            valor_barrido, nota_barrido = '—', 'Aún no se ha sincronizado con SECOP II'
        with ui.row().classes('w-full gap-3'):
            kpi(str(len(nuevas)), 'Alertas sin revisar',
                f"Afinidad mínima {estado.get('umbral', '—')} · últimos {estado.get('dias', '—')} días",
                'ambar', 'notifications_active')
            kpi(str(en_analisis), 'Enviadas a análisis', 'Desde las alertas', 'azul', 'pending_actions')
            kpi(valor_barrido, 'Último barrido', nota_barrido, 'violeta', 'schedule')

    indicadores()
    aviso_vigilancia = ui.column().classes('w-full')

    async def cargar(automatica: bool = True):
        try:
            r_alertas = await llamar_api('GET', '/vigilancia/alertas', automatica=automatica)
            r_estado = await llamar_api('GET', '/vigilancia/estado', automatica=True)
        except httpx.HTTPError:
            ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
            return
        if r_alertas.status_code == 200:
            alertas[:] = r_alertas.json()
            tabla_alertas.rows = [a for a in alertas if a['estado'] != 'Descartada']
            tabla_alertas.update()
        if r_estado.status_code == 200:
            en_curso_antes = estado.get('en_curso')
            estado.clear()
            estado.update(r_estado.json())
            if en_curso_antes and not estado.get('en_curso'):
                ultimo = estado.get('ultimo_barrido') or {}
                if ultimo.get('estado') == 'completado':
                    ui.notify(f"Barrido terminado: {ultimo.get('alertas_nuevas', 0)} alertas nuevas.",
                              type='positive')
                else:
                    ui.notify(f"El barrido falló: {ultimo.get('mensaje', '')}", type='negative')
        indicadores.refresh()
        _aviso_sincronizacion(aviso_vigilancia, estado.get('sincronizacion'))

    async def barrer():
        try:
            response = await llamar_api('POST', '/vigilancia/barrido')
        except httpx.HTTPError:
            ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
            return
        if response.status_code == 202:
            ui.notify('Consultando SECOP II. Puede tardar unos segundos.', type='info')
            estado['en_curso'] = True
            indicadores.refresh()

    with ui.row().classes('w-full gap-4 items-start'):

        with ui.column().classes('flex-[3] gap-4 min-w-[420px]'):
            with tarjeta('ambar'):
                cabecera_seccion('Alertas de oportunidades',
                                 'Procesos abiertos con mayor afinidad al portafolio. Las palabras '
                                 'resaltadas explican la coincidencia.',
                                 'notifications_active', 'ambar')
                columnas = [
                    {'name': 'afinidad', 'label': 'Afinidad', 'field': 'afinidad', 'align': 'left', 'sortable': True},
                    {'name': 'proceso', 'label': 'Proceso', 'field': 'objeto', 'align': 'left'},
                    {'name': 'precio_base', 'label': 'Precio base', 'field': 'precio_base', 'align': 'right', 'sortable': True},
                    {'name': 'estado', 'label': 'Estado', 'field': 'estado', 'align': 'left'},
                    {'name': 'acciones', 'label': '', 'field': 'id_proceso', 'align': 'right'},
                ]
                tabla_alertas = ui.table(columns=columnas, rows=[], row_key='id_proceso',
                                         pagination=8).props('flat dense wrap-cells').classes('w-full')
                tabla_alertas.add_slot('body-cell-afinidad', '''
                    <q-td :props="props">
                        <div style="display:flex;align-items:center;gap:8px">
                            <span style="font-weight:700;min-width:24px">{{ Math.round(props.value) }}</span>
                            <div class="medidor" style="width:56px"><span :style="'width:' + props.value + '%;background:' +
                                (props.value >= 60 ? '#047857' : (props.value >= 40 ? '#B45309' : '#64748B'))"></span></div>
                        </div>
                    </q-td>
                ''')
                tabla_alertas.add_slot('body-cell-proceso', '''
                    <q-td :props="props" style="max-width:520px">
                        <div style="font-weight:600;color:#0F172A;font-size:0.8rem">{{ props.row.entidad }}</div>
                        <div style="font-size:0.78rem;color:#334155;line-height:1.4">{{ props.row.objeto }}</div>
                        <div style="font-size:0.7rem;color:#64748B;margin-top:3px">
                            <a v-if="props.row.url_proceso" :href="props.row.url_proceso" target="_blank"
                               style="color:#2563EB">{{ props.row.id_proceso }}</a>
                            <span v-else>{{ props.row.id_proceso }}</span>
                            · {{ props.row.modalidad }} · {{ (props.row.fecha_publicacion || '').slice(0, 10) }}
                        </div>
                        <div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px">
                            <span v-for="c in props.row.coincidencias.slice(0, 6)" class="tag"
                                  style="background:#EFF4FF;color:#1D4ED8;border-color:#C7D7FE">{{ c }}</span>
                        </div>
                        <div v-if="props.row.revision_modelo" style="font-size:0.72rem;color:#6D28D9;margin-top:4px">
                            {{ props.row.revision_modelo }}</div>
                    </q-td>
                ''')
                tabla_alertas.add_slot('body-cell-precio_base', '''
                    <q-td :props="props" style="white-space:nowrap">
                        {{ props.value ? '$' + Math.round(props.value).toLocaleString('es-CO') : '—' }}
                    </q-td>
                ''')
                tabla_alertas.add_slot('body-cell-estado', _ranura_tono('estado', {
                    'Nueva': 'ambar', 'En análisis': 'azul', 'Descartada': 'neutro'}))
                acciones = ''
                if solicita:
                    acciones += '''
                        <q-btn v-if="props.row.estado === 'Nueva'" flat dense round icon="play_arrow" color="primary"
                               @click="$parent.$emit('analizar', props.row.id_proceso)">
                            <q-tooltip>Solicitar análisis</q-tooltip></q-btn>'''
                if gestiona:
                    acciones += '''
                        <q-btn v-if="props.row.estado === 'Nueva'" flat dense round icon="close" color="grey-7"
                               @click="$parent.$emit('descartar', props.row.id_proceso)">
                            <q-tooltip>Descartar</q-tooltip></q-btn>'''
                tabla_alertas.add_slot('body-cell-acciones',
                                       f'<q-td :props="props" class="text-right">{acciones}</q-td>')

                async def analizar(e):
                    try:
                        response = await solicitar_analisis(ctx, f'/vigilancia/alertas/{e.args}/analizar')
                    except httpx.HTTPError:
                        ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
                        return
                    if response is None:
                        return
                    if response.status_code == 202:
                        ui.notify(f'Análisis solicitado para {e.args}. Síguelo en "Seguimiento".',
                                  type='positive')
                        await cargar(automatica=False)
                    elif response.status_code not in (401, 403):
                        ui.notify(f'No se pudo solicitar: {detalle_error(response)}', type='negative')

                async def descartar(e):
                    response = await llamar_api('POST', f'/vigilancia/alertas/{e.args}/descartar')
                    if response.status_code == 200:
                        ui.notify('Alerta descartada.')
                        await cargar(automatica=False)

                tabla_alertas.on('analizar', analizar)
                tabla_alertas.on('descartar', descartar)

        if solicita:
            with ui.column().classes('flex-[2] gap-4 min-w-[300px]'):
                if gestiona:
                    with tarjeta('violeta'):
                        cabecera_seccion('Radicar un proceso',
                                         'Registra un proceso que el barrido no detectó: el sistema recupera sus '
                                         'documentos publicados y te muestra los faltantes para cargarlos (RF-022).',
                                         'create_new_folder', 'violeta')
                        boton('Radicar y ver expediente', lambda: radicar_proceso(ctx), 'add_link',
                              'primario').classes('w-full')
                with tarjeta('azul'):
                    cabecera_seccion('Solicitud manual',
                                     'Analiza un proceso que la vigilancia no haya detectado.',
                                     'add_link', 'azul')
                    secop_id = ui.input(
                        'ID de proceso SECOP II', placeholder='Ej: CO1.REQ.1234567',
                    ).props('outlined dense').classes('w-full')
                    # Datos Abiertos solo publica metadatos: el texto del pliego mejora la extracción.
                    pliego = ui.textarea(
                        'Texto del pliego (opcional)',
                        placeholder='Pega aquí el pliego de condiciones o sus secciones clave',
                    ).props('outlined dense autogrow').classes('w-full')

                    async def request_analysis():
                        if not secop_id.value:
                            ui.notify('Indica el ID del proceso.', type='warning')
                            return
                        try:
                            response = await solicitar_analisis(
                                ctx, '/analisis/',
                                {"licitacion_url": secop_id.value, "contenido_pliego": pliego.value or None},
                            )
                        except httpx.HTTPError:
                            ui.notify(f"Sin conexión con la API en {API_URL}.", type='negative')
                            return
                        if response is None:
                            return
                        if response.status_code == 202:
                            data = response.json()
                            ui.notify(f"Análisis en curso (tarea {data['tarea_id'][:8]}). "
                                      'Síguelo en "Seguimiento".', type='positive')
                            secop_id.value = ''
                            pliego.value = ''
                        elif response.status_code not in (401, 403):
                            ui.notify(f"No se pudo solicitar: {detalle_error(response)}", type='negative')

                    boton('Iniciar análisis', request_analysis, 'rocket_launch',
                          'primario').classes('w-full')

    ui.timer(0.1, cargar, once=True)
    # Refresco mientras hay un barrido en curso.
    ui.timer(4.0, lambda: cargar() if estado.get('en_curso') else None)


# --- Oportunidades: tablero, radicación, expediente y novedades (RF-011 a RF-022) ---

TONO_DOCUMENTO = {'Disponible': 'verde', 'Faltante': 'ambar', 'Ilegible': 'rojo'}
TONO_NOVEDAD = {'Estado': 'azul', 'Fechas': 'violeta', 'Documentos': 'neutro', 'Requisitos': 'ambar'}
FORMATOS_EXPEDIENTE = '.pdf,.docx,.xlsx,.txt,.md,.csv'


def _sin_conexion() -> None:
    ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')


def _aviso_sincronizacion(contenedor, sincronizacion: dict | None) -> None:
    """HU-04 CA-04: con la fuente caída o sin sincronizar, la advertencia y la fecha de la última exitosa."""
    contenedor.clear()
    if not sincronizacion:
        return
    with contenedor:
        if sincronizacion.get('desactualizada'):
            with ui.row().classes('w-full items-center gap-2 no-wrap').style(
                    f"background:{TONOS['ambar'][0]};border:1px solid {TONOS['ambar'][2]};"
                    'border-radius:10px;padding:10px 14px'):
                ui.icon('warning', size='20px').style(f"color:{TONOS['ambar'][1]}")
                ui.label(sincronizacion.get('aviso') or 'Los datos pueden estar desactualizados.') \
                    .style(f"color:{TONOS['ambar'][1]};font-size:0.82rem")
        else:
            exitosa = sincronizacion.get('ultima_exitosa') or {}
            ui.label(f"Sincronizado con SECOP II el {_fecha_corta(exitosa.get('fin'))} · "
                     f"{exitosa.get('procesos', 0)} procesos revisados").classes('meta')


def _lista(texto: str | None) -> list[str]:
    return [p.strip() for p in (texto or '').split(',') if p.strip()]


async def radicar_proceso(ctx: Contexto, identificador: str | None = None, al_terminar=None) -> None:
    """HU-02: registra un proceso por su enlace, ID o referencia y abre su expediente."""
    with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[520px]'):
        cabecera_seccion('Radicar un proceso de SECOP II',
                         'Pega el enlace del proceso, su ID (CO1.REQ…) o su referencia. El sistema recupera '
                         'sus datos y sus documentos publicados, y te muestra los que no pudo obtener.',
                         'add_link', 'azul')
        entrada = ui.input('Enlace, ID o referencia', value=identificador or '') \
            .props('outlined dense autofocus').classes('w-full')
        error = ui.label('').style('color:#C01048;font-size:0.8rem')
        with ui.row().classes('w-full justify-end gap-2'):
            boton('Cancelar', lambda: dialogo.submit(None), '', 'claro')
            enviar = boton('Radicar', lambda: radicar(), 'download', 'primario')

    async def radicar():
        if len((entrada.value or '').strip()) < 3:
            error.text = 'Indica el enlace, el ID o la referencia del proceso.'
            return
        enviar.props('loading')
        try:
            response = await llamar_api('POST', '/oportunidades/', json={'identificador': entrada.value.strip()})
        except httpx.HTTPError:
            _sin_conexion()
            return
        finally:
            enviar.props(remove='loading')
        if response.status_code == 201:
            dialogo.submit(response.json())
        elif response.status_code not in (401, 403):
            # HU-02 CA-04: se informa la causa y no se crea ninguna tarea.
            error.text = detalle_error(response)

    entrada.on('keydown.enter', radicar)
    resultado = await dialogo
    if not resultado:
        return
    oportunidad = resultado['oportunidad']
    resumen = resultado.get('resumen') or {}
    ui.notify(f"Proceso {oportunidad['id_proceso']} radicado: {resumen.get('nuevos', 0)} documentos publicados, "
              f"{len(resultado['expediente']['faltantes'])} faltantes.", type='positive')
    if al_terminar:
        await al_terminar()
    if puede(Permiso.EXPEDIENTE_VER):
        await abrir_expediente(ctx, oportunidad['id_proceso'], al_terminar)


async def abrir_expediente(ctx: Contexto, id_proceso: str, al_cambiar=None) -> None:
    """
    RF-021: cada documento con su versión, procedencia y fechas; faltantes e ilegibles explícitos.
    RF-022: carga manual de lo que la fuente no entregó. HU-02 CA-02: continuar o cancelar.
    """
    carga = puede(Permiso.EXPEDIENTE_CARGAR)
    solicita = puede(Permiso.ANALISIS_SOLICITAR)
    datos: dict = {}

    with ui.dialog() as dialogo, \
            ui.column().classes('tarjeta gap-3 p-6 w-[1100px] max-w-[95vw]'):
        with ui.row().classes('w-full items-start justify-between'):
            cabecera_seccion('Expediente documental', f'Proceso {id_proceso}', 'folder_open', 'azul')
            ui.button(icon='close', on_click=dialogo.close).props('flat round dense')
        resumen = ui.row().classes('w-full items-center gap-2')
        columnas = [
            {'name': 'nombre', 'label': 'Documento', 'field': 'nombre', 'align': 'left'},
            {'name': 'version', 'label': 'Versión', 'field': 'version', 'align': 'center'},
            {'name': 'procedencia', 'label': 'Procedencia', 'field': 'procedencia', 'align': 'left'},
            {'name': 'fechas', 'label': 'Publicado · obtenido', 'field': 'obtenido_en', 'align': 'left'},
            {'name': 'estado', 'label': 'Estado', 'field': 'estado', 'align': 'left'},
            {'name': 'acciones', 'label': '', 'field': 'id', 'align': 'right'},
        ]
        tabla = ui.table(columns=columnas, rows=[], row_key='id').props('flat dense wrap-cells').classes('w-full')
        tabla.add_slot('body-cell-nombre', '''
            <q-td :props="props" style="max-width:300px">
                <div style="font-weight:600;color:#0F172A;font-size:0.8rem">{{ props.value }}</div>
                <div v-if="props.row.paginas" style="font-size:0.7rem;color:#64748B">{{ props.row.paginas }}</div>
                <div v-if="props.row.huella_sha256" style="font-size:0.65rem;color:#94A3B8;font-family:monospace">
                    SHA-256 {{ props.row.huella_sha256.slice(0, 16) }}…</div>
            </q-td>''')
        tabla.add_slot('body-cell-fechas', '''
            <q-td :props="props" style="font-size:0.75rem;white-space:nowrap">
                {{ (props.row.publicado_en || '—').slice(0, 10) }} · {{ (props.row.obtenido_en || '—').slice(0, 16).replace('T', ' ') }}
            </q-td>''')
        tabla.add_slot('body-cell-estado', '''
            <q-td :props="props" style="max-width:280px">
                <span class="tag" :style="{'Disponible':'background:#ECFDF5;color:#047857;border-color:#A7F3D0',
                    'Faltante':'background:#FFFBEB;color:#B45309;border-color:#FDE68A',
                    'Ilegible':'background:#FFF1F3;color:#C01048;border-color:#FECDD6'}[props.value]">{{ props.value }}</span>
                <div v-if="props.row.motivo" style="font-size:0.7rem;color:#64748B;margin-top:3px;line-height:1.35">
                    {{ props.row.motivo }}</div>
            </q-td>''')
        acciones = '''
            <q-btn v-if="props.row.tiene_archivo" flat dense round icon="download" color="grey-8"
                   @click="$parent.$emit('descargar', props.row)"><q-tooltip>Descargar</q-tooltip></q-btn>
            <q-btn v-if="props.row.url_fuente" flat dense round icon="open_in_new" color="grey-8"
                   :href="props.row.url_fuente" target="_blank"><q-tooltip>Abrir en SECOP II</q-tooltip></q-btn>'''
        if carga:
            acciones += '''
            <q-btn flat dense round :icon="props.row.estado === 'Disponible' ? 'upload_file' : 'file_upload'"
                   :color="props.row.estado === 'Disponible' ? 'grey-7' : 'primary'"
                   @click="$parent.$emit('reemplazar', props.row)">
                <q-tooltip>{{ props.row.estado === 'Disponible' ? 'Cargar una versión nueva' : 'Cargar el archivo' }}</q-tooltip></q-btn>'''
        tabla.add_slot('body-cell-acciones', f'<q-td :props="props" class="text-right">{acciones}</q-td>')
        historico = ui.expansion('Versiones anteriores', icon='history').classes('w-full').props('dense')

        if carga:
            with ui.column().classes('w-full gap-2').style('border:1px dashed #CBD5E1;border-radius:10px;padding:12px'):
                ui.label('Carga manual (RF-022)').style('font-weight:600;font-size:0.85rem')
                with ui.row().classes('w-full items-start gap-3'):
                    reemplaza = ui.select({0: 'Documento nuevo'}, value=0, label='Corresponde a') \
                        .props('outlined dense').classes('min-w-[280px]')
                    nota = ui.input('Procedencia (opcional)', placeholder='Ej: descargado del portal SECOP II') \
                        .props('outlined dense maxlength=200').classes('flex-grow')
                subida = ui.upload(label=f'Arrastra o elige el archivo ({FORMATOS_EXPEDIENTE.replace(",", " ")})',
                                   auto_upload=True, max_file_size=25 * 1024 * 1024,
                                   on_upload=lambda e: subir(e),
                                   on_rejected=lambda: ui.notify('El archivo supera 25 MB.', type='warning')) \
                    .props(f'accept="{FORMATOS_EXPEDIENTE}" flat bordered').classes('w-full')

        aviso = ui.row().classes('w-full')
        with ui.row().classes('w-full justify-between items-center gap-2'):
            with ui.row().classes('gap-2'):
                if carga:
                    boton('Actualizar desde SECOP II', lambda: actualizar(), 'sync', 'claro')
            with ui.row().classes('gap-2'):
                boton('Cerrar', dialogo.close, '', 'claro')
                if solicita:
                    boton_analizar = boton('Solicitar análisis', lambda: analizar(), 'rocket_launch', 'primario')

    def pintar():
        documentos = datos.get('documentos', [])
        tabla.rows = [{**d, 'obtenido_en': _fecha_corta(d.get('obtenido_en'))} for d in documentos]
        tabla.update()
        resumen.clear()
        with resumen:
            etiqueta(f"{datos.get('disponibles', 0)} disponibles", 'verde')
            if datos.get('faltantes'):
                etiqueta(f"{len(datos['faltantes'])} faltantes", 'ambar')
            if datos.get('ilegibles'):
                etiqueta(f"{len(datos['ilegibles'])} ilegibles", 'rojo')
            if datos.get('responsable'):
                ui.label(f"Responsable: {datos['responsable']}").classes('meta')
            ultimo = datos.get('ultimo_analisis')
            if ultimo:
                ui.label(f"Último análisis: {ultimo['estado']} ({_fecha_corta(ultimo.get('creado_en'))})").classes('meta')
        historico.clear()
        with historico:
            if not datos.get('historico'):
                ui.label('Sin versiones anteriores.').classes('meta')
            for d in datos.get('historico', []):
                ui.label(f"{d['nombre']} · versión {d['version']} · {d['procedencia']} · {d['estado']}"
                         f" · {_fecha_corta(d.get('obtenido_en')) or 'no obtenido'}").classes('meta')
        if carga:
            opciones = {0: 'Documento nuevo'}
            for d in sorted(documentos, key=lambda d: d['estado'] == 'Disponible'):
                opciones[d['id']] = f"{d['nombre']} ({d['estado'].lower()})"
            reemplaza.set_options(opciones, value=reemplaza.value if reemplaza.value in opciones else 0)
        aviso.clear()
        with aviso:
            pendientes = datos.get('faltantes', []) + datos.get('ilegibles', [])
            if pendientes:
                # HU-02 CA-02: se listan y el analista decide si continuar o cargarlos primero.
                ui.label(f"El análisis no incluirá {len(pendientes)} documento(s): {', '.join(pendientes[:4])}"
                         f"{'…' if len(pendientes) > 4 else ''}. Cárgalos antes o continúa con lo disponible.") \
                    .style(f"color:{TONOS['ambar'][1]};font-size:0.8rem")
            elif not documentos:
                ui.label('SECOP II no publica documentos de este proceso: el análisis usará solo su ficha. '
                         'Carga el pliego para un análisis completo.').style(f"color:{TONOS['ambar'][1]};font-size:0.8rem")
        if solicita:
            boton_analizar.text = ('Analizar con lo disponible' if datos.get('faltantes') or datos.get('ilegibles')
                                   else 'Solicitar análisis')

    async def cargar():
        try:
            response = await llamar_api('GET', f'/oportunidades/{id_proceso}/expediente')
        except httpx.HTTPError:
            _sin_conexion()
            return False
        if response.status_code != 200:
            if response.status_code not in (401, 403):
                ui.notify(detalle_error(response), type='negative')
            return False
        datos.clear()
        datos.update(response.json())
        pintar()
        return True

    async def subir(e):
        contenido = await e.file.read()
        data = {}
        if reemplaza.value:
            data['reemplaza_id'] = str(reemplaza.value)
        if nota.value:
            data['nota'] = nota.value
        try:
            response = await llamar_api('POST', f'/oportunidades/{id_proceso}/expediente/documentos',
                                        files={'archivo': (e.file.name, contenido, e.file.content_type or
                                                           'application/octet-stream')}, data=data)
        except httpx.HTTPError:
            _sin_conexion()
            return
        subida.reset()
        if response.status_code == 201:
            d = response.json()
            tipo = 'positive' if d['estado'] == 'Disponible' else 'warning'
            ui.notify(f"{d['nombre']}: versión {d['version']}, {d['estado'].lower()}."
                      + (f" {d['motivo']}" if d.get('motivo') else ''), type=tipo)
            reemplaza.value = 0
            nota.value = ''
            await cargar()
            if al_cambiar:
                await al_cambiar()
        elif response.status_code not in (401, 403):
            ui.notify(f'No se cargó: {detalle_error(response)}', type='negative')

    async def reemplazar(e):
        reemplaza.value = e.args['id']
        ui.notify(f"Elige el archivo para «{e.args['nombre']}».", type='info')
        subida.run_method('pickFiles')

    async def descargar(e):
        try:
            r = await llamar_api('GET', f"/oportunidades/{id_proceso}/expediente/documentos/{e.args['id']}/archivo")
        except httpx.HTTPError:
            _sin_conexion()
            return
        if r.status_code == 200:
            ui.download.content(r.content, e.args['nombre'])
        elif r.status_code not in (401, 403):
            ui.notify(detalle_error(r), type='negative')

    async def actualizar():
        try:
            response = await llamar_api('POST', f'/oportunidades/{id_proceso}/expediente/actualizar')
        except httpx.HTTPError:
            _sin_conexion()
            return
        if response.status_code == 200:
            r = response.json()['resumen']
            ui.notify(r.get('mensaje') or f"{r.get('nuevos', 0)} documentos nuevos en SECOP II.", type='info')
            await cargar()
        elif response.status_code not in (401, 403):
            ui.notify(detalle_error(response), type='negative')

    async def analizar():
        try:
            response = await solicitar_analisis(ctx, '/analisis/', {'licitacion_url': id_proceso,
                                                                    'contenido_pliego': None})
        except httpx.HTTPError:
            _sin_conexion()
            return
        if response is None:
            return
        if response.status_code == 202:
            ui.notify(f"Análisis en curso (tarea {response.json()['tarea_id'][:8]}). Síguelo en \"Seguimiento\".",
                      type='positive')
            dialogo.close()
            if al_cambiar:
                await al_cambiar()
        elif response.status_code not in (401, 403):
            ui.notify(f'No se pudo solicitar: {detalle_error(response)}', type='negative')

    tabla.on('descargar', descargar)
    tabla.on('reemplazar', reemplazar)
    if await cargar():
        dialogo.open()


async def abrir_novedades(id_proceso: str, al_cambiar=None) -> None:
    """RF-019: cambios detectados en un proceso seguido; abrirlos los marca como revisados."""
    try:
        response = await llamar_api('GET', f'/oportunidades/{id_proceso}/novedades')
    except httpx.HTTPError:
        _sin_conexion()
        return
    if response.status_code != 200:
        return
    novedades = response.json()
    with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 w-[760px] max-w-[95vw]'):
        cabecera_seccion('Novedades del proceso', f'{id_proceso} · cambios publicados en SECOP II',
                         'notifications', 'violeta')
        if not novedades:
            ui.label('Sin novedades desde que lo sigues.').classes('meta')
        for n in novedades:
            with ui.row().classes('w-full items-start gap-3 no-wrap').style(
                    'border-bottom:1px solid #EEF2F7;padding:6px 0'):
                etiqueta(n['tipo'], TONO_NOVEDAD.get(n['tipo'], 'neutro'))
                with ui.column().classes('gap-0 flex-grow'):
                    cambio = ' → '.join(v for v in (n.get('antes'), n.get('despues')) if v) or '—'
                    ui.label(f"{n['campo']}: {cambio}").style('font-size:0.82rem;color:#0F172A')
                    if n.get('tarea_afectada'):
                        ui.label(f"El análisis {n['tarea_afectada'][:8]} puede haber quedado desactualizado: "
                                 'solicita uno nuevo con el documento cargado; solo los requisitos que el '
                                 'cambio afecta vuelven a revisión.') \
                            .style(f"font-size:0.72rem;color:{TONOS['ambar'][1]}")
                ui.label(_fecha_corta(n['detectada_en'])).classes('meta')
                if n.get('nueva'):
                    etiqueta('Nueva', 'ambar', punto=False)
        with ui.row().classes('w-full justify-end'):
            boton('Cerrar', dialogo.close, '', 'claro')
    dialogo.open()
    if any(n.get('nueva') for n in novedades):
        await llamar_api('POST', f'/oportunidades/{id_proceso}/novedades/revisadas')
        if al_cambiar:
            await al_cambiar()


async def abrir_gestion(id_proceso: str, al_cambiar=None) -> None:
    """RF-040: responsable y notas de una oportunidad."""
    edita = puede(Permiso.ORGANIZACION_EDITAR)
    borra = puede(Permiso.ORGANIZACION_BORRAR)
    yo = usuario_actual().get('email')
    try:
        r = await llamar_api('GET', f'/oportunidades/{id_proceso}')
        opciones = await llamar_api('GET', f'/oportunidades/{id_proceso}/responsable/opciones') if edita else None
    except httpx.HTTPError:
        _sin_conexion()
        return
    if r.status_code != 200:
        return
    oportunidad = r.json()

    with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 w-[680px] max-w-[95vw]'):
        with ui.row().classes('w-full items-start justify-between'):
            cabecera_seccion('Gestión de la oportunidad', f"{id_proceso} · {oportunidad.get('entidad') or ''}",
                             'sticky_note_2', 'azul')
            ui.button(icon='close', on_click=dialogo.close).props('flat round dense')
        ui.label(oportunidad.get('objeto') or oportunidad.get('nombre') or '').style('font-size:0.8rem;color:#334155')

        ui.label('Responsable').style('font-weight:600;font-size:0.85rem')
        with ui.row().classes('w-full items-end gap-3'):
            analistas = opciones.json() if opciones is not None and opciones.status_code == 200 else []
            if edita and analistas:
                valores = {'': 'Sin asignar', **{a['email']: f"{a['nombre']} ({a['email']})" for a in analistas}}
                actual = oportunidad.get('responsable') or ''
                if actual and actual not in valores:
                    valores[actual] = actual
                responsable = ui.select(valores, value=actual, label='Analista a cargo') \
                    .props('outlined dense').classes('flex-grow')
            elif edita:
                responsable = ui.input('Correo del analista a cargo', value=oportunidad.get('responsable') or '') \
                    .props('outlined dense clearable').classes('flex-grow')
            else:
                responsable = None
                ui.label(oportunidad.get('responsable') or 'Sin asignar').classes('meta')
            if edita:
                boton('Asignar', lambda: asignar(), 'person_add', 'primario')
        ui.label('El responsable gestiona el expediente documental de la oportunidad.').classes('meta')

        ui.label('Notas').style('font-weight:600;font-size:0.85rem;margin-top:6px')
        lista = ui.column().classes('w-full gap-0').style('max-height:40vh;overflow-y:auto')
        if edita:
            texto = ui.textarea(placeholder='Escribe una nota para el equipo').props('outlined dense autogrow maxlength=2000') \
                .classes('w-full')
            with ui.row().classes('w-full justify-end'):
                boton('Agregar nota', lambda: agregar(), 'add_comment', 'claro')

    async def cargar_notas():
        rn = await llamar_api('GET', f'/oportunidades/{id_proceso}/notas')
        if rn.status_code != 200:
            return
        lista.clear()
        with lista:
            if not rn.json():
                ui.label('Sin notas todavía.').classes('meta')
            for n in rn.json():
                with ui.row().classes('w-full items-start gap-2 no-wrap').style('border-bottom:1px solid #EEF2F7;padding:8px 0'):
                    with ui.column().classes('gap-0 flex-grow'):
                        ui.label(n['texto']).style('font-size:0.8rem;color:#0F172A;white-space:pre-line')
                        ui.label(f"{n['autor']} · {_fecha_corta(n['creada_en'])}").classes('meta')
                    if borra and n['autor'] == yo:
                        ui.button(icon='delete', on_click=lambda n=n: borrar(n)) \
                            .props('flat round dense color=grey-7').tooltip('Borrar mi nota')

    async def agregar():
        if not (texto.value or '').strip():
            return
        rn = await llamar_api('POST', f'/oportunidades/{id_proceso}/notas', json={'texto': texto.value})
        if rn.status_code == 201:
            texto.value = ''
            await cargar_notas()
            if al_cambiar:
                await al_cambiar()
        elif rn.status_code not in (401, 403):
            ui.notify(detalle_error(rn), type='negative')

    async def borrar(n: dict):
        if (await llamar_api('DELETE', f"/oportunidades/{id_proceso}/notas/{n['id']}")).status_code == 204:
            await cargar_notas()
            if al_cambiar:
                await al_cambiar()

    async def asignar():
        ra = await llamar_api('PUT', f'/oportunidades/{id_proceso}/responsable',
                              json={'responsable': responsable.value or None})
        if ra.status_code == 200:
            nuevo = ra.json().get('responsable')
            ui.notify(f'Responsable: {nuevo}.' if nuevo else 'La oportunidad quedó sin responsable.', type='positive')
            if al_cambiar:
                await al_cambiar()
        elif ra.status_code not in (401, 403):
            ui.notify(detalle_error(ra), type='negative')

    await cargar_notas()
    dialogo.open()


def show_oportunidades(ctx: Contexto):
    """Figura 26: lista filtrable de procesos con su estado, su novedad y la acción disponible."""
    gestiona = puede(Permiso.VIGILANCIA_GESTIONAR)
    solicita = puede(Permiso.ANALISIS_SOLICITAR)
    ve_expediente = puede(Permiso.EXPEDIENTE_VER)
    # RF-040 y RF-041 (Tabla 61, carpetas y exportación).
    organiza = puede(Permiso.ORGANIZACION_VER)
    organiza_edita = puede(Permiso.ORGANIZACION_EDITAR)
    organiza_borra = puede(Permiso.ORGANIZACION_BORRAR)
    estado = {'filas': [], 'total': 0, 'carpetas': []}

    with banda(
        'Tablero de oportunidades',
        'Procesos sincronizados desde SECOP II. Busca por palabras clave, filtra, sigue los que te interesan '
        'para recibir sus novedades y revisa el expediente antes de enviarlos a análisis.',
        'Analista comercial',
    ):
        if gestiona:
            boton('Radicar proceso', lambda: radicar_proceso(ctx, al_terminar=lambda: cargar(reiniciar=True)),
                  'add_link', 'banda')

    aviso = ui.column().classes('w-full')

    with tarjeta('azul'):
        with ui.row().classes('w-full items-end gap-3'):
            q = ui.input('Palabras clave', placeholder='Objeto o nombre del proceso').props('outlined dense clearable') \
                .classes('flex-grow min-w-[240px]')
            entidad = ui.input('Entidad').props('outlined dense clearable').classes('w-56')
            departamento = ui.select({'': 'Todos'}, value='', label='Departamento').props('outlined dense') \
                .classes('w-48')
            ciudad = ui.input('Ciudad').props('outlined dense clearable').classes('w-40')
        with ui.row().classes('w-full items-end gap-3'):
            modalidad = ui.select({'': 'Todas'}, value='', label='Modalidad').props('outlined dense').classes('w-60')
            estado_proceso = ui.select({'': 'Todos'}, value='', label='Estado o fase').props('outlined dense') \
                .classes('w-52')
            cuantia_min = ui.number('Cuantía mínima', min=0, format='%.0f').props('outlined dense clearable') \
                .classes('w-40')
            cuantia_max = ui.number('Cuantía máxima', min=0, format='%.0f').props('outlined dense clearable') \
                .classes('w-40')
            carpeta = ui.select({'': 'Todas'}, value='', label='Mi carpeta').props('outlined dense').classes('w-48')
            carpeta.set_visibility(organiza)
        with ui.row().classes('w-full items-end gap-3'):
            publicada_desde = ui.input('Publicada desde').props('outlined dense type=date stack-label').classes('w-40')
            publicada_hasta = ui.input('Publicada hasta').props('outlined dense type=date stack-label').classes('w-40')
            cierre_desde = ui.input('Cierre desde').props('outlined dense type=date stack-label').classes('w-40')
            cierre_hasta = ui.input('Cierre hasta').props('outlined dense type=date stack-label').classes('w-40')
            seguidas = ui.switch('Solo las que sigo')
            con_novedades = ui.switch('Con novedades sin revisar')
            ui.element('div').classes('flex-grow')
            boton('Limpiar', lambda: limpiar(), 'filter_alt_off', 'claro')
            boton('Buscar', lambda: cargar(reiniciar=True), 'search', 'primario')
        q.on('keydown.enter', lambda: cargar(reiniciar=True))

    with tarjeta('violeta'):
        resumen = ui.row().classes('w-full items-center gap-3')
        if organiza:
            with ui.row().classes('w-full items-center gap-2'):
                seleccion_info = ui.label('Sin selección: se exportan todas las filtradas.').classes('meta')
                ui.element('div').classes('flex-grow')
                if organiza_edita:
                    boton('Agregar a carpeta', lambda: agregar_a_carpeta(), 'create_new_folder', 'claro')
                    boton('Quitar de la carpeta', lambda: quitar_de_carpeta(), 'folder_off', 'claro')
                    boton('Mis carpetas', lambda: administrar_carpetas(), 'folder_special', 'claro')
                boton('Exportar a CSV', lambda: exportar(), 'download', 'primario')
        columnas = [
            {'name': 'proceso', 'label': 'Proceso', 'field': 'objeto', 'align': 'left'},
            {'name': 'precio_base', 'label': 'Cuantía', 'field': 'precio_base', 'align': 'right', 'sortable': True},
            {'name': 'fecha_cierre', 'label': 'Cierre', 'field': 'fecha_cierre', 'align': 'left', 'sortable': True},
            {'name': 'estado', 'label': 'Estado', 'field': 'estado', 'align': 'left'},
            {'name': 'novedad', 'label': 'Novedad', 'field': 'novedades_sin_revisar', 'align': 'left'},
            {'name': 'analisis', 'label': 'Análisis', 'field': 'ultimo_analisis', 'align': 'left'},
            {'name': 'acciones', 'label': '', 'field': 'id_proceso', 'align': 'right'},
        ]
        tabla = ui.table(columns=columnas, rows=[], row_key='id_proceso', pagination=15,
                         selection='multiple' if organiza else None,
                         on_select=lambda: actualizar_seleccion()) \
            .props('flat dense wrap-cells').classes('w-full')
        tabla.add_slot('body-cell-proceso', '''
            <q-td :props="props" style="max-width:480px">
                <div style="font-weight:600;color:#0F172A;font-size:0.8rem">{{ props.row.entidad }}</div>
                <div style="font-size:0.78rem;color:#334155;line-height:1.4">{{ props.row.objeto || props.row.nombre }}</div>
                <div style="font-size:0.7rem;color:#64748B;margin-top:3px">
                    <a v-if="props.row.url_proceso" :href="props.row.url_proceso" target="_blank"
                       style="color:#2563EB">{{ props.row.id_proceso }}</a>
                    <span v-else>{{ props.row.id_proceso }}</span>
                    · {{ props.row.modalidad || 'Sin modalidad' }}
                    · {{ [props.row.ciudad, props.row.departamento].filter(Boolean).join(', ') || 'Sin ubicación' }}
                    · publicado {{ (props.row.fecha_publicacion || '').slice(0, 10) }}
                    <span v-if="props.row.origen_registro === 'Radicación manual'"> · radicado</span>
                </div>
                <div v-if="props.row.responsable || props.row.notas || (props.row.carpetas || []).length"
                     style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;align-items:center">
                    <span v-if="props.row.responsable" style="font-size:0.7rem;color:#047857">
                        Responsable: {{ props.row.responsable }}</span>
                    <span v-if="props.row.notas" style="font-size:0.7rem;color:#64748B">· {{ props.row.notas }} notas</span>
                    <span v-for="c in (props.row.carpetas || [])" class="tag"
                          style="background:#F5F3FF;color:#6D28D9;border-color:#DDD6FE">{{ c.nombre }}</span>
                </div>
            </q-td>''')
        tabla.add_slot('body-cell-precio_base', '''
            <q-td :props="props" style="white-space:nowrap">
                {{ props.value ? '$' + Math.round(props.value).toLocaleString('es-CO') : '—' }}
            </q-td>''')
        tabla.add_slot('body-cell-fecha_cierre', '''
            <q-td :props="props" style="white-space:nowrap;font-size:0.78rem">{{ (props.value || '—').slice(0, 10) }}</q-td>''')
        tabla.add_slot('body-cell-estado', '''
            <q-td :props="props" style="font-size:0.75rem">
                <div>{{ props.row.estado || '—' }}</div>
                <div style="color:#64748B">{{ props.row.fase }}</div>
            </q-td>''')
        tabla.add_slot('body-cell-novedad', '''
            <q-td :props="props" style="max-width:200px">
                <span v-if="props.value" class="tag" style="background:#FFFBEB;color:#B45309;border-color:#FDE68A;cursor:pointer"
                      @click="$parent.$emit('novedades', props.row.id_proceso)">{{ props.value }} sin revisar</span>
                <div v-if="props.row.ultima_novedad" style="font-size:0.7rem;color:#64748B;margin-top:3px">
                    {{ props.row.ultima_novedad.campo }}</div>
                <span v-if="!props.value && !props.row.ultima_novedad" style="color:#94A3B8">—</span>
            </q-td>''')
        tabla.add_slot('body-cell-analisis', '''
            <q-td :props="props" style="font-size:0.75rem">
                <div v-if="props.value">{{ props.value.estado }}</div>
                <div v-if="props.value && props.value.recomendacion" style="color:#64748B">{{ props.value.recomendacion }}</div>
                <span v-if="!props.value" style="color:#94A3B8">Sin análisis</span>
            </q-td>''')
        acciones = '''
            <q-btn flat dense round icon="notifications" color="grey-7" @click="$parent.$emit('novedades', props.row.id_proceso)">
                <q-tooltip>Novedades</q-tooltip></q-btn>'''
        if gestiona:
            acciones = '''
            <q-btn flat dense round :icon="props.row.seguida ? 'star' : 'star_border'"
                   :color="props.row.seguida ? 'amber-8' : 'grey-7'" @click="$parent.$emit('seguir', props.row)">
                <q-tooltip>{{ props.row.seguida ? 'Dejar de seguir' : 'Seguir sus novedades' }}</q-tooltip></q-btn>''' + acciones
        if organiza:
            acciones += '''
            <q-btn flat dense round icon="sticky_note_2" color="grey-7" @click="$parent.$emit('gestion', props.row.id_proceso)">
                <q-tooltip>Notas y responsable</q-tooltip></q-btn>'''
        if ve_expediente:
            acciones += '''
            <q-btn flat dense round icon="folder_open" color="primary" @click="$parent.$emit('expediente', props.row.id_proceso)">
                <q-tooltip>Expediente documental</q-tooltip></q-btn>'''
        elif solicita:
            acciones += '''
            <q-btn flat dense round icon="play_arrow" color="primary" @click="$parent.$emit('analizar', props.row.id_proceso)">
                <q-tooltip>Solicitar análisis</q-tooltip></q-btn>'''
        tabla.add_slot('body-cell-acciones', f'<q-td :props="props" class="text-right" style="white-space:nowrap">{acciones}</q-td>')
        pie = ui.row().classes('w-full items-center justify-between')

    def parametros() -> dict:
        valores = {'q': q.value, 'entidad': entidad.value, 'departamento': departamento.value, 'ciudad': ciudad.value,
                   'modalidad': modalidad.value, 'estado': estado_proceso.value, 'cuantia_min': cuantia_min.value,
                   'cuantia_max': cuantia_max.value, 'publicada_desde': publicada_desde.value,
                   'publicada_hasta': publicada_hasta.value, 'cierre_desde': cierre_desde.value,
                   'cierre_hasta': cierre_hasta.value}
        params = {k: v for k, v in valores.items() if v not in (None, '')}
        if seguidas.value:
            params['seguidas'] = 'true'
        if con_novedades.value:
            params['con_novedades'] = 'true'
        if organiza and carpeta.value:
            params['carpeta_id'] = carpeta.value
        return params

    def seleccionados() -> list[str]:
        return [f['id_proceso'] for f in tabla.selected]

    def actualizar_seleccion() -> None:
        if organiza:
            n = len(tabla.selected)
            seleccion_info.text = (f'{n} seleccionadas: se exportan solo esas.' if n
                                   else 'Sin selección: se exportan todas las filtradas.')

    async def cargar_carpetas():
        if not organiza:
            return
        r = await llamar_api('GET', '/carpetas/', automatica=True)
        if r.status_code == 200:
            estado['carpetas'] = r.json()
            valor = carpeta.value if any(c['id'] == carpeta.value for c in estado['carpetas']) else ''
            carpeta.set_options({'': 'Todas', **{c['id']: f"{c['nombre']} ({c['oportunidades']})"
                                                 for c in estado['carpetas']}}, value=valor)

    async def exportar():
        """RF-041: las seleccionadas o todas las que cumplen los filtros; el CSV lo arma la API."""
        params = parametros()
        if seleccionados():
            params['ids'] = seleccionados()
        try:
            r = await llamar_api('GET', '/resultados/oportunidades.csv', params=params)
        except httpx.HTTPError:
            _sin_conexion()
            return
        if r.status_code != 200:
            if r.status_code not in (401, 403):
                ui.notify(detalle_error(r), type='negative')
            return
        nombre = r.headers.get('content-disposition', '').split('filename=')[-1].strip('"') or 'oportunidades.csv'
        ui.download.content(r.content, nombre, 'text/csv')
        exportadas, totales = r.headers.get('x-registros-exportados'), r.headers.get('x-registros-totales')
        aviso_tope = f' (de {totales}; el máximo por archivo es 5000)' if exportadas != totales else ''
        ui.notify(f'{exportadas} oportunidades exportadas{aviso_tope}.', type='positive')

    async def elegir_carpeta(titulo: str) -> int | None:
        await cargar_carpetas()
        with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[420px]'):
            cabecera_seccion(titulo, f'{len(seleccionados())} oportunidades seleccionadas.', 'folder', 'violeta')
            opciones = {c['id']: c['nombre'] for c in estado['carpetas']}
            eleccion = ui.select(opciones, label='Carpeta', value=carpeta.value or None) \
                .props('outlined dense').classes('w-full')
            nueva = ui.input('O crea una carpeta nueva').props('outlined dense maxlength=60').classes('w-full')
            with ui.row().classes('w-full justify-end gap-2'):
                boton('Cancelar', lambda: dialogo.submit(None), '', 'claro')
                boton('Aceptar', lambda: dialogo.submit('ok'), 'check', 'primario')
        if await dialogo != 'ok':
            return None
        if (nueva.value or '').strip():
            r = await llamar_api('POST', '/carpetas/', json={'nombre': nueva.value})
            if r.status_code != 201:
                if r.status_code not in (401, 403):
                    ui.notify(detalle_error(r), type='negative')
                return None
            return r.json()['id']
        return eleccion.value

    async def agregar_a_carpeta():
        if not seleccionados():
            ui.notify('Selecciona primero las oportunidades.', type='warning')
            return
        carpeta_id = await elegir_carpeta('Agregar a una carpeta')
        if carpeta_id is None:
            return
        r = await llamar_api('POST', f'/carpetas/{carpeta_id}/oportunidades', json={'ids': seleccionados()})
        if r.status_code == 200:
            ui.notify(f"{r.json()['agregadas']} oportunidades agregadas.", type='positive')
            tabla.selected = []
            await cargar_carpetas()
            await recargar()

    async def quitar_de_carpeta():
        if not carpeta.value:
            ui.notify('Filtra primero por una de tus carpetas.', type='warning')
            return
        if not seleccionados():
            ui.notify('Selecciona las oportunidades que quieres quitar de la carpeta.', type='warning')
            return
        r = await llamar_api('POST', f'/carpetas/{carpeta.value}/oportunidades/quitar', json={'ids': seleccionados()})
        if r.status_code == 200:
            ui.notify(f"{r.json()['quitadas']} oportunidades quitadas de la carpeta.", type='info')
            tabla.selected = []
            await cargar_carpetas()
            await recargar()

    async def administrar_carpetas():
        await cargar_carpetas()
        with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 w-[520px] max-w-[95vw]'):
            cabecera_seccion('Mis carpetas', 'Solo tú ves tus carpetas. Borrar una carpeta no borra sus oportunidades.',
                             'folder_special', 'violeta')
            lista = ui.column().classes('w-full gap-1')
            with ui.row().classes('w-full items-end gap-2'):
                nombre = ui.input('Nueva carpeta').props('outlined dense maxlength=60').classes('flex-grow')
                boton('Crear', lambda: crear(), 'add', 'primario')
            with ui.row().classes('w-full justify-end'):
                boton('Cerrar', dialogo.close, '', 'claro')

        def pintar():
            lista.clear()
            with lista:
                if not estado['carpetas']:
                    ui.label('Aún no tienes carpetas.').classes('meta')
                for c in estado['carpetas']:
                    with ui.row().classes('w-full items-center gap-2 no-wrap'):
                        campo = ui.input(value=c['nombre']).props('outlined dense maxlength=60').classes('flex-grow')
                        ui.label(f"{c['oportunidades']} oportunidades").classes('meta')
                        ui.button(icon='save', on_click=lambda c=c, campo=campo: renombrar(c, campo.value)) \
                            .props('flat round dense color=grey-7').tooltip('Renombrar')
                        if organiza_borra:
                            ui.button(icon='delete', on_click=lambda c=c: borrar(c)) \
                                .props('flat round dense color=grey-7').tooltip('Borrar la carpeta')

        async def refrescar():
            await cargar_carpetas()
            pintar()
            await recargar()

        async def crear():
            r = await llamar_api('POST', '/carpetas/', json={'nombre': nombre.value or ''})
            if r.status_code == 201:
                nombre.value = ''
                await refrescar()
            elif r.status_code not in (401, 403):
                ui.notify(detalle_error(r), type='negative')

        async def renombrar(c: dict, valor: str):
            r = await llamar_api('PUT', f"/carpetas/{c['id']}", json={'nombre': valor or ''})
            if r.status_code == 200:
                ui.notify('Carpeta renombrada.')
                await refrescar()
            elif r.status_code not in (401, 403):
                ui.notify(detalle_error(r), type='negative')

        async def borrar(c: dict):
            if (await llamar_api('DELETE', f"/carpetas/{c['id']}")).status_code == 204:
                if carpeta.value == c['id']:
                    carpeta.value = ''
                await refrescar()

        pintar()
        dialogo.open()

    async def cargar(reiniciar: bool = False, automatica: bool = False):
        if reiniciar:
            estado['filas'] = []
        params = {**parametros(), 'limite': 100, 'desplazamiento': len(estado['filas'])}
        try:
            response = await llamar_api('GET', '/oportunidades/', params=params, automatica=automatica)
        except httpx.HTTPError:
            _sin_conexion()
            return
        if response.status_code != 200:
            if response.status_code not in (401, 403):
                ui.notify(detalle_error(response), type='warning')
            return
        datos = response.json()
        estado['total'] = datos['total']
        estado['filas'] += datos['oportunidades']
        tabla.rows = estado['filas']
        tabla.update()
        _aviso_sincronizacion(aviso, datos.get('sincronizacion'))
        resumen.clear()
        with resumen:
            cabecera_seccion('Oportunidades', f"{estado['total']} procesos coinciden con los filtros.",
                             'travel_explore', 'violeta')
        pie.clear()
        with pie:
            ui.label(f"{len(estado['filas'])} de {estado['total']}").classes('meta')
            if len(estado['filas']) < estado['total']:
                boton('Cargar más', lambda: cargar(), 'expand_more', 'claro')

    async def cargar_filtros():
        try:
            response = await llamar_api('GET', '/oportunidades/filtros', automatica=True)
        except httpx.HTTPError:
            return
        if response.status_code == 200:
            f = response.json()
            departamento.set_options({'': 'Todos', **{d: d for d in f['departamentos']}}, value='')
            modalidad.set_options({'': 'Todas', **{m: m for m in f['modalidades']}}, value='')
            estado_proceso.set_options({'': 'Todos', **{e: e for e in f['estados']}}, value='')

    async def limpiar():
        for campo in (q, entidad, ciudad, publicada_desde, publicada_hasta, cierre_desde, cierre_hasta):
            campo.value = ''
        for campo in (departamento, modalidad, estado_proceso):
            campo.value = ''
        cuantia_min.value = cuantia_max.value = None
        seguidas.value = con_novedades.value = False
        carpeta.value = ''
        await cargar(reiniciar=True)

    async def recargar():
        await cargar(reiniciar=True)

    async def seguir(e):
        fila = e.args
        metodo = 'DELETE' if fila['seguida'] else 'PUT'
        try:
            response = await llamar_api(metodo, f"/oportunidades/{fila['id_proceso']}/seguimiento")
        except httpx.HTTPError:
            _sin_conexion()
            return
        if response.status_code == 200:
            ui.notify('Ahora sigues este proceso: verás sus novedades.' if metodo == 'PUT'
                      else 'Dejaste de seguir este proceso.', type='positive' if metodo == 'PUT' else 'info')
            await recargar()

    async def analizar(e):
        try:
            response = await solicitar_analisis(ctx, '/analisis/', {'licitacion_url': e.args, 'contenido_pliego': None})
        except httpx.HTTPError:
            _sin_conexion()
            return
        if response is not None and response.status_code == 202:
            ui.notify('Análisis solicitado. Síguelo en "Seguimiento".', type='positive')
            await recargar()
        elif response is not None and response.status_code not in (401, 403):
            ui.notify(f'No se pudo solicitar: {detalle_error(response)}', type='negative')

    tabla.on('seguir', seguir)
    tabla.on('analizar', analizar)
    tabla.on('novedades', lambda e: abrir_novedades(e.args, recargar))
    tabla.on('expediente', lambda e: abrir_expediente(ctx, e.args, recargar))
    tabla.on('gestion', lambda e: abrir_gestion(e.args, recargar))
    carpeta.on_value_change(lambda: cargar(reiniciar=True))

    async def inicio():
        await cargar_filtros()
        await cargar_carpetas()
        await cargar(reiniciar=True, automatica=True)

    ui.timer(0.1, inicio, once=True)


# --- Notificaciones (RF-016, RF-017, RF-020) ---

TONO_AVISO = {'Oportunidad': 'verde', 'Novedad': 'violeta', 'Revisión pendiente': 'ambar',
              'Análisis suspendido': 'rojo', 'Oportunidad asignada': 'azul'}


async def abrir_bandeja(al_cambiar=None) -> None:
    """Avisos del usuario; quedan aquí aunque el correo falle (Tabla 16)."""
    try:
        response = await llamar_api('GET', '/notificaciones/', params={'limite': 50})
    except httpx.HTTPError:
        _sin_conexion()
        return
    if response.status_code != 200:
        return
    datos = response.json()

    async def leida(n: dict, fila) -> None:
        if (await llamar_api('POST', f"/notificaciones/{n['id']}/leida")).status_code == 204:
            fila.style('background:transparent')
            if al_cambiar:
                await al_cambiar()

    async def todas() -> None:
        if (await llamar_api('POST', '/notificaciones/leidas')).status_code == 200:
            ui.notify('Notificaciones marcadas como leídas.')
            dialogo.close()
            if al_cambiar:
                await al_cambiar()

    with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-2 p-6 w-[720px] max-w-[95vw]'):
        with ui.row().classes('w-full items-start justify-between'):
            cabecera_seccion('Notificaciones', f"{datos['no_leidas']} sin leer · oportunidades de tus perfiles, "
                             'novedades de los procesos que sigues y análisis que te esperan', 'notifications', 'ambar')
            ui.button(icon='close', on_click=dialogo.close).props('flat round dense')
        if not datos['notificaciones']:
            ui.label('No tienes notificaciones.').classes('meta')
        with ui.column().classes('w-full gap-0').style('max-height:60vh;overflow-y:auto'):
            for n in datos['notificaciones']:
                fondo = 'transparent' if n['leida_en'] else '#F8FAFF'
                with ui.row().classes('w-full items-start gap-3 no-wrap').style(
                        f'border-bottom:1px solid #EEF2F7;padding:10px 6px;background:{fondo}') as fila:
                    etiqueta(n['tipo'], TONO_AVISO.get(n['tipo'], 'neutro'))
                    with ui.column().classes('gap-0.5 flex-grow'):
                        ui.label(n['titulo']).style('font-weight:600;font-size:0.82rem;color:#0F172A')
                        ui.label(n['cuerpo']).style('font-size:0.76rem;color:#334155;white-space:pre-line')
                        correo = ('Enviada por correo' if n['enviada_en'] else
                                  f"Correo pendiente ({n['ultimo_error'][:60]})" if n.get('ultimo_error') else '')
                        ui.label(' · '.join(p for p in (_fecha_corta(n['creada_en']), correo) if p)).classes('meta')
                    if n.get('enlace'):
                        ui.button(icon='open_in_new').props(
                            f'flat round dense color=grey-7 href="{n["enlace"]}" target=_blank').tooltip('Ver en SECOP II')
                    if not n['leida_en']:
                        ui.button(icon='done', on_click=lambda n=n, f=fila: leida(n, f)) \
                            .props('flat round dense color=primary').tooltip('Marcar como leída')
        with ui.row().classes('w-full justify-end gap-2'):
            if datos['no_leidas']:
                boton('Marcar todas como leídas', todas, 'done_all', 'claro')
            boton('Cerrar', dialogo.close, '', 'claro')
    dialogo.open()


def tarjeta_preferencias() -> None:
    """RF-016: canal y frecuencia de los avisos de perfiles y procesos seguidos."""
    configura = puede(Permiso.NOTIFICACIONES_CONFIGURAR)
    with tarjeta('violeta'):
        cabecera_seccion('Cómo recibir los avisos',
                         'Las notificaciones siempre quedan en la campana de la aplicación; además puedes '
                         'recibirlas por correo, una a una o en un resumen diario.', 'tune', 'violeta')
        with ui.row().classes('w-full items-end gap-3'):
            canal = ui.select([], label='Canal').props('outlined dense').classes('min-w-[240px]')
            frecuencia = ui.select([], label='Frecuencia').props('outlined dense').classes('min-w-[200px]')
            if configura:
                guardar_btn = boton('Guardar', lambda: guardar(), 'save', 'primario')
        nota = ui.label('').classes('meta')
        if not configura:
            canal.disable()
            frecuencia.disable()

    async def cargar():
        try:
            r = await llamar_api('GET', '/notificaciones/preferencias', automatica=True)
        except httpx.HTTPError:
            return
        if r.status_code != 200:
            return
        p = r.json()
        canal.set_options(p['canales'], value=p['canal'])
        frecuencia.set_options(p['frecuencias'], value=p['frecuencia'])
        partes = [f"El resumen diario sale a partir de las {p['hora_resumen']}:00."]
        if not p['correo_configurado']:
            partes.insert(0, 'El servidor de correo no está configurado (SMTP_HOST): por ahora los avisos '
                             'quedan solo en la aplicación.')
        nota.text = ' '.join(partes)

    async def guardar():
        r = await llamar_api('PUT', '/notificaciones/preferencias',
                             json={'canal': canal.value, 'frecuencia': frecuencia.value})
        if r.status_code == 200:
            ui.notify('Preferencias de notificación guardadas.', type='positive')
        elif r.status_code not in (401, 403):
            ui.notify(detalle_error(r), type='negative')

    ui.timer(0.1, cargar, once=True)


# --- Perfiles de búsqueda (RF-015, RF-017) ---

def show_perfiles(ctx: Contexto):
    gestiona = puede(Permiso.PERFILES_GESTIONAR)
    edita = puede(Permiso.PERFILES_EDITAR)
    perfiles: list[dict] = []

    with banda(
        'Perfiles de búsqueda',
        'Define qué oportunidades te interesan. En cada sincronización con SECOP II el sistema contrasta los '
        'procesos nuevos con tus perfiles activos y registra las coincidencias con el proceso, la entidad y la '
        'fecha de cierre. Cada usuario ve solo sus perfiles.',
        'Analista comercial',
    ):
        if gestiona:
            boton('Nuevo perfil', lambda: editar(None), 'add', 'banda')

    if puede(Permiso.NOTIFICACIONES_VER):
        tarjeta_preferencias()

    with tarjeta('azul'):
        cabecera_seccion('Mis perfiles', 'Un proceso coincide si contiene alguna palabra clave y cumple los demás '
                         'criterios definidos.', 'manage_search', 'azul')
        columnas = [
            {'name': 'nombre', 'label': 'Perfil', 'field': 'nombre', 'align': 'left'},
            {'name': 'criterios', 'label': 'Criterios', 'field': 'palabras_clave', 'align': 'left'},
            {'name': 'coincidencias', 'label': 'Coincidencias', 'field': 'coincidencias', 'align': 'center'},
            {'name': 'activo', 'label': 'Estado', 'field': 'activo', 'align': 'left'},
            {'name': 'acciones', 'label': '', 'field': 'id', 'align': 'right'},
        ]
        tabla = ui.table(columns=columnas, rows=[], row_key='id').props('flat dense wrap-cells').classes('w-full')
        tabla.add_slot('body-cell-criterios', '''
            <q-td :props="props" style="max-width:520px">
                <div style="display:flex;flex-wrap:wrap;gap:4px">
                    <span v-for="p in props.row.palabras_clave" class="tag"
                          style="background:#EFF4FF;color:#1D4ED8;border-color:#C7D7FE">{{ p }}</span>
                </div>
                <div style="font-size:0.7rem;color:#64748B;margin-top:4px">
                    <span v-if="props.row.entidades.length">Entidades: {{ props.row.entidades.join(', ') }} · </span>
                    <span v-if="props.row.departamentos.length">Departamentos: {{ props.row.departamentos.join(', ') }} · </span>
                    <span v-if="props.row.modalidades.length">Modalidades: {{ props.row.modalidades.join(', ') }} · </span>
                    <span v-if="props.row.cuantia_min !== null || props.row.cuantia_max !== null">Cuantía
                        {{ props.row.cuantia_min !== null ? 'desde $' + Math.round(props.row.cuantia_min).toLocaleString('es-CO') : '' }}
                        {{ props.row.cuantia_max !== null ? 'hasta $' + Math.round(props.row.cuantia_max).toLocaleString('es-CO') : '' }}</span>
                </div>
            </q-td>''')
        tabla.add_slot('body-cell-activo', '''
            <q-td :props="props">
                <span class="tag" :style="props.value ? 'background:#ECFDF5;color:#047857;border-color:#A7F3D0'
                    : 'background:#F1F5F9;color:#475569;border-color:#DFE5EF'">{{ props.value ? 'Activo' : 'Inactivo' }}</span>
            </q-td>''')
        acciones = ''
        if edita:
            acciones += '''
            <q-btn flat dense round :icon="props.row.activo ? 'pause_circle' : 'play_circle'" color="grey-7"
                   @click="$parent.$emit('alternar', props.row)">
                <q-tooltip>{{ props.row.activo ? 'Desactivar' : 'Activar' }}</q-tooltip></q-btn>
            <q-btn flat dense round icon="edit" color="grey-7" @click="$parent.$emit('editar', props.row)">
                <q-tooltip>Editar</q-tooltip></q-btn>'''
        if gestiona:
            acciones += '''
            <q-btn flat dense round icon="delete" color="grey-7" @click="$parent.$emit('eliminar', props.row)">
                <q-tooltip>Eliminar</q-tooltip></q-btn>'''
        tabla.add_slot('body-cell-acciones', f'<q-td :props="props" class="text-right">{acciones}</q-td>')
        vacio = ui.label('Aún no tienes perfiles de búsqueda.').classes('meta')

    with tarjeta('ambar'):
        cabecera_seccion('Coincidencias recientes', 'Procesos que coincidieron con tus perfiles activos (RF-017).',
                         'notifications_active', 'ambar')
        tabla_c = ui.table(columns=[
            {'name': 'perfil', 'label': 'Perfil', 'field': 'perfil', 'align': 'left'},
            {'name': 'proceso', 'label': 'Proceso', 'field': 'objeto', 'align': 'left'},
            {'name': 'fecha_cierre', 'label': 'Cierre', 'field': 'fecha_cierre', 'align': 'left'},
            {'name': 'detectada_en', 'label': 'Detectada', 'field': 'detectada_en', 'align': 'left'},
        ], rows=[], row_key='id_proceso', pagination=10).props('flat dense wrap-cells').classes('w-full')
        tabla_c.add_slot('body-cell-proceso', '''
            <q-td :props="props" style="max-width:520px">
                <div style="font-weight:600;font-size:0.8rem">{{ props.row.entidad }}</div>
                <div style="font-size:0.78rem;color:#334155">{{ props.row.objeto }}</div>
                <a v-if="props.row.url_proceso" :href="props.row.url_proceso" target="_blank"
                   style="font-size:0.7rem;color:#2563EB">{{ props.row.id_proceso }}</a>
            </q-td>''')
        tabla_c.add_slot('body-cell-fecha_cierre', '''
            <q-td :props="props" style="font-size:0.78rem">{{ (props.value || 'Sin fecha publicada').slice(0, 10) }}</q-td>''')
        tabla_c.add_slot('body-cell-detectada_en', '''
            <q-td :props="props" style="font-size:0.78rem">{{ (props.value || '').slice(0, 16).replace('T', ' ') }}</q-td>''')

    async def cargar():
        try:
            r = await llamar_api('GET', '/perfiles/', automatica=True)
            rc = await llamar_api('GET', '/perfiles/coincidencias', automatica=True)
        except httpx.HTTPError:
            _sin_conexion()
            return
        if r.status_code == 200:
            perfiles[:] = r.json()
            tabla.rows = perfiles
            tabla.update()
            vacio.set_visibility(not perfiles)
        if rc.status_code == 200:
            tabla_c.rows = [{**c, 'detectada_en': _fecha_corta(c.get('detectada_en'))} for c in rc.json()]
            tabla_c.update()

    async def editar(perfil: dict | None):
        p = perfil or {}
        with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 w-[620px] max-w-[95vw]'):
            cabecera_seccion('Editar perfil' if perfil else 'Nuevo perfil',
                             'Separa con comas las palabras y los valores de cada criterio. Los criterios vacíos '
                             'no restringen.', 'manage_search', 'azul')
            nombre = ui.input('Nombre', value=p.get('nombre', '')).props('outlined dense maxlength=80').classes('w-full')
            palabras = ui.input('Palabras clave', value=', '.join(p.get('palabras_clave', [])),
                                placeholder='Ej: software, gestión documental, ERP') \
                .props('outlined dense').classes('w-full')
            entidades = ui.input('Entidades', value=', '.join(p.get('entidades', []))) \
                .props('outlined dense').classes('w-full')
            departamentos = ui.input('Departamentos', value=', '.join(p.get('departamentos', []))) \
                .props('outlined dense').classes('w-full')
            modalidades = ui.input('Modalidades', value=', '.join(p.get('modalidades', [])),
                                   placeholder='Ej: Licitación pública, Selección abreviada') \
                .props('outlined dense').classes('w-full')
            with ui.row().classes('w-full gap-3'):
                minimo = ui.number('Cuantía mínima', value=p.get('cuantia_min'), min=0, format='%.0f') \
                    .props('outlined dense clearable').classes('flex-1')
                maximo = ui.number('Cuantía máxima', value=p.get('cuantia_max'), min=0, format='%.0f') \
                    .props('outlined dense clearable').classes('flex-1')
            activo = ui.switch('Activo', value=p.get('activo', True))
            error = ui.label('').style('color:#C01048;font-size:0.8rem')
            with ui.row().classes('w-full justify-end gap-2'):
                boton('Cancelar', dialogo.close, '', 'claro')
                boton('Guardar', lambda: guardar(), 'save', 'primario')

        async def guardar():
            cuerpo = {'nombre': (nombre.value or '').strip(), 'palabras_clave': _lista(palabras.value),
                      'entidades': _lista(entidades.value), 'departamentos': _lista(departamentos.value),
                      'modalidades': _lista(modalidades.value), 'cuantia_min': minimo.value,
                      'cuantia_max': maximo.value, 'activo': activo.value}
            try:
                if perfil:
                    response = await llamar_api('PUT', f"/perfiles/{perfil['id']}", json=cuerpo)
                else:
                    response = await llamar_api('POST', '/perfiles/', json=cuerpo)
            except httpx.HTTPError:
                _sin_conexion()
                return
            if response.status_code in (200, 201):
                ui.notify('Perfil guardado. Se aplicará en la próxima sincronización.', type='positive')
                dialogo.close()
                await cargar()
            elif response.status_code not in (401, 403):
                error.text = detalle_error(response)

        dialogo.open()

    async def alternar(e):
        response = await llamar_api('PUT', f"/perfiles/{e.args['id']}", json={'activo': not e.args['activo']})
        if response.status_code == 200:
            await cargar()

    async def eliminar(e):
        with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6'):
            ui.label(f"¿Eliminar el perfil «{e.args['nombre']}» y sus coincidencias?")
            with ui.row().classes('w-full justify-end gap-2'):
                boton('Cancelar', lambda: dialogo.submit(False), '', 'claro')
                boton('Eliminar', lambda: dialogo.submit(True), 'delete', 'primario')
        if await dialogo:
            response = await llamar_api('DELETE', f"/perfiles/{e.args['id']}")
            if response.status_code == 204:
                ui.notify('Perfil eliminado.')
                await cargar()

    tabla.on('editar', lambda e: editar(e.args))
    tabla.on('alternar', alternar)
    tabla.on('eliminar', eliminar)
    ui.timer(0.1, cargar, once=True)


# --- Seguimiento de análisis ---

def show_seguimiento(ctx: Contexto):
    tareas: list[dict] = []
    revisa = puede(Permiso.REQUISITOS_APROBAR)
    solicita = puede(Permiso.ANALISIS_SOLICITAR)

    with banda(
        'Seguimiento de análisis',
        'Estado de cada licitación en análisis. El flujo se detiene en "Esperando revisión" hasta '
        'que un analista valida los requisitos extraídos.',
        'Analista comercial',
    ):
        pass

    @ui.refreshable
    def indicadores():
        activos = sum(1 for t in tareas if t['estado'] in ESTADOS_ACTIVOS)
        revision = sum(1 for t in tareas if t['estado'] == ESTADO_ESPERANDO_REVISION)
        fallidas = sum(1 for t in tareas if t['estado'] in ('Fallida', 'Suspendida'))
        finalizadas = sum(1 for t in tareas if t['estado'] == 'Finalizada')
        with ui.row().classes('w-full gap-3'):
            kpi(str(activos), 'En ejecución', 'Recibidas, en proceso o evaluando', 'azul', 'autorenew')
            kpi(str(revision), 'Esperando revisión', 'Requieren al analista', 'ambar', 'pan_tool')
            kpi(str(finalizadas), 'Finalizadas', 'Con recomendación', 'verde', 'task_alt')
            kpi(str(fallidas), 'Fallidas o suspendidas', 'Ver el detalle', 'rojo', 'error')

    indicadores()

    async def cargar(automatica: bool = True):
        try:
            response = await llamar_api('GET', '/analisis/', automatica=automatica)
        except httpx.HTTPError:
            return
        if response.status_code != 200:
            return
        tareas[:] = response.json()
        tabla.rows = [{**t, 'actualizado': _fecha_corta(t.get('actualizado_en'))} for t in tareas]
        tabla.update()
        indicadores.refresh()

    with tarjeta('azul'):
        with ui.row().classes('w-full items-end justify-between'):
            cabecera_seccion('Tareas de análisis', 'Se actualiza sola cada pocos segundos.',
                             'list_alt', 'azul')
            boton('Actualizar', lambda: cargar(automatica=False), 'refresh', 'claro')
        columnas = [
            {'name': 'licitacion_id', 'label': 'Proceso', 'field': 'licitacion_id', 'align': 'left', 'sortable': True},
            {'name': 'estado', 'label': 'Estado', 'field': 'estado', 'align': 'left', 'sortable': True},
            {'name': 'detalle', 'label': 'Detalle', 'field': 'detalle_error', 'align': 'left'},
            {'name': 'solicitado_por', 'label': 'Solicitado por', 'field': 'solicitado_por', 'align': 'left'},
            {'name': 'actualizado', 'label': 'Actualizado', 'field': 'actualizado', 'align': 'left', 'sortable': True},
            {'name': 'acciones', 'label': '', 'field': 'tarea_id', 'align': 'right'},
        ]
        tabla = ui.table(columns=columnas, rows=[], row_key='tarea_id', pagination=12).props(
            'flat dense wrap-cells').classes('w-full')
        tabla.add_slot('body-cell-licitacion_id', '''
            <q-td :props="props">
                <div style="font-weight:600;color:#0F172A">{{ props.value }}</div>
                <div style="font-size:0.7rem;color:#64748B">Tarea {{ props.row.tarea_id.slice(0, 8) }}</div>
            </q-td>
        ''')
        tabla.add_slot('body-cell-estado', _ranura_tono('estado', TONO_ESTADO))
        tabla.add_slot('body-cell-detalle', '''
            <q-td :props="props" style="max-width:420px">
                <span v-if="props.value" style="color:#C01048;font-size:0.76rem">{{ props.value }}</span>
                <span v-else-if="props.row.puntaje !== null" style="font-size:0.76rem">
                    Puntaje {{ Math.round(props.row.puntaje) }} · {{ props.row.recomendacion }}</span>
            </q-td>
        ''')
        botones = ''
        if revisa:
            botones += '''
                    <q-btn v-if="props.row.estado === 'Esperando revisión'" dense unelevated no-caps
                           color="warning" icon="fact_check" label="Revisar"
                           @click="$parent.$emit('revisar', props.row.tarea_id)" />'''
        if solicita:
            botones += '''
                    <q-btn v-if="props.row.estado === 'Suspendida' && props.row.causa_suspension === 'cuota'"
                           dense unelevated no-caps color="primary" icon="play_arrow" label="Continuar"
                           @click="$parent.$emit('continuar', props.row.tarea_id)" />'''
        if botones:
            tabla.add_slot('body-cell-acciones', f'<q-td :props="props" class="text-right">{botones}</q-td>')

        async def continuar(e):
            response = await llamar_api('POST', f'/analisis/{e.args}/continuar')
            if response.status_code == 202:
                ui.notify('La tarea continúa desde la etapa que quedó pendiente.', type='positive')
                await cargar(automatica=False)
            elif response.status_code not in (401, 403):
                ui.notify(f'No se pudo continuar: {detalle_error(response)}', type='negative')

        tabla.on('continuar', continuar)

        if revisa:

            async def revisar(e):
                ctx.ir_a('Revisión de requisitos')
                if ctx.abrir_revision:
                    await ctx.abrir_revision(e.args)

            tabla.on('revisar', revisar)

    ui.timer(0.1, cargar, once=True)
    ui.timer(6.0, cargar)


# --- Revisión de requisitos (verificación humana) ---

def show_analisis(ctx: Contexto):
    with banda(
        'Revisión de requisitos extraídos',
        'El análisis se detiene aquí. Revisa, corrige o agrega requisitos antes de que el '
        'agente evaluador los contraste con el portafolio.',
        'Verificación humana',
    ):
        pass

    with ui.row().classes('w-full items-start gap-3 p-4').style(
        'background:#FFFBEB;border:1px solid #FDE68A;border-left:4px solid #D97706;border-radius:10px'
    ):
        ficha_icono('pan_tool', 'ambar')
        with ui.column().classes('gap-0.5 flex-1'):
            ui.html(
                '<span style="font-weight:600;color:#92400E;font-size:0.86rem">El análisis '
                'espera tu confirmación</span>'
            )
            ui.html(
                '<span style="font-size:0.78rem;color:#B45309;line-height:1.45">Ningún requisito se '
                'evalúa sin tu validación: un criterio mal leído arrastra el error hasta la '
                'recomendación final y el informe.</span>'
            )

    requisitos: list[dict] = []
    # Borrador (CU-05 A1): la revisión se guarda en la API mientras se edita y sobrevive a la sesión.
    estado_borrador = {'pendiente': False, 'guardado': None}

    @ui.refreshable
    def indicadores():
        habilitantes = sum(1 for r in requisitos if r.get('condicion_habilitante_propuesta'))
        por_revisar = sum(1 for r in requisitos if r.get('revision') in ('Pendiente de revisión', 'Nuevo'))
        with ui.row().classes('w-full gap-3'):
            kpi(str(len(requisitos)), 'Requisitos extraídos', 'Por el agente extractor',
                'azul', 'fact_check')
            kpi(str(habilitantes), 'Habilitantes', 'Su incumplimiento descalifica', 'rojo', 'gpp_maybe')
            kpi(str(len(requisitos) - habilitantes), 'Puntuables', 'Suman al puntaje ponderado',
                'verde', 'scoreboard')
            if any(r.get('revision') for r in requisitos):
                # HU-06 CA-03: tras una adenda solo se revisa lo afectado; lo demás conserva su aprobación.
                kpi(str(por_revisar), 'Por revisar', 'Afectados por el cambio documental', 'ambar',
                    'difference')

    indicadores()

    with tarjeta('ambar'):
        with ui.row().classes('w-full items-end justify-between gap-4'):
            cabecera_seccion('Lista extraída del expediente',
                             'Doble clic sobre una celda para corregirla.',
                             'edit_note', 'ambar')
            tarea_sel = ui.select({}, label='Tarea en espera').props(
                'outlined dense').classes('min-w-[340px]')

        grid_options = {
            'columnDefs': [
                {'field': 'identificador', 'headerName': 'ID', 'editable': False, 'width': 100},
                {'field': 'categoria', 'headerName': 'Categoría', 'editable': True, 'width': 150,
                 'cellEditor': 'agSelectCellEditor', 'cellEditorParams': {'values': CATEGORIAS_REQUISITO}},
                {'field': 'texto', 'headerName': 'Requisito', 'editable': True, 'flex': 1,
                 'wrapText': True, 'autoHeight': True},
                {'field': 'condicion_habilitante_propuesta', 'headerName': 'Habilitante', 'editable': True,
                 'cellEditor': 'agCheckboxCellEditor', 'width': 120},
                {'field': 'referencia_documental', 'headerName': 'Referencia', 'editable': True, 'width': 180},
                {'field': 'revision', 'headerName': 'Revisión', 'editable': False, 'width': 170,
                 'tooltipField': 'motivo', 'hide': True,
                 'cellClassRules': {'celda-afectada': "x == 'Pendiente de revisión' || x == 'Nuevo'"}},
            ],
            'rowData': requisitos,
            'rowSelection': {'mode': 'singleRow'},
            'tooltipShowDelay': 300,
        }
        ui.add_css('.celda-afectada { background:#FEF3C7; color:#92400E; font-weight:600; }')

        aggrid = ui.aggrid(grid_options).classes('h-96 w-full')
        aviso_borrador = ui.label('').classes('meta')

        def mostrar_requisitos(nuevos: list[dict], revision: dict | None = None):
            marcas = (revision or {}).get('requisitos') or {}
            if revision is not None:
                for r in nuevos:
                    marca = marcas.get(r['identificador'])
                    r['revision'] = marca['estado'] if marca else ''
                    r['motivo'] = marca['motivo'] if marca else ''
                # Lo afectado primero: es lo único que el analista debe revisar.
                orden = {'Pendiente de revisión': 0, 'Nuevo': 1}
                nuevos.sort(key=lambda r: orden.get(r.get('revision'), 2))
            requisitos[:] = nuevos
            aggrid.options['rowData'] = requisitos
            aggrid.options['columnDefs'][-1]['hide'] = not any(r.get('revision') for r in requisitos)
            aggrid.update()
            indicadores.refresh()

        async def cargar_tareas(automatica: bool = True):
            try:
                response = await llamar_api('GET', '/analisis/', params={'estado': ESTADO_ESPERANDO_REVISION},
                                            automatica=automatica)
            except httpx.HTTPError as e:
                logger.warning(f"No se pudieron cargar las tareas: {type(e).__name__}")
                ui.notify(f'No se pudieron cargar las tareas desde {API_URL}.', type='negative')
                return
            if response.status_code != 200:
                return
            opciones = {t['tarea_id']: f"{t['licitacion_id']} · {t['tarea_id'][:8]}" for t in response.json()}
            tarea_sel.set_options(opciones, value=tarea_sel.value if tarea_sel.value in opciones else None)

        async def cargar_requisitos(evento):
            if not evento.value:
                mostrar_requisitos([])
                return
            try:
                response = await llamar_api('GET', f'/analisis/{evento.value}/requisitos')
            except httpx.HTTPError:
                ui.notify('No se pudieron cargar los requisitos de la tarea.', type='negative')
                return
            if response.status_code != 200:
                if response.status_code not in (401, 403):
                    ui.notify(f'No se pudieron cargar los requisitos: {detalle_error(response)}',
                              type='negative')
                return
            datos = response.json()
            mostrar_requisitos(datos['requisitos'], datos.get('revision') or {})
            estado_borrador['pendiente'] = False
            borrador = datos.get('borrador')
            aviso_borrador.text = (f"Borrador guardado por {borrador['guardado_por']} el "
                                   f"{_fecha_corta(borrador['guardado_en'])}." if borrador else '')
            previa = (datos.get('revision') or {}).get('tarea_previa')
            if previa:
                ui.notify(f'El proceso ya tenía una lista aprobada (tarea {previa[:8]}): solo los requisitos '
                          'marcados en la columna Revisión necesitan tu atención.', type='info')

        async def abrir(tarea_id: str):
            await cargar_tareas(automatica=False)
            tarea_sel.value = tarea_id

        ctx.abrir_revision = abrir
        tarea_sel.on_value_change(cargar_requisitos)
        ui.timer(0.1, cargar_tareas, once=True)
        ui.timer(15.0, cargar_tareas)

        async def guardar_borrador(automatico: bool = False):
            if not tarea_sel.value or (automatico and not estado_borrador['pendiente']):
                return
            filas = await aggrid.get_client_data()
            try:
                response = await llamar_api('PUT', f'/analisis/{tarea_sel.value}/requisitos',
                                            json={'requisitos': filas, 'aprobar': False}, automatica=automatico)
            except httpx.HTTPError:
                if not automatico:
                    ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
                return
            if response.status_code == 200:
                estado_borrador['pendiente'] = False
                guardado = response.json()
                aviso_borrador.text = f"Borrador guardado el {_fecha_corta(guardado['guardado_en'])}."
                if not automatico:
                    ui.notify('Borrador guardado. La tarea sigue esperando tu aprobación.', type='positive')
            elif not automatico and response.status_code not in (401, 403):
                ui.notify(f'No se pudo guardar el borrador: {detalle_error(response)}', type='negative')

        def marcar_cambio(_=None):
            estado_borrador['pendiente'] = True

        aggrid.on('cellValueChanged', marcar_cambio)
        ui.timer(20.0, lambda: guardar_borrador(automatico=True))

        async def add_row():
            marcar_cambio()
            # Conserva las ediciones hechas en el navegador antes de añadir la fila.
            filas = await aggrid.get_client_data()
            ids = {f['identificador'] for f in filas}
            n = len(filas) + 1
            while f'REQ-M{n:03d}' in ids:
                n += 1
            filas.append({"identificador": f"REQ-M{n:03d}", "categoria": "tecnico",
                          "texto": "Nuevo requisito...", "condicion_habilitante_propuesta": False,
                          "referencia_documental": "Agregado por el analista"})
            mostrar_requisitos(filas)

        async def quitar_fila():
            seleccion = await aggrid.get_selected_rows()
            if not seleccion:
                ui.notify('Selecciona la fila que quieres quitar.', type='warning')
                return
            filas = await aggrid.get_client_data()
            marcar_cambio()
            mostrar_requisitos([f for f in filas if f['identificador'] != seleccion[0]['identificador']])

        async def approve_and_resume():
            if not tarea_sel.value:
                ui.notify('Selecciona una tarea primero.', type='warning')
                return
            filas = await aggrid.get_client_data()
            if not filas:
                ui.notify('La lista está vacía: agrega al menos un requisito.', type='warning')
                return
            try:
                response = await llamar_api('PUT', f'/analisis/{tarea_sel.value}/requisitos',
                                            json={'requisitos': filas, 'aprobar': True})
            except httpx.HTTPError:
                ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
                return
            if response.status_code != 202:
                if response.status_code not in (401, 403):
                    ui.notify(f"No se pudo aprobar: {detalle_error(response)}", type='negative')
                return
            ui.notify('Lista aprobada. La evaluación continúa; el resultado aparecerá en "Resultados".',
                      type='positive')
            estado_borrador['pendiente'] = False
            aviso_borrador.text = ''
            tarea_sel.value = None
            await cargar_tareas(automatica=False)

        with ui.row().classes('w-full items-center justify-between gap-3 pt-1'):
            with ui.row().classes('gap-2'):
                boton('Añadir requisito', add_row, 'add', 'claro')
                boton('Quitar seleccionado', quitar_fila, 'remove', 'claro')
                boton('Guardar borrador', guardar_borrador, 'save', 'claro')
                boton('Actualizar bandeja', lambda: cargar_tareas(automatica=False), 'refresh', 'claro')
            with ui.row().classes('items-center gap-3'):
                ui.html(
                    '<span class="meta">Al aprobar, la lista queda sellada y el análisis continúa.</span>'
                )
                boton('Aprobar y continuar evaluación', approve_and_resume, 'check_circle', 'exito')


# --- Resultados ---

def show_resultados(ctx: Contexto):
    filas: list[dict] = []
    decide = puede(Permiso.DECISION_REGISTRAR)

    with banda(
        'Resultados y decisiones',
        'Análisis finalizados con el puntaje calculado y la recomendación del sistema. '
        'La decisión comercial final la toma el gerente y queda registrada con su justificación.',
        'Gerente comercial',
    ):
        pass

    @ui.refreshable
    def indicadores():
        continuar = sum(1 for r in filas if r['decision'] == 'Continuar')
        pendientes = sum(1 for r in filas if r['decision'] == 'Pendiente')
        promedio = round(sum(r['puntaje'] for r in filas) / len(filas)) if filas else 0
        with ui.row().classes('w-full gap-3'):
            kpi(str(len(filas)), 'Licitaciones analizadas', 'Con informe emitido', 'azul',
                'analytics')
            kpi(str(continuar), 'Decididas para continuar', 'Por el gerente', 'verde', 'trending_up')
            kpi(str(pendientes), 'Decisiones pendientes', 'Esperan al gerente', 'ambar', 'how_to_vote')
            kpi(str(promedio), 'Puntaje promedio', 'Sobre 100 puntos', 'violeta', 'speed')

    indicadores()

    async def cargar(automatica: bool = True):
        params = {}
        if filtro_recomendacion.value != 'Todas':
            params['recomendacion'] = filtro_recomendacion.value
        if filtro_decision.value != 'Todas':
            params['decision'] = filtro_decision.value
        try:
            response = await llamar_api('GET', '/resultados/', params=params, automatica=automatica)
        except httpx.HTTPError:
            ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
            return
        if response.status_code != 200:
            return
        filas[:] = [{
            'id': t['tarea_id'],
            'licitacion': t['licitacion_id'],
            'estado': t['estado'],
            'puntaje': round(t['puntaje'] or 0),
            'recomendacion': t['recomendacion'] or 'Sin recomendación',
            'decision': t['decision'],
            'decision_detalle': (f"{t['decision_por']} · {_fecha_corta(t['decision_en'])}"
                                 if t.get('decision_por') else ''),
            # RF-033: el puntaje solo es reproducible junto a la versión de reglas que lo calculó.
            'versiones': ' · '.join(p for p in (
                f"reglas v{t['reglas_version']}" if t.get('reglas_version') else '',
                f"portafolio v{t['portafolio_version']}" if t.get('portafolio_version') else '') if p),
        } for t in response.json()]
        table.rows = filas
        table.update()
        indicadores.refresh()

    with tarjeta('verde'):
        with ui.row().classes('w-full items-end justify-between gap-3'):
            cabecera_seccion('Embudo comercial',
                             'El puntaje agrega el cumplimiento ponderado de cada requisito.',
                             'dashboard', 'verde')
            with ui.row().classes('items-end gap-2'):
                filtro_recomendacion = ui.select(
                    ['Todas', 'Ofertar', 'No ofertar', 'Solicitar revisión'], value='Todas',
                    label='Recomendación', on_change=lambda: cargar(automatica=False),
                ).props('outlined dense').classes('min-w-[170px]')
                filtro_decision = ui.select(
                    ['Todas', 'Pendiente', *DECISIONES], value='Todas',
                    label='Decisión', on_change=lambda: cargar(automatica=False),
                ).props('outlined dense').classes('min-w-[190px]')
                boton('Actualizar', lambda: cargar(automatica=False), 'refresh', 'claro')

        columns = [
            {'name': 'licitacion', 'label': 'Licitación', 'field': 'licitacion', 'align': 'left', 'sortable': True},
            {'name': 'puntaje', 'label': 'Puntaje', 'field': 'puntaje', 'align': 'left', 'sortable': True},
            {'name': 'recomendacion', 'label': 'Recomendación', 'field': 'recomendacion', 'align': 'left'},
            {'name': 'decision', 'label': 'Decisión comercial', 'field': 'decision', 'align': 'left'},
            {'name': 'acciones', 'label': 'Acciones', 'field': 'acciones', 'align': 'right'}
        ]

        with ui.table(columns=columns, rows=filas, row_key='id').props(
            'flat dense wrap-cells'
        ).classes('w-full') as table:
            table.add_slot('body-cell-licitacion', '''
                <q-td :props="props">
                    <div style="font-weight:600;color:#0F172A">{{ props.value }}</div>
                    <div style="font-size:0.7rem;color:#64748B">Tarea {{ props.row.id.slice(0, 8) }}
                        <span v-if="props.row.versiones"> · {{ props.row.versiones }}</span></div>
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
            table.add_slot('body-cell-recomendacion', _ranura_tono('recomendacion', {
                'Ofertar': 'verde', 'No ofertar': 'rojo', 'Solicitar revisión': 'ambar',
                'Sin recomendación': 'neutro'}))
            table.add_slot('body-cell-decision', _ranura_tono('decision', TONO_DECISION,
                                                              subtitulo='decision_detalle'))
            boton_decidir = '''
                    <q-btn flat dense round icon="gavel" color="deep-purple"
                           @click="$parent.$emit('decide', props.row.id)">
                        <q-tooltip>Registrar decisión</q-tooltip>
                    </q-btn>''' if decide else ''
            table.add_slot('body-cell-acciones', f'''
                <q-td :props="props" class="text-right">
                    <q-btn flat dense round icon="checklist" color="teal-8"
                           @click="$parent.$emit('detalle', props.row.id)">
                        <q-tooltip>Detalle de la evaluación</q-tooltip>
                    </q-btn>
                    <q-btn flat dense round icon="description" color="primary"
                           @click="$parent.$emit('download', props.row.id)">
                        <q-tooltip>Ver informe</q-tooltip>
                    </q-btn>
                    <q-btn flat dense round icon="history" color="grey-8"
                           @click="$parent.$emit('historial', props.row.id)">
                        <q-tooltip>Historial de decisiones</q-tooltip>
                    </q-btn>{boton_decidir}
                </q-td>
            ''')

            async def ver_informe(e):
                try:
                    response = await llamar_api('GET', f'/analisis/{e.args}/informe/texto')
                    verificacion = await llamar_api('GET', f'/analisis/{e.args}/informe/verificacion')
                except httpx.HTTPError:
                    ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
                    return
                if response.status_code != 200:
                    if response.status_code not in (401, 403):
                        ui.notify(f'Informe no disponible: {detalle_error(response)}', type='negative')
                    return
                sello = verificacion.json() if verificacion.status_code == 200 else None

                async def descargar_pdf():
                    r = await llamar_api('GET', f'/analisis/{e.args}/informe')
                    if r.status_code == 200:
                        ui.download.content(r.content, f'informe_{e.args}.pdf', 'application/pdf')
                    elif r.status_code not in (401, 403):
                        ui.notify(f'No se pudo descargar: {detalle_error(r)}', type='negative')

                with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[680px]'):
                    cabecera_seccion('Informe de viabilidad',
                                     'Vista previa del PDF sellado. Un informe emitido no se modifica.',
                                     'description', 'azul')
                    if sello:
                        with ui.row().classes('w-full items-center gap-3'):
                            if sello['coincide']:
                                etiqueta('Huella verificada', 'verde')
                            else:
                                etiqueta('El PDF no coincide con su huella', 'rojo')
                            ui.label(f"SHA-256 {sello['huella_registrada']}").classes('meta') \
                                .style('font-family:monospace;word-break:break-all')
                    ui.code(response.text, language='text').classes('w-full max-h-[55vh] overflow-auto')
                    with ui.row().classes('w-full justify-end gap-2'):
                        boton('Cerrar', dialogo.close, '', 'claro')
                        if sello:
                            boton('Descargar PDF', descargar_pdf, 'picture_as_pdf', 'primario')
                dialogo.open()

            table.on('download', ver_informe)

            async def ver_detalle(e):
                """Tabla 28, Detalle de la evaluación: dictamen por requisito con su evidencia (RF-031,
                RF-034, RF-035) y la versión de reglas, sin la cual el puntaje no es reproducible (RF-033)."""
                try:
                    response = await llamar_api('GET', f'/analisis/{e.args}/resultado')
                except httpx.HTTPError:
                    ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
                    return
                if response.status_code != 200:
                    if response.status_code not in (401, 403):
                        ui.notify(f'Detalle no disponible: {detalle_error(response)}', type='negative')
                    return
                datos = response.json()
                fila = next((r for r in filas if r['id'] == e.args), None)
                dictamenes = {d['identificador_requisito']: d for d in datos.get('dictamenes') or []}
                reglas = datos.get('reglas') or {}
                desglose = datos.get('desglose') or {}

                with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[900px] max-w-[1100px]'):
                    cabecera_seccion(f'Detalle de la evaluación · {fila["licitacion"] if fila else e.args[:8]}',
                                     'Cada dictamen cita la evidencia del portafolio que lo sustenta.',
                                     'checklist', 'verde')
                    with ui.row().classes('w-full items-center gap-6 p-4').style(
                        'background:#F4F6FB;border:1px solid #E2E8F2;border-radius:9px'
                    ):
                        with ui.column().classes('gap-0'):
                            ui.html('<span class="rotulo">Puntaje</span>')
                            ui.html(f'<span style="font-size:1.5rem;font-weight:700">'
                                    f'{round(datos.get("puntaje") or 0)}</span>')
                        with ui.column().classes('gap-1'):
                            ui.html('<span class="rotulo">Recomendación</span>')
                            etiqueta(datos.get('recomendacion') or 'Sin recomendación',
                                     {'Ofertar': 'verde', 'No ofertar': 'rojo'}.get(datos.get('recomendacion'), 'ambar'))
                        with ui.column().classes('gap-0 flex-1'):
                            ui.html('<span class="rotulo">Versiones</span>')
                            umbrales = (f" · ofertar ≥ {reglas['umbral_ofertar']}, revisión ≥ {reglas['umbral_revision']}"
                                        if reglas.get('umbral_ofertar') is not None else '')
                            version = str(datos.get('reglas_version') or desglose.get('version_reglas') or '')
                            reglas_txt = f"Reglas v{version}" if version.isdigit() else 'Reglas provisionales'
                            ui.label(f"{reglas_txt}{umbrales} · portafolio v{datos.get('portafolio_version') or '—'}") \
                                .classes('text-sm')
                            ui.label(f"Lista aprobada por {datos.get('aprobado_por') or '—'}").classes('meta')

                    aportes = desglose.get('aporte_por_categoria') or {}
                    pesos = desglose.get('peso_efectivo_por_categoria') or {}
                    if aportes:
                        with ui.row().classes('w-full gap-2'):
                            for categoria, aporte in aportes.items():
                                with ui.column().classes('gap-0 p-2').style(
                                        'border:1px solid #E2E8F2;border-radius:8px;min-width:140px'):
                                    ui.html(f'<span class="rotulo">{categoria}</span>')
                                    peso = pesos.get(categoria, 0)
                                    # HU-08 CA-02: sin requisitos, la categoría no aplica y su peso se redistribuye.
                                    ui.label(f"{aporte:.1f} de {peso:.1f} puntos" if peso else 'No aplica') \
                                        .classes('text-sm')

                    columnas = [
                        {'name': 'id', 'label': 'ID', 'field': 'id', 'align': 'left'},
                        {'name': 'requisito', 'label': 'Requisito', 'field': 'requisito', 'align': 'left'},
                        {'name': 'categoria', 'label': 'Categoría', 'field': 'categoria', 'align': 'left'},
                        {'name': 'dictamen', 'label': 'Dictamen', 'field': 'dictamen', 'align': 'left'},
                        {'name': 'sustento', 'label': 'Evidencia y justificación', 'field': 'sustento', 'align': 'left'},
                    ]
                    filas_detalle = []
                    for r in datos.get('requisitos_aprobados') or []:
                        d = dictamenes.get(r['identificador'], {})
                        filas_detalle.append({
                            'id': r['identificador'],
                            'requisito': r['texto'],
                            'referencia': r.get('referencia_documental') or '',
                            'categoria': r['categoria'] + (' · habilitante' if r.get('condicion_habilitante_propuesta')
                                                           else ''),
                            'dictamen': d.get('estado') or 'Sin dictamen',
                            'sustento': d.get('evidencia') or 'Sin evidencia en el portafolio',
                            'justificacion': d.get('justificacion') or '',
                        })
                    with ui.table(columns=columnas, rows=filas_detalle, row_key='id').props(
                            'flat dense wrap-cells').classes('w-full max-h-[45vh]') as detalle:
                        detalle.add_slot('body-cell-requisito', '''
                            <q-td :props="props">
                                <div style="color:#0F172A">{{ props.value }}</div>
                                <div style="font-size:0.7rem;color:#64748B">{{ props.row.referencia }}</div>
                            </q-td>''')
                        detalle.add_slot('body-cell-dictamen', _ranura_tono('dictamen', {
                            'Cumple': 'verde', 'Cumple parcialmente': 'ambar', 'No cumple': 'rojo',
                            'No verificable': 'neutro', 'Sin dictamen': 'neutro'}))
                        detalle.add_slot('body-cell-sustento', '''
                            <q-td :props="props">
                                <div style="font-size:0.78rem;color:#0F172A">{{ props.value }}</div>
                                <div style="font-size:0.72rem;color:#64748B">{{ props.row.justificacion }}</div>
                            </q-td>''')
                    if datos.get('justificacion'):
                        ui.html('<span class="rotulo">Justificación de la recomendación</span>')
                        ui.label(datos['justificacion']).classes('text-sm').style('white-space:pre-wrap')
                    with ui.row().classes('w-full justify-end'):
                        boton('Cerrar', dialogo.close, '', 'claro')
                dialogo.open()

            table.on('detalle', ver_detalle)

            async def ver_historial(e):
                row_id = e.args
                fila = next((r for r in filas if r['id'] == row_id), None)
                try:
                    response = await llamar_api('GET', f'/resultados/{row_id}/decisiones')
                except httpx.HTTPError:
                    ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
                    return
                if response.status_code != 200:
                    if response.status_code not in (401, 403):
                        ui.notify(f'Historial no disponible: {detalle_error(response)}', type='negative')
                    return
                historial = response.json()
                with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[560px]'):
                    cabecera_seccion(
                        f'Historial de decisiones · {fila["licitacion"] if fila else row_id[:8]}',
                        'Cada decisión queda en la bitácora de auditoría; registrar otra no borra las anteriores.',
                        'history', 'violeta')
                    if not historial:
                        ui.html('<span class="meta">Aún no se ha registrado ninguna decisión.</span>')
                    for d in historial:
                        with ui.column().classes('w-full gap-1 p-3').style(
                            'background:#F4F6FB;border:1px solid #E2E8F2;border-radius:9px'
                        ):
                            with ui.row().classes('w-full items-center justify-between'):
                                etiqueta(d['decision'], TONO_DECISION.get(d['decision'], 'neutro'))
                                ui.label(f'{d["registrado_por"]} · {_fecha_corta(d["registrado_en"])}') \
                                    .classes('meta')
                            ui.label(d['justificacion']).classes('text-sm').style('white-space:pre-wrap')
                            if d['coincide_con_sugerencia'] is False:
                                ui.label(f'Se apartó de la sugerencia del sistema '
                                         f'({d["recomendacion_sistema"]}).').classes('meta')
                    boton('Cerrar', dialogo.close, '', 'claro')
                dialogo.open()

            table.on('historial', ver_historial)

            async def registrar_decision(e):
                row_id = e.args
                fila = next((r for r in filas if r['id'] == row_id), None)
                sugerida = DECISION_SUGERIDA.get(fila['recomendacion'] if fila else '', 'Continuar')

                with ui.dialog() as dialog, ui.column().classes('tarjeta gap-4 p-6 min-w-[460px]'):
                    cabecera_seccion(f'Registrar decisión · {fila["licitacion"] if fila else row_id[:8]}',
                                     'Queda registrada con su fecha, su autor y la justificación.',
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
                                    {'Ofertar': 'verde', 'No ofertar': 'rojo'}.get(fila['recomendacion'], 'ambar'),
                                )
                                medidor(
                                    fila['puntaje'],
                                    'verde' if fila['puntaje'] >= 70 else 'rojo',
                                )

                    decision = ui.select(DECISIONES, value=sugerida,
                                         label='Decisión comercial').props('outlined dense').classes('w-full')
                    justificacion = ui.textarea(
                        'Justificación',
                        placeholder='Explique por qué se continúa, se descarta o qué información falta.',
                    ).props('outlined dense rows=3').classes('w-full')

                    def guardar():
                        if not (justificacion.value or '').strip():
                            ui.notify('La justificación es obligatoria.', type='warning')
                            return
                        dialog.submit({'decision': decision.value, 'justificacion': justificacion.value})

                    with ui.row().classes('w-full justify-end gap-2'):
                        boton('Cancelar', lambda: dialog.submit(None), '', 'claro')
                        boton('Guardar', guardar, 'check', 'primario')

                result = await dialog
                if not result:
                    return
                try:
                    response = await llamar_api('POST', f'/resultados/{row_id}/decision', json=result)
                except httpx.HTTPError:
                    ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
                    return
                if response.status_code != 201:
                    if response.status_code not in (401, 403):
                        ui.notify(f'No se pudo registrar la decisión: {detalle_error(response)}',
                                  type='negative')
                    return
                ui.notify(f'Decisión «{result["decision"]}» registrada.', type='positive')
                await cargar(automatica=False)

            table.on('decide', registrar_decision)

    ui.timer(0.1, cargar, once=True)


# --- Bitácora de auditoría (Gerente y Administrador) ---

ETIQUETAS_EVENTO = {
    'REQUISITOS_APROBADOS': ('Requisitos aprobados', 'ambar'),
    'INFORME_GENERADO': ('Informe emitido', 'verde'),
    'DECISION_COMERCIAL': ('Decisión comercial', 'violeta'),
    'ANALISIS_SUSPENDIDO': ('Análisis suspendido', 'rojo'),
    'REGLAS_PROPUESTAS': ('Reglas propuestas', 'azul'),
    'REGLAS_PUBLICADAS': ('Reglas publicadas', 'azul'),
    'REGLAS_RECHAZADAS': ('Reglas rechazadas', 'neutro'),
    'PORTAFOLIO_PUBLICADO': ('Portafolio publicado', 'azul'),
    'CUOTA_AMPLIADA': ('Cuota ampliada', 'violeta'),
    'USUARIO_CREADO': ('Usuario creado', 'neutro'),
    'USUARIO_ACTUALIZADO': ('Usuario modificado', 'neutro'),
    'CLAVE_CAMBIADA': ('Contraseña cambiada', 'neutro'),
    'CUENTA_BLOQUEADA': ('Cuenta bloqueada', 'rojo'),
    'ACCESO_DENEGADO': ('Acceso denegado', 'rojo'),
    'BARRIDO_VIGILANCIA': ('Barrido de SECOP II', 'neutro'),
    'PROCESO_RADICADO': ('Proceso radicado', 'azul'),
    'DOCUMENTO_CARGADO': ('Documento cargado', 'azul'),
    'RESPONSABLE_ASIGNADO': ('Responsable asignado', 'violeta'),
    'EXPORTACION_CSV': ('Exportación a CSV', 'neutro'),
}


def _resumen_detalles(detalles: dict | None) -> str:
    """Una línea legible con los valores del evento (RF-042: valores modificados)."""
    if not detalles:
        return ''
    if 'cambios' in detalles:
        return '; '.join(f"{campo}: {c['antes']} → {c['despues']}" for campo, c in detalles['cambios'].items())
    partes = []
    for clave, valor in detalles.items():
        if clave in ('informe_path',) or valor in (None, '', [], {}):
            continue
        texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
        partes.append(f'{clave}: {texto[:80]}')
    return ' · '.join(partes)


def show_bitacora(ctx: Contexto):
    estado = {'eventos': [], 'total': 0, 'acciones': []}

    with banda(
        'Bitácora de auditoría',
        'Eventos críticos con su autor, fecha, tarea y valores modificados. Es de solo anexado: '
        'nadie puede editarla ni borrarla, y cada registro guarda la huella del anterior, de modo que '
        'cualquier alteración rompe la cadena.',
        'Auditoría',
    ):
        pass

    with tarjeta('violeta'):
        with ui.row().classes('w-full items-end justify-between gap-3'):
            cabecera_seccion('Integridad de la cadena', 'Recorre todos los registros y compara sus huellas.',
                             'verified_user', 'violeta')
            boton('Verificar ahora', lambda: verificar(), 'fact_check', 'claro')
        resultado_verificacion = ui.column().classes('w-full')

    async def verificar():
        response = await llamar_api('GET', '/auditoria/verificacion')
        if response.status_code != 200:
            return
        r = response.json()
        resultado_verificacion.clear()
        with resultado_verificacion:
            with ui.row().classes('items-center gap-3'):
                if r['integra']:
                    etiqueta('Cadena íntegra', 'verde')
                    ui.label(f"{r['registros']} registros verificados · {_fecha_corta(r['verificada_en'])}") \
                        .classes('meta')
                else:
                    etiqueta('Cadena alterada', 'rojo')
                    ui.label(r['detalle']).style('color:#C01048;font-size:0.8rem')

    with tarjeta('azul'):
        with ui.row().classes('w-full items-end gap-3'):
            cabecera_seccion('Eventos', 'Del más reciente al más antiguo.', 'history_edu', 'azul')
            ui.element('div').classes('flex-grow')
            filtro_accion = ui.select({'': 'Todas las acciones'}, value='', label='Acción',
                                      on_change=lambda: cargar(reiniciar=True)) \
                .props('outlined dense').classes('min-w-[220px]')
            filtro_usuario = ui.input('Autor (correo)').props('outlined dense clearable').classes('w-48')
            filtro_tarea = ui.input('Tarea').props('outlined dense clearable').classes('w-48')
            boton('Buscar', lambda: cargar(reiniciar=True), 'search', 'claro')
        columnas = [
            {'name': 'fecha', 'label': 'Fecha', 'field': 'fecha', 'align': 'left'},
            {'name': 'accion', 'label': 'Acción', 'field': 'nombre', 'align': 'left'},
            {'name': 'registrado_por', 'label': 'Autor', 'field': 'registrado_por', 'align': 'left'},
            {'name': 'tarea_id', 'label': 'Tarea u objeto', 'field': 'tarea_id', 'align': 'left'},
            {'name': 'resumen', 'label': 'Valores', 'field': 'resumen', 'align': 'left'},
        ]
        tabla = ui.table(columns=columnas, rows=[], row_key='id').props('flat dense wrap-cells').classes('w-full')
        tabla.add_slot('body-cell-accion', _ranura_tono('accion', dict(ETIQUETAS_EVENTO.values())))
        tabla.add_slot('body-cell-resumen', '''
            <q-td :props="props" style="max-width:460px;font-size:0.75rem;color:#334155">{{ props.value }}</q-td>''')
        pie = ui.row().classes('w-full items-center justify-between')

    async def cargar(reiniciar: bool = False, automatica: bool = False):
        if reiniciar:
            estado['eventos'] = []
        params = {'limite': 50, 'desplazamiento': len(estado['eventos'])}
        if filtro_accion.value:
            params['accion'] = filtro_accion.value
        if filtro_usuario.value:
            params['usuario'] = filtro_usuario.value
        if filtro_tarea.value:
            params['tarea_id'] = filtro_tarea.value
        try:
            response = await llamar_api('GET', '/auditoria/', params=params, automatica=automatica)
        except httpx.HTTPError:
            ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
            return
        if response.status_code != 200:
            return
        datos = response.json()
        estado['total'] = datos['total']
        estado['eventos'] += datos['eventos']
        filtro_accion.set_options({'': 'Todas las acciones', **{
            a: ETIQUETAS_EVENTO.get(a, (a, ''))[0] for a in datos['acciones']}}, value=filtro_accion.value)
        tabla.rows = [{**e, 'fecha': _fecha_corta(e['fecha']),
                       'nombre': ETIQUETAS_EVENTO.get(e['accion'], (e['accion'], ''))[0],
                       'resumen': _resumen_detalles(e['detalles'])} for e in estado['eventos']]
        tabla.update()
        pie.clear()
        with pie:
            ui.label(f"{len(estado['eventos'])} de {estado['total']} eventos").classes('meta')
            if len(estado['eventos']) < estado['total']:
                boton('Cargar más', lambda: cargar(), 'expand_more', 'claro')

    ui.timer(0.1, lambda: cargar(reiniciar=True, automatica=True), once=True)


# --- Usuarios y diagnóstico (administrador) ---

def show_usuarios(ctx: Contexto):
    usuarios: list[dict] = []
    roles: list[str] = []
    yo = usuario_actual()

    with banda(
        'Usuarios y roles',
        'Crea usuarios, asigna su rol y habilítalos o deshabilítalos. Deshabilitar a un usuario '
        'cierra sus sesiones abiertas de inmediato.',
        'Administrador del sistema',
    ):
        pass

    async def cargar(automatica: bool = True):
        try:
            r_usuarios = await llamar_api('GET', '/usuarios/', automatica=automatica)
            r_roles = await llamar_api('GET', '/usuarios/roles', automatica=True)
        except httpx.HTTPError:
            ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
            return
        if r_roles.status_code == 200:
            roles[:] = [r['rol'] for r in r_roles.json()]
            rol_nuevo.set_options(roles, value=rol_nuevo.value)
        if r_usuarios.status_code == 200:
            usuarios[:] = r_usuarios.json()
            tabla.rows = [{**u, 'ultimo': _fecha_corta(u.get('ultimo_acceso')) or 'Nunca'} for u in usuarios]
            tabla.update()

    federado = api.modo_oidc()
    clave_opcional = federado or api.oidc_disponible()
    with tarjeta('azul'):
        cabecera_seccion('Nuevo usuario',
                         'Entrará con su cuenta institucional: la contraseña la gestiona el proveedor de identidad '
                         '(RN-02).' if federado else
                         'Contraseña opcional: sin ella, el usuario solo entra con su cuenta institucional. Si la '
                         'defines, debe tener al menos 8 caracteres con letras y números.' if clave_opcional else
                         'La contraseña debe tener al menos 8 caracteres con letras y números.',
                         'person_add', 'azul')
        with ui.row().classes('w-full items-start gap-3'):
            nombre = ui.input('Nombre completo').props('outlined dense').classes('flex-1')
            correo = ui.input('Correo institucional').props('outlined dense').classes('flex-1')
            rol_nuevo = ui.select([], label='Rol').props('outlined dense').classes('flex-1')
            clave = ui.input('Contraseña inicial', password=True, password_toggle_button=True).props(
                'outlined dense').classes('flex-1')
            clave.set_visibility(not federado)

            async def crear():
                if not (nombre.value and correo.value and rol_nuevo.value and (clave.value or clave_opcional)):
                    ui.notify('Completa todos los campos.', type='warning')
                    return
                response = await llamar_api('POST', '/usuarios/', json={
                    'nombre': nombre.value, 'email': correo.value, 'rol': rol_nuevo.value,
                    'password': None if federado else (clave.value or None), 'activo': True,
                })
                if response.status_code == 201:
                    ui.notify(f'Usuario {correo.value} creado.', type='positive')
                    nombre.value = correo.value = clave.value = ''
                    rol_nuevo.value = None
                    await cargar(automatica=False)
                elif response.status_code not in (401, 403):
                    ui.notify(detalle_error(response), type='negative')

            boton('Crear', crear, 'save', 'primario')

    with tarjeta('violeta'):
        with ui.row().classes('w-full items-end justify-between'):
            cabecera_seccion('Usuarios registrados', 'Edita el rol o el estado desde las acciones.',
                             'group', 'violeta')
            boton('Actualizar', lambda: cargar(automatica=False), 'refresh', 'claro')
        columnas = [
            {'name': 'nombre', 'label': 'Usuario', 'field': 'nombre', 'align': 'left', 'sortable': True},
            {'name': 'rol', 'label': 'Rol', 'field': 'rol', 'align': 'left', 'sortable': True},
            {'name': 'activo', 'label': 'Estado', 'field': 'activo', 'align': 'left'},
            {'name': 'ultimo', 'label': 'Último acceso', 'field': 'ultimo', 'align': 'left'},
            {'name': 'acciones', 'label': '', 'field': 'id', 'align': 'right'},
        ]
        tabla = ui.table(columns=columnas, rows=[], row_key='id').props('flat dense wrap-cells').classes('w-full')
        tabla.add_slot('body-cell-nombre', '''
            <q-td :props="props">
                <div style="font-weight:600;color:#0F172A">{{ props.value }}</div>
                <div style="font-size:0.72rem;color:#64748B">{{ props.row.email }}</div>
            </q-td>
        ''')
        tabla.add_slot('body-cell-activo', '''
            <q-td :props="props">
                <span class="tag" :style="props.value
                    ? 'background:#ECFDF5;color:#047857;border-color:#A7F3D0'
                    : 'background:#F1F5F9;color:#475569;border-color:#DFE5EF'">
                    {{ props.value ? 'Habilitado' : 'Deshabilitado' }}</span>
            </q-td>
        ''')
        boton_clave = '' if federado else '''
                <q-btn flat dense round icon="key" color="grey-8" @click="$parent.$emit('clave', props.row.id)">
                    <q-tooltip>Restablecer contraseña</q-tooltip></q-btn>'''
        tabla.add_slot('body-cell-acciones', f'''
            <q-td :props="props" class="text-right">
                <q-btn flat dense round icon="edit" color="primary" @click="$parent.$emit('editar', props.row.id)">
                    <q-tooltip>Cambiar rol o estado</q-tooltip></q-btn>{boton_clave}
            </q-td>
        ''')

        async def editar(e):
            u = next((x for x in usuarios if x['id'] == e.args), None)
            if not u:
                return
            with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-4 p-6 min-w-[420px]'):
                cabecera_seccion(f'Editar · {u["nombre"]}', u['email'], 'edit', 'azul')
                nuevo_nombre = ui.input('Nombre', value=u['nombre']).props('outlined dense').classes('w-full')
                nuevo_rol = ui.select(roles, value=u['rol'], label='Rol').props('outlined dense').classes('w-full')
                habilitado = ui.switch('Habilitado', value=u['activo'])
                if str(u['id']) == str(yo.get('user_id')):
                    ui.html('<span class="meta">Es tu propio usuario: no puedes quitarte el rol de '
                            'administrador ni deshabilitarte.</span>')
                with ui.row().classes('w-full justify-end gap-2'):
                    boton('Cancelar', lambda: dialogo.submit(None), '', 'claro')
                    boton('Guardar', lambda: dialogo.submit(True), 'check', 'primario')
            if not await dialogo:
                return
            response = await llamar_api('PATCH', f'/usuarios/{u["id"]}', json={
                'nombre': nuevo_nombre.value, 'rol': nuevo_rol.value, 'activo': habilitado.value,
            })
            if response.status_code == 200:
                ui.notify('Usuario actualizado.', type='positive')
                await cargar(automatica=False)
            elif response.status_code not in (401, 403):
                ui.notify(detalle_error(response), type='negative')

        async def restablecer(e):
            u = next((x for x in usuarios if x['id'] == e.args), None)
            if not u:
                return
            with ui.dialog() as dialogo, ui.column().classes('tarjeta gap-4 p-6 min-w-[420px]'):
                cabecera_seccion(f'Restablecer contraseña · {u["nombre"]}',
                                 'Sus sesiones abiertas se cerrarán.', 'key', 'ambar')
                nueva = ui.input('Nueva contraseña', password=True, password_toggle_button=True).props(
                    'outlined dense').classes('w-full')
                with ui.row().classes('w-full justify-end gap-2'):
                    boton('Cancelar', lambda: dialogo.submit(None), '', 'claro')
                    boton('Guardar', lambda: dialogo.submit(True), 'check', 'primario')
            if not await dialogo:
                return
            response = await llamar_api('POST', f'/usuarios/{u["id"]}/password', json={'password': nueva.value})
            if response.status_code == 204:
                ui.notify('Contraseña restablecida.', type='positive')
            elif response.status_code not in (401, 403):
                ui.notify(detalle_error(response), type='negative')

        tabla.on('editar', editar)
        tabla.on('clave', restablecer)

    if puede(Permiso.DIAGNOSTICO_VER):
        with tarjeta('verde'):
            with ui.row().classes('w-full items-end justify-between'):
                cabecera_seccion('Diagnóstico de servicios',
                                 'Prueba la base de datos, SECOP II, Azure OpenAI y la cola de trabajo.',
                                 'monitor_heart', 'verde')
                boton('Verificar ahora', lambda: diagnosticar(), 'play_arrow', 'claro')
            contenedor = ui.column().classes('w-full gap-2')

            async def diagnosticar():
                contenedor.clear()
                with contenedor:
                    ui.spinner(size='md')
                try:
                    response = await llamar_api('GET', '/diagnostico')
                except httpx.HTTPError:
                    contenedor.clear()
                    ui.notify(f'Sin conexión con la API en {API_URL}.', type='negative')
                    return
                contenedor.clear()
                if response.status_code != 200:
                    return
                with contenedor:
                    for r in response.json():
                        with ui.row().classes('w-full items-start gap-3 p-3').style(
                            'border:1px solid #E2E8F2;border-radius:9px'
                        ):
                            ficha_icono('check_circle' if r['ok'] else 'error', 'verde' if r['ok'] else 'rojo')
                            with ui.column().classes('gap-0 flex-1'):
                                ui.label(r['servicio']).style('font-weight:600;font-size:0.84rem')
                                ui.label(r['detalle']).classes('meta')
                                if r.get('accion'):
                                    ui.label(r['accion']).style('font-size:0.76rem;color:#B45309')

    if puede(Permiso.DIAGNOSTICO_VER):
        with tarjeta('violeta'):
            with ui.row().classes('w-full items-end justify-between'):
                cabecera_seccion('Consumo de inferencia',
                                 'Tokens enviados al proveedor del modelo en el periodo y cuota disponible. '
                                 'Al agotarse, no se aceptan análisis nuevos y los que necesitan más '
                                 'inferencia quedan suspendidos.', 'data_usage', 'violeta')
                boton('Actualizar', lambda: cargar_consumo(), 'refresh', 'claro')
            consumo_ui = ui.column().classes('w-full gap-3')

            async def cargar_consumo():
                try:
                    response = await llamar_api('GET', '/consumo/', automatica=True)
                except httpx.HTTPError:
                    return
                if response.status_code != 200:
                    return
                c = response.json()
                consumo_ui.clear()
                with consumo_ui:
                    tono = 'rojo' if c['agotada'] else ('ambar' if c['alerta'] else 'verde')
                    with ui.row().classes('w-full items-center gap-4'):
                        ui.label(f"Periodo {c['periodo']}").style('font-weight:600')
                        medidor(min(round(c['porcentaje']), 100), tono)
                        ui.label(f"{c['consumido']:,} de {c['limite']:,} tokens ({c['porcentaje']:g} %)"
                                 .replace(',', '.') if c['limite'] else f"{c['consumido']:,} tokens · sin límite"
                                 .replace(',', '.')).classes('meta')
                        if c['agotada']:
                            etiqueta('Cuota agotada', 'rojo')
                        elif c['alerta']:
                            etiqueta(f"Sobre el {c['umbral_alerta']:g} %", 'ambar')
                    if c['por_operacion']:
                        ui.label(' · '.join(f'{op}: {n:,}'.replace(',', '.')
                                            for op, n in sorted(c['por_operacion'].items()))).classes('meta')
                    if c.get('ampliacion'):
                        a = c['ampliacion']
                        ui.label(f"Ampliada por {a['por']} el {_fecha_corta(a['en'])}: {a['motivo']}").classes('meta')
                    if puede(Permiso.CUOTA_AMPLIAR):
                        with ui.row().classes('w-full items-start gap-3'):
                            nuevo = ui.number('Nuevo límite (tokens)', value=(c['limite'] or 0) * 2 or 1_000_000,
                                              min=1, format='%.0f').props('outlined dense').classes('w-56')
                            motivo = ui.input('Motivo de la ampliación').props('outlined dense').classes('flex-1')

                            async def ampliar():
                                r = await llamar_api('POST', '/consumo/ampliar', json={
                                    'limite': int(nuevo.value or 0), 'motivo': motivo.value or ''})
                                if r.status_code == 200:
                                    ui.notify('Cuota ampliada. Las tareas suspendidas por cuota pueden continuar '
                                              'desde "Seguimiento".', type='positive')
                                    await cargar_consumo()
                                elif r.status_code not in (401, 403):
                                    ui.notify(f'No se amplió: {detalle_error(r)}', type='negative')

                            boton('Ampliar cuota', ampliar, 'add_chart', 'primario')

            ui.timer(0.2, cargar_consumo, once=True)

    ui.timer(0.1, cargar, once=True)


# --- Inicio de sesión ---

@ui.page('/login')
async def pagina_login():
    if api.modo_desarrollo():
        return RedirectResponse('/')
    motivo = api.tomar_motivo()
    if api.token_actual() and not motivo:
        return RedirectResponse('/')
    cargar_tema()

    with ui.column().classes('w-full min-h-screen items-center justify-center').style(
        'background:linear-gradient(160deg,#1B2C5A 0%,#111C3A 55%,#0D1530 100%)'
    ):
        with ui.column().classes('tarjeta gap-4 p-8 w-[400px] max-w-[92vw]'):
            with ui.row().classes('items-center gap-2.5'):
                ui.html(
                    '<div style="width:34px;height:34px;border-radius:9px;'
                    'background:linear-gradient(135deg,#60A5FA,#2563EB);display:flex;'
                    'align-items:center;justify-content:center">'
                    '<span class="material-icons" style="font-size:18px;color:#FFFFFF">diamond</span></div>'
                )
                with ui.column().classes('gap-0'):
                    ui.html('<span style="font-weight:600;font-size:1.05rem">Licita</span>')
                    ui.html('<span class="meta">Análisis de licitaciones SECOP II</span>')
            ui.html('<p class="titulo-seccion" style="margin-top:6px">Iniciar sesión</p>')
            if motivo:
                with ui.row().classes('w-full items-start gap-2 p-3').style(
                    'background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px'
                ):
                    ui.icon('info', size='18px').style('color:#B45309')
                    ui.label(motivo).style('font-size:0.8rem;color:#92400E;flex:1')
            if api.oidc_disponible():
                # Tabla 28: el acceso se delega al proveedor; las cuentas las crea el administrador.
                ui.label('Entra con tu cuenta institucional. Las cuentas las crea el administrador de Licita.') \
                    .classes('meta')
                boton('Entrar con la cuenta institucional', lambda: ui.navigate.to('/auth/oidc/inicio'),
                      'badge', 'primario').classes('w-full')
                if api.modo_oidc():
                    return  # RN-02: sin contraseña local
                with ui.row().classes('w-full items-center gap-2'):
                    ui.element('div').classes('flex-grow').style('border-top:1px solid #E2E8F2')
                    ui.label('o con usuario de Licita').classes('meta')
                    ui.element('div').classes('flex-grow').style('border-top:1px solid #E2E8F2')
            correo = ui.input('Correo').props('outlined dense autofocus').classes('w-full')
            clave = ui.input('Contraseña', password=True, password_toggle_button=True).props(
                'outlined dense').classes('w-full')
            error = ui.label('').style('color:#C01048;font-size:0.8rem')

            async def entrar():
                error.text = ''
                if not (correo.value and clave.value):
                    error.text = 'Escribe tu correo y tu contraseña.'
                    return
                boton_entrar.props('loading')
                mensaje = await api.iniciar_sesion(correo.value, clave.value)
                boton_entrar.props(remove='loading')
                if mensaje:
                    error.text = mensaje
                    clave.value = ''
                    return
                ui.navigate.to('/')

            clave.on('keydown.enter', entrar)
            correo.on('keydown.enter', lambda: clave.run_method('focus'))
            boton_entrar = boton('Entrar', entrar, 'login', 'primario').classes('w-full')


CLAVE_SOLICITUD_OIDC = 'oidc_solicitud'


@ui.page('/auth/oidc/inicio')
async def oidc_inicio():
    """Redirige al proveedor con state, nonce y PKCE guardados en el servidor (DA-10)."""
    if not api.oidc_disponible():
        return RedirectResponse('/login')
    solicitud = oidc.nueva_solicitud()
    try:
        destino = await oidc.url_autorizacion(solicitud)
    except oidc.ErrorOIDC as e:
        api.limpiar_sesion(str(e))
        return RedirectResponse('/login')
    app.storage.user[CLAVE_SOLICITUD_OIDC] = solicitud
    return RedirectResponse(destino)


@ui.page('/auth/callback')
async def oidc_callback(code: str = '', state: str = '', error: str = '', error_description: str = ''):
    """
    Vuelta del proveedor: se comprueba el state, se canjea el código desde el servidor y la API
    valida el id_token y abre la sesión. Ningún token del proveedor llega al navegador.
    """
    solicitud = app.storage.user.pop(CLAVE_SOLICITUD_OIDC, None)
    if error:
        api.limpiar_sesion(f"El proveedor de identidad no completó el inicio de sesión ({error_description or error})."[:300])
        return RedirectResponse('/login')
    if not oidc.solicitud_vigente(solicitud, state) or not code:
        api.limpiar_sesion('La solicitud de inicio de sesión no es válida o venció. Intenta de nuevo.')
        return RedirectResponse('/login')
    try:
        tokens = await oidc.canjear_codigo(code, solicitud)
    except oidc.ErrorOIDC as e:
        api.limpiar_sesion(str(e))
        return RedirectResponse('/login')
    motivo = await api.iniciar_sesion_federada(tokens['id_token'], solicitud['nonce'])
    if motivo:
        api.limpiar_sesion(motivo)
        return RedirectResponse('/login')
    return RedirectResponse('/')


# --- Layout principal ---

ENTRADAS = [
    ('Portafolio', 'inventory_2', Permiso.PORTAFOLIO_VER, show_portafolio),
    ('Vigilancia', 'radar', Permiso.VIGILANCIA_VER, show_vigilancia),
    ('Oportunidades', 'travel_explore', Permiso.VIGILANCIA_VER, show_oportunidades),
    ('Perfiles de búsqueda', 'manage_search', Permiso.PERFILES_VER, show_perfiles),
    ('Seguimiento', 'list_alt', Permiso.ANALISIS_VER, show_seguimiento),
    ('Revisión de requisitos', 'fact_check', Permiso.REQUISITOS_APROBAR, show_analisis),
    ('Resultados', 'dashboard', Permiso.RESULTADOS_VER, show_resultados),
    ('Reglas del puntaje', 'tune', Permiso.REGLAS_VER, show_reglas),
    ('Bitácora', 'history_edu', Permiso.BITACORA_VER, show_bitacora),
    ('Usuarios', 'manage_accounts', Permiso.USUARIOS_GESTIONAR, show_usuarios),
]


def _iniciales(nombre: str) -> str:
    partes = [p for p in (nombre or '?').split() if p]
    return ''.join(p[0] for p in partes[:2]).upper() or '?'


@ui.page('/')
async def index():
    if not api.token_actual():
        return RedirectResponse('/login')
    cargar_tema()

    # Valida la sesión y refresca el perfil (rol y permisos) antes de pintar nada.
    try:
        response = await llamar_api('GET', '/auth/yo')
    except httpx.HTTPError:
        with ui.column().classes('w-full min-h-screen items-center justify-center gap-3'):
            ui.icon('cloud_off', size='48px').style('color:#64748B')
            ui.label(f'No hay conexión con la API en {API_URL}.').classes('titulo-seccion')
            ui.label('Verifica que el servicio de la API esté encendido y recarga la página.').classes('meta')
        return
    if response.status_code != 200:
        return  # llamar_api ya redirigió al inicio de sesión
    yo = response.json()
    app.storage.user[api.CLAVE_USUARIO] = yo

    entradas = [e for e in ENTRADAS if e[2] in yo.get('permisos', [])]
    # Cada rol abre en su pantalla principal (Tabla 27); si no la tiene, en la primera del menú.
    nombres = [nombre for nombre, *_ in entradas]
    inicial = PANTALLA_INICIAL.get(yo.get('rol'))
    inicial = inicial if inicial in nombres else (nombres[0] if nombres else '')
    ctx = Contexto()

    with ui.header().props('flat bordered=false').classes(
        'items-center justify-between px-7 h-16'
    ).style('background:#FFFFFF;border-bottom:1px solid #E2E8F2'):
        estado_api = ui.html('')
        with ui.row().classes('items-center gap-4'):
            if Permiso.NOTIFICACIONES_VER in yo.get('permisos', []):
                with ui.button(icon='notifications', on_click=lambda: abrir_bandeja(contar_avisos)) \
                        .props('flat round dense color=grey-8').tooltip('Notificaciones'):
                    insignia = ui.badge('', color='red').props('floating rounded')
                    insignia.set_visibility(False)

                async def contar_avisos():
                    try:
                        r = await llamar_api('GET', '/notificaciones/', params={'no_leidas': 'true', 'limite': 1},
                                             automatica=True)
                    except httpx.HTTPError:
                        return
                    if r.status_code == 200:
                        cantidad = r.json()['no_leidas']
                        insignia.text = str(cantidad) if cantidad < 100 else '99+'
                        insignia.set_visibility(cantidad > 0)

                ui.timer(0.5, contar_avisos, once=True)
                ui.timer(60.0, contar_avisos)
            with ui.column().classes('gap-0 items-end'):
                ui.label(yo.get('nombre') or yo.get('email')).style('font-size:0.8rem;font-weight:500;color:#0F172A')
                ui.label(yo.get('rol') or '').classes('meta')
            ui.html(
                '<div style="width:33px;height:33px;border-radius:9px;'
                'background:linear-gradient(135deg,#2563EB,#4338CA);color:#FFFFFF;display:flex;'
                'align-items:center;justify-content:center;font-size:0.76rem;font-weight:600">'
                f'{_iniciales(yo.get("nombre", ""))}</div>'
            )
            if not api.modo_desarrollo():
                ui.button(on_click=api.cerrar_sesion).props(
                    'flat dense round icon=logout color=grey-7').tooltip('Cerrar sesión')

    async def refrescar_salud():
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=10.0) as client:
                salud = (await client.get('/health')).json()
            ok = salud.get('status') == 'ok'
        except (httpx.HTTPError, ValueError):
            ok = False
        tono = TONOS['verde' if ok else 'rojo']
        texto = 'Servicios operativos' if ok else 'API o base de datos sin conexión'
        estado_api.set_content(
            f'<span class="tag" style="background:{tono[0]};color:{tono[1]};border-color:{tono[2]}">'
            f'<span class="punto" style="background:{tono[1]}"></span>{texto}</span>'
        )

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
                ui.html('<span class="riel-rotulo">Análisis de licitaciones</span>')

        ui.html('<span class="riel-rotulo" style="padding:0 10px">Operación</span>')
        with ui.tabs().classes('hidden') as tabs:
            pestanas = {nombre: ui.tab(nombre) for nombre, *_ in entradas}

        activo = {'nombre': inicial}

        def seleccionar(nombre: str) -> None:
            activo['nombre'] = nombre
            tabs.set_value(nombre)
            riel.refresh()

        ctx.ir_a = seleccionar

        @ui.refreshable
        def riel() -> None:
            for nombre, icono, *_ in entradas:
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
        if Permiso.ANALISIS_VER in yo.get('permisos', []):
            with ui.column().classes('w-full gap-2 p-3.5').style(
                'background:linear-gradient(140deg,rgba(96,165,250,0.18),rgba(124,58,237,0.16));'
                'border:1px solid rgba(147,180,253,0.26);border-radius:10px'
            ):
                ui.html(
                    '<div style="display:flex;align-items:center;gap:7px">'
                    '<span class="material-icons" style="font-size:15px;color:#93B4FD">account_tree</span>'
                    '<span class="riel-rotulo" style="color:#A9C5FF">Análisis en curso</span></div>'
                )
                resumen = ui.html('')

            async def refrescar_resumen():
                try:
                    r = await llamar_api('GET', '/analisis/', automatica=True)
                except httpx.HTTPError:
                    return
                if r.status_code != 200:
                    return
                tareas = r.json()
                en_curso = sum(1 for t in tareas if t['estado'] in ESTADOS_ACTIVOS)
                en_revision = sum(1 for t in tareas if t['estado'] == ESTADO_ESPERANDO_REVISION)
                resumen.set_content(
                    '<div style="display:flex;align-items:center;justify-content:space-between;gap:6px">'
                    f'<span style="color:#E8EDF8;font-size:0.76rem">{en_curso} en ejecución</span>'
                    '<span class="tag" style="background:rgba(217,119,6,0.26);color:#FCD34D;'
                    f'border-color:rgba(252,211,77,0.32)">{en_revision} en revisión</span></div>'
                )

            ui.timer(0.2, refrescar_resumen, once=True)
            ui.timer(10.0, refrescar_resumen)

    if not entradas:
        with ui.column().classes('w-full items-center p-10'):
            ui.label('Tu rol no tiene pantallas asignadas. Contacta al administrador.').classes('titulo-seccion')
    else:
        with ui.tab_panels(tabs, value=pestanas[inicial]).classes('w-full bg-transparent'):
            for nombre, _icono, _permiso, vista in entradas:
                with ui.tab_panel(pestanas[nombre]).classes('bg-transparent px-0'):
                    with ui.column().classes('w-full max-w-[1280px] mx-auto px-8 py-7 gap-5'):
                        vista(ctx)

    # --- Vigencia de la sesión: aviso antes de expirar por inactividad ---
    aviso = {'dialogo': None}

    async def vigilar_sesion():
        if api.modo_desarrollo():
            return
        try:
            r = await llamar_api('GET', '/auth/sesion', automatica=True)
        except httpx.HTTPError:
            return
        if r.status_code != 200:
            return
        limite = r.json().get('inactividad_expira_en')
        if not limite:
            return
        restante = (datetime.fromisoformat(limite.replace('Z', '+00:00'))
                    - datetime.now(timezone.utc)).total_seconds()
        if restante <= 120 and aviso['dialogo'] is None:
            with ui.dialog().props('persistent') as dialogo, ui.column().classes('tarjeta gap-3 p-6 min-w-[380px]'):
                cabecera_seccion('Tu sesión está por expirar',
                                 'Por inactividad se cerrará en menos de dos minutos.', 'timer', 'ambar')

                async def seguir():
                    await llamar_api('GET', '/auth/yo')
                    dialogo.close()
                    aviso['dialogo'] = None

                with ui.row().classes('w-full justify-end gap-2'):
                    boton('Cerrar sesión', api.cerrar_sesion, '', 'claro')
                    boton('Seguir conectado', seguir, 'check', 'primario')
            aviso['dialogo'] = dialogo
            dialogo.open()

    ui.timer(0.1, refrescar_salud, once=True)
    ui.timer(30.0, refrescar_salud)
    ui.timer(30.0, vigilar_sesion)


if __name__ in {"__main__", "__mp_main__"}:
    # El secreto firma la cookie que liga el navegador con su sesión en la interfaz.
    secreto_ui = (os.getenv("WEBUI_STORAGE_SECRET") or os.getenv("SESION_SECRETO") or "").strip()
    if not secreto_ui:
        logger.warning("WEBUI_STORAGE_SECRET vacío: se usa uno temporal y las sesiones de la interfaz "
                       "se pierden al reiniciarla.")
        secreto_ui = secrets.token_urlsafe(32)
    # Cuarta unidad de la telemetría (RF-043); sin cadena de conexión no exporta nada.
    from src.shared import telemetria
    telemetria.configurar("webui")
    # Puerto por defecto 8080 configurado en docker-compose; WEBUI_PORT permite otra copia local.
    ui.run(title="Licita · Análisis de licitaciones", port=int(os.getenv("WEBUI_PORT", "8080")),
           language="es", storage_secret=secreto_ui)
