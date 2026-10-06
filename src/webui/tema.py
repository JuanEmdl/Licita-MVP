"""Sistema de diseno de la interfaz web.

Criterio: color con proposito. Una banda de degradado por pantalla como ancla,
superficies claras para el trabajo real y color semantico en los datos (estado,
puntaje, dictamen). Las tarjetas de cifra van en tinte suave y no en relleno
saturado: dan color sin cansar la vista en una pantalla que el analista mira
durante horas.

Iconografia: Material Icons, que NiceGUI ya empaqueta. No se usan CDN externos
para que la interfaz se vea igual dentro del contenedor y sin salida a internet.
"""

from __future__ import annotations

import html
from contextlib import contextmanager
from typing import Iterator

from nicegui import ui

TINTA = '#0F172A'
TINTA_MEDIA = '#334155'
TINTA_TENUE = '#64748B'
LIENZO = '#F4F6FB'
SUPERFICIE = '#FFFFFF'
BORDE = '#E2E8F2'
MARCA = '#2563EB'

# (fondo, texto, borde) por tono semantico.
TONOS = {
    'neutro': ('#F1F5F9', '#475569', '#DFE5EF'),
    'azul': ('#EFF4FF', '#1D4ED8', '#C7D7FE'),
    'verde': ('#ECFDF5', '#047857', '#A7F3D0'),
    'ambar': ('#FFFBEB', '#B45309', '#FDE68A'),
    'rojo': ('#FFF1F3', '#C01048', '#FECDD6'),
    'violeta': ('#F5F3FF', '#6D28D9', '#DDD6FE'),
}

HOJA = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --tinta: #0F172A;
    --tinta-media: #334155;
    --tinta-tenue: #64748B;
    --lienzo: #F4F6FB;
    --superficie: #FFFFFF;
    --borde: #E2E8F2;
    --borde-suave: #EEF2F8;
    --marca: #2563EB;
    --sans: 'Sora', 'Segoe UI', system-ui, sans-serif;
    --sombra: 0 1px 2px rgba(15,23,42,0.05);
    --sombra-alta: 0 6px 18px -8px rgba(15,23,42,0.22);
  }

  body, .q-layout, .nicegui-content {
    background: var(--lienzo);
    font-family: var(--sans);
    color: var(--tinta);
    font-size: 14px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  .nicegui-content { padding: 0; }

  /* --- Tipografia --- */
  .titulo-pagina { font-size: 1.6rem; font-weight: 600; letter-spacing: -0.02em; line-height: 1.15; margin: 0; }
  .titulo-seccion { font-size: 0.95rem; font-weight: 600; letter-spacing: -0.01em; margin: 0; }
  .meta { font-size: 0.78rem; color: var(--tinta-tenue); line-height: 1.5; margin: 0; }
  .rotulo { font-size: 0.64rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.09em; color: var(--tinta-tenue); }

  /* --- Banda de encabezado: una por pantalla --- */
  .banda {
    background: linear-gradient(115deg, #1E3A8A 0%, #2563EB 58%, #4338CA 100%);
    border-radius: 12px; padding: 22px 26px; color: #FFFFFF;
    position: relative; overflow: hidden;
    box-shadow: 0 8px 22px -12px rgba(37,99,235,0.6);
  }
  .banda::after {
    content: ''; position: absolute; right: -70px; top: -90px;
    width: 290px; height: 290px; border-radius: 9999px;
    background: radial-gradient(circle, rgba(255,255,255,0.15) 0%, transparent 68%);
    pointer-events: none;
  }
  .banda .titulo-pagina { color: #FFFFFF; }
  .banda .rotulo { color: #AFC8FF; }
  .banda .meta { color: #CBDBFA; }

  /* --- Tarjetas --- */
  .tarjeta {
    background: var(--superficie); border: 1px solid var(--borde);
    border-radius: 11px; box-shadow: var(--sombra);
    transition: box-shadow 180ms ease;
  }
  .tarjeta:hover { box-shadow: var(--sombra-alta); }
  .acento { height: 3px; border-radius: 11px 11px 0 0; }

  /* Cifra en tinte suave: color sin saturacion plena. */
  .kpi { border-radius: 11px; padding: 15px 17px; border: 1px solid transparent; }
  .kpi-cifra { font-size: 1.7rem; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; }
  .ficha { width: 30px; height: 30px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }

  /* --- Etiquetas --- */
  .tag {
    display: inline-flex; align-items: center; gap: 5px;
    border-radius: 6px; padding: 3px 9px;
    font-size: 0.68rem; font-weight: 600; white-space: nowrap;
    border: 1px solid transparent;
  }
  .punto { width: 6px; height: 6px; border-radius: 9999px; flex-shrink: 0; }

  /* --- Botones ---
     Los selectores llevan .q-btn por delante a proposito: NiceGUI marca cada
     boton con bg-primary/text-white, que ganan sobre una clase suelta. */
  .q-btn { border-radius: 7px; text-transform: none; font-weight: 500; font-family: var(--sans); letter-spacing: 0; }
  .q-btn.btn-primario {
    background: linear-gradient(135deg,#2563EB,#1E40AF) !important; color: #FFFFFF !important;
    box-shadow: 0 4px 12px -5px rgba(37,99,235,0.6) !important;
  }
  .q-btn.btn-exito {
    background: linear-gradient(135deg,#059669,#047857) !important; color: #FFFFFF !important;
    box-shadow: 0 4px 12px -5px rgba(5,150,105,0.6) !important;
  }
  .q-btn.btn-claro {
    background: var(--superficie) !important; color: var(--tinta-media) !important;
    border: 1px solid var(--borde) !important; box-shadow: var(--sombra) !important;
  }
  .q-btn.btn-claro:hover { background: #F8FAFC !important; }
  .q-btn.btn-banda {
    background: rgba(255,255,255,0.15) !important; color: #FFFFFF !important;
    border: 1px solid rgba(255,255,255,0.3) !important;
  }

  /* --- Riel de navegacion ---
     Se dibuja a mano en lugar de usar q-tabs vertical: las clases de utilidad
     de Quasar (row/no-wrap) ganan en especificidad y deforman el riel. */
  .riel-item {
    display: flex; align-items: center; gap: 11px;
    width: 100%; box-sizing: border-box;
    padding: 9px 11px; margin-bottom: 2px;
    border-radius: 8px; cursor: pointer;
    font-size: 0.82rem; color: #9FB0CE;
    border-left: 2px solid transparent;
    transition: background 150ms ease, color 150ms ease;
  }
  .riel-item:hover { background: rgba(255,255,255,0.06); color: #E2E8F0; }
  .riel-item.activo {
    background: rgba(93,143,232,0.20); color: #FFFFFF; font-weight: 500;
    border-left: 2px solid #60A5FA;
  }
  .riel-rotulo { font-size: 0.6rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.11em; color: #64769B; }

  /* --- Tablas --- */
  .q-table__container { box-shadow: none !important; background: transparent; }
  .q-table thead th {
    font-size: 0.66rem !important; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.07em;
    color: #475569 !important; background: #F4F7FD;
    border-bottom: 1px solid #DDE4F1 !important;
    padding-top: 9px; padding-bottom: 9px;
  }
  .q-table thead th:first-child { border-radius: 8px 0 0 0; }
  .q-table thead th:last-child { border-radius: 0 8px 0 0; }
  .q-table tbody td { font-size: 0.8rem; color: var(--tinta-media); border-bottom: 1px solid var(--borde-suave) !important; }
  .q-table tbody tr:hover { background: #F8FAFF; }
  .q-table__bottom { border-top: 1px solid var(--borde); font-size: 0.74rem; color: var(--tinta-tenue); }

  /* --- Campos --- */
  .q-field__control { border-radius: 7px !important; background: var(--superficie); }
  .q-field--outlined .q-field__control:before { border: 1px solid var(--borde) !important; }
  .q-field--outlined.q-field--focused .q-field__control:after { border-color: var(--marca) !important; }

  .ag-theme-balham { --ag-font-family: var(--sans); --ag-font-size: 12px; }

  .medidor { height: 6px; background: #E6EBF5; border-radius: 9999px; overflow: hidden; }
  .medidor > span { display: block; height: 100%; border-radius: 9999px; }
</style>
"""


def cargar_tema() -> None:
    """Alinea la paleta de Quasar con la de marca y carga la hoja del sistema."""
    ui.colors(
        primary=MARCA,
        secondary=TINTA_TENUE,
        accent='#6D28D9',
        dark=TINTA,
        positive='#047857',
        negative='#C01048',
        warning='#B45309',
        info='#1D4ED8',
    )
    ui.add_head_html(HOJA)


def etiqueta(texto: str, tono: str = 'neutro', punto: bool = True) -> ui.html:
    fondo, letra, borde = TONOS.get(tono, TONOS['neutro'])
    marca = f'<span class="punto" style="background:{letra}"></span>' if punto else ''
    return ui.html(
        f'<span class="tag" style="background:{fondo};color:{letra};border-color:{borde}">'
        f'{marca}{html.escape(texto)}</span>'
    )


def ficha_icono(icono: str, tono: str = 'azul', tam: str = '17px') -> None:
    fondo, letra, borde = TONOS.get(tono, TONOS['azul'])
    ui.html(
        f'<div class="ficha" style="background:{fondo};border:1px solid {borde}">'
        f'<span class="material-icons" style="font-size:{tam};color:{letra}">{icono}</span></div>'
    )


def medidor(valor: int, tono: str = 'neutro') -> ui.html:
    _, letra, _ = TONOS.get(tono, TONOS['neutro'])
    return ui.html(
        f'<div class="medidor"><span style="width:{max(0, min(100, valor))}%;'
        f'background:{letra}"></span></div>'
    )


def kpi(valor: str, rotulo: str, nota: str = '', tono: str = 'azul', icono: str = '') -> None:
    """Tarjeta de cifra en tinte suave. El tono codifica la lectura del dato."""
    fondo, letra, borde = TONOS.get(tono, TONOS['azul'])
    with ui.column().classes('kpi gap-1.5 flex-1 min-w-[170px]').style(
        f'background:{fondo};border-color:{borde}'
    ):
        with ui.row().classes('items-center justify-between w-full'):
            ui.html(f'<span class="rotulo" style="color:{letra};opacity:0.85">{html.escape(rotulo)}</span>')
            if icono:
                ui.html(
                    f'<span class="material-icons" style="font-size:18px;color:{letra};'
                    f'opacity:0.7">{icono}</span>'
                )
        ui.html(f'<span class="kpi-cifra" style="color:{letra}">{html.escape(valor)}</span>')
        if nota:
            ui.html(
                f'<span style="font-size:0.74rem;color:{letra};opacity:0.8">{html.escape(nota)}</span>'
            )


@contextmanager
def tarjeta(tono_acento: str | None = 'azul', relleno: str = 'p-5') -> Iterator[None]:
    """Tarjeta blanca con franja de acento al tope."""
    with ui.column().classes('tarjeta w-full gap-0 overflow-hidden'):
        if tono_acento:
            _, letra, _ = TONOS.get(tono_acento, TONOS['azul'])
            ui.html(f'<div class="acento" style="background:{letra}"></div>')
        with ui.column().classes(f'w-full gap-3 {relleno}'):
            yield


def cabecera_seccion(titulo: str, apoyo: str = '', icono: str = '', tono: str = 'azul') -> None:
    with ui.row().classes('items-center gap-2.5 w-full'):
        if icono:
            ficha_icono(icono, tono)
        with ui.column().classes('gap-0'):
            ui.html(f'<p class="titulo-seccion">{html.escape(titulo)}</p>')
            if apoyo:
                ui.html(f'<p class="meta">{html.escape(apoyo)}</p>')


@contextmanager
def banda(titulo: str, bajada: str = '', rotulo: str = '') -> Iterator[None]:
    """Encabezado de pantalla. Lo que se abra dentro va a la derecha, sobre el color."""
    with ui.row().classes('banda w-full items-end justify-between gap-6'):
        with ui.column().classes('gap-1 relative'):
            if rotulo:
                ui.html(f'<span class="rotulo">{html.escape(rotulo)}</span>')
            ui.html(f'<h1 class="titulo-pagina">{html.escape(titulo)}</h1>')
            if bajada:
                ui.html(f'<p class="meta" style="max-width:82ch">{html.escape(bajada)}</p>')
        with ui.row().classes('gap-2 shrink-0 relative'):
            yield


def boton(texto: str, al_click, icono: str = '', estilo: str = 'primario') -> ui.button:
    """color=None evita que NiceGUI marque el boton con bg-primary/text-white,
    que ganan sobre las clases propias y aplanan el estilo del sistema."""
    clases = {
        'primario': 'btn-primario',
        'exito': 'btn-exito',
        'claro': 'btn-claro',
        'banda': 'btn-banda',
    }[estilo]
    b = ui.button(texto, on_click=al_click, color=None).classes(
        f'{clases} px-4 py-2 text-sm'
    ).props('unelevated no-caps')
    if icono:
        b.props(f'icon={icono}')
    return b
