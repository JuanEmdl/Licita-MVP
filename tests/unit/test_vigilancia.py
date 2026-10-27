"""Vigilancia de SECOP II: afinidad con el portafolio y filtro de consulta (sin red)."""
from datetime import datetime

from src.worker_vigilance.afinidad import PerfilPortafolio, calcular_afinidad, terminos_tecnologia
from src.worker_vigilance.sync.secop_sync import construir_filtro, normalizar_proceso

PORTAFOLIO = [
    {"tecnologia": "EJEMPLO - Python / FastAPI", "categoria": "Desarrollo", "descripcion": "APIs REST con Python."},
    {"tecnologia": "ISO/IEC 27001", "categoria": "Certificación", "descripcion": "Seguridad de la información."},
    {"tecnologia": "Experiencia sector público", "categoria": "Experiencia",
     "descripcion": "Contratos de desarrollo de software a la medida."},
]


def perfil():
    return PerfilPortafolio.desde_capacidades(PORTAFOLIO)


def test_terminos_de_tecnologia():
    assert terminos_tecnologia("EJEMPLO - Python / FastAPI") == ["python", "fastapi"]
    # Sin espacios alrededor de la barra es un solo término: no se busca "iso" suelto.
    assert terminos_tecnologia("ISO/IEC 27001") == ["iso/iec 27001"]


def test_la_experiencia_no_se_busca_como_tecnologia():
    assert "experiencia sector publico" not in perfil().tecnologias


def test_proceso_de_software_supera_a_uno_que_no_lo_es():
    software = calcular_afinidad("Desarrollo de software a la medida en Python para el portal web", perfil())
    laboratorio = calcular_afinidad(
        "Servicios de laboratorio bajo la norma ISO/IEC 17025 y aplicación de métodos", perfil())
    sillas = calcular_afinidad("Compra de sillas para la oficina de sistemas", perfil())
    assert software.puntaje >= 60
    assert "python" in software.coincidencias
    assert laboratorio.puntaje == 0
    assert sillas.puntaje == 0


def test_tildes_y_mayusculas_no_afectan():
    a = calcular_afinidad("PLATAFORMA TECNOLÓGICA Y SISTEMA DE INFORMACIÓN", perfil())
    b = calcular_afinidad("plataforma tecnologica y sistema de informacion", perfil())
    assert a.puntaje == b.puntaje > 0


def test_un_termino_contenido_en_otro_no_suma_dos_veces():
    r = calcular_afinidad("Rediseño del portal web institucional", perfil())
    assert "portal web" in r.coincidencias and "web" not in r.coincidencias


def test_filtro_soql():
    filtro = construir_filtro(7, ["SOFTWARE", "o'reilly"], hoy=datetime(2026, 10, 19))
    assert "fecha_de_publicacion_del >= '2026-10-12T00:00:00'" in filtro
    assert "estado_del_procedimiento in ('Publicado', 'Abierto')" in filtro
    assert "like '%SOFTWARE%'" in filtro
    assert "O''REILLY" in filtro  # comillas escapadas


def test_normalizar_proceso():
    p = normalizar_proceso({
        "id_del_proceso": "CO1.REQ.1", "nombre_del_procedimiento": "Plataforma",
        "descripci_n_del_procedimiento": "No definido", "precio_base": "1000",
        "urlproceso": {"url": "https://community.secop.gov.co/x"},
        "fecha_de_publicacion_del": "2026-10-16T00:00:00.000",
    })
    assert p["objeto"] == "Plataforma"  # sin descripción se usa el nombre
    assert p["precio_base"] == 1000.0
    assert p["url_proceso"].startswith("https://")
    assert p["fecha_publicacion"] == datetime(2026, 10, 16)
