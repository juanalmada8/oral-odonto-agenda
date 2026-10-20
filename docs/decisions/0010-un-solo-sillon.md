# 0010 · Un solo sillón: la superposición se controla en todo el consultorio

**Estado:** vigente · **Fecha:** octubre de 2026

## Contexto

El consultorio tiene un solo sillón y dos profesionales. La agenda controlaba la superposición **por
profesional** (en la aplicación y con una restricción de exclusión en PostgreSQL), lo que permitía dos
turnos a la misma hora con profesionales distintos.

## Decisión

- La regla pasa a ser **del consultorio**: un turno activo de cualquier profesional ocupa el sillón. Se
  aplica en la aplicación (al reservar, cargar, mover, reactivar y al calcular los horarios online).
- Para que dos reservas simultáneas de profesionales distintos no se salteen el control, toda escritura en
  la agenda **bloquea a todos los profesionales** (`SELECT … FOR UPDATE` en orden de id, siempre el mismo
  orden para no generar bloqueos cruzados). Con dos o tres profesionales el costo es nulo.
- **No es configurable.** Si el consultorio suma un segundo sillón, se cambia el código con su
  especificación: una variable que nadie recuerda que existe es peor que una regla escrita.
- La restricción de exclusión de PostgreSQL pasa a cubrir **todo el consultorio**
  (`appointment_chair_no_overlap`, migración `20261020_13`): la base rechaza dos turnos a la vez aunque
  alguien se saltee la aplicación. Se aplicó después de confirmar con el consultorio que no había turnos
  superpuestos entre profesionales; si los hubiera, la migración falla entera (es una sola transacción) y
  el despliegue se frena antes de tocar la aplicación.

## Consecuencias

- Online, un día en que atienden las dos profesionales se ofrecen menos horarios: los que el sillón tiene
  realmente libres.
- Agregar un sillón implica revisar esta decisión, la especificación 0006 y el cálculo de disponibilidad.
