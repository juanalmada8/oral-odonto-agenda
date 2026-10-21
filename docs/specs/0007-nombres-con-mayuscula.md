# 0007 · Nombres y apellidos con mayúscula inicial

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Que los nombres se vean bien en el panel, en los emails y en los avisos, sin importar cómo se tipearon.
Pacientes y profesionales cargan "juan martín" o "ALMADA ORTIZ", y así aparecían en todos lados.

## Fuera de alcance

- Corregir la ortografía o los acentos ("Martin" no pasa a "Martín").
- Los nombres de usuarios del panel (son internos).

## Reglas

1. Al guardar un nombre o apellido (reserva online, alta y edición de pacientes, lista de espera,
   profesionales), cada palabra escrita **toda en minúscula o toda en mayúscula** queda con inicial
   mayúscula: "juan martín" → "Juan Martín", "ALMADA ORTIZ" → "Almada Ortiz".
2. Las partículas **de, del, la, las, los, y, e, van, von** quedan en minúscula, salvo al principio:
   "maría de los ángeles" → "María de los Ángeles"; "de la fuente" → "De la Fuente". "Di", "Da" y "Dos"
   no se tratan como partículas porque en apellidos argentinos se escriben con mayúscula ("Di María",
   "Dos Santos").
3. Después de un apóstrofo o un guion también va mayúscula: "o'connor-díaz" → "O'Connor-Díaz".
4. Una palabra que ya mezcla mayúsculas y minúsculas **se respeta** tal cual: "McDonald", "DiMaría".
5. Los nombres ya cargados de pacientes y profesionales se corrigen una vez, con la misma regla, al
   desplegar (migración `20261021_14`, solo datos; no se puede deshacer porque no se guarda cómo estaban).

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | Minúsculas y mayúsculas sostenidas quedan con inicial mayúscula | `test_names_are_capitalized` |
| 2 | Partículas en minúscula salvo al principio | `test_name_particles_stay_lowercase_except_first` |
| 3 | Apóstrofo y guion | `test_names_after_apostrophe_or_hyphen_are_capitalized` |
| 4 | Lo escrito con mayúsculas intencionales no se toca | `test_mixed_case_names_are_kept` |
| 5 | Una reserva online con el nombre en minúscula se guarda con mayúscula | `test_an_online_booking_saves_the_name_capitalized` |
| 6 | La migración usa la misma regla que la aplicación | `test_the_data_migration_capitalizes_like_the_app` |

## Casos límite y errores

- Iniciales: "j." → "J.".
- Un nombre que no es válido (números, una sola letra) se sigue rechazando con el mismo mensaje.

## Configuración

No agrega variables.
