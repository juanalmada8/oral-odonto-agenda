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

# Managed here only while the app runs on Cloud SQL. On Neon the connection string carries Neon's password,
# so the operator loads it with `gcloud secrets versions add` and it never touches Terraform or its state.
# The secret itself always exists, which is what lets the jobs and the service reference it in both modes.
moved {
  from = google_secret_manager_secret_version.database_url
  to   = google_secret_manager_secret_version.database_url[0]
}

resource "google_secret_manager_secret_version" "database_url" {
  count  = local.use_cloud_sql ? 1 : 0
  secret = google_secret_manager_secret.database_url.id
  # Unix socket provided by the Cloud SQL volume mounted in Cloud Run.
  secret_data = "postgresql+psycopg://${google_sql_user.app[0].name}:${random_password.db[0].result}@/${google_sql_database.app[0].name}?host=/cloudsql/${google_sql_database_instance.main[0].connection_name}"
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
