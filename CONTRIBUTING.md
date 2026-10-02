# Contribuir

Cómo trabajar en este proyecto. La versión corta para herramientas de programación asistida está en
[AGENTS.md](AGENTS.md); la de infraestructura, en [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Entorno

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head && python -m app.tasks.seed_demo
uvicorn app.main:app --reload
```

## Cómo se hace un cambio

Ningún cambio de comportamiento entra "a ojo". El camino es siempre el mismo:

1. **Especificar.** Si cambia lo que el sistema hace, escribí o ajustá la especificación en
   [`docs/specs/`](docs/specs/) (hay plantilla). Si implica una decisión de fondo, un ADR en
   [`docs/decisions/`](docs/decisions/).
2. **Probar primero.** Escribí el test que expresa el criterio y verificá que **falla**. Un arreglo
   de bug lleva un test que falla sin el arreglo.
3. **Implementar** lo mínimo que lo hace pasar.
4. **Verificar** localmente (abajo).
5. **Pull request** chico, con la plantilla, desde una rama corta (`feat/…`, `fix/…`, `chore/…`).
   Nada va directo a `main`.
6. **Revisión y CI** en verde antes de mergear.

## Antes de cada commit

```bash
make lint
make test
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/oral_test make test-pg   # si tocaste la base
```

Los tests corren sobre SQLite y sobre PostgreSQL. Sobre PostgreSQL se aplican las migraciones
reales, se prueban la restricción de superposición y la concurrencia, y un chequeo falla si los
modelos y las migraciones se desalinean: **si cambiás un modelo, agregá su migración**.

Los tests nunca leen tu `.env` (podría tener credenciales reales).

Los cambios visuales se comprueban en un navegador, a ancho de escritorio **y** de celular.

## Convenciones

- Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `ci:`. El mensaje explica el
  *por qué*, no solo el qué.
- Texto que ve el paciente o el consultorio: **español rioplatense**, claro y sin detalles técnicos.
- Identificadores de código en inglés; comentarios y tests, en el idioma del archivo que se toca.
- Toda fecha u hora de negocio se calcula con `app.core.clock`, nunca con `datetime.now()`.
- Cada PR anota su cambio en `CHANGELOG.md`, bajo `[Unreleased]`.

## Seguridad: este repositorio es público

- **Nunca** se versionan secretos, `.env`, `terraform.tfvars`, estado ni planes de Terraform
  (`tfplan*`: traen las credenciales en texto plano). CI falla si aparece alguno.
- Los datos de pacientes reales no van en tests, capturas ni ejemplos.
- No se guardan datos de salud ([ADR 0002](docs/decisions/0002-sin-datos-de-salud.md)).

## Herramientas de programación asistida

Se pueden usar, con las mismas reglas que para cualquier persona:

- Quien envía el cambio **lo entiende y responde por él**. "Lo escribió la herramienta" no es una
  explicación válida en una revisión.
- El flujo de arriba no se saltea: especificación, test que falla, implementación, CI.
- No se aceptan cambios grandes sin leer: se piden en pasos chicos y se revisa cada diff.
- No se les pega nada sensible (claves, datos de pacientes).
- Las acciones destructivas o sobre producción —`terraform apply`, `git push --force`, rotar
  secretos, desplegar— las confirma una persona.

## Pull requests

Usá la plantilla. CI corre lint, tests (SQLite y PostgreSQL), migraciones de ida y vuelta, build de
la imagen Docker con prueba de humo, validación de Terraform y el control de secretos.

## Dependencias

Dependabot propone actualizaciones. No se mergean a ciegas: una versión mayor (de Python, de una
acción, del proveedor de Terraform) se prueba en su PR, se lee su guía de migración y recién ahí se
integra. Que CI pase es necesario pero no suficiente para infraestructura.

## Releases

1. Anotá los cambios en `CHANGELOG.md`, bajo `[Unreleased]`.
2. Actions → **Preparar release** → versión (`0.3.0`). Abre un PR con la versión y el changelog.
3. Al mergearlo se crea el tag, se publica el GitHub Release con esas notas y se despliega a
   producción.

Localmente equivale a `python ops/release.py prepare 0.3.0`.
