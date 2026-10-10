# Especificaciones

Una especificación describe **qué debe hacer** una funcionalidad, antes (o al mismo tiempo) de
escribir el código, y queda como referencia viva de lo que el sistema promete. Es lo que evita
programar "a ojo": si el comportamiento no está escrito, no se puede revisar ni probar.

## Cuándo escribir una

- Una funcionalidad nueva o un cambio de comportamiento visible para pacientes o para el consultorio.
- Un bug cuyo arreglo cambia una regla (la regla correcta queda anotada).

No hace falta para cambios internos que no alteran el comportamiento, ni para ajustes de estilo.

## Cómo se trabaja

1. Copiá [`TEMPLATE.md`](TEMPLATE.md) a `NNNN-nombre-corto.md` y completalo en estado *Borrador*.
2. Cada criterio de aceptación se redacta de forma que **un test pueda comprobarlo**.
3. Escribí el test, verificá que falla, implementá, verificá que pasa.
4. Pasá la especificación a *Implementada* y completá la columna del test que cubre cada criterio.
5. Si el comportamiento cambia más adelante, se edita la especificación en el mismo pull request.

La especificación dice **qué**; el [ADR](../decisions/) dice **por qué se eligió ese camino**.

## Índice

| N.º | Funcionalidad | Estado |
| --- | --- | --- |
| [0001](0001-reserva-online.md) | Reserva online del paciente | Implementada |
| [0002](0002-avisos-al-profesional.md) | Avisos al profesional por turnos nuevos, cancelados y movidos, y resumen diario | Implementada |
