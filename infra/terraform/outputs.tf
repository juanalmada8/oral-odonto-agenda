output "service_url" {
  description = "Cloud Run URL of the service."
  value       = google_cloud_run_v2_service.web.uri
}

output "public_base_url" {
  description = "URL patients use (custom domain when configured)."
  value       = local.public_url
}

output "load_balancer_ip" {
  description = "A record to create for the custom domain (empty when no load balancer)."
  value       = local.use_load_balancer ? google_compute_global_address.web[0].address : ""
}

output "sql_connection_name" {
  value = google_sql_database_instance.main.connection_name
}

output "github_variables" {
  description = "Paste these into GitHub -> Settings -> Secrets and variables -> Actions -> Variables."
  value = {
    GCP_PROJECT_ID                 = var.project_id
    GCP_REGION                     = var.region
    GCP_ARTIFACT_REPOSITORY        = google_artifact_registry_repository.images.repository_id
    GCP_WORKLOAD_IDENTITY_PROVIDER = google_iam_workload_identity_pool_provider.github.name
    GCP_DEPLOYER_SERVICE_ACCOUNT   = google_service_account.deployer.email
    CLOUD_RUN_SERVICE              = google_cloud_run_v2_service.web.name
    CLOUD_RUN_MIGRATE_JOB          = google_cloud_run_v2_job.migrate.name
    CLOUD_RUN_SCHEDULED_JOB        = google_cloud_run_v2_job.scheduled.name
    PUBLIC_BASE_URL                = local.public_url
  }
}

output "secret_ids" {
  description = "Secrets to fill with `gcloud secrets versions add <id> --data-file=-`."
  value       = { for name in local.optional_secret_names : name => google_secret_manager_secret.optional[name].secret_id }
}
