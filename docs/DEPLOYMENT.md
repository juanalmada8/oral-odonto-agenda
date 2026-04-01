# Deploy de Producción (PostgreSQL)

Esta guía deja ORAL lista para un entorno productivo mínimo.

## 1) Variables de entorno

Partí de:

```bash
cp .env.production.example .env
```

Completá al menos:

- `SECRET_KEY` (largo, aleatorio, único)
- `DATABASE_URL` (PostgreSQL real)
- `SMTP_*` y `EMAIL_FROM`

Podés validar todo con:

```bash
make prod-check
```

## 2) Base de datos

La app en producción **no** crea tablas automáticamente.  
Aplicá migraciones antes de levantar:

```bash
alembic upgrade head
```

## 3) Levantar app en modo producción

Ejemplo simple con Uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Recomendado: correr detrás de un proxy con HTTPS (Nginx/Caddy o plataforma gestionada).

## 4) Deploy recomendado (Render)

Este repo incluye `render.yaml` para levantar:

- Web service FastAPI
- Base PostgreSQL
- Variables de entorno base

Pasos:

1. En Render, crear servicio desde el repo y seleccionar `render.yaml`.
2. Completar secrets no sincronizadas:
   - `SECRET_KEY`
   - `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM`
3. Deploy inicial.
4. Verificar:
   - `/docs` (si corresponde por entorno)
   - login `/app/login`
   - reserva pública `/reservar`

## 5) HTTPS + dominio

- Render entrega HTTPS por defecto en el dominio `onrender.com`.
- Para dominio propio:
  1. Agregar custom domain en el panel de Render.
  2. Crear CNAME/A según indique Render.
  3. Esperar validación SSL automática.
  4. Confirmar redirección a HTTPS.

## 6) Checklist pre go-live

- `APP_ENV=production`
- `DEBUG=false`
- `SECRET_KEY` segura (>= 32 chars)
- `DATABASE_URL` apunta a PostgreSQL (no SQLite)
- migraciones aplicadas
- SMTP validado con envío real de prueba
- backup diario de PostgreSQL configurado
- chequeo automatizado en verde: `odonto-prod-check` o `make prod-check`

## 7) Backups

Ver guía dedicada: `docs/BACKUPS.md`.

- Si usás DB gestionada: activar backups automáticos del proveedor.
- Si usás infraestructura propia: programar `ops/pg_backup.sh` diario con retención.

## 8) Comandos de verificación rápida

```bash
pytest
ruff check .
```
