locals {
  # Created empty: the operator loads the value with `gcloud secrets versions add`, then adds the
  # name to var.optional_secrets so the service receives it.
  optional_secret_names = [
    "MERCADOPAGO_ACCESS_TOKEN",
    "MERCADOPAGO_WEBHOOK_SECRET",
    "SMTP_PASSWORD",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
  ]
}

resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "google_secret_manager_secret" "app_secret_key" {
  secret_id = "${var.service_name}-secret-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "app_secret_key" {
  secret      = google_secret_manager_secret.app_secret_key.id
  secret_data = random_password.secret_key.result
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "${var.service_name}-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  # Unix socket provided by the Cloud SQL volume mounted in Cloud Run.
  secret_data = "postgresql+psycopg://${google_sql_user.app.name}:${random_password.db.result}@/${google_sql_database.app.name}?host=/cloudsql/${google_sql_database_instance.main.connection_name}"
}

resource "google_secret_manager_secret" "optional" {
  for_each  = toset(local.optional_secret_names)
  secret_id = "${var.service_name}-${lower(replace(each.value, "_", "-"))}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_iam_member" "run_reads_required" {
  for_each  = { for name, secret_id in local.required_secrets : name => secret_id }
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}

resource "google_secret_manager_secret_iam_member" "run_reads_optional" {
  for_each  = toset(local.optional_secret_names)
  secret_id = google_secret_manager_secret.optional[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}
