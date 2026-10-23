# Own daily copy of the database, outside the database provider. Neon's free plan only keeps six hours of
# history; this is what lets the clinic go back further. Spec 0010, rule 4.
#
# The bucket always exists (it also receives the final export when Cloud SQL is retired). The job and its
# schedule exist only on Neon: on Cloud SQL the native backups cover it.

resource "google_storage_bucket" "backups" {
  name                        = "${var.project_id}-${var.service_name}-backups"
  location                    = "US" # multi-region, like the Cloud SQL backups (ADR 0009)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  lifecycle_rule {
    condition {
      age = var.backup_retention_days
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_service_account" "backup" {
  account_id   = "${var.service_name}-backup"
  display_name = "Daily database dump to the backups bucket"
}

resource "google_storage_bucket_iam_member" "backup_writes" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.backup.email}"
}

resource "google_secret_manager_secret_iam_member" "backup_reads_database_url" {
  secret_id = google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backup.email}"
}

resource "google_cloud_run_v2_job" "backup" {
  count               = local.use_cloud_sql ? 0 : 1
  name                = "${var.service_name}-backup"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account       = google_service_account.backup.email
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2" # required to mount a bucket
      max_retries           = 1
      timeout               = "900s"

      volumes {
        name = "backups"
        gcs {
          bucket    = google_storage_bucket.backups.name
          read_only = false
        }
      }

      containers {
        image = var.backup_image
        # The script lives in the repository (ops/neon_backup.sh, covered by tests) and is inlined here.
        command = ["/bin/sh", "-c"]
        args    = [file("${path.module}/../../ops/neon_backup.sh")]

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi" # the dump is staged in memory-backed /tmp before it is validated
          }
        }

        volume_mounts {
          name       = "backups"
          mount_path = "/backups"
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_storage_bucket_iam_member.backup_writes,
    google_secret_manager_secret_iam_member.backup_reads_database_url,
  ]
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_backup" {
  count    = local.use_cloud_sql ? 0 : 1
  name     = google_cloud_run_v2_job.backup[0].name
  location = google_cloud_run_v2_job.backup[0].location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "backup" {
  count            = local.use_cloud_sql ? 0 : 1
  name             = "${var.service_name}-backup"
  region           = var.region
  description      = "Copia diaria de la base a un bucket propio"
  schedule         = var.backup_cron
  time_zone        = "America/Argentina/Buenos_Aires"
  attempt_deadline = "320s"

  retry_config {
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.backup[0].name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_project_service.enabled, google_cloud_run_v2_job_iam_member.scheduler_runs_backup]
}
