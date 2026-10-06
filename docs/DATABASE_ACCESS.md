# Acceso manual a la base de datos

Para mirar o corregir datos de producción a mano (DBeaver, psql, TablePlus, Cloud SQL Studio).

**No se usa la contraseña de la aplicación.** Cada persona entra con **su propia cuenta de Google**
(autenticación IAM de Cloud SQL): no hay contraseña que se pueda filtrar ni rotar, cada acceso queda a
nombre de quien lo hizo y se revoca sacando la cuenta de Terraform.

## Datos de conexión

| | |
| --- | --- |
| Instancia | `oral-odonto-agenda:us-central1:oral-pg` |
| Motor | PostgreSQL 16 |
| Base | `oral` |
| Usuario | tu email de Google, tal cual (ej. `juanalmada1395@gmail.com`) |
| Contraseña | ninguna: la pone el proxy |
| Host / puerto | `127.0.0.1` / `5433` (a través del proxy, ver abajo) |

La base **no acepta conexiones directas desde internet**: no tiene redes autorizadas. Siempre se entra a
través del proxy oficial de Cloud SQL, que cifra la conexión y verifica tu identidad.

## Paso a paso (una sola vez)

1. Instalar el proxy: `brew install cloud-sql-proxy`
2. Autenticar tu cuenta: `gcloud auth application-default login` (la misma cuenta que figura en
   `db_iam_users`).

## Cada vez que te quieras conectar

1. Abrí una terminal y dejala corriendo:

   ```bash
   cloud-sql-proxy --auto-iam-authn --port 5433 oral-odonto-agenda:us-central1:oral-pg
   ```

   Cuando diga *ready for new connections*, está listo. Al terminar, `Ctrl+C`.

2. En DBeaver: **Nueva conexión → PostgreSQL**, con host `127.0.0.1`, puerto `5433`, base `oral`, tu email
   como usuario y **la contraseña vacía**.

**Cloud SQL Studio** (desde la consola de Google Cloud): elegí la base `oral` y *Autenticación de la base
de datos de IAM*. No hace falta el proxy.

## Qué se puede y qué no

- **Sí:** leer y modificar datos (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) en todas las tablas, incluidas
  las que agreguen las migraciones futuras.
- **No:** cambiar la estructura (`CREATE`, `ALTER`, `DROP`). Eso lo hacen solo las migraciones de Alembic;
  un cambio a mano desalinearía la base y el código y rompería el siguiente despliegue.

**Cuidado al escribir a mano:** la base no pasa por las validaciones de la app. Un `UPDATE` sin `WHERE`
cambia todas las filas. Antes de corregir algo, hacé un `SELECT` con el mismo filtro. Si algo sale mal,
existe recuperación a un punto en el tiempo de los últimos 7 días ([BACKUPS.md](BACKUPS.md)).

## Sumar o quitar a una persona

1. Agregá (o sacá) su email en `db_iam_users` en `terraform.tfvars` y aplicá con plan revisado.
2. Al sumar, dale permisos sobre las tablas: `ops/grant_db_access.sh <email>`.

Al quitarla de Terraform pierde el acceso de inmediato.
