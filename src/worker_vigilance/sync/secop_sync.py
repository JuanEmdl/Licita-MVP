"""
Lectura automática de SECOP II por los mecanismos autorizados (ASR-03, RF-011, RF-012).

- Procesos: Datos Abiertos, conjunto p6dx-8zbt. Descarga los publicados en los últimos
  días cuyo nombre u objeto menciona términos de tecnología, del portafolio o de los
  perfiles de búsqueda. El filtro grueso se hace en el servidor (SoQL) para no
  descargar los miles de procesos diarios; la afinidad fina se calcula después.
- Documentos del expediente: Datos Abiertos, conjunto dmgg-8hin (nombre, fecha de
  carga y enlace de descarga de cada archivo). El archivo se pide al enlace publicado;
  si la plataforma no lo entrega a un cliente automático, el documento queda como
  faltante con el motivo, para cargarlo a mano (RF-022). No se evaden controles.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

import httpx

from src.shared.config import obtener_configuracion

logger = logging.getLogger(__name__)

# Raíces en mayúsculas y sin la sílaba acentuada final para que coincidan con
# o sin tilde (p. ej. "APLICACI" cubre APLICACIÓN y APLICACION).
TERMINOS_TECNOLOGIA = [
    "SOFTWARE", "DESARROLLO DE", "PLATAFORMA", "SISTEMA DE INFORMACI", "SISTEMAS DE INFORMACI",
    "APLICACI", "APLICATIVO", "PORTAL WEB", "PAGINA WEB", "PÁGINA WEB", "SITIO WEB",
    "LICENCIA", "NUBE", "CLOUD", "INTEROPERABILIDAD", "BASE DE DATOS", "BASES DE DATOS",
    "CIBERSEGURIDAD", "SEGURIDAD DE LA INFORMACI", "INTELIGENCIA ARTIFICIAL", "ANALITICA", "ANALÍTICA",
    "TRANSFORMACI", "DIGITALIZACI", "AUTOMATIZACI", "MESA DE AYUDA", "FABRICA DE SOFTWARE",
    "FÁBRICA DE SOFTWARE", "TECNOLOG", "INFORMATIC", "INFORMÁTIC",
]

ESTADOS_ABIERTOS = ("Publicado", "Abierto")

CAMPOS = [
    "id_del_proceso", "referencia_del_proceso", "id_del_portafolio", "entidad", "nit_entidad",
    "nombre_del_procedimiento", "descripci_n_del_procedimiento", "modalidad_de_contratacion",
    "precio_base", "departamento_entidad", "ciudad_entidad", "fase", "estado_del_procedimiento",
    "fecha_de_publicacion_del", "fecha_de_recepcion_de", "fecha_de_ultima_publicaci", "urlproceso",
]

# Un enlace de SECOP II identifica el proceso por su aviso (noticeUID=CO1.NTC…) o por su ID.
_PATRON_AVISO = re.compile(r"CO1\.NTC\.\d+", re.IGNORECASE)
_PATRON_PROCESO = re.compile(r"CO1\.REQ\.\d+", re.IGNORECASE)


class DescargaNoDisponibleError(Exception):
    """La fuente no entregó el archivo; el motivo se muestra en el expediente (RF-011)."""


def nombre_fuente(url: str) -> str:
    """'https://www.datos.gov.co/resource/p6dx-8zbt.json' -> 'SECOP II · Datos Abiertos (p6dx-8zbt)'."""
    conjunto = re.search(r"/resource/([^/.]+)", url or "")
    return f"SECOP II · Datos Abiertos ({conjunto.group(1)})" if conjunto else "SECOP II · Datos Abiertos"


def _escapar(valor: str) -> str:
    return valor.replace("'", "''")


def construir_filtro(dias: int, terminos: Iterable[str], hoy: Optional[datetime] = None) -> str:
    desde = ((hoy or datetime.utcnow()) - timedelta(days=dias)).strftime("%Y-%m-%dT00:00:00")
    estados = ", ".join(f"'{e}'" for e in ESTADOS_ABIERTOS)
    condiciones = []
    for termino in dict.fromkeys(t.upper().strip() for t in terminos if t and len(t.strip()) >= 3):
        t = _escapar(termino)
        condiciones.append(f"upper(descripci_n_del_procedimiento) like '%{t}%'")
        condiciones.append(f"upper(nombre_del_procedimiento) like '%{t}%'")
    filtro = f"fecha_de_publicacion_del >= '{desde}' AND estado_del_procedimiento in ({estados})"
    if condiciones:
        filtro += " AND (" + " OR ".join(condiciones) + ")"
    return filtro


def _texto(valor: Any) -> Optional[str]:
    """Datos Abiertos rellena con 'No Definido' lo que no publica: se guarda como vacío."""
    if valor is None:
        return None
    valor = str(valor).strip()
    return None if valor.lower() in ("", "no definido", "no definida") else valor


def _fecha(valor: Optional[str]) -> Optional[datetime]:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", ""))
    except ValueError:
        return None


def _numero(valor: Any) -> Optional[float]:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def normalizar_proceso(crudo: Dict[str, Any]) -> Dict[str, Any]:
    url = crudo.get("urlproceso")
    if isinstance(url, dict):
        url = url.get("url")
    nombre = (crudo.get("nombre_del_procedimiento") or "").strip()
    objeto = (crudo.get("descripci_n_del_procedimiento") or "").strip()
    if objeto.lower() in ("", "no definido"):
        objeto = nombre
    return {
        "id_proceso": crudo.get("id_del_proceso"),
        "referencia": crudo.get("referencia_del_proceso"),
        "id_portafolio": _texto(crudo.get("id_del_portafolio")),
        "entidad": crudo.get("entidad"),
        "nit_entidad": _texto(crudo.get("nit_entidad")),
        "nombre": nombre,
        "objeto": objeto,
        "modalidad": crudo.get("modalidad_de_contratacion"),
        "precio_base": _numero(crudo.get("precio_base")),
        "departamento": _texto(crudo.get("departamento_entidad")),
        "ciudad": _texto(crudo.get("ciudad_entidad")),
        "fase": crudo.get("fase"),
        "estado": _texto(crudo.get("estado_del_procedimiento")),
        "fecha_publicacion": _fecha(crudo.get("fecha_de_publicacion_del")),
        "fecha_cierre": _fecha(crudo.get("fecha_de_recepcion_de")),
        "actualizado_en_fuente": _fecha(crudo.get("fecha_de_ultima_publicaci")),
        "url_proceso": url,
    }


def normalizar_documento(crudo: Dict[str, Any]) -> Dict[str, Any]:
    """Registro del conjunto dmgg-8hin traducido al modelo interno (ASR-03)."""
    url = crudo.get("url_descarga_documento")
    if isinstance(url, dict):
        url = url.get("url")
    return {
        "id_documento_fuente": crudo.get("id_documento"),
        "nombre": (crudo.get("nombre_archivo") or crudo.get("descripci_n") or "Documento sin nombre").strip(),
        "extension": (crudo.get("extensi_n") or "").lower().strip(".") or None,
        "tamano_bytes": int(_numero(crudo.get("tamanno_archivo")) or 0) or None,
        "publicado_en": _fecha(crudo.get("fecha_carga")),
        "url_fuente": url,
    }


class ClienteSECOP:
    """Consulta paginada a Datos Abiertos con el token de aplicación (X-App-Token)."""

    TAMANO_PAGINA = 200

    def __init__(self, base_url: Optional[str] = None, app_token: Optional[str] = None, timeout: float = 60.0,
                 documentos_url: Optional[str] = None):
        config = obtener_configuracion()
        self.base_url = base_url or config.secop_base_url
        self.documentos_url = documentos_url or config.secop_documentos_url
        token = config.socrata_app_token if app_token is None else app_token
        self.cabeceras = {"X-App-Token": token} if token else {}
        self.timeout = timeout
        self.fuente = nombre_fuente(self.base_url)
        self.fuente_documentos = nombre_fuente(self.documentos_url)
        if not token:
            logger.warning("SOCRATA_APP_TOKEN vacío: Datos Abiertos aplica una cuota de consultas reducida.")

    def _consultar(self, url: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        respuesta = httpx.get(url, params=params, headers=self.cabeceras, timeout=self.timeout)
        if respuesta.status_code == 403:
            raise PermissionError("Datos Abiertos rechazó el token de aplicación (SOCRATA_APP_TOKEN).")
        respuesta.raise_for_status()
        return respuesta.json()

    def proceso(self, identificador: str) -> Optional[Dict[str, Any]]:
        """
        Busca un proceso por su ID (CO1.REQ…), su referencia o el enlace de SECOP II
        (noticeUID=CO1.NTC…). None si no corresponde a ningún proceso publicado (HU-02 CA-04).
        """
        identificador = (identificador or "").strip()
        if not identificador:
            return None
        aviso = _PATRON_AVISO.search(identificador)
        proceso = _PATRON_PROCESO.search(identificador)
        if proceso:
            consultas = [{"id_del_proceso": proceso.group(0).upper()}]
        elif aviso:
            consultas = [{"$where": f"urlproceso.url like '%{_escapar(aviso.group(0).upper())}%'"}]
        else:
            consultas = [{"id_del_proceso": identificador}, {"referencia_del_proceso": identificador}]
        for params in consultas:
            datos = self._consultar(self.base_url, {"$select": ",".join(CAMPOS), "$limit": 5, **params})
            if datos:
                return normalizar_proceso(datos[0])
        return None

    def procesos_por_id(self, ids: Iterable[str]) -> List[Dict[str, Any]]:
        """Estado actual de los procesos seguidos, en lotes (RF-019)."""
        ids = [i for i in dict.fromkeys(ids) if i]
        encontrados: Dict[str, Dict[str, Any]] = {}
        for inicio in range(0, len(ids), 50):
            lote = ", ".join(f"'{_escapar(i)}'" for i in ids[inicio:inicio + 50])
            for crudo in self._consultar(self.base_url, {
                "$select": ",".join(CAMPOS), "$where": f"id_del_proceso in ({lote})", "$limit": 500,
            }):
                proceso = normalizar_proceso(crudo)
                encontrados.setdefault(proceso["id_proceso"], proceso)
        return list(encontrados.values())

    def documentos(self, id_portafolio: Optional[str]) -> List[Dict[str, Any]]:
        """Archivos publicados del proceso según Datos Abiertos, sin repetir (RF-011)."""
        if not id_portafolio:
            return []
        vistos: Dict[str, Dict[str, Any]] = {}
        for crudo in self._consultar(self.documentos_url, {
            "proceso": id_portafolio, "$order": "fecha_carga, id_documento", "$limit": 500,
        }):
            documento = normalizar_documento(crudo)
            clave = documento["id_documento_fuente"] or documento["url_fuente"] or documento["nombre"]
            vistos.setdefault(clave, documento)
        return list(vistos.values())

    def descargar(self, url: Optional[str], max_bytes: int) -> bytes:
        """
        Pide el archivo al enlace publicado en Datos Abiertos. Si la plataforma no lo
        entrega (p. ej. 403 a clientes automáticos), lanza DescargaNoDisponibleError
        con el motivo; el documento queda como faltante para la carga manual (RF-022).
        """
        if not url:
            raise DescargaNoDisponibleError("La fuente no publica un enlace de descarga.")
        try:
            with httpx.stream("GET", url, timeout=self.timeout, follow_redirects=True) as respuesta:
                if respuesta.status_code != 200:
                    raise DescargaNoDisponibleError(
                        f"SECOP II no entregó el archivo a la descarga automática (HTTP {respuesta.status_code}).")
                if "text/html" in respuesta.headers.get("content-type", ""):
                    raise DescargaNoDisponibleError("SECOP II respondió una página en lugar del archivo.")
                contenido = bytearray()
                for bloque in respuesta.iter_bytes():
                    contenido.extend(bloque)
                    if len(contenido) > max_bytes:
                        raise DescargaNoDisponibleError(
                            f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.")
                return bytes(contenido)
        except httpx.HTTPError as e:
            raise DescargaNoDisponibleError(f"No se pudo descargar ({type(e).__name__}).") from e

    def procesos_recientes(self, dias: int, terminos: Iterable[str], maximo: int) -> List[Dict[str, Any]]:
        filtro = construir_filtro(dias, terminos)
        procesos: List[Dict[str, Any]] = []
        vistos = set()
        with httpx.Client(timeout=self.timeout, headers=self.cabeceras) as cliente:
            desplazamiento = 0
            while len(procesos) < maximo:
                respuesta = cliente.get(self.base_url, params={
                    "$select": ",".join(CAMPOS),
                    "$where": filtro,
                    "$order": "fecha_de_publicacion_del DESC, id_del_proceso",
                    "$limit": min(self.TAMANO_PAGINA, maximo - len(procesos)),
                    "$offset": desplazamiento,
                })
                if respuesta.status_code == 403:
                    raise PermissionError("Datos Abiertos rechazó el token de aplicación (SOCRATA_APP_TOKEN).")
                respuesta.raise_for_status()
                pagina = respuesta.json()
                if not pagina:
                    break
                for crudo in pagina:
                    proceso = normalizar_proceso(crudo)
                    # Un mismo proceso aparece una vez por lote/versión: se conserva el primero.
                    if proceso["id_proceso"] and proceso["id_proceso"] not in vistos:
                        vistos.add(proceso["id_proceso"])
                        procesos.append(proceso)
                desplazamiento += len(pagina)
                if len(pagina) < self.TAMANO_PAGINA:
                    break
        logger.info(f"SECOP II: {len(procesos)} procesos candidatos en los últimos {dias} días.")
        return procesos
