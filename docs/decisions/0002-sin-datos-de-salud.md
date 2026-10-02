# 0002 · No guardar datos de salud

**Estado:** vigente · **Fecha:** octubre de 2026

## Contexto

El sistema nació con un campo de antecedentes (alergias, medicación) en la ficha del paciente y un
campo libre en el formulario público. En la Ley 25.326 los datos de salud son **datos sensibles**:
exigen consentimiento expreso, registro de la base ante la AAIP y condiciones mucho más estrictas
para transferirlos fuera del país, y la infraestructura está en Estados Unidos.

## Decisión

El producto es una **agenda de turnos, no una historia clínica**. No se guardan datos de salud:

- Se eliminó la columna `patient.medical_notes` (migración `20261001_11`) y el campo del
  formulario público.
- La ficha del paciente es administrativa: contacto, obra social, domicilio, contacto de urgencia.
  El campo `observations` se muestra como *Notas administrativas* y avisa que no se cargue
  información clínica.
- Existe una página pública `/privacidad` y el formulario pide consentimiento explícito.

## Consecuencias

- Lo que el profesional necesite saber de la salud del paciente se conversa en el consultorio y
  vive en los registros propios del consultorio, fuera de este sistema.
- Agregar un campo clínico es un cambio de esta decisión, no una mejora más: requiere reemplazar
  este documento y revisar el aspecto legal.
- Tests que lo sostienen: `test_la_reserva_publica_no_pide_datos_de_salud`,
  `test_la_ficha_no_guarda_informacion_clinica`.

## Pendiente fuera del código

Revisión por un abogado del plazo de conservación de datos, y el trámite ante la AAIP para la
transferencia internacional.
