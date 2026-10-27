# Estrategia del repositorio

Cómo se organiza el código y cómo entra un cambio a la rama principal (Tabla 30, frente «Repositorio
y estrategia de ramas»; gobernanza del apartado 3.36). El repositorio vive en Azure DevOps
(proyecto *AGENTE IA TG*).

## Estructura de carpetas

| Carpeta | Contenido |
|---|---|
| `src/api` | API de aplicación (FastAPI): filtro de autenticación y autorización, módulos de identidad, portafolio, oportunidades, análisis, resultados, notificaciones, auditoría y consumo. |
| `src/worker_analysis` | Trabajador de análisis: orquestador LangGraph, agentes, pasarela de modelos, procesamiento documental (guardia, segmentador, adendas), motor de puntaje e informes. |
| `src/worker_vigilance` | Trabajador de vigilancia: sincronización con SECOP II, detector de novedades, perfiles y notificador. |
| `src/webui` | Interfaz web (NiceGUI), cliente confidencial OIDC. |
| `src/shared` | Modelos, repositorios, configuración, roles, telemetría y esquemas de dominio compartidos. |
| `tests/unit`, `tests/asr`, `tests/integration` | Pruebas unitarias, de escenarios arquitectónicos y de integración con PostgreSQL. |
| `tests/aptitud` | Funciones de aptitud FF-02 a FF-05 y FF-08 (Tabla 33). |
| `tests/carga` | Prueba de carga con Locust (FF-01). |
| `infra/terraform` | Infraestructura como código (Anexo G). |
| `infra/devops` | Políticas de rama de Azure DevOps. |
| `docker`, `docker-compose.yml` | Imágenes de las cuatro unidades y entorno local. |
| `architecture` | Código fuente de los diagramas C4 (Anexo D). |
| `scripts`, `data` | Utilidades (carga del portafolio, usuarios, evaluación del extractor) y datos de ejemplo. |

## Ramas

- `main`: lo que está en condiciones de desplegarse. Protegida: solo recibe cambios por solicitud de
  incorporación y la canalización despliega desde ella.
- `develop`: integración de la iteración en curso. Protegida con las mismas políticas que `main`.
- `feature/<tema>` y `fix/<tema>`: una por historia o corrección, salen de `develop` y vuelven a ella
  por solicitud de incorporación. Se borran al fusionarse.
- Al cierre de cada sprint, `develop` se integra a `main` con una solicitud de incorporación.

## Solicitudes de incorporación

Una solicitud de incorporación no se puede completar si falta cualquiera de estas condiciones
(se configuran con `infra/devops/politicas_rama.sh`):

1. La canalización `azure-pipelines.yml` pasó: pruebas, cobertura del dominio, funciones de aptitud,
   validación de Terraform, Bandit y pip-audit.
2. La aprobó el otro integrante: el voto del autor no cuenta (papeles de autor y revisor, apartado 3.36).
3. Todos los comentarios están resueltos.
4. Está vinculada a la historia o tarea del tablero.

La plantilla de `.azuredevops/pull_request_template.md` recoge la trazabilidad (RF, HU, ASR, DA) y la
definición de terminado de la Tabla 3.

## Reglas para el cambio

- Mensajes de commit con la convención *Conventional Commits* en español:
  `feat(analisis): borrador de la revisión de requisitos`.
- Código, nombres y comentarios en español; versiones fijadas en `requirements.txt`.
- Un cambio en un contrato de la API o de la cola actualiza la Tabla 45 o la 46 y conserva la ruta
  anterior como alias obsoleto mientras haya clientes que la usen.
- Un cambio en el modelo de datos se agrega a `src/shared/database.py` como sentencia aditiva e
  idempotente (`ADD COLUMN IF NOT EXISTS`); no se borran ni renombran columnas.
- Una decisión arquitectónica nueva o cambiada deja su registro MADR (Tabla 43).
- Los secretos nunca entran al repositorio: `.env` está ignorado y en Azure viven en Key Vault.
