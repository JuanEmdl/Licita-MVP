import hashlib
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.shared.config import obtener_configuracion
from src.worker_analysis.reports.pdf import DocumentoPDF

logger = logging.getLogger(__name__)

# Estados que el informe declara como incertidumbre (HU-10 CA-01).
_INCIERTOS = {"No verificable", "Cumple parcialmente"}


class GeneradorInforme:
    """
    Generador de informe (RF-037, ASR-06, HU-09, HU-10).
    Emite el informe de viabilidad en PDF con los dictámenes, la evidencia, el puntaje
    y su desglose, la recomendación, las versiones utilizadas (reglas, portafolio,
    instrucciones y modelo), las intervenciones humanas, los documentos faltantes y
    las incertidumbres, y calcula su huella SHA-256 para la bitácora.

    El PDF es el documento sellado. Junto a él se guarda una versión en texto con el
    mismo contenido para la vista previa de la interfaz; la huella es la del PDF.
    """

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or obtener_configuracion().informes_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def ruta_informe(self, tarea_id: str) -> str:
        return os.path.join(self.output_dir, f"informe_{tarea_id}.pdf")

    def ruta_texto(self, tarea_id: str) -> str:
        return os.path.join(self.output_dir, f"informe_{tarea_id}.txt")

    def generar_y_sellar(self, state_data: Dict[str, Any], emitido_en: Optional[datetime] = None) -> Dict[str, str]:
        """Genera el PDF y su vista en texto; devuelve las rutas y la huella SHA-256 del PDF."""
        tarea_id = state_data.get("tarea_id", "tarea_desconocida")
        emitido_en = emitido_en or datetime.utcnow()
        secciones = self.secciones(state_data, emitido_en)

        pdf = self._pdf(secciones, tarea_id)
        ruta_pdf, ruta_txt = self.ruta_informe(tarea_id), self.ruta_texto(tarea_id)
        with open(ruta_pdf, "wb") as f:
            f.write(pdf)
        with open(ruta_txt, "w", encoding="utf-8") as f:
            f.write(self._texto(secciones))

        huella = hashlib.sha256(pdf).hexdigest()
        logger.info(f"Informe PDF guardado en {ruta_pdf}; huella {huella}")
        return {"informe_path": ruta_pdf, "texto_path": ruta_txt, "huella_sha256": huella,
                "emitido_en": emitido_en.isoformat()}

    # --- Contenido ---

    def secciones(self, s: Dict[str, Any], emitido_en: datetime) -> List[Tuple[str, List[Tuple[str, str]]]]:
        """
        Contenido del informe como (título de sección, [(tipo, texto)]), con tipo
        "dato", "parrafo", "item", "subitem" o "nota". Lo comparten el PDF y el texto.
        """
        desglose = s.get("desglose_puntaje") or {}
        reglas = s.get("reglas_aplicadas") or {}
        aprobados = s.get("requisitos_aprobados", [])
        extraidos = s.get("requisitos_extraidos", [])
        dictamenes = s.get("dictamenes", [])
        por_id = {r.get("identificador"): r for r in aprobados}

        resultado = [
            ("dato", f"Recomendación del sistema: {s.get('recomendacion', 'Sin recomendación')}"),
            ("dato", f"Puntaje de cumplimiento: {s.get('puntaje_global', 0.0)} de 100"),
            ("parrafo", s.get("justificacion_recomendacion") or "Sin justificación."),
        ]
        for categoria, aporte in (desglose.get("aporte_por_categoria") or {}).items():
            peso = (desglose.get("peso_efectivo_por_categoria") or {}).get(categoria, 0.0)
            if peso:
                resultado.append(("item", f"{categoria}: aporta {aporte} de {peso} puntos posibles"))
        if desglose.get("categorias_no_aplicables"):
            resultado.append(("nota", "Categorías sin requisitos (su peso se redistribuyó): "
                                      + ", ".join(desglose["categorias_no_aplicables"])))
        resultado.append(("nota", "La decisión comercial corresponde al Gerente Comercial; este informe la "
                                  "sustenta, no la reemplaza."))

        versiones = [
            ("dato", f"Reglas del puntaje: versión {desglose.get('version_reglas', 'N/A')}"),
        ]
        if reglas:
            pesos = ", ".join(f"{c} {p:g} %" for c, p in sorted((reglas.get("pesos") or {}).items()))
            versiones.append(("item", f"Pesos: {pesos}"))
            versiones.append(("item", f"Umbrales: ofertar desde {reglas.get('umbral_ofertar'):g}; "
                                      f"solicitar revisión desde {reglas.get('umbral_revision'):g}"))
        versiones += [
            ("dato", f"Portafolio usado como evidencia: versión {s.get('portafolio_version') or 'N/A'}"),
            ("dato", f"Instrucciones de los agentes: versión {s.get('version_prompts') or 'N/A'}"),
            ("dato", f"Modelo de lenguaje: {obtener_configuracion().azure_openai_deployment}"),
        ]

        documentos = self._documentos(s)

        intervenciones = self._intervenciones(s, extraidos, aprobados)

        inciertos = [d for d in dictamenes if d.get("estado") in _INCIERTOS]
        incertidumbres = [("item", f"{d.get('identificador_requisito')}: {d.get('estado')}. {d.get('justificacion', '')}")
                          for d in inciertos]
        if not incertidumbres:
            incertidumbres = [("parrafo", "Ningún requisito quedó como No verificable o Cumple parcialmente.")]

        detalle = []
        for d in dictamenes:
            req = por_id.get(d.get("identificador_requisito"), {})
            tipo = "habilitante" if req.get("condicion_habilitante_propuesta") else "puntuable"
            detalle.append(("item", f"{d.get('identificador_requisito')} · {req.get('categoria', '')} · {tipo} · "
                                    f"{d.get('estado')}"))
            if req.get("texto"):
                detalle.append(("subitem", f"Requisito: {req['texto']} [{req.get('referencia_documental', '')}]"))
            detalle.append(("subitem", f"Razón: {d.get('justificacion', '')}"))
            detalle.append(("subitem", f"Evidencia: {d.get('evidencia') or 'Sin evidencia en el portafolio.'}"))

        return [
            ("Identificación", [
                ("dato", f"Proceso SECOP II: {s.get('licitacion_url', 'N/A')}"),
                ("dato", f"Tarea de análisis: {s.get('tarea_id', 'N/A')}"),
                ("dato", f"Emitido: {emitido_en.strftime('%Y-%m-%d %H:%M')} UTC"),
            ]),
            ("1. Resultado y recomendación", resultado),
            ("2. Versiones utilizadas", versiones),
            ("3. Documentos analizados y faltantes", documentos),
            ("4. Intervenciones humanas", intervenciones),
            ("5. Incertidumbres", incertidumbres),
            ("6. Dictamen por requisito", detalle or [("parrafo", "No se emitieron dictámenes.")]),
        ]

    @staticmethod
    def _documentos(s: Dict[str, Any]) -> List[Tuple[str, str]]:
        """Qué se analizó, con versión, procedencia y fecha de obtención, y qué faltó (RF-021, HU-10)."""
        crudo = s.get("contenido_crudo") or ""
        ficha = s.get("ficha_recuperada")
        if ficha is None:  # análisis anteriores al expediente documental
            ficha = bool(crudo.strip()) and not crudo.startswith("PLIEGO")
        documentos = [("item", "Ficha del proceso en Datos Abiertos de SECOP II: "
                               + ("recuperada." if ficha else "no disponible."))]
        analizados = s.get("documentos_analizados") or []
        for d in analizados:
            obtenido = (d.get("obtenido_en") or "")[:16].replace("T", " ")
            documentos.append(("item", f"{d.get('nombre')} (versión {d.get('version')}, {d.get('paginas')} "
                                       f"páginas): {d.get('procedencia')}" + (f", obtenido el {obtenido} UTC." if obtenido else ".")))
            if d.get("huella_sha256"):
                documentos.append(("subitem", f"Huella SHA-256: {d['huella_sha256']}"))
        pliego = (s.get("contenido_pliego") or "").strip()
        if pliego:
            documentos.append(("item", f"Pliego de condiciones aportado por el analista ({len(pliego):,} caracteres)."
                               .replace(",", ".")))
        for d in s.get("documentos_no_analizados") or []:
            documentos.append(("item", f"Documento {d.get('estado', 'faltante').lower()}, no analizado: "
                                       f"{d.get('nombre')}. {d.get('motivo') or ''}".strip()))
        if not analizados and not pliego:
            documentos.append(("item", "Documento faltante: no se aportó el pliego de condiciones. Datos Abiertos "
                                       "solo publica metadatos, por lo que los requisitos pueden estar incompletos."))
        if not analizados:
            documentos.append(("nota", "Los anexos y adendas no incluidos en el texto aportado no fueron analizados."))
        elif s.get("documentos_no_analizados"):
            documentos.append(("nota", "Los requisitos de los documentos no analizados no están en este informe."))
        return documentos

    @staticmethod
    def _intervenciones(s: Dict[str, Any], extraidos: List[dict], aprobados: List[dict]) -> List[Tuple[str, str]]:
        """Qué cambió el analista en la compuerta humana (RF-030, ASR-12)."""
        textos_extraidos = {r.get("identificador"): r.get("texto") for r in extraidos}
        ids_aprobados = {r.get("identificador") for r in aprobados}
        agregados = sorted(ids_aprobados - set(textos_extraidos))
        eliminados = sorted(set(textos_extraidos) - ids_aprobados)
        modificados = sorted(r.get("identificador") for r in aprobados
                             if r.get("identificador") in textos_extraidos
                             and textos_extraidos[r.get("identificador")] != r.get("texto"))
        lista = [
            ("dato", f"Lista de requisitos revisada y aprobada por: {s.get('aprobado_por') or 'N/A'}"),
            ("item", f"Extraídos por el Agente Extractor: {len(extraidos)}; aprobados: {len(aprobados)}"),
            ("item", f"Agregados por el analista: {', '.join(agregados) or 'ninguno'}"),
            ("item", f"Eliminados por el analista: {', '.join(eliminados) or 'ninguno'}"),
            ("item", f"Modificados por el analista: {', '.join(modificados) or 'ninguno'}"),
        ]
        return lista

    # --- Presentación ---

    @staticmethod
    def _pdf(secciones, tarea_id: str) -> bytes:
        doc = DocumentoPDF("Informe de viabilidad de licitación", pie=f"Licita · Tarea {tarea_id}")
        doc.titulo("Informe de viabilidad de licitación")
        doc.parrafo("Documento emitido por el sistema y sellado con su huella SHA-256 en la bitácora de "
                    "auditoría. Un informe emitido no se modifica (RN-08).", tamano=8.5, gris=0.35)
        for titulo, contenido in secciones:
            doc.seccion(titulo)
            for tipo, texto in contenido:
                if tipo == "dato":
                    doc.parrafo(texto, negrita=True)
                elif tipo == "item":
                    doc.parrafo(f"•  {texto}", sangria=10)
                elif tipo == "subitem":
                    doc.parrafo(texto, tamano=8.8, sangria=24, gris=0.2)
                elif tipo == "nota":
                    doc.parrafo(texto, tamano=8.5, gris=0.4)
                else:
                    doc.parrafo(texto)
                    doc.espacio(3)
        return doc.bytes()

    @staticmethod
    def _texto(secciones) -> str:
        lineas = ["INFORME DE VIABILIDAD DE LICITACIÓN", ""]
        for titulo, contenido in secciones:
            lineas += [titulo.upper(), "-" * len(titulo)]
            for tipo, texto in contenido:
                prefijo = {"item": "  - ", "subitem": "      ", "nota": "  Nota: "}.get(tipo, "")
                lineas.append(f"{prefijo}{texto}")
            lineas.append("")
        return "\n".join(lineas)

    @staticmethod
    def huella_archivo(ruta: str) -> str:
        sha256 = hashlib.sha256()
        with open(ruta, "rb") as f:
            for bloque in iter(lambda: f.read(65536), b""):
                sha256.update(bloque)
        return sha256.hexdigest()
