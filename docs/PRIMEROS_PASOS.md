# Primeros pasos para el consultorio

Esta guía es para quien atiende el consultorio. No hace falta saber de computación: son cuatro cosas
que se hacen una sola vez, y después el día a día.

**Dirección del panel:** https://oral.com.ar/app/login
**Dirección que ven los pacientes:** https://oral.com.ar

> Hasta que cargues al menos un profesional con sus horarios (pasos 2 y 3), **la página de reservas no
> ofrece ningún turno**. Es lo único que falta para que los pacientes puedan sacar turno.

## Paso 1: entrar y cambiar tu contraseña

1. Entrá a la dirección del panel con tu usuario y la contraseña que te dieron.
2. En el menú de la izquierda, **Usuarios**.
3. Buscá tu fila. En la columna **Contraseña** escribí una contraseña nueva y apretá **Cambiar**.
4. Guardala en un lugar seguro. **Si la perdés, no hay forma de recuperarla por email**: por eso conviene
   que haya siempre dos personas con acceso de administración.

## Paso 2: cargar a cada profesional

1. Menú **Profesionales**.
2. Completá **Nombre**, **Apellido** y **Especialidad**. El email y el teléfono son opcionales.
3. **Duración del turno**: cuántos minutos dura una consulta normal (por ejemplo, 30).
4. **Seña**: dejala **vacía**. Por ahora no se cobran señas por internet.
5. Apretá **Guardar profesional**.

Repetí con cada profesional que atienda.

> **Importante:** el nombre y el apellido se muestran a los pacientes en la página de reservas. Escribilos
> como quieras que los vean, sin números ni símbolos.

## Paso 3: cargar los horarios de atención

Menú **Disponibilidad**. Los pacientes solo pueden elegir los horarios que cargues acá.

**Para los horarios que se repiten todas las semanas** (lo más común), usá **Repetir cada semana**:

1. Elegí el profesional.
2. Tildá los **Días** en que atiende.
3. **Desde el día** y **Hasta el día**: el período a cubrir. Conviene cargar un par de meses.
4. **Horario desde** y **Horario hasta**: la franja de atención (por ejemplo, de 9:00 a 13:00).
5. **Duración de cada turno**: en minutos.
6. Apretá **Cargar disponibilidad**.

Si algún día atiende en un horario distinto, usá **Agregar un bloque** para ese día puntual.

**Vacaciones, feriados o congresos:** usá **Bloquear días** y **Bloquear período**. Si ya hay turnos
tomados en esos días, el sistema te avisa y no los toca hasta que los reprogrames.

> Cada tanto hay que volver a cargar las semanas siguientes, porque los horarios solo existen hasta la
> fecha que pusiste en "Hasta el día".

## Paso 4: probar como si fueras un paciente

1. Abrí https://oral.com.ar desde tu celular y apretá **Elegir horario**.
2. Elegí el profesional, un día y un horario, completá los datos y confirmá.
3. Tenés que recibir un **email de confirmación** desde `turnos@oral.com.ar`. Si no está en la bandeja,
   mirá en **correo no deseado**.
4. Entrá al panel, menú **Turnos**: tiene que aparecer ese turno.
5. **Cancelalo** desde el panel, para que el horario quede libre.

## El día a día

- **Turnos:** la agenda del día. Desde ahí marcás cada turno como **atendido** o **ausente**, o lo
  **cancelás**. De esas marcas salen las métricas.
- **Crear un turno a mano:** cuando alguien llama por teléfono, en **Turnos** podés cargarlo vos.
- **Pacientes:** la ficha de cada paciente y su historial de turnos.
- **Lista de espera:** las personas que pidieron que les avisen si se libera un horario antes.
- **Notificaciones:** si algún email no se pudo enviar, aparece acá con el motivo.

## Cargar un turno a mano (a cualquier hora y con su duración)

En **Turnos → Crear turno manual** elegí el paciente, el profesional y el día. Después poné la **Duración**
(de 15 minutos a 4 horas) y la **Hora de inicio**, que puede ser cualquiera: no tiene que coincidir con los
horarios que se ofrecen online. Un tratamiento de 10:00 a 11:30 se carga así, directo, y al paciente le llega
**un solo email**.

- Abajo del formulario ves qué horas atiende ese día y qué ya está **ocupado**.
- Si el turno pisa a otro, te avisa antes de guardar, por ejemplo: *"Atención, tenés un turno a las 11:00
  (hasta 11:40)"*. Acortalo para que termine a las 11:00 o elegí otro horario: **nunca se puede pisar un
  turno ya reservado**.
- Mientras dure ese turno, nadie puede reservar online los horarios que cubre, y el siguiente horario online
  arranca justo cuando termina (si termina 11:30, el próximo libre es 11:30).
- Si el trabajo termina más tarde que la disponibilidad cargada, antes agregá un bloque en
  **Disponibilidad → Agregar un bloque** para ese día.
- Dos bloques pegados (por ejemplo, de 9 a 11 y de 11 a 13) cuentan como una sola mañana. Si hay un hueco
  entre ellos, el turno no puede cruzarlo.

## Los pacientes confirman solos

No hace falta confirmar los turnos uno por uno. **El día anterior** (24 horas antes) cada paciente con email
recibe un mensaje con el botón **Confirmar turno**. Cuando lo confirma, en **Turnos** aparece como
*Confirmado* y con la marca "✓ Confirmó el paciente".

- Si a **12 horas** del turno todavía no confirmó, a la profesional le llega un email avisándole. El turno
  **no se cancela**: queda en la agenda y ustedes deciden si lo llaman.
- Si cambiás el día o la hora de un turno, la confirmación anterior se borra y el paciente recibe un pedido
  nuevo para el horario nuevo.
- Los pacientes sin email no reciben el pedido: a esos hay que confirmarlos por teléfono, como siempre.

## Qué NO cargar en el sistema

El sistema es una **agenda de turnos, no una historia clínica**. No cargues diagnósticos, alergias,
medicación ni ningún dato de salud, ni siquiera en las notas. Eso se guarda en los registros propios del
consultorio. Los motivos de esta decisión están en
[decisions/0002-sin-datos-de-salud.md](decisions/0002-sin-datos-de-salud.md).

## Que cada profesional se entere de sus turnos

El sistema le manda un email a cada profesional, **a la dirección que figura en su ficha**:

- cuando le **reservan** un turno (online o cargado por el consultorio),
- cuando se **cancela** o se **mueve**,
- y **cada tarde, desde las 18 h, su agenda del día siguiente** (si tiene turnos).

Para que funcione, revisá en **Profesionales** que cada uno tenga el **email** cargado. Si lo dejás vacío,
ese profesional no recibe avisos. Los mensajes traen solo el nombre del paciente, el día y la hora, con un
enlace al panel: el resto de los datos se ve ahí.

Además, cada profesional puede tener **su propio acceso al panel** (**Usuarios**, rol *Profesional*,
vinculado a su ficha) y ver en **Mi agenda** su día y los próximos 7 días.

## Los emails y las respuestas

- Los pacientes reciben los avisos desde **turnos@oral.com.ar**: confirmación, recordatorio, cambios y
  cancelaciones.
- Cuando un paciente **responde** a uno de esos emails, la respuesta llega a la casilla personal que esté
  configurada para recibirlos. **Alguien tiene que revisarla todos los días.**
- Si un paciente dice que no le llegan los emails, ver [OPERATIONS.md](OPERATIONS.md).

## Si algo no anda

Ver [OPERATIONS.md](OPERATIONS.md), sección *Situaciones frecuentes*. Si el problema es técnico, avisá a
quien administra el sistema.
