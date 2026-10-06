resource "google_sql_database_instance" "main" {
  name             = "${var.service_name}-pg"
  database_version = "POSTGRES_16"
  region           = var.region

  deletion_protection = var.db_deletion_protection

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true

    # Google-side guard: the instance cannot be deleted from the console, gcloud or the API until this is
    # turned off. deletion_protection above only stops Terraform.
    deletion_protection_enabled = true

    # Lets people log in with their Google account (IAM database authentication) instead of sharing the
    # app's password. Does not require a restart.
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = var.db_backup_start_time
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      # No authorized networks: the only way in is the Cloud SQL connector with IAM (Cloud Run volume).
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 6 # 03:00 in Buenos Aires
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled = true
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_sql_database" "app" {
  name     = var.service_name
  instance = google_sql_database_instance.main.name
}

resource "random_password" "db" {
  length  = 32
  special = false # keeps the URL readable and avoids escaping in the connection string
}

resource "google_sql_user" "app" {
  name     = var.service_name
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
}

# People who connect by hand (DBeaver, psql, Cloud SQL Studio) with their own Google account. There is no
# password to leak or rotate: access ends when the account is removed here or loses the IAM role below.
resource "google_sql_user" "people" {
  for_each = toset(var.db_iam_users)
  name     = each.value
  instance = google_sql_database_instance.main.name
  type     = "CLOUD_IAM_USER"
}

resource "google_project_iam_member" "db_people_login" {
  for_each = toset(var.db_iam_users)
  project  = var.project_id
  role     = "roles/cloudsql.instanceUser"
  member   = "user:${each.value}"
}
