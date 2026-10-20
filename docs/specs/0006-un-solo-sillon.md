# 0006 · Un solo sillón: nunca dos turnos a la vez en el consultorio

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

El consultorio tiene **un solo sillón**. Dos profesionales no pueden atender al mismo tiempo, así que dos
turnos nunca pueden superponerse, aunque sean de profesionales distintos. Antes la regla era por
profesional: el sistema dejaba cargar a Sabina y a Nazarena a la misma hora y, si las dos atendían el mismo
día, ofrecía online el mismo horario a dos pacientes.

## Fuera de alcance

- Más de un sillón (ver [ADR 0010](../decisions/0010-un-solo-sillon.md)).
- Cambiar la disponibilidad que carga cada profesional: dos profesionales pueden tener horario de atención
  el mismo día y a la misma hora; lo que no puede haber es dos turnos a la vez.

## Reglas

1. **Un turno ocupa el sillón**, sea de quien sea. Ningún turno nuevo, movido o reactivado puede
   superponerse con otro turno activo de **cualquier** profesional (los mismos estados que ya ocupaban
   agenda: reservado, confirmado y la seña en espera mientras no venció).
2. La **reserva online** no ofrece un horario si el sillón está ocupado en ese rango por otro profesional, y
   la grilla arranca donde termina ese turno (0004, regla 6).
3. Al consultorio se le dice **quién** ocupa el sillón: *"Atención, el sillón está ocupado: Nazarena Almada
   Ortiz tiene un turno a las 11:00 (hasta 11:40). Acortá este turno para que termine a las 11:00 o elegí
   otro horario."* Si el turno que estorba es del mismo profesional, el mensaje es el de siempre.
4. El paciente online ve el mensaje genérico, sin datos de otros turnos ni de otros profesionales.
5. El formulario de turno manual muestra como **ocupado** todo lo que ocupa el sillón ese día, con el nombre
   del profesional cuando es otro, y sus horarios libres ya lo descuentan.
6. Si el mismo paciente ya tiene un turno en ese horario, se avisa eso primero (es más preciso).
7. Dos reservas simultáneas para profesionales distintos en el mismo horario: gana una sola.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | No se carga a mano un turno que pisa el de otro profesional, y el aviso dice de quién es | `test_a_manual_appointment_cannot_overlap_another_professional` |
| 2 | Pegado al de otro profesional (termina cuando el otro empieza) sí se carga | `test_back_to_back_with_another_professional_is_fine` |
| 3 | La reserva online no ofrece horarios que ocupa otro profesional | `test_online_slots_skip_the_chair_taken_by_another_professional` |
| 4 | Un paciente online no puede reservar ese horario y no ve de quién es | `test_an_online_patient_cannot_take_the_chair_from_another_professional` |
| 5 | Mover un turno encima del de otro profesional se rechaza | `test_moving_onto_another_professional_is_rejected` |
| 6 | Reactivar un turno cancelado cuyo horario ya tomó otro profesional se rechaza | `test_reactivating_onto_another_professional_is_rejected` |
| 7 | El plan del día muestra lo que ocupa el sillón, con el nombre del otro profesional | `test_the_day_plan_shows_every_professional_in_the_chair` |
| 8 | Un turno cancelado no ocupa el sillón | `test_a_cancelled_appointment_frees_the_chair` |
| 9 | La serie saltea las fechas en que el sillón está ocupado | `test_a_series_skips_dates_when_the_chair_is_taken` |
| 10 | Dos reservas simultáneas para profesionales distintos: gana una (PostgreSQL) | `test_concurrent_bookings_for_two_professionals_only_one_wins` |

## Casos límite y errores

- Turno del mismo paciente con otro profesional a esa hora: *"El paciente ya tiene otro turno en ese
  horario."*
- Turnos que ya se superponían antes de esta regla siguen existiendo; solo se impide crear nuevos choques.
  Mover uno de ellos exige que el nuevo horario quede libre.

## Configuración

No agrega variables: es una regla del consultorio, no una opción (ver ADR 0010).
