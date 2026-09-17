# Deploy en Google Cloud (Cloud Run + Cloud SQL)

La infraestructura está descrita en Terraform (`infra/terraform`) y los deploys los hace GitHub
Actions con OIDC: **no hay claves de servicio en ningún lado**.

```
GitHub Actions ──OIDC──► Workload Identity ──► Cloud Run (web)  ──► Cloud SQL (PostgreSQL)
                                               Cloud Run (job migrate / job scheduled)
                                               Secret Manager
Cloud Scheduler ──cada 10 min──► job scheduled (vencer señas, recordatorios, reintentos)
```

Costo aproximado: Cloud SQL `db-f1-micro` ~USD 9-12/mes, Cloud Run casi 0 con poco tráfico
(`min_instances = 0`), Artifact Registry y Secret Manager centavos. Dominio propio con balanceador:
~USD 18/mes extra (opcional).

---

## 1. Una sola vez: proyecto y estado de Terraform

```bash
gcloud auth login
gcloud projects create oral-turnos --name="ORAL turnos"          # o usá uno existente
gcloud config set project oral-turnos
# Asociá una cuenta de facturación (necesario para Cloud SQL y Cloud Run):
gcloud billing projects link oral-turnos --billing-account=XXXXXX-XXXXXX-XXXXXX

# Bucket para el estado de Terraform (versionado, privado)
gsutil mb -l southamerica-east1 gs://oral-turnos-tfstate
gsutil versioning set on gs://oral-turnos-tfstate
```

## 2. Crear la infraestructura

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars    # editá tus datos
terraform init -backend-config="bucket=oral-turnos-tfstate" -backend-config="prefix=prod"
terraform apply
```

Al terminar imprime `github_variables`. Cargalas en GitHub →
**Settings → Secrets and variables → Actions → Variables**:

| Variable | De dónde sale |
| --- | --- |
| `GCP_PROJECT_ID`, `GCP_REGION` | tus valores |
| `GCP_ARTIFACT_REPOSITORY` | output de Terraform |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | output de Terraform |
| `GCP_DEPLOYER_SERVICE_ACCOUNT` | output de Terraform |
| `CLOUD_RUN_SERVICE`, `CLOUD_RUN_MIGRATE_JOB`, `CLOUD_RUN_SCHEDULED_JOB` | output de Terraform |
| `PUBLIC_BASE_URL` | output `public_base_url` |

Creá además el **environment `production`** (Settings → Environments). Si querés que cada deploy
espere tu aprobación, activá *Required reviewers*. El acceso a GCP está restringido por condición
a este repositorio y a jobs que corren dentro de un environment.

## 3. Cargar los secretos

Terraform crea los secretos vacíos. Cargá los que vayas a usar:

```bash
printf '%s' 'APP_USR-...' | gcloud secrets versions add oral-mercadopago-access-token --data-file=-
printf '%s' 'mi-clave-webhook' | gcloud secrets versions add oral-mercadopago-webhook-secret --data-file=-
printf '%s' 'app-password-de-gmail' | gcloud secrets versions add oral-smtp-password --data-file=-
```

Después agregalos a `optional_secrets` en `terraform.tfvars` y volvé a aplicar:

```hcl
optional_secrets       = ["MERCADOPAGO_ACCESS_TOKEN", "MERCADOPAGO_WEBHOOK_SECRET", "SMTP_PASSWORD"]
deposit_default_amount = "10000"   # recién ahora, con el token cargado
```

> La app se niega a arrancar en producción si hay seña configurada sin token de Mercado Pago:
> es a propósito, para no mostrarle al paciente un botón de pago que no funciona.

`SECRET_KEY` y `DATABASE_URL` los genera Terraform.

## 4. Primer deploy

Actions → **Deploy** → *Run workflow* → ref `main`, environment `production`.

El workflow construye la imagen, corre las migraciones como job, publica la revisión nueva y
verifica `/health/ready`.

Después, cargá los datos iniciales (una vez):

```bash
gcloud run jobs update oral-migrate --region southamerica-east1 \
  --command python --args="-m,app.tasks.seed_demo"
gcloud run jobs execute oral-migrate --region southamerica-east1 --wait
# volvé a dejarlo como job de migraciones
gcloud run jobs update oral-migrate --region southamerica-east1 --command alembic --args="upgrade,head"
```

**Cambiá las contraseñas demo** entrando a `/app/users` con `admin / demo12345`, o creá tu usuario
admin y desactivá los de demo.

## 5. Releases

1. Anotá los cambios en `CHANGELOG.md`, bajo `[Unreleased]`.
2. Actions → **Preparar release** → versión (ej. `0.3.0`). Abre un PR con la versión y el changelog.
3. Al mergear ese PR, el workflow **Release** crea el tag `v0.3.0`, publica el GitHub Release con
   esas notas y dispara el deploy a producción.

Para volver atrás:

```bash
gcloud run revisions list --service oral-web --region southamerica-east1
gcloud run services update-traffic oral-web --region southamerica-east1 --to-revisions=REVISION_ANTERIOR=100
```

Las migraciones corren **antes** de publicar la revisión nueva: escribí migraciones compatibles con
la versión anterior (agregar columnas nullable, borrar en un release posterior).

## 6. Dominio propio

Por defecto el sitio vive en la URL `*.run.app`. Para usar dominio propio:

```hcl
custom_domain = "turnos.tu-dominio.com.ar"
```

`terraform apply` crea el balanceador y el certificado administrado; apuntá el registro **A** del
dominio a la IP del output `load_balancer_ip`. El certificado tarda entre 10 y 60 minutos.
Actualizá también `PUBLIC_BASE_URL` en las variables de GitHub y la URL del webhook en Mercado Pago.

## 7. Operación

- Logs: `gcloud run services logs tail oral-web --region southamerica-east1` (salen en JSON, se
  filtran por severidad en Cloud Logging).
- Tarea programada: se ejecuta sola cada 10 minutos; para correrla a mano
  `gcloud run jobs execute oral-scheduled --region southamerica-east1 --wait`.
- Backups: ver [BACKUPS.md](BACKUPS.md).
- Chequeo de configuración: `make prod-check` con las variables de producción exportadas.
