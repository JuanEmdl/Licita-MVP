"""
Almacén inmutable de los informes emitidos (DA-06, control C-03, ASR-06).

Con ALMACEN_INFORMES_URL (el contenedor «informes» de Blob Storage, que Terraform crea con
una política de inmutabilidad: ver infra/terraform/main.tf), cada informe sellado se sube al
emitirse y la API lo lee de ahí, así que la API y el trabajador no necesitan compartir un
volumen. Autentica con la identidad administrada (DefaultAzureCredential): no hay claves en
la configuración (ASR-05). Sin la variable, el informe queda solo en INFORMES_DIR, como en
Docker Compose.

Un informe ya subido no se reemplaza: si la etapa se repite (FF-08) y el contenido coincide
se acepta; si difiere, se rechaza, porque un informe emitido no cambia (RN-08).
"""
import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class InformeAlteradoError(Exception):
    """Ya hay un informe emitido con ese nombre y su contenido es distinto."""


class AlmacenInmutable:

    def __init__(self, url_contenedor: str, contenedor=None):
        self.url_contenedor = url_contenedor.rstrip("/")
        self._contenedor = contenedor

    def _cliente(self):
        if self._contenedor is None:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import ContainerClient
            self._contenedor = ContainerClient.from_container_url(self.url_contenedor,
                                                                  credential=DefaultAzureCredential())
        return self._contenedor

    @staticmethod
    def nombre(ruta_local: str) -> str:
        return os.path.basename(ruta_local)

    def guardar(self, ruta_local: str) -> str:
        """Sube el archivo sin sobrescribir; devuelve su URL en el almacén."""
        from azure.core.exceptions import ResourceExistsError

        with open(ruta_local, "rb") as f:
            datos = f.read()
        nombre = self.nombre(ruta_local)
        try:
            self._cliente().upload_blob(nombre, datos, overwrite=False)
        except ResourceExistsError:
            existente = self._cliente().download_blob(nombre).readall()
            if hashlib.sha256(existente).digest() != hashlib.sha256(datos).digest():
                raise InformeAlteradoError(f"El informe {nombre} ya fue emitido con otro contenido.")
            logger.info(f"El informe {nombre} ya estaba en el almacén inmutable (etapa repetida).")
        return f"{self.url_contenedor}/{nombre}"

    def leer(self, ruta_local: str) -> bytes:
        return self._cliente().download_blob(self.nombre(ruta_local)).readall()


def obtener_almacen() -> Optional[AlmacenInmutable]:
    from src.shared.config import obtener_configuracion

    url = obtener_configuracion().almacen_informes_url
    return AlmacenInmutable(url) if url else None
