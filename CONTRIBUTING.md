# Contributing

## Entorno

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head && python -m app.tasks.seed_demo
uvicorn app.main:app --reload
```

## Antes de cada commit

```bash
make lint
make test
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/oral_test make test-pg   # si tocaste la base
```

Los tests corren sobre SQLite y sobre PostgreSQL. Sobre PostgreSQL se aplican las migraciones reales,
se prueban la restricción de superposición y la concurrencia, y hay un chequeo que falla si los
modelos y las migraciones se desalinean: **si cambiás un modelo, agregá su migración**.

Los tests nunca leen tu `.env` (podría tener credenciales reales de SMTP o Mercado Pago).

## Convenciones

- Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `ci:`.
- Mensajes de error que ve el paciente o el consultorio: **en español**, claros y sin detalles
  técnicos. Los mensajes internos y los comentarios del código, en inglés.
- Toda fecha u hora de negocio se calcula con `app.core.clock`, nunca con `datetime.now()`.
- Nada de secretos en el repo (es público).

## Pull requests

Usá la plantilla. CI corre lint, tests (SQLite y PostgreSQL), migraciones ida y vuelta, build de la
imagen Docker con prueba de humo y validación de Terraform.

## Releases

1. Anotá los cambios en `CHANGELOG.md`, bajo `[Unreleased]`.
2. Actions → **Preparar release** → versión (`0.3.0`). Abre un PR con la versión y el changelog.
3. Al mergearlo, se crea el tag, se publica el GitHub Release con esas notas y se despliega a
   producción.

Localmente equivale a `python ops/release.py prepare 0.3.0`.
