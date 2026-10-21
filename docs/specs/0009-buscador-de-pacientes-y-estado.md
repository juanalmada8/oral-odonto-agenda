# 0009 · Buscador de pacientes con alta en el turno, y estados claros al editar

**Estado:** Implementada · **Fecha:** octubre de 2026

## Objetivo

Cargar un turno por teléfono tiene que poder hacerse sin salir del formulario. Hoy el paciente se elige de
un desplegable con **todos** los pacientes (inmanejable con cientos) y, si es nuevo, hay que irse a otra
pantalla y perder lo cargado. Además, al editar un turno el desplegable "Estado" ofrece opciones que no se
pueden elegir a mano ("Vencido", "Pendiente de pago").

## Fuera de alcance

- Editar la ficha completa del paciente (sigue en *Pacientes*): acá solo los datos mínimos para identificarlo.
- Cambiar quién puede cargar turnos (administración y recepción).

## Reglas

1. En *Crear turno manual* y *Turnos en serie* el paciente se **busca escribiendo** nombre, apellido o DNI
   (sin importar mayúsculas ni acentos). Aparecen hasta 8 coincidencias activas con su DNI; se elige una con un
   toque y queda a la vista, con la opción de cambiarla.
2. Se busca desde 2 letras o números. Los pacientes inactivos no aparecen.
3. *Crear turno manual* ofrece **+ Paciente nuevo** en el mismo formulario, con DNI, nombre, apellido y,
   opcionales, celular y email. Se crea junto con el turno.
4. Si el DNI ya existe, se **usa esa ficha** en lugar de duplicarla (y se completan los datos que faltaban).
   Nombre y apellido siguen las reglas de la [0007](0007-nombres-con-mayuscula.md).
5. Sin paciente elegido ni uno nuevo, no se guarda: *"Elegí un paciente o cargá uno nuevo."*
6. En *Editar turno*, el estado ofrece **solo lo que se puede hacer desde el estado actual**, con nombres de
   acción: el estado actual, *Confirmado*, *Atendido*, *Ausente*, *Cancelar el turno* o *Reactivar el turno*.
   Nunca "Vencido" ni "Pendiente de pago", que los pone el sistema.
7. La búsqueda es solo para administración y recepción.

## Criterios de aceptación

| # | Criterio | Test |
| --- | --- | --- |
| 1 | La búsqueda encuentra por nombre, apellido y DNI, sin acentos ni mayúsculas | `test_patient_search_matches_name_surname_and_dni` |
| 2 | Pide mínimo 2 caracteres, limita a 8 y omite inactivos | `test_patient_search_limits_and_skips_inactive` |
| 3 | La búsqueda exige sesión del consultorio | `test_patient_search_is_for_staff_only` |
| 4 | El formulario usa el buscador, no un desplegable con todos los pacientes | `test_the_manual_form_uses_the_patient_search` |
| 5 | Un paciente nuevo se crea junto con el turno | `test_a_new_patient_is_created_with_the_appointment` |
| 6 | Si el DNI existe, se reutiliza la ficha | `test_a_new_patient_with_an_existing_dni_reuses_the_record` |
| 7 | Sin paciente no se guarda | `test_an_appointment_needs_a_patient` |
| 8 | Datos inválidos del paciente nuevo se rechazan con mensaje claro | `test_a_new_patient_with_invalid_data_is_rejected` |
| 9 | El estado al editar ofrece solo acciones posibles | `test_the_edit_form_only_offers_possible_statuses` |
| 10 | Un turno cancelado ofrece "Reactivar" | `test_a_cancelled_appointment_offers_reactivate` |

## Casos límite y errores

- Dos pacientes con el mismo apellido: se distinguen por el DNI que se muestra al lado.
- Cambiar de paciente tras elegir uno: *Cambiar* vuelve a la búsqueda.
- Sin JavaScript el formulario no puede elegir paciente; el panel ya depende de JavaScript para el resto.

## Configuración

No agrega variables.
