# Seña con Mercado Pago (Checkout Pro)

## Cómo funciona

1. El paciente elige horario y completa sus datos: el turno queda en **seña pendiente** y el horario
   se bloquea por `BOOKING_HOLD_MINUTES` (20 minutos por defecto).
2. Se crea una preferencia de Checkout Pro y se lo redirige a pagar.
3. Mercado Pago avisa por webhook. La app **no le cree a la notificación**: consulta el pago en la
   API con su propio token, verifica firma, monto, moneda y referencia, y recién ahí confirma el turno.
4. Si la seña no se acredita a tiempo, el horario se libera solo y queda disponible para otro paciente.

Detalles de la preferencia:

- `binary_mode: true` — el pago se aprueba o se rechaza en el momento (nada queda "en revisión",
  que no sirve para un horario bloqueado 20 minutos).
- Se excluyen efectivo (`ticket`) y cajero (`atm`): tardan días en acreditarse.
- Una sola cuota y vencimiento igual al del bloqueo del horario.

## Configuración

1. Entrá a [Tus integraciones](https://www.mercadopago.com.ar/developers/panel) y creá una aplicación
   de tipo **Pagos online → Checkout Pro**.
2. Copiá el **Access token** (producción: empieza con `APP_USR-`; pruebas: `TEST-`).
3. En la sección **Webhooks** de la aplicación:
   - URL: `https://TU-DOMINIO/webhooks/mercadopago`
   - Evento: **Pagos** (`payment`).
   - Copiá la **clave secreta** que genera para firmar las notificaciones.
4. Cargá ambos valores como secretos (ver [DEPLOYMENT.md](DEPLOYMENT.md)):
   `MERCADOPAGO_ACCESS_TOKEN` y `MERCADOPAGO_WEBHOOK_SECRET`.
5. Definí el monto: `DEPOSIT_DEFAULT_AMOUNT` para toda la clínica y, si hace falta, un monto distinto
   por profesional desde el panel (vacío = valor general, 0 = sin seña).

## Probar sin cobrar plata

- **En tu compu:** sin `MERCADOPAGO_ACCESS_TOKEN` la app usa un simulador local
  (`/pagos/simulador/...`) con botones de aprobar y rechazar. Nunca se activa en producción.
- **Con Mercado Pago:** usá credenciales de prueba (`TEST-...`) y
  [usuarios de prueba](https://www.mercadopago.com.ar/developers/es/docs/checkout-pro/additional-content/your-integrations/test/accounts)
  (uno vendedor, uno comprador) más las tarjetas de prueba. El panel avisa cuando el token es de prueba.

## Devoluciones

Si un pago se acredita después de que venció el bloqueo y alguien tomó el horario, el turno **no** se
confirma y el pago queda marcado en **Pagos → Señas a devolver** (también en el dashboard). La
devolución se hace desde Mercado Pago; la app solo la señala.

Lo mismo aplica a turnos cancelados con seña paga: la política que ve el paciente es
`DEPOSIT_POLICY` y el plazo de cancelación online es `CANCELLATION_NOTICE_HOURS`.

## Diagnóstico

| Síntoma | Dónde mirar |
| --- | --- |
| El paciente paga y el turno no se confirma | Logs del webhook; que `PUBLIC_BASE_URL` sea https y esté cargada en la app, y la URL del webhook en Mercado Pago |
| "No pudimos generar el link de pago" | Token inválido o vencido; el horario queda reservado y se puede reintentar desde la página del turno |
| Firma inválida (401 en el webhook) | `MERCADOPAGO_WEBHOOK_SECRET` no coincide con el de la aplicación |
| Pago aprobado con monto distinto | Se registra como rechazado (`amount_mismatch`) y el turno no se confirma |
