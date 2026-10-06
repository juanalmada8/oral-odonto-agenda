# 0009 · Disponibilidad, protección y acceso manual a la base

**Estado:** vigente · **Fecha:** octubre de 2026

## Contexto

La consola de Google Cloud marca tres advertencias sobre la instancia `oral-pg`: no es multirregional, no
tiene conmutación por error (alta disponibilidad) y no tiene protección contra eliminación. Además, quien
administra necesita entrar a la base a mano.

## Decisión

**Protección contra eliminación: activada** (`deletion_protection_enabled`). Es gratis y evita perder la
base por un clic o un comando equivocado. Terraform además se niega a borrarla (`deletion_protection`).

**Alta disponibilidad y réplica en otra región: no, por ahora.** Cada una aproximadamente **duplica el
costo** de la base. A cambio:

- Los backups diarios (14 retenidos) y los registros para recuperación a un punto en el tiempo (7 días) se
  guardan en la ubicación **`us`, multirregional**: sobreviven a la caída de toda la región `us-central1`.
- Ante una caída de la zona, Google reinicia la instancia; se estiman minutos u horas sin servicio, no
  pérdida de datos.

Para un consultorio con este volumen, unos minutos sin reservas online son tolerables (se puede llamar por
teléfono); duplicar el costo no lo es. Se revisa si el sistema pasa a ser crítico o crece.

**Acceso manual con la cuenta de Google (IAM), sin contraseña.** Nadie usa la contraseña de la app para
entrar a mano. Cada persona entra con su cuenta, a través del proxy de Cloud SQL, con permisos de **datos**
(lectura y escritura) pero **no de estructura** (eso es de las migraciones). Procedimiento en
[DATABASE_ACCESS.md](../DATABASE_ACCESS.md).

La base sigue sin redes autorizadas: no acepta conexiones directas desde internet.

## Consecuencias

- Una caída zonal deja el sitio sin servicio un rato; los datos están a salvo.
- Para borrar la instancia algún día hay que desactivar primero las dos protecciones, a propósito.
- Las advertencias de "no multirregional" y "sin conmutación por error" van a seguir apareciendo en la
  consola: son decisiones tomadas, no descuidos.
