data "google_project" "this" {}

locals {
  # Cloud Run's deterministic URL, known before the service exists (no chicken-and-egg with PUBLIC_BASE_URL).
  run_url        = "https://${var.service_name}-web-${data.google_project.this.number}.${var.region}.run.app"
  public_url     = var.custom_domain != "" ? "https://${var.custom_domain}" : local.run_url
  image_registry = "${var.region}-docker.pkg.dev/${var.project_id}/${var.service_name}"

  # Only the load balancer adds a second hop. Domain mapping goes straight to Cloud Run, so it stays at 1:
  # with 2 and a single real hop the app would take the client-supplied X-Forwarded-For entry, and the
  # login and booking rate limits could be bypassed by forging it.
  trusted_proxy_count = var.custom_domain != "" && var.custom_domain_mode == "load_balancer" ? 2 : 1

  app_env = {
    APP_ENV                  = "production"
    DEBUG                    = "false"
    LOG_FORMAT               = "json"
    GOOGLE_CLOUD_PROJECT     = var.project_id
    APP_TIMEZONE             = "America/Argentina/Buenos_Aires"
    TRUST_PROXY_HEADERS      = "true"
    TRUSTED_PROXY_COUNT      = tostring(local.trusted_proxy_count)
    PUBLIC_BASE_URL          = local.public_url
    CLINIC_NAME              = var.clinic_name
    CLINIC_ADDRESS           = var.clinic_address
    CLINIC_PHONE             = var.clinic_phone
    DEPOSIT_DEFAULT_AMOUNT   = var.deposit_default_amount
    SMTP_HOST                = var.smtp_host
    SMTP_PORT                = var.smtp_port
    SMTP_USERNAME            = var.smtp_username
    SMTP_USE_TLS             = "true"
    EMAIL_FROM               = var.email_from
    WHATSAPP_PHONE_NUMBER_ID = var.whatsapp_phone_number_id
    DB_POOL_SIZE             = tostring(var.db_pool_size)
    DB_MAX_OVERFLOW          = tostring(var.db_max_overflow)
  }

  # Always mounted; the rest only once the operator loads a value and lists it in optional_secrets.
  required_secrets = {
    DATABASE_URL = google_secret_manager_secret.database_url.secret_id
    SECRET_KEY   = google_secret_manager_secret.app_secret_key.secret_id
  }
  secret_env = merge(local.required_secrets, { for name in var.optional_secrets : name => google_secret_manager_secret.optional[name].secret_id })
}

resource "google_project_service" "enabled" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "monitoring.googleapis.com",
    "compute.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.service_name
  description   = "Container images for ${var.service_name}"
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 15
    }
  }
  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "1209600s" # 14 days
    }
  }

  depends_on = [google_project_service.enabled]
}

# ----------------------------------------------------------------- service accounts

resource "google_service_account" "run" {
  account_id   = "${var.service_name}-run"
  display_name = "Runtime identity of the ${var.service_name} service and jobs"
}

resource "google_service_account" "deployer" {
  account_id   = "${var.service_name}-deployer"
  display_name = "GitHub Actions deployer"
}

resource "google_service_account" "scheduler" {
  account_id   = "${var.service_name}-scheduler"
  display_name = "Cloud Scheduler trigger for the periodic job"
}

resource "google_project_iam_member" "run_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.run.email}"
}

resource "google_project_iam_member" "deployer_run" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Deploying a revision means acting as the runtime service account.
resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  service_account_id = google_service_account.run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_push" {
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}
