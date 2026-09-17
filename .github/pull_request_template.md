## Qué cambia

<!-- Resumen corto y por qué. -->

## Cómo se probó

- [ ] `pytest` (SQLite) y, si toca la base, `TEST_DATABASE_URL=... pytest` (PostgreSQL)
- [ ] Probado a mano en `/reservar` y/o `/app` (desktop y celular)

## Checklist

- [ ] Migración de Alembic si cambian los modelos (el test de desvío en CI la exige)
- [ ] Nota en `CHANGELOG.md` bajo `[Unreleased]`
- [ ] Sin secretos ni datos de pacientes reales en el diff
