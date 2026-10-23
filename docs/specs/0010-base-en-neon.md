# 0010 · La base vive en Neon y se respalda sola

**Estado:** Implementada (mudanza ejecutada el 23/10/2026) · **Fecha:** octubre de 2026

## Objetivo

Bajar el costo mensual de la plataforma de ~USD 20 a **menos de USD 10** sin perder datos ni ninguna de las
garantías de la agenda. La base pasa de Cloud SQL a PostgreSQL en Neon (plan gratuito), con una copia
diaria propia fuera de Neon, y la vuelta a Cloud SQL queda preparada y documentada por si el consultorio crece.
Decisión y alternativas: [ADR 0011](../decisions/0011-neon-postgres.md).

## Fuera de alcance

- **Ningún cambio visible** para pacientes ni para el consultorio: mismas pantallas, mismas reglas.
- Alta disponibilidad, réplicas o ramas de Neon como método de backup.
- Migrar datos de otro sistema: se copian los de producción tal cual, una sola vez, con el procedimiento de
  [MIGRACION_A_NEON.md](../MIGRACION_A_NEON.md).
- Cambiar de nube el servicio web, los jobs o el scheduler: siguen en Cloud Run.

## Reglas

1. **La base se elige por configuración**, no por código: `database_backend = "neon"` o `"cloud_sql"` en
   Terraform. La aplicación solo recibe un `DATABASE_URL` y no distingue a quién le habla.
2. **Una base remota se conecta siempre cifrada.** En producción la aplicación se niega a arrancar si el
   `DATABASE_URL` apunta a un servidor por red sin pedir SSL (`sslmode=require`, `verify-ca` o
   `verify-full`). El socket local de Cloud SQL (`host=/cloudsql/...`) queda exento: ya va cifrado por el
   conector.
3. **Se mantienen todas las garantías de la agenda** ([ADR 0001](../decisions/0001-postgresql.md) y
   [0010](../decisions/0010-un-solo-sillon.md)): la restricción de exclusión y los locks funcionan igual
   en Neon. Se comprueba corriendo las migraciones y la suite sobre PostgreSQL antes de cambiar nada.
4. **Hay una copia diaria propia, fuera de Neon.** Cada día se vuelca la base completa a un bucket del
   proyecto y se conserva 30 días. La copia se valida antes de guardarse: un volcado vacío o ilegible cuenta
   como fallo y nunca llega al bucket.
5. **Si falla la tarea programada o la copia, alguien se entera.** Llega un email a `alert_email`.
6. **Ningún chequeo automático despierta la base.** Neon se suspende tras 5 minutos sin uso y el plan gratuito
   tiene un tope de horas de cómputo. El monitor de disponibilidad pregunta por el proceso (`/health`), no por
   la base. Solo despiertan la base el uso real y la tarea programada (cada 15 minutos por defecto).
7. **Volver a Cloud SQL es un cambio de configuración**, no de código, con procedimiento escrito
   ([VOLVER_A_CLOUD_SQL.md](../VOLVER_A_CLOUD_SQL.md)).
8. **La instancia de Cloud SQL no se borra el día de la mudanza.** Queda apagada de la aplicación pero
   existente un mínimo de 14 días como red de seguridad, y recién se elimina con una copia final guardada.

9. **El orden alfabético no cambia.** Las listas ordenadas por apellido salen igual que con Cloud SQL
   (`en_US`): la base de Neon se crea con collation ICU `en-US`, no con la `C.UTF-8` por defecto.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | Dado producción, cuando el `DATABASE_URL` es de Neon con `sslmode=require`, entonces la configuración es válida | `test_production_accepts_remote_database_with_ssl` |
| 2 | Dado producción, cuando el `DATABASE_URL` es remoto sin SSL (o con `sslmode=disable`/`prefer`), entonces la app no arranca | `test_production_rejects_remote_database_without_ssl` |
| 3 | Dado producción, cuando el `DATABASE_URL` usa el socket de Cloud SQL, entonces la configuración es válida | `test_production_accepts_cloud_sql_socket` |
| 4 | Dado desarrollo, cuando la base es local sin SSL, entonces no se exige | `test_development_does_not_require_ssl` |
| 5 | Dado el chequeo `/health`, cuando la base no responde, entonces `/health` sigue respondiendo y no abre conexiones | `test_liveness_never_touches_the_database` |
| 6 | Dado el chequeo `/health/ready`, cuando la base no responde, entonces devuelve 503 | `test_readiness_reports_unavailable_database` |
| 7 | Dado el monitor de Terraform, entonces apunta a `/health` y no a `/health/ready` | `test_uptime_check_does_not_wake_the_database` |
| 8 | Dado `ops/neon_backup.sh` con un volcado válido, entonces deja un archivo `oral_AAAAMMDD_HHMMSS.dump` completo en el destino y ninguno parcial | `test_backup_stores_a_valid_dump` |
| 9 | Dado un `DATABASE_URL` de SQLAlchemy (`postgresql+psycopg://`), entonces el volcado usa el formato que entiende `pg_dump` | `test_backup_translates_sqlalchemy_url` |
| 10 | Dado un volcado vacío o ilegible, entonces el script falla y no deja nada en el destino | `test_backup_rejects_empty_or_unreadable_dump` |
| 11 | Dado que falta `DATABASE_URL`, entonces el script falla sin intentar nada | `test_backup_requires_database_url` |
| 12 | Dado un `terraform validate` y un `plan` revisado, entonces la infraestructura es coherente en los dos modos (`neon` y `cloud_sql`) | CI → job *Terraform* + revisión del plan |
| 13 | Dadas las migraciones de ida y vuelta y la suite sobre PostgreSQL, entonces pasan sobre la base de Neon | `make test-pg` contra Neon (paso 3 de la migración) |

Los criterios 12 y 13 y las reglas 5, 8 y 9 no se pueden probar con un test unitario: se verifican con los
pasos de [MIGRACION_A_NEON.md](../MIGRACION_A_NEON.md), que dejan constancia de cada comprobación.

## Casos límite y errores

- **Primera consulta después de una pausa:** la base tarda unos segundos en despertar. El pool de conexiones
  ya prueba cada conexión antes de usarla (`pool_pre_ping`) y la conexión tiene un tiempo de espera de 15
  segundos (`connect_timeout=15` en el `DATABASE_URL`). El paciente ve la página un poco más lenta, nunca un error.
- **Neon con problemas:** `/health/ready` responde 503 y Cloud Run no manda tráfico a una instancia nueva
  hasta que la base responda. La tarea programada falla, reintenta una vez y dispara la alerta por email.
- **Se agota el cómputo gratuito del mes:** Neon suspende la base hasta el mes siguiente y la agenda deja
  de funcionar. Para evitarlo, el cron es de 15 minutos y se revisa el consumo la primera semana. Si no
  alcanza: `scheduler_cron` más espaciado, pasar a un plan de pago de Neon o volver a Cloud SQL.
- **La copia diaria falla dos días seguidos:** la alerta llega el primer día; no se espera al segundo.

## Configuración

| Variable (Terraform) | Por defecto | Efecto |
| --- | --- | --- |
| `database_backend` | `cloud_sql` | `neon` o `cloud_sql`. Cambiarlo a `neon` es el paso final de la mudanza |
| `keep_cloud_sql_instance` | `true` | Mantiene la instancia de Cloud SQL aunque la app use Neon (red de seguridad) |
| `scheduler_cron` | `*/15 * * * *` | Frecuencia de la tarea programada (antes cada 10 minutos) |
| `backup_cron` | `30 3 * * *` | Hora de la copia diaria (hora de Buenos Aires) |
| `backup_retention_days` | `30` | Días que se conserva cada copia en el bucket |
| `backup_image` | `postgres:16-alpine` | Debe ser de la misma versión mayor que la base de Neon, o superior |

El `DATABASE_URL` de Neon **no** está en Terraform ni en el repositorio: se carga en Secret Manager con
`gcloud secrets versions add` (paso 5 de la migración).
