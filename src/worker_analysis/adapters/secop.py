import logging
import httpx
from typing import Dict, Any, List, Optional

from src.shared.config import obtener_configuracion

logger = logging.getLogger(__name__)

# Campos del conjunto "SECOP II - Procesos de Contratación" (p6dx-8zbt) que se
# incluyen en el texto analizado, con la etiqueta que verá el modelo.
CAMPOS_PROCESO = [
    ("nombre_del_procedimiento", "NOMBRE DEL PROCEDIMIENTO"),
    ("descripci_n_del_procedimiento", "OBJETO DEL CONTRATO"),
    ("entidad", "ENTIDAD"),
    ("nit_entidad", "NIT ENTIDAD"),
    ("departamento_entidad", "DEPARTAMENTO"),
    ("ciudad_entidad", "CIUDAD"),
    ("modalidad_de_contratacion", "MODALIDAD DE CONTRATACIÓN"),
    ("justificaci_n_modalidad_de", "JUSTIFICACIÓN DE LA MODALIDAD"),
    ("tipo_de_contrato", "TIPO DE CONTRATO"),
    ("subtipo_de_contrato", "SUBTIPO DE CONTRATO"),
    ("precio_base", "PRECIO BASE (COP)"),
    ("duracion", "DURACIÓN"),
    ("unidad_de_duracion", "UNIDAD DE DURACIÓN"),
    ("fase", "FASE ACTUAL"),
    ("estado_del_procedimiento", "ESTADO DEL PROCEDIMIENTO"),
    ("fecha_de_publicacion_del", "FECHA DE PUBLICACIÓN"),
    ("fecha_de_recepcion_de", "FECHA DE RECEPCIÓN DE OFERTAS"),
    ("codigo_principal_de_categoria", "CÓDIGO UNSPSC PRINCIPAL"),
]

class AdaptadorSECOP:
    """
    Adaptador SECOP II (ASR-03).
    Se conecta a la API real de Datos Abiertos de Colombia (Socrata) para recuperar
    la información del proceso de contratación.

    Limitación conocida: Datos Abiertos solo publica metadatos del proceso. El
    pliego y sus anexos (PDF) viven en community.secop.gov.co y no se descargan
    aquí; por eso el orquestador acepta también el texto del pliego en la solicitud.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 15.0, app_token: Optional[str] = None):
        config = obtener_configuracion()
        self.base_url = base_url or config.secop_base_url
        self.timeout = timeout
        # X-App-Token es opcional en Socrata: amplía la cuota de consultas.
        token = config.socrata_app_token if app_token is None else app_token
        self.cabeceras = {"X-App-Token": token} if token else {}

    def _consultar(self, campo: str, valor: str) -> List[Dict[str, Any]]:
        response = httpx.get(
            self.base_url, params={campo: valor, "$limit": 5}, headers=self.cabeceras, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def recuperar_expediente(self, licitacion_id: str) -> Dict[str, Any]:
        """
        Recupera los metadatos y descripción del proceso desde la API oficial.
        licitacion_id debe ser el ID del proceso, ej: 'CO1.REQ.2315053'
        """
        licitacion_id = licitacion_id.strip()
        logger.info(f"Conectando a API Datos Abiertos (SECOP II) para: {licitacion_id}")

        try:
            datos = self._consultar("id_del_proceso", licitacion_id)
            if not datos:
                # Intento alternativo por 'referencia_del_proceso' si el usuario ingresó eso
                datos = self._consultar("referencia_del_proceso", licitacion_id)
            if not datos:
                raise ValueError(f"No se encontró la licitación {licitacion_id} en SECOP II.")

            proceso = datos[0] # Tomamos el registro principal

            lineas = [
                f"{etiqueta}: {proceso[campo]}"
                for campo, etiqueta in CAMPOS_PROCESO
                if proceso.get(campo) not in (None, "", "No Definido")
            ]
            url_proceso = proceso.get("urlproceso")
            if isinstance(url_proceso, dict):
                url_proceso = url_proceso.get("url")

            return {
                "id_proceso": proceso.get('id_del_proceso', licitacion_id),
                "entidad": proceso.get('entidad', 'Desconocida'),
                "version": proceso.get('estado_del_procedimiento', 'N/A'),
                "url_proceso": url_proceso,
                "contenido_crudo": "\n".join(lineas) + "\n",
            }

        except Exception as e:
            logger.error(f"Fallo de conexión o parseo en el Adaptador SECOP: {e}")
            raise
