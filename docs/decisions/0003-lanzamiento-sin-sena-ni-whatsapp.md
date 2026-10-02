# 0003 · Lanzar sin seña ni WhatsApp, activables por configuración

**Estado:** vigente · **Fecha:** octubre de 2026

## Contexto

Mercado Pago (seña) y el bot de WhatsApp están implementados y probados, pero el consultorio decidió
abrir al público sin ellos y sumarlos más adelante.

## Decisión

El lanzamiento cobra en el consultorio y recuerda **por email**. El código de la seña y de WhatsApp
**queda completo y se enciende solo con configuración**, sin cambios de código ni migraciones.

Reglas que lo sostienen:

- Sin pasarela de pago configurada **no se pide seña**, aunque un profesional tenga un monto cargado
  (`PaymentService.deposit_for`). Antes la reserva quedaba esperando un pago imposible con el horario
  bloqueado. Test: `test_without_a_payment_gateway_a_deposit_does_not_block_the_booking`.
- En producción la aplicación **no arranca** si `DEPOSIT_DEFAULT_AMOUNT > 0` sin token de Mercado Pago.
- Sin WhatsApp el recordatorio sale solo por email
  (`test_sin_whatsapp_configurado_el_recordatorio_sale_solo_por_email`).
- El texto de política que acepta el paciente habla de seña **solo si hay seña**
  (`test_without_a_deposit_the_policy_does_not_talk_about_one`).

## Consecuencias

Para activar la seña o WhatsApp se siguen los pasos de
[PROD_ENV_CHECKLIST.md](../PROD_ENV_CHECKLIST.md). Sin seña no hay barrera contra reservas falsas
más allá del límite por paciente y por IP; si el ausentismo o el abuso se vuelven un problema, la
seña es la herramienta prevista.
