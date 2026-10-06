# Despliegue en Google Cloud

La infraestructura está descrita en Terraform (`infra/terraform`) y los despliegues los hace GitHub
Actions con identidad federada (OIDC): **no hay claves de servicio en ningún lado**.

```
GitHub Actions ──OIDC──► Workload Identity ──► Cloud Run (web)  ──► Cloud SQL (PostgreSQL)
                                               Cloud Run (job migrate / job scheduled)
                                               Secret Manager
Cloud Scheduler ──cada 10 min──► job scheduled (vencer señas, recordatorios, reintentos)
```

Por qué se eligió esta arquitectura y qué se descartó: [ADR 0004](decisions/0004-google-cloud-run.md).
Costo aproximado con la configuración actual: **USD 20-23 por mes** (Cloud SQL `db-f1-micro` ~USD 10,
instancia web siempre encendida ~USD 10, el resto son centavos). Verificalo en la calculadora de
Google Cloud: los precios cambian.

## Esta instalación

| | |
| --- | --- |
| Proyecto de GCP | `oral-odonto-agenda` |
| Región | `us-central1` |
| Servicio web / jobs | `oral-web` / `oral-migrate`, `oral-scheduled` |
| Base de datos | Cloud SQL `oral-pg` (PostgreSQL 16, `db-f1-micro`, zonal, 10 GB) |
| Instancias mínimas | 1 |
| Estado de Terraform | bucket `gs://oral-odonto-agenda-tfstate`, prefijo `prod` |
| Dominio | `oral.com.ar` (registrado en nic.ar, DNS en Cloudflare) |

Nada de esto es secreto. Los secretos viven en Secret Manager y no se escriben en ningún documento.

## 0. Requisitos

- Una cuenta de Google con **facturación activa**.
- `gcloud`, `terraform` (≥ 1.6) y `gh` (GitHub CLI) instalados y autenticados.
- Permisos de administración sobre el repositorio de GitHub.

## 1. Proyecto y estado de Terraform (una sola vez)

```bash
PROYECTO=oral-odonto-agenda
gcloud auth login
gcloud auth application-default login      # ¡con la MISMA cuenta! Terraform usa estas credenciales
gcloud projects create $PROYECTO --name="ORAL turnos"
gcloud config set project $PROYECTO
gcloud billing projects link $PROYECTO --billing-account=XXXXXX-XXXXXX-XXXXXX

# Bucket privado y versionado para el estado de Terraform
gcloud storage buckets create gs://$PROYECTO-tfstate --location=us-central1 --uniform-bucket-level-access
gsutil versioning set on gs://$PROYECTO-tfstate
gsutil versioning get gs://$PROYECTO-tfstate        # debe decir: Enabled
```

> Si `terraform init` falla con *403 … storage.objects.list*, las credenciales por defecto son de otra
> cuenta (suele pasar con varias cuentas de Google en la misma máquina). Repetí
> `gcloud auth application-default login` con la cuenta correcta.

## 2. Crear la infraestructura

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars      # completá tus datos
terraform init -backend-config="bucket=$PROYECTO-tfstate" -backend-config="prefix=prod"
terraform plan -out=/ruta/FUERA/del/repo/plan.tfplan
terraform apply /ruta/FUERA/del/repo/plan.tfplan
```

**Dos advertencias que salen de la experiencia real:**

- **Los archivos de plan contienen las credenciales en texto plano** (contraseña de la base, cadena de
  conexión, `SECRET_KEY`). Guardalos siempre fuera del repositorio, que es público. CI falla si
  detecta uno versionado.
- **El primer `apply` puede terminar con errores del tipo *Secret … was not found*.** Es una carrera
  de propagación de permisos en Google Cloud: Cloud Run revisa el secreto antes de que el permiso se
  replique. Es transitorio: volvé a correr `terraform plan` y `apply` y completa lo que faltó.

`terraform.tfvars` **no se versiona** (está en `.gitignore`) y por eso no queda respaldado en
ningún lado. Guardá una copia en un gestor de contraseñas o un almacenamiento privado: sin ella hay
que reconstruirlo a mano a partir de `terraform.tfvars.example`.

Si el repositorio se transfiere a otra cuenta u organización de GitHub, **hay que actualizar
`github_repository` y volver a aplicar**: el acceso a GCP está atado a ese nombre.

## 3. Conectar GitHub con GCP

`terraform apply` imprime `github_variables`. Cargalas en el repositorio y creá el environment:

```bash
terraform -chdir=infra/terraform output -json github_variables \
  | python3 -c 'import json,sys,subprocess; [subprocess.run(["gh","variable","set",k,"--body",v],check=True) for k,v in json.load(sys.stdin).items()]'

gh api -X PUT repos/<dueño>/<repo>/environments/production --input - <<< '{}'
```

Si querés que cada despliegue espere una aprobación, agregá *Required reviewers* al environment
`production` (Settings → Environments). El acceso a GCP está restringido por condición a este
repositorio y a jobs que corren dentro de un environment.

## 4. Cargar los secretos opcionales

Terraform crea los secretos vacíos y genera `SECRET_KEY` y `DATABASE_URL`. Los demás se cargan a mano
cuando se necesitan (el lanzamiento sin seña ni WhatsApp no necesita ninguno, ver
[ADR 0003](decisions/0003-lanzamiento-sin-sena-ni-whatsapp.md)):

```bash
printf '%s' 'app-password-del-correo' | gcloud secrets versions add oral-smtp-password --data-file=-
printf '%s' 'APP_USR-...'             | gcloud secrets versions add oral-mercadopago-access-token --data-file=-
printf '%s' 'clave-del-webhook'       | gcloud secrets versions add oral-mercadopago-webhook-secret --data-file=-
```

Después sumalos a `optional_secrets` en `terraform.tfvars` y volvé a aplicar:

```hcl
optional_secrets = ["SMTP_PASSWORD"]
smtp_host        = "smtp.ejemplo.com"
smtp_username    = "turnos@ejemplo.com.ar"
email_from       = "turnos@ejemplo.com.ar"
```

> **Sin `email_from` y `smtp_host` el sistema reserva turnos pero no envía ningún email.**
>
> La configuración vigente (Cloudflare Email Routing para recibir y Brevo para enviar) y sus límites están en
> el [ADR 0008](decisions/0008-correo-cloudflare-y-brevo.md). La clave SMTP se carga sin pasar por el
> historial de la terminal:
>
> ```bash
> printf 'Clave: '; stty -echo; IFS= read -r K; stty echo; echo; \
>   printf '%s' "$K" | gcloud secrets versions add oral-smtp-password --data-file=-; unset K
> ```

## 5. Primer despliegue

```bash
gh workflow run deploy.yml --ref main -f ref=main -f environment=production
gh run watch
```

El workflow construye la imagen, corre las migraciones como job, publica la revisión nueva y hace
una prueba de humo sobre `/health/ready`. Si las migraciones fallan, el tráfico **no** cambia: la
versión anterior sigue sirviendo.

## 6. Crear los administradores

No uses `seed_demo` en producción: carga profesionales y pacientes inventados.

```bash
ops/create_admin.sh admin "Nombre Apellido" correo@ejemplo.com
```

La clave se pide por teclado sin mostrarse (o se pasa un archivo como cuarto argumento). El script es
idempotente y deja el job de migraciones como estaba. **Creá al menos dos administradores:** no hay
recuperación de contraseña por email; si el único administrador pierde la suya, hay que intervenir la
base a mano. Después, cada persona cambia su clave desde el panel (Usuarios).

Los profesionales, sus horarios y la disponibilidad los carga el consultorio desde el panel
(`/app`): ver [OPERATIONS.md](OPERATIONS.md).

## 7. Desplegar una funcionalidad nueva

El ciclo completo, de la idea a producción:

1. **Especificación** del cambio en `docs/specs/` y, si hay una decisión de fondo, un ADR.
2. **Rama corta** (`feat/…` o `fix/…`) y desarrollo con tests. Localmente: `make lint && make test`
   (y `make test-pg` si se tocó la base).
3. **Pull request** con la plantilla. CI corre lint, tests en SQLite y PostgreSQL, migraciones de ida
   y vuelta, build de la imagen con prueba de humo, validación de Terraform y el control de secretos.
4. **Merge a `main`** cuando CI está en verde.
5. **Desplegar**: `gh workflow run deploy.yml --ref main -f ref=main -f environment=production`, o con un
   release versionado (sección siguiente).
6. **Verificar en producción** (`/health/ready`, y recorrer lo que cambió). Si algo anda mal, volver
   atrás (sección 9).

### Cambios de base de datos

Las migraciones corren **antes** de publicar la revisión nueva, así que durante unos segundos conviven
el código viejo y la base nueva. Escribilas compatibles hacia atrás: agregar columnas como `nullable`
y borrar lo que sobre en un release posterior. Toda migración debe ser reversible y está probada de
ida y vuelta en CI.

### Cambios de infraestructura

Se hacen en `infra/terraform/` por pull request y se aplican a mano, con el plan revisado:

```bash
terraform plan -out=/ruta/fuera/del/repo/plan.tfplan     # leerlo entero
terraform apply /ruta/fuera/del/repo/plan.tfplan
```

Nunca `apply` sin haber leído el plan, y nunca `-auto-approve` contra producción.

## 8. Releases versionados

1. Anotá los cambios en `CHANGELOG.md`, bajo `[Unreleased]`.
2. Actions → **Preparar release** → versión (ej. `0.3.0`). Abre un PR con la versión y el changelog.
3. Al mergear ese PR, el workflow **Release** crea el tag, publica el GitHub Release con esas notas y
   dispara el despliegue.

## 9. Volver atrás

```bash
gcloud run revisions list --service oral-web --region us-central1
gcloud run services update-traffic oral-web --region us-central1 --to-revisions=REVISION_ANTERIOR=100
```

Volver la revisión **no deshace las migraciones**: por eso deben ser compatibles hacia atrás.

## 10. Dominio propio

Sin dominio propio el sitio vive en la URL `*.run.app`. Hay dos formas de usar uno, y la diferencia es
plata. Se eligió el **mapeo de dominio de Cloud Run, que es gratis** y solo funciona en algunas
regiones (`us-central1` es una); el balanceador de carga cuesta ~USD 18 por mes y se usa si hace falta
otra región o reglas por ruta, CDN o WAF.

```hcl
custom_domain      = "oral.com.ar"
custom_domain_mode = "mapping"      # o "load_balancer"
```

Si la región no admite mapeo, Terraform corta antes de aplicar con un mensaje claro.

**Orden de los pasos** (cada uno depende del anterior):

1. **Registrar el dominio** a nombre del consultorio, no de la persona que desarrolla. En nic.ar hace
   falta CUIT/CUIL y Clave Fiscal.
2. **Delegar el DNS a Cloudflare** (plan gratuito): agregar el dominio, copiar los dos servidores de
   nombres que da Cloudflare y cargarlos en nic.ar → *Delegaciones* → *Agregar una nueva delegación*
   (una por servidor, **dejando IPv4 e IPv6 vacíos**). Verificar con `dig +short NS oral.com.ar`.
3. **Verificar la propiedad del dominio con Google** (registro TXT que pide Google). Cloud Run no
   permite mapear un dominio sin esa verificación, que debe hacerla la cuenta que ejecuta Terraform.
4. **Activar el mapeo** (`custom_domain` y `custom_domain_mode` arriba) y aplicar. La salida
   `domain_dns_records` lista los registros que hay que cargar en Cloudflare.
5. **Cargar esos registros en Cloudflare con la nube GRIS (*DNS only*), no la naranja (*Proxied*).**
   Con el proxy encendido Google no puede validar el dominio ni emitir el certificado, y el mapeo se
   queda colgado sin un error claro.
6. **Esperar el certificado HTTPS**, que Google emite y renueva solo (de minutos a unas horas).
7. **Actualizar `PUBLIC_BASE_URL`** (variable de GitHub y configuración) y, si hay seña, la URL del
   webhook de Mercado Pago. Redesplegar.

Para el correo de la casilla del consultorio se cargan además registros MX, SPF y DKIM en el mismo
DNS, según el proveedor elegido.

> **Dónde quedan los datos.** `us-central1` guarda la base en Estados Unidos: no en Argentina. El
> sistema no guarda datos de salud ([ADR 0002](decisions/0002-sin-datos-de-salud.md)), pero la
> transferencia internacional de datos personales debe informarse y consentirse; el sitio ya lo hace
> en `/privacidad`.

## 11. Rotar secretos y responder a una filtración

Rotar `SECRET_KEY` cierra todas las sesiones abiertas (hay que volver a entrar al panel). Rotar la
contraseña de la base cambia también el usuario de Cloud SQL.

```bash
cd infra/terraform
terraform plan -replace=random_password.secret_key -replace=random_password.db \
  -out=/ruta/FUERA/del/repo/rotacion.tfplan
terraform apply /ruta/FUERA/del/repo/rotacion.tfplan
# Si falla con "Secret Version … is in DESTROYED state" (mismo orden de propagación que en el primer apply):
terraform plan -out=/ruta/FUERA/del/repo/rot2.tfplan && terraform apply /ruta/FUERA/del/repo/rot2.tfplan

# Los contenedores en ejecución todavía tienen los valores viejos en memoria: redesplegar.
gh workflow run deploy.yml --ref main -f ref=main -f environment=production
```

Después comprobar `/health/ready` (confirma que la base conecta con la contraseña nueva) y un login.

**Si algo sensible llegó al repositorio** (el repo es público):

1. **Rotar primero.** Sacarlo del historial no lo des-expone: pudo haberse copiado.
2. Dejar de rastrear el archivo y sumarlo a `.gitignore`.
3. Purgar el historial (`git filter-branch` o `git filter-repo`) y publicar con `git push --force`. `main`
   está protegida y rechaza el push forzado aun para administradores: hay que desactivar la protección
   (Settings → Branches), publicar y volver a activarla enseguida.
4. GitHub conserva los commits de pull requests cerrados bajo `refs/pull/N/head`: para quitarlos hay que
   pedírselo a soporte de GitHub indicando el repositorio y los identificadores de commit.

## 12. Operación

- Logs: `gcloud run services logs tail oral-web --region us-central1` (salen en JSON y se filtran por
  severidad en Cloud Logging).
- La tarea programada corre sola cada 10 minutos. A mano:
  `gcloud run jobs execute oral-scheduled --region us-central1 --wait`.
- Backups y restauración: [BACKUPS.md](BACKUPS.md).
- Chequeo de configuración: `make prod-check` con las variables de producción exportadas.
- Día a día del consultorio: [OPERATIONS.md](OPERATIONS.md).
