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
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM` | sin esto no salen emails. Usá una casilla del consultorio: `EMAIL_FROM` es el remitente que ve el paciente |
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

## Perfil de lanzamiento: sin seña y sin WhatsApp

Se puede abrir al público cobrando en el consultorio y avisando solo por email. Mercado Pago y
WhatsApp se suman después sin tocar código ni migrar nada.

| Variable | Valor para arrancar |
| --- | --- |
| `DEPOSIT_DEFAULT_AMOUNT` | `0` — la reserva queda confirmada sin pago |
| `MERCADOPAGO_ACCESS_TOKEN` / `MERCADOPAGO_WEBHOOK_SECRET` | vacías |
| `WHATSAPP_*` | vacías: los recordatorios salen por email |

La app se niega a arrancar si hay seña configurada sin token de Mercado Pago, y si WhatsApp está
cargado a medias `make prod-check` lo marca como error.

**Para sumar la seña más adelante:** cargá el token y el secreto en Secret Manager, agregalos a
`optional_secrets` en `terraform.tfvars`, poné `deposit_default_amount` y aplicá. Desde ese momento las
reservas nuevas piden seña; los profesionales pueden tener un monto propio (0 = sin seña).

**Para sumar WhatsApp:** completá las cuatro variables `WHATSAPP_*` y el recordatorio pasa a salir
también por ahí, además del email.

## Antes de abrir al público

- [ ] `make prod-check` en verde
- [ ] Migraciones aplicadas (`alembic upgrade head` vía job)
- [ ] Tu usuario administrador creado con `odonto-create-admin` (nunca `seed_demo` en producción)
- [ ] Profesionales, horarios de atención y disponibilidad cargados desde el panel
- [ ] Prueba real: reservar un turno y recibir el email de confirmación (y el pago de la seña, si está activa)
- [ ] Si hay seña: webhook de Mercado Pago apuntando al dominio productivo
- [ ] Backups verificados ([BACKUPS.md](BACKUPS.md))
- [ ] Alerta de caída configurada (`alert_email` en Terraform)
