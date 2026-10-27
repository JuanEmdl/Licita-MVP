# Despliegue en Azure

> **Infraestructura completa con Terraform (Anexo G):** `infra/terraform` declara la red, PostgreSQL
> con pgvector, Service Bus, Storage con informes inmutables, Key Vault, Azure OpenAI, las cuatro
> unidades en Container Apps y las alertas de la Tabla 49. Pasos:
>
> 1. Una sola vez: `az login` y `./infra/terraform/bootstrap/crear_backend.sh` (estado remoto).
> 2. `terraform -chdir=infra/terraform init -backend-config="key=licita-pruebas.tfstate"`
> 3. `terraform -chdir=infra/terraform plan -var-file=entornos/pruebas.tfvars -var="subscription_id=<id>" -out=plan.tfplan`
>    (secretos opcionales por `TF_VAR_oidc_client_secret` y `TF_VAR_smtp_clave`)
> 4. `terraform -chdir=infra/terraform apply plan.tfplan`
> 5. Registrar `<url_interfaz>/auth/callback` como URI de redirección del App Registration.
>
> La canalización (`azure-pipelines.yml`) hace lo mismo cuando la variable `aplicarTerraform` es
> `true`. Lo que sigue describe la primera vuelta, que publicó solo la interfaz.

Guía para publicar el MVP. Esta primera vuelta despliega **solo la interfaz
web** con sus datos mock: sin base de datos, sin workers y sin Service Bus.
La idea es validar la cadena de despliegue completa antes de encender servicios
que cuestan dinero.

## Azure DevOps y Azure no son lo mismo

Son dos productos distintos y hacen falta los dos:

| | Qué es | Dónde | Costo |
|---|---|---|---|
| **Azure DevOps** | Repositorio del código y pipelines de CI/CD | `dev.azure.com` | Gratis hasta 5 usuarios |
| **Azure** | La nube donde se *ejecutan* los contenedores | `portal.azure.com` | Requiere suscripción con facturación |

Tener Azure DevOps no da acceso a Azure. Para que la aplicación corra hace
falta una suscripción de Azure asociada a un método de pago o a un crédito
(Azure for Students, por ejemplo).

Para ver qué suscripciones tienen disponibles:

```bash
az login
```

```bash
az account list --output table
```

Si la lista sale vacía, aún no hay suscripción y hay que crear una antes de
seguir.

## Qué se crea

| Recurso | Para qué | Costo aproximado |
|---|---|---|
| Resource Group | Agrupa todo y permite borrarlo de un golpe | Gratis |
| Container Registry (Basic) | Guarda la imagen de la webui | ~5 USD/mes |
| Container Apps Environment | Entorno de ejecución, incluye Log Analytics | Consumo |
| Container App (webui) | La aplicación | Cubierto en gran parte por la capa gratuita |

Container Apps regala cada mes 180.000 vCPU-segundo y 360.000 GiB-segundo, así
que una sola réplica pequeña sale casi gratis. El registro es el único costo
fijo apreciable.

## Despliegue inicial

Una sola vez, desde la raíz del repositorio:

```bash
az login
```

```bash
az account set --subscription "<ID O NOMBRE DE LA SUSCRIPCIÓN>"
```

```powershell
./infra/provision-webui.ps1
```

El script registra los proveedores, crea los recursos, construye la imagen con
`az acr build` (en la nube, sin Docker local) y publica la aplicación. Al
terminar imprime la URL pública. Es idempotente: se puede repetir sin romper
nada.

Si el nombre del registro ya está tomado por otra persona en Azure —es un
espacio de nombres global— hay que cambiar la variable `$sufijo` en la cabecera
del script.

## Despliegues siguientes

Ya con el pipeline configurado, cada push a `main` que toque la webui dispara
el despliegue solo.

Para conectarlo, una vez:

1. En Azure DevOps: **Project Settings → Service connections → New service
   connection → Azure Resource Manager**, y nombrarla `sc-licitaciones-azure`.
2. **Pipelines → New pipeline → Azure Repos Git**, elegir el repositorio y
   seleccionar el `azure-pipelines.yml` existente.

Si cambian los nombres de los recursos en `provision-webui.ps1`, hay que
reflejarlos en el bloque `variables` del pipeline.

## Borrar todo

```bash
az group delete --name rg-licitaciones-mvp --yes --no-wait
```

Esto elimina el grupo completo y detiene cualquier cobro. Es la forma más
segura de no dejar recursos encendidos por olvido.

## Lo que falta para el sistema completo

Esta vuelta deja fuera, a propósito:

- **PostgreSQL con pgvector** → Azure Database for PostgreSQL Flexible Server,
  habilitando la extensión `vector` en los parámetros del servidor.
- **Los dos workers** → Container Apps Jobs (DA-12), el de vigilancia con
  disparador programado y el de análisis disparado por cola.
- **Service Bus** → la cola que exige ASR-11 para el patrón web-cola-trabajador.
- **Blob Storage** → informes inmutables de EP-05.
- **Azure OpenAI** → requiere solicitar acceso y cuota, y no suele estar
  disponible en suscripciones de estudiante.
- **Key Vault** → para dejar de pasar secretos como variables de entorno.

Conviene añadirlos de a uno, verificando cada uno antes del siguiente.
