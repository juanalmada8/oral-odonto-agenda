resource "google_cloud_run_v2_service" "web" {
  name                = "${var.service_name}-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.run.email
    max_instance_request_concurrency = 40
    timeout                          = "60s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = var.image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      dynamic "env" {
        for_each = local.app_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health/ready"
        }
        period_seconds    = 3
        timeout_seconds   = 3
        failure_threshold = 20
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds = 30
      }
    }
  }

  lifecycle {
    # The image is rolled out by the Deploy workflow.
    #
    # Do NOT add template[0].revision here. The workflow names each revision (--revision-suffix <sha>),
    # so every plan shows "revision -> null": that is expected noise. Ignoring it makes Terraform resend the
    # current revision name on every update, and Cloud Run answers 409 ("Revision ... with different
    # configuration already exists") as soon as the template really changes, blocking real changes.
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [
    google_project_service.enabled,
    google_secret_manager_secret_iam_member.run_reads_required,
    google_secret_manager_secret_iam_member.run_reads_optional,
  ]
}

# The booking site is public.
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.web.name
  location = google_cloud_run_v2_service.web.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ----------------------------------------------------------------- jobs (same image)

locals {
  job_env = merge(local.app_env, {
    # Jobs are single instances: they need far fewer connections than the web service.
    DB_POOL_SIZE    = "1"
    DB_MAX_OVERFLOW = "1"
  })
}

resource "google_cloud_run_v2_job" "migrate" {
  name                = "${var.service_name}-migrate"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.run.email
      max_retries     = 0
      timeout         = "900s"

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.main.connection_name]
        }
      }

      containers {
        image   = var.image
        command = ["alembic"]
        args    = ["upgrade", "head"]

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }

        dynamic "env" {
          for_each = local.job_env
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = local.secret_env
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_project_service.enabled]
}

resource "google_cloud_run_v2_job" "scheduled" {
  name                = "${var.service_name}-scheduled"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.run.email
      max_retries     = 1
      timeout         = "600s"

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.main.connection_name]
        }
      }

      containers {
        image   = var.image
        command = ["python"]
        args    = ["-m", "app.tasks.run_scheduled"]

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }

        dynamic "env" {
          for_each = local.job_env
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = local.secret_env
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_project_service.enabled]
}

# ----------------------------------------------------------------- scheduler

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_job" {
  name     = google_cloud_run_v2_job.scheduled.name
  location = google_cloud_run_v2_job.scheduled.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "scheduled" {
  name             = "${var.service_name}-scheduled"
  region           = var.region
  description      = "Expira señas impagas, prepara recordatorios y reintenta envíos"
  schedule         = var.scheduler_cron
  time_zone        = "America/Argentina/Buenos_Aires"
  attempt_deadline = "320s"

  retry_config {
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.scheduled.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_project_service.enabled, google_cloud_run_v2_job_iam_member.scheduler_runs_job]
}
