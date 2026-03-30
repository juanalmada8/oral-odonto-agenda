# Contributing

Gracias por aportar al proyecto ORAL · Odonto Agenda.

## Flujo recomendado

1. Crear branch desde `main`:

```bash
git checkout main
git pull
git checkout -b feature/mi-cambio
```

2. Instalar entorno:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

3. Ejecutar validaciones antes de commit:

```bash
ruff check .
pytest
```

4. Commits claros y atómicos:

- `feat: ...`
- `fix: ...`
- `refactor: ...`
- `docs: ...`
- `test: ...`

5. Abrir PR con:

- contexto del problema
- cambios realizados
- forma de validar
- capturas de UI si aplica

## Guías de código

- Evitar lógica de negocio en templates.
- Mantener responsabilidades separadas por servicio/agente.
- Priorizar validación en schemas + servicios.
- Evitar hardcodear secretos y datos sensibles.
- Mantener UI consistente con branding y criterio clínico-operativo.

## Base de datos

- No usar `create_all` para producción.
- Toda evolución de esquema va por Alembic.
- Comandos:

```bash
alembic revision -m "descripcion_del_cambio"
alembic upgrade head
```

## Testing

Tests mínimos esperados para cambios funcionales:

- flujo principal afectado
- caso borde
- regresión básica del módulo tocado

## Checklist de PR

- [ ] Código compila y levanta
- [ ] Tests pasan localmente
- [ ] Lint sin errores
- [ ] Sin secretos en commits
- [ ] Docs actualizadas (README/CHANGELOG si corresponde)

