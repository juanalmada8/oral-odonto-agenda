# Checklist de configuración productiva

En GCP estas variables las define Terraform (`infra/terraform/terraform.tfvars`) y los valores
sensibles viven en Secret Manager. Referencia completa: `.env.production.example`.

## Obligatorio

| Variable | Nota |
| --- | --- |
| `APP_ENV=production`, `DEBUG=false` | la app valida ambas al arrancar |
| `SECRET_KEY` | [secreto] ≥ 32 caracteres aleatorios (lo genera Terraform) |
| `DATABASE_URL` | [secreto] PostgreSQL (la app rechaza SQLite en producción) |
| `PUBLIC_BASE_URL` | https; se usa en links de emails y callbacks de pago |
| `TRUST_PROXY_HEADERS=true` | detrás de Cloud Run; `TRUSTED_PROXY_COUNT=2` si hay balanceador |
| `LOG_FORMAT=json` | logs estructurados para Cloud Logging |

## Seña (si se cobra)

| Variable | Nota |
| --- | --- |
| `DEPOSIT_DEFAULT_AMOUNT` | 0 = sin seña; con seña, el token de Mercado Pago es obligatorio |
| `MERCADOPAGO_ACCESS_TOKEN` | [secreto] `APP_USR-...` en producción |
| `MERCADOPAGO_WEBHOOK_SECRET` | [secreto] valida la firma de las notificaciones |

## Notificaciones

| Variable | Nota |
| --- | --- |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM` | sin esto no salen emails |
| `WHATSAPP_*` | opcional; ver [WHATSAPP.md](WHATSAPP.md). O están todas o ninguna |

## Reglas de negocio

`BOOKING_MIN_LEAD_MINUTES`, `BOOKING_MAX_DAYS_AHEAD`, `BOOKING_MAX_ACTIVE_PER_PATIENT`,
`BOOKING_HOLD_MINUTES`, `CANCELLATION_NOTICE_HOURS`, `REMINDER_HOURS_AHEAD`, `DEPOSIT_POLICY`
(el texto que ve el paciente), `CLINIC_NAME`, `CLINIC_ADDRESS`, `CLINIC_PHONE`.

## Validación

```bash
make prod-check
```

Revisa configuración y conexión a la base, y marca como error (no advertencia) lo que rompe
producción. Contraseñas y tokens nunca se imprimen.

## Antes de abrir al público

- [ ] `make prod-check` en verde
- [ ] Migraciones aplicadas (`alembic upgrade head` vía job)
- [ ] Usuarios demo desactivados o con contraseña cambiada
- [ ] Prueba real: reservar un turno, pagar la seña y recibir el email
- [ ] Webhook de Mercado Pago apuntando al dominio productivo
- [ ] Backups verificados ([BACKUPS.md](BACKUPS.md))
- [ ] Alerta de caída configurada (`alert_email` en Terraform)
