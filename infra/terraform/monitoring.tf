# Optional uptime check: alerts by email when the site stops answering /health/ready.

locals {
  monitored_host = replace(replace(local.public_url, "https://", ""), "/", "")
}

resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "Alertas ${var.service_name}"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_uptime_check_config" "web" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "${var.service_name} disponible"
  timeout      = "10s"
  period       = "300s"

  http_check {
    path         = "/health/ready"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = local.monitored_host
    }
  }

  # The host cannot be edited in place. Google refuses to delete a check that an alert policy still
  # references, so the new one is created first and the policy is repointed before the old one goes.
  lifecycle {
    create_before_destroy = true
  }

  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_alert_policy" "uptime" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "${var.service_name}: el sitio no responde"
  combiner     = "OR"

  conditions {
    display_name = "Uptime check fallando"

    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.web[0].uptime_check_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "300s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.host"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email[0].id]

  documentation {
    content = "El sitio de turnos no responde /health/ready. Revisá los logs del servicio en Cloud Run y el estado de Cloud SQL."
  }
}
