# 0011 · La base pasa de Cloud SQL a Neon, con copia diaria propia

**Estado:** vigente (la mudanza se ejecuta con [MIGRACION_A_NEON.md](../MIGRACION_A_NEON.md)) · **Fecha:** octubre de 2026
**Reemplaza en parte a:** [0004](0004-google-cloud-run.md) (la base) y [0009](0009-disponibilidad-y-acceso-a-la-base.md) (acceso y protección de la instancia).

## Contexto

El gasto mensual en Google Cloud ronda los **USD 20** y el tope que se quiere sostener es **USD 10 por
todo**. La mayor parte es la base: Cloud SQL cobra por tener la instancia encendida, no por los datos. Con
la configuración mínima (`db-f1-micro`, disco SSD de 10 GB, IPv4 pública, copias y registros de
recuperación) la base sola cuesta del orden de USD 17-19 por mes, y la web con una instancia siempre
encendida casi no suma (una instancia ociosa de 1 CPU y 512 MiB cuesta muy poco).

Volumetría medida en producción en octubre de 2026: **432 filas y ~1,2 MB de datos** (9,5 MB la base
completa, casi todo catálogo de PostgreSQL), con ~14 filas por turno. Proyectando ~220 turnos por mes, a un
año son ~40.000 filas y menos de 35 MB. El tamaño no condiciona ninguna opción; lo que cuesta es la
instancia encendida.

## Decisión

1. **Producción usa PostgreSQL en Neon, plan gratuito**, en una región de Estados Unidos cercana a `us-central1`,
   creado con PostgreSQL 16 (la misma versión mayor que hoy). Se conecta por el endpoint **directo** (sin
   pooler), con `sslmode=require`: la aplicación ya tiene su propio pool chico, el pooler de Neon traba
   comportamientos que las migraciones y los locks de la agenda usan, y el plan gratuito alcanza.
2. **Copia diaria propia fuera de Neon**: un job de Cloud Run hace `pg_dump` cada madrugada a un bucket del
   proyecto con retención de 30 días. El plan gratuito de Neon solo conserva ~6 horas de historia, que no
   alcanza para deshacer un error que se descubre al día siguiente.
3. **La tarea programada pasa de 10 a 15 minutos**, y el monitor de disponibilidad deja de consultar la
   base. Neon se suspende tras 5 minutos sin uso y el plan gratuito da ~100 horas de cómputo al mes: una
   consulta cada pocos minutos, las 24 horas, lo agotaría. Con 15 minutos la base duerme buena parte del
   día. Las reglas de negocio toleran el cambio: las señas se liberan hasta 15 minutos más tarde y los
   avisos con horas de margen no se notan.
4. **La elección es configuración, no código** (`database_backend` en Terraform). La instancia de Cloud SQL
   no se borra el día de la mudanza: queda 14 días como red de seguridad y se elimina con una copia final.
   La vuelta a Cloud SQL está escrita en [VOLVER_A_CLOUD_SQL.md](../VOLVER_A_CLOUD_SQL.md).
5. **`min_instances = 1` se mantiene.** No era el costo importante y evita que el primer paciente espere.

## Alternativas descartadas

- **Quedarse en Cloud SQL.** Es lo más tranquilo (SLA, copias de 14 días, recuperación a un punto en el
  tiempo), pero no baja de ~USD 17-19 solo por la base. Sigue siendo el plan B (ver abajo).
- **DigitalOcean (Postgres administrado).** Cuesta ~USD 15 por mes el plan más chico: no ahorra, y mudar
  también la web, los jobs y el despliegue implicaría reescribir la infraestructura.
- **Postgres propio en una VM barata.** Entra en el presupuesto, pero parches, copias y seguridad pasarían a
  ser responsabilidad de una persona, con datos personales de pacientes.
- **Supabase gratuito.** Pausa el proyecto tras una semana sin actividad; no es apto para una agenda.
- **Pooler de Neon (PgBouncer).** Se descartó para no depender de su modo de transacciones.

## Consecuencias

- **Costo estimado: USD 2-5 por mes** (Cloud Run, bucket de copias y centavos de Secret Manager y
  Scheduler), contra ~USD 20. A confirmar en la facturación el primer mes completo.
- **Menos garantías operativas que Cloud SQL:** el plan gratuito de Neon no tiene SLA, y hubo incidentes
  menores en 2026 (arranques lentos de bases en una región). Para un consultorio, unos minutos sin reservas
  online son tolerables: se atiende por teléfono. No hay datos de salud ([ADR 0002](0002-sin-datos-de-salud.md)).
- **Primer pedido tras una pausa:** unos segundos más lento. El pool ya prueba cada conexión antes de usarla.
- **Se pierde la autenticación IAM y el proxy** para entrar a mano. Se reemplaza por un rol propio en Neon
  ([DATABASE_ACCESS.md](../DATABASE_ACCESS.md)). A diferencia de la cuenta IAM, ese rol puede alterar la
  estructura; la regla de "solo migraciones" pasa a ser una convención, no un permiso.
- **Tope de cómputo:** si se agota el mes, Neon suspende la base. Se mitiga con el cron de 15 minutos y se
  revisa el consumo la primera semana.
- **Un nuevo punto de falla a vigilar:** la alerta por email avisa si falla la tarea programada o la copia.
- **La base sale de GCP:** viaja por internet cifrada (TLS obligatorio, regla 2 de la
  [especificación 0010](../specs/0010-base-en-neon.md)) y su contraseña vive en Secret Manager.

## Cuándo reabrir esta decisión

Volver a Cloud SQL (o pasar a un plan de pago de Neon) si ocurre cualquiera de estas:

- El consultorio depende de la agenda online todo el día o se activa la **seña con Mercado Pago** de forma
  que una caída implique perder cobros.
- Se agota el cómputo gratuito de Neon más de un mes, o los arranques lentos molestan a los pacientes.
- La base supera ~300 MB o los turnos superan ~1.000 por mes.
- Un incidente de Neon deja la agenda caída más de unas pocas horas.
- El presupuesto deja de ser el límite.

Procedimiento: [VOLVER_A_CLOUD_SQL.md](../VOLVER_A_CLOUD_SQL.md). Es un cambio de configuración más una
restauración de datos, sin cambios de código.
