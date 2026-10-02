# 0004 · Cloud Run + Cloud SQL en `us-central1`, con dominio por mapeo

**Estado:** vigente · **Fecha:** octubre de 2026

## Contexto

Un consultorio chico necesita algo barato, sin servidores que mantener, con backups y recuperación
de datos que no dependan de una persona. El tráfico es bajo y a ráfagas.

## Decisión

- **Cloud Run** para la web y dos jobs (migraciones y tarea programada); **Cloud SQL** PostgreSQL
  `db-f1-micro`, zonal, 10 GB, con backups diarios, 14 días de retención y recuperación a un punto
  en el tiempo.
- Región **`us-central1`**: es la más barata y soporta el **mapeo de dominio gratuito** de Cloud Run.
  `southamerica-east1` (São Paulo) no lo soporta y obligaría a un balanceador (~USD 18 por mes).
- `min_instances = 1`: una instancia siempre encendida evita que la primera visita espere el
  arranque. Cuesta unos USD 10 por mes extra.
- Infraestructura en Terraform; despliegues desde GitHub Actions con **OIDC**, sin claves de servicio.

Costo total aproximado: USD 20-23 por mes (verificar en la calculadora de Google Cloud).

## Alternativas descartadas

- **Postgres gratuito de terceros** (Neon, Supabase): sin SLA ni backups garantizados, sacan los
  datos de GCP (un procesador más para declarar) y Supabase se pausa tras 7 días sin actividad.
- **PostgreSQL en una VM `e2-micro`**: más barato, pero los backups y los parches pasan a ser una
  tarea permanente de una persona.
- **Parquet en GCS consultado con BigQuery**: es analítica, no transacciones. No hay `UPDATE`
  por fila, bloqueos ni restricciones de exclusión, así que dos reservas simultáneas se confirmarían.

## Consecuencias

- Los datos quedan en Estados Unidos, no en Argentina (ver [0002](0002-sin-datos-de-salud.md)).
- Pasar a São Paulo exige `custom_domain_mode = "load_balancer"`.
- Procedimiento completo en [DEPLOYMENT.md](../DEPLOYMENT.md).
