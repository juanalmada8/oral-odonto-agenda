# Operación y Runbook

## 1) Inicialización local

```bash
cp .env.example .env
docker compose up -d db mailhog
alembic upgrade head
python -m app.tasks.seed_demo
uvicorn app.main:app --reload
```

## 2) Recordatorios y notificaciones

### Flujo recomendado

1. Confirmar turnos desde panel de turnos.
2. Ir a `Notificaciones`.
3. Ejecutar `Preparar recordatorios`.
4. Revisar previsualización de “Se enviarán ahora”.
5. Ejecutar `Despachar pendientes`.

### Regla de envío

- Se despachan por lote únicamente recordatorios (`REMINDER`) de turnos confirmados.
- Confirmaciones (`CONFIRMATION`) se envían en el momento de confirmar.

## 3) SMTP con Gmail

### Configuración sugerida

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=tu_cuenta@gmail.com
SMTP_PASSWORD=tu_app_password_de_google
SMTP_USE_TLS=true
EMAIL_FROM=tu_cuenta@gmail.com
```

### Cómo generar App Password

1. Activar verificación en dos pasos en tu cuenta Google.
2. Ir a Google Account > Seguridad > Contraseñas de aplicaciones.
3. Crear nueva contraseña para “Correo”.
4. Copiar la clave de 16 caracteres en `SMTP_PASSWORD`.

## 4) Migraciones

### Crear migración

```bash
alembic revision -m "descripcion"
```

### Aplicar migraciones

```bash
alembic upgrade head
```

## 5) Comandos de mantenimiento

```bash
# tests
pytest

# lint
ruff check .

# seed demo
python -m app.tasks.seed_demo

# enviar pendientes por script
python -m app.tasks.send_reminders
```

## 6) Resolución de problemas

### Error: tablas faltantes al hacer seed

- Ejecutar:

```bash
alembic upgrade head
```

### Error SMTP no configurado

- Revisar `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM`.
- Confirmar que `SMTP_USE_TLS` sea consistente con el proveedor.

### Se preparan notificaciones pero no se envían

- Verificar que estén vencidas (`scheduled_for <= now`).
- Verificar que el turno siga `CONFIRMED`.
- Revisar sección de `Fallidas` y `Omitidas`.

