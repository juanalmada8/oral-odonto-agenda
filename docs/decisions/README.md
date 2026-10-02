# Decisiones de arquitectura

Cada archivo registra **una decisión**: qué se eligió, por qué y qué se descartó. El código dice
*cómo* funciona algo; esto dice *por qué es así*, que es lo primero que se olvida.

Una decisión no se edita cuando cambia: se escribe una nueva que la reemplaza y la anterior pasa a
*Reemplazada por…*. Así queda el historial del razonamiento.

| N.º | Decisión | Estado |
| --- | --- | --- |
| [0001](0001-postgresql.md) | PostgreSQL como única base de producción | Vigente |
| [0002](0002-sin-datos-de-salud.md) | No guardar datos de salud | Vigente |
| [0003](0003-lanzamiento-sin-sena-ni-whatsapp.md) | Lanzar sin seña ni WhatsApp, activables por configuración | Vigente |
| [0004](0004-google-cloud-run.md) | Cloud Run + Cloud SQL en `us-central1`, con dominio por mapeo | Vigente |
| [0005](0005-huella-de-estaticos.md) | La URL de los estáticos lleva el hash de su contenido | Vigente |
| [0006](0006-mulish-como-unica-tipografia.md) | Mulish como única tipografía | Vigente |
| [0007](0007-titularidad-de-repositorio-y-nube.md) | El negocio es del consultorio; repositorio y nube los administra quien desarrolla | Vigente |

Para agregar una: copiá el formato de cualquiera, numerala en orden y sumala a esta tabla.
