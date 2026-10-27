"""
Monitoreo de oportunidades y expediente documental (RF-011 a RF-015, RF-018, RF-019,
RF-021 a RF-023; HU-02, HU-04, HU-05 CA-02 y CA-04; Tabla 61). Sin red ni PostgreSQL:
SECOP II es un cliente falso y la base es SQLite en memoria.
"""
import io
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.api.middleware.auth as auth_mod
from src.shared.config import Configuracion
from src.shared.expediente_repo import DocumentoNoAdmitidoError, EstadoDocumento, RepositorioExpediente
from src.shared.lectura_documentos import leer_documento
from src.shared.models import (
    AlertaOportunidad, Carpeta, CarpetaOportunidad, CoincidenciaPerfil, DocumentoExpediente, Licitacion,
    NotaOportunidad, NovedadProceso, Oportunidad, Notificacion, PerfilBusqueda, PreferenciaNotificacion, SeguimientoProceso, Sincronizacion, TareaAnalisis,
)
from src.shared.oportunidades_repo import RepositorioOportunidades
from src.shared.perfiles_repo import PerfilNoEncontradoError, RepositorioPerfiles
from src.shared.roles import ADMINISTRADOR, ANALISTA, GERENTE
from src.worker_analysis.orchestrator.graph import completar_referencia
from src.worker_analysis.pipeline.segmentador import SegmentadorDocumental, marca_documento
from src.worker_vigilance.detector import TipoNovedad, cambios_documentos, cambios_proceso
from src.worker_vigilance.perfiles import coincide, terminos_de_perfiles
from src.worker_vigilance.sync.secop_sync import DescargaNoDisponibleError, normalizar_documento

TABLAS = [Licitacion, TareaAnalisis, Oportunidad, SeguimientoProceso, NovedadProceso, DocumentoExpediente,
          PerfilBusqueda, CoincidenciaPerfil, Sincronizacion, AlertaOportunidad, Notificacion, PreferenciaNotificacion,
          Carpeta, CarpetaOportunidad, NotaOportunidad]


def proceso(id_proceso="CO1.REQ.1", **campos):
    base = {"id_proceso": id_proceso, "id_portafolio": f"BDOS-{id_proceso}", "referencia": "LP-001",
            "entidad": "Alcaldía de Medellín", "nombre": "Plataforma de gestión documental",
            "objeto": "Desarrollo de software para la gestión documental en la nube",
            "modalidad": "Licitación pública", "precio_base": 850_000_000.0, "departamento": "Antioquia",
            "ciudad": "Medellín", "fase": "Presentación de oferta", "estado": "Publicado",
            "fecha_publicacion": datetime(2026, 10, 20), "fecha_cierre": datetime(2026, 11, 5),
            "url_proceso": "https://community.secop.gov.co/x", "actualizado_en_fuente": datetime(2026, 10, 20)}
    return {**base, **campos}


@pytest.fixture
def fabrica():
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for tabla in TABLAS:
        tabla.__table__.create(motor)
    # Igual que en producción (SessionLocal): los objetos expiran al confirmar.
    return sessionmaker(bind=motor)


# --- Detector de cambios (RF-019) ---

def test_detecta_cambios_de_estado_y_fechas_pero_no_valores_que_dejan_de_publicarse():
    cambios = cambios_proceso(proceso(), proceso(estado="Cerrado", fecha_cierre=datetime(2026, 11, 12), fase=None))
    assert {(c["tipo"], c["campo"]) for c in cambios} == {(TipoNovedad.ESTADO, "Estado del procedimiento"),
                                                          (TipoNovedad.FECHAS, "Fecha de cierre")}
    assert cambios_proceso(proceso(), proceso()) == []
    # Completar un dato que no se tenía no es un cambio, salvo publicar la fecha de cierre.
    sin_fechas = proceso(fecha_publicacion=None, fecha_cierre=None)
    assert [c["campo"] for c in cambios_proceso(sin_fechas, proceso())] == ["Fecha de cierre"]


def test_documentos_nuevos_retirados_y_posible_cambio_de_requisitos():
    conocidos = [{"id_documento_fuente": "1", "nombre": "Estudios previos.pdf"},
                 {"id_documento_fuente": "2", "nombre": "Formato 1.docx"}]
    publicados = [{"id_documento_fuente": "1", "nombre": "Estudios previos.pdf"},
                  {"id_documento_fuente": "3", "nombre": "Adenda No. 1.pdf"}]
    cambios = cambios_documentos(conocidos, publicados)
    assert {"tipo": TipoNovedad.DOCUMENTOS, "campo": "Documento publicado", "antes": None,
            "despues": "Adenda No. 1.pdf"} in cambios
    assert any(c["tipo"] == TipoNovedad.REQUISITOS for c in cambios)  # una adenda puede cambiar los requisitos
    assert any(c["campo"] == "Documento retirado de la fuente" and c["antes"] == "Formato 1.docx" for c in cambios)
    assert cambios_documentos(conocidos, []) == []  # una respuesta vacía de la fuente no retira todo


# --- Perfiles de búsqueda (RF-015) ---

def test_un_proceso_coincide_con_un_perfil_segun_todos_sus_criterios():
    perfil = {"palabras_clave": ["gestión documental", "ERP"], "departamentos": ["Antioquia"],
              "modalidades": ["Licitación"], "cuantia_min": 100_000_000, "cuantia_max": 1_000_000_000}
    assert coincide(perfil, proceso())
    assert not coincide(perfil, proceso(departamento="Cundinamarca"))
    assert not coincide(perfil, proceso(precio_base=50_000_000))
    assert not coincide(perfil, proceso(nombre="Compra de sillas", objeto="Mobiliario"))
    assert not coincide({**perfil, "entidades": ["Gobernación"]}, proceso())
    # Sin tildes ni mayúsculas en el perfil o en el proceso.
    assert coincide({"palabras_clave": ["GESTION DOCUMENTAL"]}, proceso())
    assert {"gestión documental", "gestion documental"} <= set(terminos_de_perfiles([perfil]))


# --- Lectura de documentos (RF-022, RF-023) ---

def _docx(cuerpo: str) -> bytes:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    archivo = io.BytesIO()
    with zipfile.ZipFile(archivo, "w") as z:
        z.writestr("word/document.xml", f'<w:document {w}><w:body>{cuerpo}</w:body></w:document>')
    return archivo.getvalue()


def _p(texto: str, salto: bool = False) -> str:
    br = '<w:r><w:br w:type="page"/></w:r>' if salto else ""
    return f"<w:p>{br}<w:r><w:t>{texto}</w:t></w:r></w:p>"


def test_lee_pdf_por_paginas():
    from src.worker_analysis.reports.pdf import DocumentoPDF

    pdf = DocumentoPDF("Pliego de condiciones")
    pdf.parrafo("3.2 CAPACIDAD FINANCIERA. El proponente deberá acreditar un índice de liquidez mayor o igual a 1,5.")
    pdf._nueva_pagina()
    pdf.parrafo("4.1 EXPERIENCIA. Tres contratos de desarrollo de software ejecutados en los últimos cinco años.")
    lectura = leer_documento("pliego.pdf", pdf.bytes())
    assert not lectura.ilegible and len(lectura.paginas) == 2
    assert "liquidez" in lectura.paginas[0] and "Tres contratos" in lectura.paginas[1]


def test_lee_docx_con_tablas_y_saltos_de_pagina():
    tabla = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Indicador</w:t></w:r></w:p></w:tc>"
             "<w:tc><w:p><w:r><w:t>Mínimo</w:t></w:r></w:p></w:tc></w:tr>"
             "<w:tr><w:tc><w:p><w:r><w:t>Liquidez</w:t></w:r></w:p></w:tc>"
             "<w:tc><w:p><w:r><w:t>1,5</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
    contenido = _docx(_p("3. REQUISITOS HABILITANTES") + tabla + _p("4. EXPERIENCIA del proponente en software", True)
                      + _p("El proponente acreditará tres contratos de desarrollo de software."))
    lectura = leer_documento("anexo.docx", contenido)
    assert len(lectura.paginas) == 2
    assert "Liquidez | 1,5" in lectura.paginas[0] and "tres contratos" in lectura.paginas[1]


def test_formato_no_admitido_o_sin_texto_es_ilegible():
    assert leer_documento("plano.dwg", b"x").ilegible
    escaneado = leer_documento("escaneado.txt", b"   \n  ")
    assert escaneado.ilegible and "texto" in escaneado.motivo
    assert leer_documento("danado.pdf", b"%PDF-1.4 basura").ilegible


def test_normaliza_el_registro_de_documentos_de_datos_abiertos():
    d = normalizar_documento({"id_documento": "851844516", "nombre_archivo": "1.EstudioPrevio.pdf",
                              "extensi_n": "pdf", "tamanno_archivo": "204683", "fecha_carga": "2026-01-18T19:00:00.000",
                              "url_descarga_documento": {"url": "https://community.secop.gov.co/a"}})
    assert d == {"id_documento_fuente": "851844516", "nombre": "1.EstudioPrevio.pdf", "extension": "pdf",
                 "tamano_bytes": 204683, "publicado_en": datetime(2026, 1, 18, 19), "url_fuente": "https://community.secop.gov.co/a"}


# --- Segmentador (RF-023, HU-05 CA-02 y CA-04) ---

def test_cada_fragmento_conserva_documento_version_pagina_y_seccion():
    contenido = (marca_documento("Pliego.pdf", 2, "Carga manual por ana@x.co") + "\n[Página 1]\n"
                 "3.2 CAPACIDAD FINANCIERA\nEl proponente deberá acreditar los siguientes indicadores:\n"
                 "Indicador | Mínimo\nLiquidez | 1,5\n[Página 2]\nEndeudamiento | 60 %\n\n"
                 "4. EXPERIENCIA\nTres contratos de desarrollo de software.")
    fragmentos = SegmentadorDocumental(chunk_size=4000).segmentar_con_metadatos(contenido, {})
    assert len(fragmentos) == 1
    f = fragmentos[0]
    assert (f.documento, f.version, f.procedencia, f.paginas) == ("Pliego.pdf", "2", "Carga manual por ana@x.co", [1, 2])
    assert "Páginas: 1-2" in f.texto and "Sección: 3.2 CAPACIDAD FINANCIERA" in f.texto
    # La tabla que sigue en la página 2 no se parte y queda con el título que la introduce.
    assert ("(Tabla de la sección 3.2 CAPACIDAD FINANCIERA)\nIndicador | Mínimo\nLiquidez | 1,5\n[Página 2]\n"
            "Endeudamiento | 60 %") in f.texto


def test_la_tabla_no_se_parte_aunque_el_fragmento_se_llene():
    filas = "\n".join(f"Perfil {i} | Ingeniero | {i} años" for i in range(30))
    contenido = (marca_documento("Anexo técnico.docx", 1, "SECOP II") + "\n[Página 7]\n5.1 EQUIPO MÍNIMO\n"
                 + "Texto introductorio del equipo. " * 20 + "\n\n" + filas)
    fragmentos = SegmentadorDocumental(chunk_size=1200, chunk_overlap=100).segmentar_con_metadatos(contenido, {})
    con_tabla = [f for f in fragmentos if "Perfil 0 |" in f.texto]
    assert len(con_tabla) == 1 and "Sección: 5.1 EQUIPO MÍNIMO" in con_tabla[0].texto
    # Una tabla más grande que un fragmento se reparte por filas repitiendo el encabezado.
    grande = SegmentadorDocumental(chunk_size=400, chunk_overlap=50).segmentar_con_metadatos(contenido, {})
    assert all("Perfil 0 | Ingeniero" in f.texto for f in grande if "(continúa la tabla)" in f.texto)


def test_sin_marcas_se_comporta_como_antes_y_sin_referencia_se_descarta():
    segmentador = SegmentadorDocumental()
    fragmentos = segmentador.segmentar("PLIEGO DE CONDICIONES:\nEl proponente deberá tener ISO 27001.",
                                       {"documento": "storage/secop/P1", "version": "1.0"})
    assert len(fragmentos) == 1 and "Documento Origen: storage/secop/P1" in fragmentos[0]
    assert segmentador.segmentar("texto sin ninguna referencia de origen", {"documento": ""}) == []
    assert segmentador.descartados and "sin referencia" in segmentador.descartados[0]["motivo"]


def test_la_referencia_se_completa_con_documento_y_pagina():
    contenido = (marca_documento("Pliego.pdf", 3, "SECOP II") + "\n[Página 14]\n3.2 CAPACIDAD FINANCIERA\n"
                 "Índice de liquidez mayor o igual a 1,5.\n\n[Página 15]\n4.1 EXPERIENCIA\n"
                 "Tres contratos de desarrollo de software con entidades públicas.")
    fragmento = SegmentadorDocumental().segmentar(contenido, {})[0]
    assert completar_referencia("Numeral 4.1", "Tres contratos de desarrollo de software", fragmento) == \
        "Pliego.pdf (v3) · Numeral 4.1, página 15"
    assert completar_referencia("Página 14", "Índice de liquidez", fragmento) == "Pliego.pdf (v3) · Página 14"
    sin_paginas = SegmentadorDocumental().segmentar("PLIEGO DE CONDICIONES:\nISO 27001.", {"documento": "P1"})[0]
    assert completar_referencia("Numeral 1", "ISO 27001", sin_paginas) == "Numeral 1"


# --- Sincronización, búsqueda, seguimiento y novedades (RF-012 a RF-014, RF-018, RF-019) ---

def test_la_sincronizacion_no_duplica_y_conserva_fuente_y_fecha(fabrica):
    repo = RepositorioOportunidades(fabrica)
    assert repo.guardar_lote([proceso(), proceso("CO1.REQ.2")], "SECOP II · Datos Abiertos (p6dx-8zbt)")["nuevos"] == 2
    segunda = repo.guardar_lote([proceso(), proceso("CO1.REQ.2")], "SECOP II · Datos Abiertos (p6dx-8zbt)")
    assert (segunda["nuevos"], segunda["actualizados"]) == (0, 2)
    o = repo.obtener("CO1.REQ.1")
    assert o["fuente"] == "SECOP II · Datos Abiertos (p6dx-8zbt)" and o["sincronizada_en"]
    assert repo.buscar()["total"] == 2


def test_busqueda_por_palabras_clave_y_filtros(fabrica):
    repo = RepositorioOportunidades(fabrica)
    repo.guardar_lote([
        proceso(),
        proceso("CO1.REQ.2", nombre="Mesa de ayuda", objeto="Soporte técnico y mesa de ayuda", departamento="Bogotá D.C.",
                ciudad="Bogotá", entidad="Ministerio TIC", precio_base=90_000_000.0, modalidad="Mínima cuantía",
                fecha_publicacion=datetime(2026, 9, 1), fecha_cierre=datetime(2026, 9, 10), estado="Cerrado"),
    ], "SECOP II")
    ids = lambda r: [o["id_proceso"] for o in r["oportunidades"]]  # noqa: E731
    assert ids(repo.buscar(q="GESTIÓN nube")) == ["CO1.REQ.1"]  # todas las palabras, sin tildes
    assert ids(repo.buscar(q="ayuda soporte")) == ["CO1.REQ.2"]
    assert ids(repo.buscar(entidad="ministerio")) == ["CO1.REQ.2"]
    assert ids(repo.buscar(departamento="Antioquia", ciudad="medell")) == ["CO1.REQ.1"]
    assert ids(repo.buscar(modalidad="Mínima cuantía")) == ["CO1.REQ.2"]
    assert ids(repo.buscar(cuantia_min=100_000_000)) == ["CO1.REQ.1"]
    assert ids(repo.buscar(cuantia_max=100_000_000)) == ["CO1.REQ.2"]
    assert ids(repo.buscar(publicada_desde=datetime(2026, 10, 1))) == ["CO1.REQ.1"]
    assert ids(repo.buscar(cierre_hasta=datetime(2026, 9, 10))) == ["CO1.REQ.2"]
    assert ids(repo.buscar(estado="Cerrado")) == ["CO1.REQ.2"]
    assert "Antioquia" in repo.opciones_filtro()["departamentos"]


def test_solo_los_procesos_seguidos_registran_novedades(fabrica):
    repo = RepositorioOportunidades(fabrica)
    repo.guardar_lote([proceso(), proceso("CO1.REQ.2")], "SECOP II")
    repo.seguir("CO1.REQ.1", "ana@x.co", asignar_responsable=True)
    resultado = repo.guardar_lote([proceso(estado="Cerrado"), proceso("CO1.REQ.2", estado="Cerrado")], "SECOP II")
    assert [(n["id_proceso"], n["despues"]) for n in resultado["novedades"]] == [("CO1.REQ.1", "Cerrado")]
    o = repo.obtener("CO1.REQ.1", "ana@x.co")
    assert o["seguida"] and o["novedades_sin_revisar"] == 1 and o["responsable"] == "ana@x.co"
    assert repo.obtener("CO1.REQ.1", "otro@x.co")["seguida"] is False  # el seguimiento es por usuario
    assert [x["id_proceso"] for x in repo.buscar(usuario="ana@x.co", con_novedades=True)["oportunidades"]] == ["CO1.REQ.1"]
    assert repo.novedades("CO1.REQ.1", "ana@x.co")[0]["nueva"] is True
    repo.marcar_revisadas("CO1.REQ.1", "ana@x.co")
    assert repo.obtener("CO1.REQ.1", "ana@x.co")["novedades_sin_revisar"] == 0
    assert repo.buscar(usuario="ana@x.co", con_novedades=True)["total"] == 0
    repo.dejar_de_seguir("CO1.REQ.1", "ana@x.co")
    assert repo.seguidos() == []


def test_con_la_fuente_caida_se_avisa_y_se_muestra_la_ultima_sincronizacion_exitosa(fabrica):
    repo = RepositorioOportunidades(fabrica)
    assert repo.estado_sincronizacion(26)["desactualizada"]  # nunca sincronizado
    repo.registrar_sincronizacion(datetime.utcnow() - timedelta(minutes=5), "Exitosa", procesos=10)
    assert repo.estado_sincronizacion(26)["desactualizada"] is False
    repo.registrar_sincronizacion(datetime.utcnow(), "Fallida", mensaje="ConnectError: sin red")
    estado = repo.estado_sincronizacion(26)
    assert estado["desactualizada"] and "falló" in estado["aviso"] and "última sincronización exitosa" in estado["aviso"]
    assert estado["ultima_exitosa"]["procesos"] == 10


# --- Expediente documental (RF-011, RF-021, RF-022) ---

@pytest.fixture
def expediente(fabrica, tmp_path):
    RepositorioOportunidades(fabrica).guardar_lote([proceso()], "SECOP II")
    return RepositorioExpediente(fabrica, directorio=str(tmp_path), max_mb=1)


PUBLICADOS = [{"id_documento_fuente": str(i), "nombre": n, "url_fuente": f"https://secop/{i}",
               "publicado_en": datetime(2026, 10, 20)} for i, n in
              enumerate(["Estudios previos.pdf", "Pliego.pdf", "Anexo técnico.docx", "Formato.xlsx"], start=1)]


def test_lo_que_la_fuente_no_entrega_queda_como_faltante_con_su_motivo(expediente):
    intentos = []

    def descargar(url, maximo):
        intentos.append(url)
        raise DescargaNoDisponibleError("SECOP II no entregó el archivo a la descarga automática (HTTP 403).")

    resumen = expediente.registrar_publicados("CO1.REQ.1", PUBLICADOS, "SECOP II · Datos Abiertos (dmgg-8hin)", descargar)
    assert resumen["nuevos"] == 4 and resumen[EstadoDocumento.FALTANTE] == 4
    assert len(intentos) == 3  # tras tres rechazos seguidos no se insiste con el resto
    vista = expediente.expediente("CO1.REQ.1")
    assert vista["faltantes"] == ["Estudios previos.pdf", "Pliego.pdf", "Anexo técnico.docx", "Formato.xlsx"]
    assert all("HTTP 403" in d["motivo"] and "Cárguelo manualmente" in d["motivo"] for d in vista["documentos"])
    # Una segunda sincronización no los duplica.
    assert expediente.registrar_publicados("CO1.REQ.1", PUBLICADOS, "SECOP II", descargar)["nuevos"] == 0


def test_documento_descargado_queda_disponible_con_huella(expediente):
    resumen = expediente.registrar_publicados(
        "CO1.REQ.1", PUBLICADOS[:1], "SECOP II", lambda url, maximo: "Requisito: ISO 27001 vigente. ".encode() * 5)
    assert resumen[EstadoDocumento.DISPONIBLE] == 0 and resumen[EstadoDocumento.ILEGIBLE] == 1  # .pdf con texto plano
    resumen = expediente.registrar_publicados(
        "CO1.REQ.1", [{**PUBLICADOS[0], "id_documento_fuente": "9", "nombre": "Ficha.txt"}], "SECOP II",
        lambda url, maximo: "Requisito: ISO 27001 vigente. ".encode() * 5)
    assert resumen[EstadoDocumento.DISPONIBLE] == 1
    documento = next(d for d in expediente.expediente("CO1.REQ.1")["documentos"] if d["nombre"] == "Ficha.txt")
    assert documento["huella_sha256"] and documento["obtenido_en"] and documento["tiene_archivo"]


def test_carga_manual_registra_procedencia_y_version(expediente):
    expediente.registrar_publicados("CO1.REQ.1", PUBLICADOS[1:2], "SECOP II", None)
    faltante = expediente.expediente("CO1.REQ.1")["documentos"][0]
    assert faltante["estado"] == EstadoDocumento.FALTANTE and "desactivada" in faltante["motivo"]

    texto = "3.2 CAPACIDAD FINANCIERA\nÍndice de liquidez mayor o igual a 1,5 para todos los proponentes."
    v1 = expediente.cargar_manual("CO1.REQ.1", "Pliego.txt", texto.encode(), "ana@x.co", reemplaza_id=faltante["id"],
                                  nota="descargado del portal")
    assert (v1["version"], v1["estado"]) == (1, EstadoDocumento.DISPONIBLE)  # un faltante nunca tuvo versión
    assert v1["procedencia"] == "Carga manual por ana@x.co (descargado del portal)"
    v2 = expediente.cargar_manual("CO1.REQ.1", "Pliego.txt", (texto + " Adenda 1.").encode(), "ana@x.co")
    assert v2["version"] == 2
    vista = expediente.expediente("CO1.REQ.1")
    assert [d["version"] for d in vista["documentos"]] == [2] and len(vista["historico"]) == 2
    assert vista["completo"] and vista["faltantes"] == []
    analisis = expediente.contenido_para_analisis("CO1.REQ.1")
    assert analisis["documentos"][0]["version"] == 2 and "Adenda 1" in analisis["documentos"][0]["paginas"][0]
    assert expediente.huellas_vigentes("CO1.REQ.1") == [v2["huella_sha256"]]


def test_la_carga_manual_rechaza_formatos_y_tamanos_no_admitidos(expediente):
    with pytest.raises(DocumentoNoAdmitidoError, match="formato"):
        expediente.cargar_manual("CO1.REQ.1", "plano.exe", b"MZ", "ana@x.co")
    with pytest.raises(DocumentoNoAdmitidoError, match="1 MB"):
        expediente.cargar_manual("CO1.REQ.1", "grande.txt", b"x" * (1024 * 1024 + 1), "ana@x.co")
    ilegible = expediente.cargar_manual("CO1.REQ.1", "escaneado.txt", b" ", "ana@x.co")
    assert ilegible["estado"] == EstadoDocumento.ILEGIBLE
    assert expediente.expediente("CO1.REQ.1")["ilegibles"] == ["escaneado.txt"]


# --- Perfiles: alcance por propietario (Tabla 61) y coincidencias únicas (HU-04 CA-02) ---

def test_cada_usuario_ve_y_modifica_solo_sus_perfiles(fabrica):
    repo = RepositorioPerfiles(fabrica)
    propio = repo.crear("ana@x.co", {"nombre": "Software", "palabras_clave": ["software"]})
    repo.crear("otro@x.co", {"nombre": "Ajeno", "palabras_clave": ["nube"]})
    assert [p["nombre"] for p in repo.listar("ana@x.co")] == ["Software"]
    with pytest.raises(PerfilNoEncontradoError):
        repo.actualizar(propio["id"], "otro@x.co", {"activo": False})
    assert repo.actualizar(propio["id"], "ana@x.co", {"activo": False})["activo"] is False
    assert [p["nombre"] for p in repo.activos()] == ["Ajeno"]


def test_un_proceso_coincide_una_sola_vez_con_cada_perfil(fabrica):
    RepositorioOportunidades(fabrica).guardar_lote([proceso()], "SECOP II")
    repo = RepositorioPerfiles(fabrica)
    perfil = repo.crear("ana@x.co", {"nombre": "Software", "palabras_clave": ["software"]})
    assert len(repo.registrar_coincidencias([(perfil["id"], "CO1.REQ.1")])) == 1
    assert repo.registrar_coincidencias([(perfil["id"], "CO1.REQ.1")]) == []
    coincidencia = repo.coincidencias("ana@x.co")[0]
    assert (coincidencia["entidad"], coincidencia["fecha_cierre"]) == ("Alcaldía de Medellín", "2026-11-05T00:00:00")
    assert repo.coincidencias("otro@x.co") == []


# --- Barrido y radicación con un SECOP II falso ---

class SecopFalso:
    fuente = "SECOP II · Datos Abiertos (p6dx-8zbt)"
    fuente_documentos = "SECOP II · Datos Abiertos (dmgg-8hin)"

    def __init__(self):
        self.procesos = [proceso(), proceso("CO1.REQ.2", nombre="Compra de sillas", objeto="Mobiliario de oficina")]
        self.seguido = proceso("CO1.REQ.9", fecha_publicacion=datetime(2026, 1, 1))
        self.archivos = {"BDOS-CO1.REQ.9": [PUBLICADOS[0]]}
        self.falla = None

    def procesos_recientes(self, dias, terminos, maximo):
        if self.falla:
            raise self.falla
        self.terminos = list(terminos)
        return list(self.procesos)

    def procesos_por_id(self, ids):
        return [self.seguido] if "CO1.REQ.9" in ids else []

    def documentos(self, id_portafolio):
        return list(self.archivos.get(id_portafolio, []))

    def proceso(self, identificador):
        return self.seguido if "9" in identificador else None

    def descargar(self, url, maximo):
        raise DescargaNoDisponibleError("SECOP II no entregó el archivo a la descarga automática (HTTP 403).")


@pytest.fixture
def vigilancia(fabrica, tmp_path, monkeypatch):
    import src.worker_analysis.reports.auditoria as auditoria_mod
    import src.worker_vigilance.servicio as servicio_mod

    @contextmanager
    def get_db():
        with fabrica() as db:
            yield db

    class PortafolioVacio:
        def __init__(self, db):
            pass

        def listar(self):
            return []

    class AuditoriaNula:
        def registrar_evento(self, *args, **kwargs):
            pass

    monkeypatch.setattr(servicio_mod, "get_db", get_db)
    monkeypatch.setattr(servicio_mod, "PortfolioRepository", PortafolioVacio)
    monkeypatch.setattr(auditoria_mod, "RegistradorAuditoria", AuditoriaNula)
    from src.shared.notificaciones_repo import RepositorioNotificaciones
    from src.worker_vigilance.notificador import Notificador

    class EnviadorFalso:
        configurado = True

        def __init__(self):
            self.enviados = []

        def enviar(self, destinatario, asunto, texto):
            self.enviados.append((destinatario, asunto, texto))

    notificaciones = RepositorioNotificaciones(fabrica)
    servicio = servicio_mod.ServicioVigilancia(
        cliente=SecopFalso(), usar_modelo=False, oportunidades=RepositorioOportunidades(fabrica),
        expediente=RepositorioExpediente(fabrica, directorio=str(tmp_path)), perfiles=RepositorioPerfiles(fabrica),
        notificaciones=notificaciones,
        notificador=Notificador(notificaciones, EnviadorFalso()))
    return servicio


def test_el_barrido_sincroniza_evalua_perfiles_y_revisa_los_seguidos(vigilancia):
    perfil = vigilancia.perfiles.crear("ana@x.co", {"nombre": "Gestión documental", "palabras_clave": ["documental"]})
    vigilancia.oportunidades.guardar_lote([vigilancia.cliente.seguido], "SECOP II")
    vigilancia.oportunidades.seguir("CO1.REQ.9", "ana@x.co")

    primero = vigilancia.barrer()
    assert primero["estado"] == "completado" and primero["procesos_nuevos"] == 2
    assert "documental" in vigilancia.cliente.terminos  # las palabras de los perfiles entran al filtro
    # Solo los procesos del barrido se contrastan con los perfiles; las sillas no coinciden.
    assert [c["id_proceso"] for c in vigilancia.perfiles.coincidencias("ana@x.co")] == ["CO1.REQ.1"]
    # El seguido fuera de la ventana se revisó por su ID y su expediente quedó registrado.
    assert vigilancia.expediente.expediente("CO1.REQ.9")["faltantes"] == ["Estudios previos.pdf"]
    assert primero["novedades"] == 0  # la primera lectura del expediente no es novedad
    assert (primero["avisos"], primero["correos_enviados"]) == (1, 1)  # RF-017: la coincidencia, a su dueña

    vigilancia.cliente.seguido = proceso("CO1.REQ.9", estado="Adjudicado", fecha_publicacion=datetime(2026, 1, 1))
    vigilancia.cliente.archivos["BDOS-CO1.REQ.9"].append(
        {"id_documento_fuente": "77", "nombre": "Adenda 1.pdf", "url_fuente": "https://secop/77"})
    segundo = vigilancia.barrer()
    tipos = {n["tipo"] for n in vigilancia.oportunidades.novedades("CO1.REQ.9", "ana@x.co")}
    assert segundo["novedades"] == 3 and tipos == {TipoNovedad.ESTADO, TipoNovedad.DOCUMENTOS, TipoNovedad.REQUISITOS}
    assert segundo["coincidencias_perfiles"] == 0  # HU-04 CA-02: no se vuelve a registrar
    assert segundo["avisos"] == 3  # RF-020: cada novedad, a quien sigue el proceso
    assert perfil["id"] in {c["perfil_id"] for c in vigilancia.perfiles.coincidencias("ana@x.co")}


def test_un_barrido_fallido_queda_registrado(vigilancia):
    vigilancia.barrer()
    vigilancia.cliente.falla = ConnectionError("sin red")
    assert vigilancia.barrer()["estado"] == "fallido"
    estado = vigilancia.estado_sincronizacion()
    assert estado["desactualizada"] and estado["ultima"]["estado"] == "Fallida" and estado["ultima_exitosa"]


def test_radicar_recupera_metadatos_y_documentos_o_rechaza_el_enlace(vigilancia):
    from src.worker_vigilance.servicio import ProcesoNoEncontradoError

    with pytest.raises(ProcesoNoEncontradoError, match="no corresponde"):
        vigilancia.radicar("https://community.secop.gov.co/no-existe", "ana@x.co")
    resultado = vigilancia.radicar("CO1.REQ.9", "ana@x.co")
    assert resultado["oportunidad"]["origen_registro"] == "Radicación manual"
    assert resultado["oportunidad"]["responsable"] == "ana@x.co"
    assert resultado["expediente"]["faltantes"] == ["Estudios previos.pdf"]


# --- API: rutas y matriz de la Tabla 61 ---

USUARIOS = {
    "tok-ana": {"user_id": "2", "email": "ana@x.co", "rol": ANALISTA, "roles": [ANALISTA]},
    "tok-beto": {"user_id": "4", "email": "beto@x.co", "rol": ANALISTA, "roles": [ANALISTA]},
    "tok-gerente": {"user_id": "3", "email": "gema@x.co", "rol": GERENTE, "roles": [GERENTE]},
    "tok-admin": {"user_id": "1", "email": "admin@x.co", "rol": ADMINISTRADOR, "roles": [ADMINISTRADOR]},
}


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def cliente(vigilancia, monkeypatch):
    from src.api.main import app
    from src.api.modules.opportunities import router as modulo

    config = replace(Configuracion(), auth_mode="local")
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)
    monkeypatch.setattr(auth_mod, "_validar_local", lambda token, tocar=True: USUARIOS[token])
    eventos = []

    class Auditoria:
        def registrar_evento(self, tarea, evento, detalles, **kwargs):
            eventos.append((evento, detalles))

    app.dependency_overrides[modulo.obtener_servicio_vigilancia] = lambda: vigilancia
    app.dependency_overrides[modulo.obtener_oportunidades] = lambda: vigilancia.oportunidades
    app.dependency_overrides[modulo.obtener_perfiles] = lambda: vigilancia.perfiles
    app.dependency_overrides[modulo.obtener_expediente] = lambda: vigilancia.expediente
    app.dependency_overrides[modulo.obtener_auditoria] = Auditoria
    yield TestClient(app), eventos
    app.dependency_overrides.clear()


def test_api_radicacion_busqueda_y_seguimiento(cliente):
    c, eventos = cliente
    r = c.post("/oportunidades/", json={"identificador": "enlace-que-no-existe"}, headers=_h("tok-ana"))
    assert r.status_code == 404 and "no corresponde" in r.json()["detail"]  # HU-02 CA-04
    assert c.post("/oportunidades/", json={"identificador": "CO1.REQ.9"}, headers=_h("tok-gerente")).status_code == 403
    r = c.post("/oportunidades/", json={"identificador": "CO1.REQ.9"}, headers=_h("tok-ana"))
    assert r.status_code == 201 and r.json()["expediente"]["faltantes"] == ["Estudios previos.pdf"]
    assert eventos[-1][0] == "PROCESO_RADICADO"

    lista = c.get("/oportunidades/", params={"q": "documental", "departamento": "Antioquia"}, headers=_h("tok-gerente"))
    assert lista.status_code == 200 and lista.json()["total"] == 1
    assert lista.json()["sincronizacion"]["desactualizada"]  # aún no hubo barrido exitoso
    assert c.get("/oportunidades/", params={"cuantia_min": 5, "cuantia_max": 1}, headers=_h("tok-ana")).status_code == 422

    assert c.put("/oportunidades/CO1.REQ.9/seguimiento", headers=_h("tok-gerente")).status_code == 403
    assert c.put("/oportunidades/CO1.REQ.9/seguimiento", headers=_h("tok-ana")).json()["seguida"] is True
    assert c.get("/oportunidades/", params={"seguidas": True}, headers=_h("tok-ana")).json()["total"] == 1
    assert c.get("/oportunidades/CO1.REQ.404", headers=_h("tok-ana")).status_code == 404


def test_api_expediente_respeta_la_tabla_61(cliente):
    c, eventos = cliente
    c.post("/oportunidades/", json={"identificador": "CO1.REQ.9"}, headers=_h("tok-ana"))  # ana queda a cargo
    assert c.get("/oportunidades/CO1.REQ.9/expediente", headers=_h("tok-gerente")).status_code == 403
    assert c.get("/oportunidades/CO1.REQ.9/expediente", headers=_h("tok-admin")).status_code == 200
    r = c.get("/oportunidades/CO1.REQ.9/expediente", headers=_h("tok-beto"))
    assert r.status_code == 403 and "ana@x.co" in r.json()["detail"]  # asignada a otra analista

    faltante = c.get("/oportunidades/CO1.REQ.9/expediente", headers=_h("tok-ana")).json()["documentos"][0]
    archivo = ("Estudios previos.txt", b"1. OBJETO\nDesarrollo de software para la gestion documental de la entidad, con soporte.",
               "text/plain")
    r = c.post("/oportunidades/CO1.REQ.9/expediente/documentos", files={"archivo": archivo},
               data={"reemplaza_id": str(faltante["id"]), "nota": "portal SECOP II"}, headers=_h("tok-ana"))
    assert r.status_code == 201 and r.json()["estado"] == "Disponible" and r.json()["version"] == 1
    assert eventos[-1][0] == "DOCUMENTO_CARGADO" and eventos[-1][1]["huella_sha256"]
    assert c.post("/oportunidades/CO1.REQ.9/expediente/documentos", files={"archivo": ("x.exe", b"MZ", "a/b")},
                  headers=_h("tok-ana")).status_code == 422
    assert c.post("/oportunidades/CO1.REQ.9/expediente/documentos", files={"archivo": archivo},
                  headers=_h("tok-admin")).status_code == 403  # el administrador solo consulta
    descarga = c.get(f"/oportunidades/CO1.REQ.9/expediente/documentos/{r.json()['id']}/archivo", headers=_h("tok-ana"))
    assert descarga.status_code == 200 and descarga.headers["x-huella-sha256"] == r.json()["huella_sha256"]
    vista = c.get("/oportunidades/CO1.REQ.9/expediente", headers=_h("tok-ana")).json()
    assert vista["completo"] and vista["faltantes"] == []


def test_api_perfiles_por_propietario(cliente):
    c, _ = cliente
    r = c.post("/perfiles/", json={"nombre": "Software", "palabras_clave": ["software", " nube "],
                                   "cuantia_min": 10, "cuantia_max": 5}, headers=_h("tok-ana"))
    assert r.status_code == 422  # rango invertido
    r = c.post("/perfiles/", json={"nombre": "Software", "palabras_clave": ["software", " nube ", "software"]},
               headers=_h("tok-ana"))
    assert r.status_code == 201 and r.json()["palabras_clave"] == ["software", "nube"]
    perfil_id = r.json()["id"]
    assert c.post("/perfiles/", json={"nombre": "x", "palabras_clave": ["ab"]}, headers=_h("tok-ana")).status_code == 422
    assert c.post("/perfiles/", json={"nombre": "G", "palabras_clave": ["erp"]}, headers=_h("tok-gerente")).status_code == 403
    assert c.get("/perfiles/", headers=_h("tok-gerente")).json() == []  # solo los propios
    assert c.put(f"/perfiles/{perfil_id}", json={"activo": False}, headers=_h("tok-beto")).status_code == 404
    assert c.put(f"/perfiles/{perfil_id}", json={"activo": False}, headers=_h("tok-ana")).json()["activo"] is False
    assert c.delete(f"/perfiles/{perfil_id}", headers=_h("tok-admin")).status_code == 403
    assert c.delete(f"/perfiles/{perfil_id}", headers=_h("tok-ana")).status_code == 204
    assert c.get("/perfiles/", headers=_h("tok-ana")).json() == []


# --- El análisis usa el expediente y el informe lo declara (RF-021, RF-023, HU-10) ---

def test_el_analisis_usa_el_expediente_y_el_informe_lo_declara(tmp_path):
    from unittest.mock import MagicMock

    from src.shared.schemas.domain import CategoriaRequisito, ListaRequisitos, RequisitoExtraido
    from src.worker_analysis.orchestrator.graph import OrquestadorAnalisis
    from src.worker_analysis.pipeline.guardia import GuardiaDocumental
    from src.worker_analysis.reports.informe import GeneradorInforme

    adaptador = MagicMock()
    adaptador.recuperar_expediente.side_effect = ConnectionError("Datos Abiertos no responde")
    expediente = {
        "documentos": [{"nombre": "Pliego.pdf", "version": 2, "procedencia": "Carga manual por ana@x.co",
                        "obtenido_en": "2026-10-24T10:00:00", "huella_sha256": "ab" * 32,
                        "paginas": ["3.2 CAPACIDAD FINANCIERA\nÍndice de liquidez mayor o igual a 1,5.",
                                    "4.1 EXPERIENCIA\nTres contratos de desarrollo de software."]}],
        "no_analizados": [{"nombre": "Anexo técnico.pdf", "estado": "Faltante",
                           "motivo": "SECOP II no entregó el archivo (HTTP 403)."}],
    }
    extractor = MagicMock()
    extractor.extraer_requisitos.return_value = ListaRequisitos(requisitos=[RequisitoExtraido(
        identificador="REQ-1", texto="Tres contratos de desarrollo de software.", categoria=CategoriaRequisito.EXPERIENCIA,
        condicion_habilitante_propuesta=True, referencia_documental="Numeral 4.1")])
    orquestador = OrquestadorAnalisis(
        extractor=extractor, evaluador=MagicMock(), guardia=GuardiaDocumental(), segmentador=SegmentadorDocumental(),
        motor_puntaje=MagicMock(), recomendador=MagicMock(), informe=MagicMock(), auditoria=MagicMock(),
        adaptador_secop=adaptador, proveedor_expediente=lambda id_proceso: expediente)

    # Con documentos en el expediente, una caída de Datos Abiertos no detiene el análisis.
    estado = {"licitacion_url": "CO1.REQ.9", "tarea_id": "t-1"}
    estado.update(orquestador._recuperar_expediente(estado))
    assert "=== DOCUMENTO: Pliego.pdf | versión: 2 | procedencia: Carga manual por ana@x.co ===" in estado["contenido_crudo"]
    estado.update(orquestador._sanear_contenido(estado))
    estado.update(orquestador._segmentar_contenido(estado))
    assert "Páginas: 1-2" in estado["fragmentos"][0]
    estado.update(orquestador._extraer_requisitos(estado))
    assert estado["requisitos_extraidos"][0]["referencia_documental"] == "Pliego.pdf (v2) · Numeral 4.1, página 2"

    texto = "\n".join(t for _, items in GeneradorInforme(str(tmp_path)).secciones(estado, datetime(2026, 10, 24))
                      for _, t in items)
    assert "Pliego.pdf (versión 2, 2 páginas): Carga manual por ana@x.co, obtenido el 2026-10-24 10:00 UTC." in texto
    assert "Documento faltante, no analizado: Anexo técnico.pdf." in texto
    assert "Ficha del proceso en Datos Abiertos de SECOP II: no disponible." in texto
