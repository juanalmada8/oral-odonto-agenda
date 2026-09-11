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
