# MVP Licitaciones — Sistema multiagente para licitaciones SECOP II

Analiza el pliego de una licitación pública, extrae sus requisitos, los somete a
revisión humana, los evalúa contra el portafolio de la fábrica de software y emite
un puntaje con una recomendación explicada (Ofertar / No ofertar / Solicitar revisión).

| Documento | Contenido |
|---|---|
| `INFORME_AUDITORIA.md` | Problemas encontrados, correcciones, matriz de validación, riesgos y resumen ejecutivo |
| `GUIA_PRUEBAS.md` | Paso a paso para probar el MVP y casos de prueba recomendados |
| `CAMBIOS.md` | Correcciones de la iteración anterior (2026-10-09) |

## Arquitectura

```
webui (NiceGUI :8080) ──HTTP+Bearer──▶ api (FastAPI :8000) ──▶ PostgreSQL 16 + pgvector
                                          │                     (tareas, portafolio, checkpoints, bitácora)
                                          ├─ sin Service Bus: ejecuta el grafo en su proceso (desarrollo)
                                          └─ con Service Bus ──▶ worker_analysis (LangGraph)
                                                                   ├─ Adaptador SECOP II (Datos Abiertos)
                                                                   ├─ Guardia documental (anti-inyección)
                                                                   ├─ Agente Extractor   ─┐
                                                                   ├─ [compuerta humana]  ├─ Azure OpenAI
                                                                   ├─ Agente Evaluador + RAG portafolio
                                                                   ├─ Motor de puntaje (determinista)
                                                                   └─ Recomendador (reglas + redacción LLM)
worker_vigilance: barrido de SECOP II (Datos Abiertos con token de aplicación) y alertas por afinidad
```

## Requisitos previos

- Docker y Docker Compose **o** Python 3.12 y PostgreSQL 16 con la extensión `vector`.
- Para el análisis real: un recurso de Azure OpenAI con un deployment de chat que
  soporte Structured Outputs (p. ej. `gpt-4o-mini` versión 2024-07-18) y, opcional,
  uno de embeddings de 1536 dimensiones (`text-embedding-3-small`).

## Configuración

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # pegue el valor en API_TOKEN_DESARROLLO y API_TOKEN
```

Mínimo para probar en local: `AUTH_MODE=local`, `SESION_SECRETO`, `WEBUI_STORAGE_SECRET`,
`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`,
`AZURE_OPENAI_DEPLOYMENT` y `SOCRATA_APP_TOKEN`. Deje `SERVICE_BUS_CONNECTION_STRING` vacía
para que la API ejecute el análisis sin worker.
Al arrancar, la API y el worker registran en el log qué variables faltan (sin mostrar valores), y
`python -m scripts.verificar_servicios` prueba cada servicio externo.

## Usuarios, roles y sesiones

Matriz de la Tabla 61 del documento de trabajo de grado, con funciones separadas:

| Rol | Pantalla inicial | Puede |
|---|---|---|
| Analista Comercial | Portafolio | Registrar y versionar el portafolio, gestionar alertas, solicitar análisis, revisar y aprobar requisitos, consultar resultados y reglas |
| Gerente Comercial | Resultados | Consultar portafolio, alertas, análisis y resultados; solicitar análisis; **único que registra la decisión comercial**; **confirma o rechaza** las reglas del puntaje propuestas |
| Administrador del Sistema | Usuarios | Gestionar usuarios y roles, ver el diagnóstico, editar capacidades y **proponer** reglas del puntaje; solo **consulta** análisis y resultados (no aprueba requisitos, no decide ni solicita análisis) |

El administrador inicial se crea al arrancar la API con `ADMIN_EMAIL`/`ADMIN_PASSWORD` si no hay
usuarios (o con `python -m scripts.crear_usuario`). Una sesión deja de ser válida al cerrarla,
tras `SESION_INACTIVIDAD_MIN` minutos sin actividad, al cumplir `SESION_DURACION_MIN` o cuando un
administrador deshabilita al usuario. La matriz está en `src/shared/roles.py` y la API la aplica en
cada ruta.

## Ejecución con Docker

```bash
docker compose up --build -d db api webui
docker compose exec api python -m scripts.cargar_portafolio data/ejemplos/portafolio_ejemplo.json
# Interfaz: http://localhost:8080   ·   API: http://localhost:8000/docs   ·   Salud: http://localhost:8000/health
```

## Ejecución local (sin Docker)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn src.api.main:app --port 8000                    # terminal 1 (crea las tablas al arrancar)
python src/webui/main.py                                # terminal 2
python -m scripts.cargar_portafolio data/ejemplos/portafolio_ejemplo.json
python -m src.worker_vigilance.main                     # opcional: un barrido de SECOP II (también desde la UI)
```

## Pruebas automatizadas

```bash
pytest                                                   # unitarias y de ASR (no requieren servicios)
TEST_DB_CONNECTION_STRING=postgresql://user:password@localhost:5432/licitaciones_test pytest   # + integración con Postgres real
```

Use una base **de pruebas** para la integración: inserta datos y no los borra.
