# Mudanza de la base de Cloud SQL a Neon

Procedimiento para pasar la base de producción a Neon. Qué se decidió y por qué: [ADR 0011](decisions/0011-neon-postgres.md).
Qué debe cumplirse al terminar: [especificación 0010](specs/0010-base-en-neon.md).
Para deshacerlo: [VOLVER_A_CLOUD_SQL.md](VOLVER_A_CLOUD_SQL.md).

Tiempo total: media jornada repartida en varios días (la mudanza en sí son ~30 minutos). Cada paso dice qué
comprobar antes de seguir. **Si una comprobación falla, no avances: frená y revisá.**

> ⚠ **Los volcados de la base contienen datos de pacientes.** Se guardan fuera del repositorio, en un
> disco cifrado, y se borran cuando terminan de servir. Ningún volcado, URL de conexión ni contraseña se
> pega en un chat, un issue o un commit.

> ⚠ **La suite de tests borra el esquema** (`DROP SCHEMA public CASCADE`). Nunca se corre contra la base
> `oral` de producción: solo contra una base de pruebas aparte (paso 3).

## Qué cambia y qué no

| Cambia | No cambia |
| --- | --- |
| La base: Cloud SQL → Neon | Cloud Run (web y jobs), Cloud Scheduler, Secret Manager, el dominio y el despliegue |
| Tarea programada: cada 10 → cada 15 minutos | Ninguna pantalla ni regla para pacientes ni consultorio |
| Monitor de disponibilidad: `/health/ready` → `/health` | |
| Se suma una copia diaria a un bucket propio, y una alerta si falla algún job | |

## Requisitos (una sola vez)

```bash
brew install postgresql@16 cloud-sql-proxy     # psql, pg_dump y pg_restore 16
export PATH="$(brew --prefix postgresql@16)/bin:$PATH"
pg_dump --version                                # debe decir 16.x
gcloud auth login && gcloud auth application-default login   # con la cuenta dueña del proyecto
```

---

## Fase 1 · Preparar la infraestructura (no mueve la base)

Esta fase deja listo el bucket de copias, la alerta, el cron de 15 minutos y el monitor nuevo. La app
sigue usando Cloud SQL.

1. **Mergear el pull request** `feat/neon-postgres` (CI en verde) y dejar que el workflow *Deploy* publique.
   El código nuevo solo agrega una validación: en producción rechaza una base remota sin SSL. El socket de
   Cloud SQL está exento, así que la app arranca igual.
2. **Revisar el plan de Terraform** (en `infra/terraform`, con tu `terraform.tfvars`):

   ```bash
   terraform init -backend-config="bucket=oral-odonto-agenda-tfstate" -backend-config="prefix=prod"
   terraform plan          # sin -out: los planes guardados traen contraseñas en texto plano
   ```

   Debe decir **`0 to destroy`** y mostrar `has moved` para los recursos de Cloud SQL (solo cambian de
   nombre interno). Crea: el bucket de copias, la cuenta de servicio de copias, la alerta de jobs fallidos y
   la API de Storage. Modifica: el cron (10 → 15 min), el monitor (`/health`) y su alerta. La línea
   `revision … -> null` del servicio web es ruido conocido.

   > Si el plan muestra que **se destruye o reemplaza** la instancia de Cloud SQL, no apliques: avisá.

3. **Aplicar** (`terraform apply`, con tu visto bueno al plan) y comprobar:
   - [ ] Cloud Scheduler → `oral-scheduled` corre cada 15 minutos.
   - [ ] La web y `/health/ready` responden bien.

## Fase 2 · Crear la base en Neon

1. Entrá a <https://neon.com> y creá la cuenta con el Google o GitHub del consultorio/administración
   ([ADR 0007](decisions/0007-titularidad-de-repositorio-y-nube.md): la titularidad es del negocio; usá un
   email que no dependa de una sola persona). Activá la verificación en dos pasos.
2. **Crear proyecto:** nombre `oral`, **Postgres 16**, región **AWS US East 2 (Ohio)** (la más cercana a
   `us-central1` entre las que ofrece el plan gratuito; si no está, la de Virginia).
3. En *Roles & Databases* dejá: base **`oral`** y un rol **`oral_app`** que la use (si el formulario inicial
   no deja elegir los nombres, creá la base y el rol desde esa pantalla). Creá además una segunda base,
   **`oral_test`**, y otra, **`oral_ensayo`**.
4. En *Connection Details* elegí la base `oral`, el rol `oral_app` y **desmarcá "Connection pooling"**: la
   dirección directa no lleva `-pooler` en el nombre. Con esa dirección armá estas dos formas, cambiando
   `CLAVE` y `HOST` por los reales:

   | Para | Forma |
   | --- | --- |
   | `psql`, `pg_dump`, `pg_restore` | `postgresql://oral_app:CLAVE@HOST/oral?sslmode=require` |
   | La aplicación (Secret Manager) | `postgresql+psycopg://oral_app:CLAVE@HOST/oral?sslmode=require&connect_timeout=15` |

   Quitá `channel_binding=require` si aparece. Guardalas en tu gestor de contraseñas.
5. Comprobar: [ ] `psql "postgresql://oral_app:CLAVE@HOST/oral?sslmode=require" -c "select version();"` muestra
   PostgreSQL 16 (la primera consulta puede tardar unos segundos: la base estaba dormida).

## Fase 3 · Probar que Neon cumple las reglas de la agenda

Es el criterio 13 de la especificación: las migraciones y la suite completa sobre la base de Neon.

```bash
# base de PRUEBAS (oral_test), nunca "oral"
export TEST_DATABASE_URL='postgresql+psycopg://oral_app:CLAVE@HOST/oral_test?sslmode=require'
make test-pg
unset TEST_DATABASE_URL
```

- [ ] Toda la suite pasa, incluido `test_concurrent_bookings_of_the_same_slot_only_one_wins`.

Si algo falla acá, es lo más importante que va a salir de toda la mudanza: **no sigas** y revisá el error.

## Fase 4 · Ensayo de la mudanza (con una copia, sin tocar producción)

Se hace exactamente lo que se hará de verdad, pero contra la base `oral_ensayo`.

1. En una terminal, dejá abierto el proxy a Cloud SQL (`Ctrl+C` al terminar):

   ```bash
   cloud-sql-proxy --auto-iam-authn --port 5433 oral-odonto-agenda:us-central1:oral-pg
   ```

2. En otra, volcar Cloud SQL (solo lee) con tu cuenta de Google ([DATABASE_ACCESS.md](DATABASE_ACCESS.md)):

   ```bash
   cd ~    # fuera del repositorio
   pg_dump --format=custom --no-owner --no-privileges \
     -h 127.0.0.1 -p 5433 -U juanalmada1395@gmail.com oral -f ~/oral-migracion.dump
   pg_restore --list ~/oral-migracion.dump | head     # debe listar tablas, no dar error
   ```

3. Restaurar en el ensayo y comparar:

   ```bash
   pg_restore --no-owner --no-privileges --exit-on-error \
     -d "postgresql://oral_app:CLAVE@HOST/oral_ensayo?sslmode=require" ~/oral-migracion.dump
   ```

   Contar filas en **las dos** bases con esta consulta (en Cloud SQL por el proxy, en Neon con la URL de psql):

   ```sql
   SELECT table_name,
          (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text::int AS filas
   FROM information_schema.tables
   WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
   ORDER BY 1;
   SELECT version_num FROM alembic_version;
   SELECT conname FROM pg_constraint WHERE contype = 'x';   -- la restricción contra turnos superpuestos
   ```

   - [ ] Las filas por tabla coinciden.
   - [ ] `alembic_version` es igual en ambas.
   - [ ] La restricción de exclusión aparece en Neon.

4. Borrar el ensayo: `psql "…/oral_ensayo?sslmode=require" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"`.

## Fase 5 · La mudanza

**Cuándo:** de madrugada y con el consultorio avisado (no cargar ni reservar turnos durante ~30 minutos).
Los pacientes que entren en ese rato pueden ver errores o perder una reserva en curso.
Elegí una ventana que no sea el domingo de 03:00 a 06:00 (mantenimiento de Cloud SQL).

1. **Copia de seguridad extra de Cloud SQL** (red de seguridad):

   ```bash
   gcloud sql backups create --instance=oral-pg
   gcloud sql backups list --instance=oral-pg --limit=3      # la nueva figura SUCCESSFUL
   ```

2. **Volcar producción** (proxy abierto como en la fase 4):

   ```bash
   rm -f ~/oral-migracion.dump
   pg_dump --format=custom --no-owner --no-privileges \
     -h 127.0.0.1 -p 5433 -U juanalmada1395@gmail.com oral -f ~/oral-migracion.dump
   ```

3. **Restaurar en Neon (`oral`)** y comparar igual que en la fase 4 (filas, `alembic_version`, restricción):

   ```bash
   pg_restore --no-owner --no-privileges --exit-on-error \
     -d "postgresql://oral_app:CLAVE@HOST/oral?sslmode=require" ~/oral-migracion.dump
   ```

   - [ ] Todo coincide. Si no, **no sigas**: la app todavía usa Cloud SQL y no pasó nada.

4. **Cargar la conexión en Secret Manager** como versión nueva (pasa a ser la "latest"). La URL no queda en
   el historial ni en pantalla:

   ```bash
   read -rs "NEON_URL?Pegá la URL de la APLICACIÓN (postgresql+psycopg://…): " ; echo
   printf '%s' "$NEON_URL" | gcloud secrets versions add oral-database-url --data-file=-
   unset NEON_URL
   gcloud secrets versions list oral-database-url          # aparece una versión nueva, habilitada
   ```

   (En bash en vez de zsh: `read -rsp "Pegá la URL…: " NEON_URL`.)

5. **Cambiar a Neon en Terraform.** En `terraform.tfvars` agregá `database_backend = "neon"` (dejá
   `keep_cloud_sql_instance` en `true`, que es el valor por defecto) y:

   ```bash
   terraform plan
   ```

   Debe mostrar, y solo esto: se crean el job `oral-backup` y su schedule; se **destruyen** `run_sql_client` y
   la **versión de secreto de Cloud SQL** (no la nueva: esa la cargaste a mano y Terraform no la conoce); el
   servicio y los jobs pierden el volumen `/cloudsql`. **La instancia de Cloud SQL no se toca.**

   > Si el plan destruye la instancia `oral-pg`, la base o el usuario: frená, `keep_cloud_sql_instance`
   > debe estar en `true`.

   Con tu visto bueno: `terraform apply`. Eso crea una revisión nueva del servicio ya apuntando a Neon.

6. **Comprobar la conexión desde Cloud Run:**

   ```bash
   gcloud run jobs execute oral-migrate --region us-central1 --wait      # no debe aplicar nada nuevo y terminar bien
   gcloud run jobs execute oral-scheduled --region us-central1 --wait   # termina bien
   curl -fsS https://oral.com.ar/health/ready                             # {"status":"ready"} (puede tardar unos segundos)
   ```

7. **Probar a mano** (como un paciente y como recepción):
   - [ ] Reservar un turno de prueba desde `/reservar` → llega el email.
   - [ ] Entrar al panel `/app`, ver la agenda con los turnos reales.
   - [ ] Cancelar el turno de prueba.
   - [ ] Intentar reservar dos veces el mismo horario (dos pestañas): la segunda debe rechazarse.
   - [ ] Logs sin errores de base: `gcloud run services logs read oral-web --region us-central1 --limit 50`.

8. **Primera copia propia, ya:**

   ```bash
   gcloud run jobs execute oral-backup --region us-central1 --wait
   gcloud storage ls -l gs://oral-odonto-agenda-oral-backups/        # un oral_AAAAMMDD_HHMMSS.dump de tamaño > 0
   ```

9. **Borrar el volcado local**: `rm -f ~/oral-migracion.dump` (o dejalo en un lugar cifrado hasta la fase 7).
   Avisale al consultorio que ya puede trabajar normal.

Anotá acá fecha y hora de la mudanza: `__________`. Desde ese momento los datos nuevos solo existen en Neon.

> **Si algo sale mal en esta fase**, la vuelta rápida está en [VOLVER_A_CLOUD_SQL.md](VOLVER_A_CLOUD_SQL.md),
> sección *Vuelta rápida*. Cuanto antes se decida, menos datos hay que copiar de vuelta.

## Fase 6 · Vigilar durante 14 días

| Cuándo | Qué mirar | Esperado |
| --- | --- | --- |
| Día 1-2 | Una copia nueva cada madrugada en el bucket | un `.dump` por día |
| Día 7 | Neon → *Usage* → horas de cómputo | menos de ~25 horas (proyecta < 100/mes). Si proyecta más de ~80, pasar `scheduler_cron` a `*/30 * * * *` |
| Día 7 | Llegó algún email de alerta de jobs fallidos | ninguno, o explicado |
| Día 7 | **Ensayo de restauración**: bajar la última copia y restaurarla en `oral_ensayo` ([BACKUPS.md](BACKUPS.md)) | la app levanta contra ella |
| Día 14 | Facturación de Google Cloud: el gasto diario bajó | el costo de Cloud SQL sigue ahí hasta la fase 7 |

## Fase 7 · Retirar Cloud SQL (no antes de los 14 días)

Condiciones: copias diarias sin huecos, restauración probada, plan de cómputo de Neon dentro del límite y
cero incidentes sin explicar.

1. **Copia final** de Cloud SQL, guardada fuera de Google si es posible:

   ```bash
   gcloud sql backups create --instance=oral-pg
   pg_dump --format=custom --no-owner --no-privileges \
     -h 127.0.0.1 -p 5433 -U juanalmada1395@gmail.com oral -f ~/oral-cloudsql-final-$(date +%F).dump
   ```

   (Con el proxy abierto. La base de Cloud SQL ya está desactualizada respecto de Neon: esta copia es solo el
   último estado antes de borrarla. Guardala cifrada. **No** va al bucket de copias: ese borra a los 30 días.)

2. **Quitar las protecciones**, en dos pasos deliberados. En `terraform.tfvars`:

   ```
   db_deletion_protection = false
   ```

   `terraform plan` → solo cambia las dos protecciones de la instancia (cero `destroy`) → `terraform apply`.

3. **Eliminar la instancia.** En `terraform.tfvars`: `keep_cloud_sql_instance = false`. `terraform plan` debe
   destruir exactamente: la instancia `oral-pg`, la base, el usuario de la app, su contraseña, los usuarios
   IAM de `db_iam_users` y sus roles. Con tu visto bueno: `terraform apply`.

4. **Actualizar la documentación**: la tabla *Esta instalación* de [DEPLOYMENT.md](DEPLOYMENT.md) (base,
   costo) y pasar la especificación 0010 de *Borrador* a *Implementada*.
5. Un mes después: confirmar en Facturación que el total mensual está por debajo de USD 10.

## Si algo no coincide con esta guía

Los nombres de recursos (`oral-pg`, `oral-database-url`, `oral-odonto-agenda-oral-backups`, `oral-backup`) salen
de `service_name = "oral"` y del proyecto `oral-odonto-agenda`. Si tu instalación usa otros, reemplazalos.
La interfaz de Neon cambia con frecuencia: los nombres de los menús pueden variar un poco.
