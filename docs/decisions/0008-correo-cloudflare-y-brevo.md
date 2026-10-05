# 0008 · Correo: recepción con Cloudflare Email Routing y envío con Brevo

**Estado:** vigente · **Fecha:** octubre de 2026

## Contexto

El consultorio necesita una dirección propia, `turnos@oral.com.ar`, para dos cosas distintas: **recibir**
(respuestas de pacientes y reclamos de privacidad) y **enviar** los emails automáticos de la app
(confirmación, recordatorio, reprogramación y cancelación). No se quería enviar desde una casilla personal.

## Decisión

- **Recibir:** Cloudflare Email Routing reenvía lo que llegue a `turnos@oral.com.ar` a la casilla de la
  titular. Es gratuito y se administra en el mismo lugar que el DNS. No es una casilla: no se puede
  *responder* desde `@oral.com.ar`, se responde desde la casilla personal.
- **Enviar:** Brevo por SMTP (`smtp-relay.brevo.com`, puerto 587). El dominio está autenticado con DKIM
  (dos CNAME), código de verificación y DMARC en modo `p=none`. El remitente `turnos@oral.com.ar` está
  verificado. El SPF del dominio es uno solo, el de Cloudflare Email Routing.
- La clave SMTP vive en Secret Manager (`oral-smtp-password`) y se inyecta al servicio como `SMTP_PASSWORD`.
- **No activar el bloqueo por IP de las claves SMTP de Brevo**: Cloud Run no tiene IP de salida fija y
  los envíos serían rechazados.

Verificado con un envío real desde producción: SPF, DKIM y DMARC en `PASS`.

## Alternativas descartadas

- **Zoho Mail Lite** (casilla real, ~USD 12 por año): válido, pero el alta no se pudo completar y su SMTP
  tiene límites dinámicos y desaconsejados para correo transaccional.
- **Google Workspace** (~USD 7 por usuario al mes): lo más simple, pero unas siete veces más caro.
- **Resend**: más simple de configurar, pero su plan gratuito se limita a 100 emails por día, contra los
  300 de Brevo, y cada turno genera como mínimo dos.

## Consecuencias

- **Tope de 300 emails por día.** Un día muy cargado puede acercarse; los envíos que fallan se reintentan.
- **Brevo agrega la cabecera `List-Unsubscribe` a todos sus emails, también a los transaccionales**, y
  solo se puede quitar en el plan Enterprise. Un paciente que toque «Anular la suscripción» queda
  bloqueado y **deja de recibir los recordatorios**, posiblemente sin que nadie se entere. El riesgo es
  bajo y se acepta; se mitiga con la revisión periódica descrita en [OPERATIONS.md](../OPERATIONS.md).
  Si se vuelve un problema real, se cambia de proveedor (Resend o Amazon SES) en lugar de resignarlo.
- Para pasar a una casilla real basta con cambiar `smtp_host`, `smtp_username`, `email_from` y la clave,
  sin tocar código.
