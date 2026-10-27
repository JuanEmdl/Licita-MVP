"""
Almacén inmutable de informes (DA-06, C-03) y lectura segura de los documentos cargados.
"""
import io
import zipfile

import pytest
from azure.core.exceptions import ResourceExistsError

from src.shared.almacen_informes import AlmacenInmutable, InformeAlteradoError
from src.shared.lectura_documentos import leer_documento


class ContenedorEnMemoria:
    """Imita un contenedor con política de inmutabilidad: lo escrito no se reemplaza."""

    def __init__(self):
        self.blobs = {}

    def upload_blob(self, nombre, datos, overwrite=False):
        if nombre in self.blobs:
            raise ResourceExistsError("BlobAlreadyExists")
        self.blobs[nombre] = bytes(datos)

    def download_blob(self, nombre):
        datos = self.blobs[nombre]
        return type("Descarga", (), {"readall": lambda self: datos})()


@pytest.fixture
def almacen():
    return AlmacenInmutable("https://stlicita.blob.core.windows.net/informes/", contenedor=ContenedorEnMemoria())


def test_el_informe_se_sube_y_se_lee(tmp_path, almacen):
    pdf = tmp_path / "informe_t1.pdf"
    pdf.write_bytes(b"%PDF-1.4 sellado")
    assert almacen.guardar(str(pdf)) == "https://stlicita.blob.core.windows.net/informes/informe_t1.pdf"
    # Otro proceso (la API) lo lee por el nombre aunque no tenga el archivo local.
    assert almacen.leer("/otra/ruta/informe_t1.pdf") == b"%PDF-1.4 sellado"


def test_repetir_la_etapa_con_el_mismo_contenido_se_acepta(tmp_path, almacen):
    pdf = tmp_path / "informe_t1.pdf"
    pdf.write_bytes(b"%PDF-1.4 sellado")
    almacen.guardar(str(pdf))
    almacen.guardar(str(pdf))  # FF-08: misma clave, mismo resultado


def test_un_informe_emitido_no_se_reemplaza(tmp_path, almacen):
    pdf = tmp_path / "informe_t1.pdf"
    pdf.write_bytes(b"%PDF-1.4 sellado")
    almacen.guardar(str(pdf))
    pdf.write_bytes(b"%PDF-1.4 alterado")
    with pytest.raises(InformeAlteradoError):
        almacen.guardar(str(pdf))


def test_la_verificacion_lee_del_almacen_si_falta_el_archivo(tmp_path, almacen):
    import hashlib
    from unittest.mock import MagicMock

    from src.worker_analysis.servicio import ServicioAnalisis

    pdf = tmp_path / "informe_t1.pdf"
    pdf.write_bytes(b"%PDF-1.4 sellado")
    almacen.guardar(str(pdf))
    huella = hashlib.sha256(b"%PDF-1.4 sellado").hexdigest()
    pdf.unlink()  # la API corre en otro contenedor, sin el volumen del trabajador

    orquestador = MagicMock(almacen_informes=almacen)
    orquestador.registro_informes.obtener.return_value = {"ruta_pdf": str(pdf), "huella_sha256": huella,
                                                          "emitido_en": None}
    servicio = ServicioAnalisis(checkpointer=None, repositorio=MagicMock(), orquestador=orquestador)
    servicio.obtener_resultado = lambda tarea_id: {}
    assert servicio.verificar_informe("t1")["coincide"] is True


# --- Lectura segura de DOCX (Bandit B314) ---

def _docx(documento_xml: str) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as z:
        z.writestr("word/document.xml", documento_xml)
    return salida.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def test_docx_normal_se_lee():
    texto = "El proponente acredita tres contratos de desarrollo de software en los últimos cinco años. " * 2
    lectura = leer_documento("pliego.docx", _docx(
        f'<w:document {W}><w:body><w:p><w:r><w:t>{texto}</w:t></w:r></w:p></w:body></w:document>'))
    assert not lectura.ilegible and "tres contratos" in lectura.paginas[0]


def test_docx_con_entidades_se_rechaza():
    bomba = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
             f'<w:document {W}><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>')
    lectura = leer_documento("adenda.docx", _docx(bomba))
    assert lectura.ilegible and "DTD" in lectura.motivo
