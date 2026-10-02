## Qué cambia

<!-- Resumen corto y por qué. -->

## Cómo se probó

- [ ] `pytest` (SQLite) y, si toca la base, `TEST_DATABASE_URL=... pytest` (PostgreSQL)
- [ ] Probado a mano en `/reservar` y/o `/app` (desktop y celular)

## Checklist

- [ ] Migración de Alembic si cambian los modelos (el test de desvío en CI la exige)
- [ ] Especificación (`docs/specs/`) o decisión (`docs/decisions/`) actualizada si cambia el comportamiento o una decisión de fondo
- [ ] Nota en `CHANGELOG.md` bajo `[Unreleased]`
- [ ] Sin secretos, `.env`, planes de Terraform (`tfplan*`) ni datos de pacientes reales en el diff
