# Checklist de `.env` para Producción

Usá `.env.production.example` como base.

## Obligatorio

- `APP_ENV=production`
- `DEBUG=false`
- `SECRET_KEY` aleatoria, única, de al menos 32 caracteres
- `DATABASE_URL` de PostgreSQL productiva

## Email / notificaciones

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_TLS`
- `EMAIL_FROM`

## Opcional

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `REMINDER_HOURS_AHEAD`

## Validación final

```bash
make prod-check
```

Si falla, corregí los campos y repetí.
