variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "region" {
  description = <<-EOT
    Region for Cloud Run, Cloud SQL and Artifact Registry.
      us-central1        – cheapest, and supports the free domain mapping. ~150 ms extra from
                           Argentina, which for server-rendered pages is not noticeable.
      southamerica-east1 – São Paulo, lowest latency and data closer to home, but pricier and
                           it needs the load balancer for a custom domain.
  EOT
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Prefix for every resource."
  type        = string
  default     = "oral"
}

variable "github_repository" {
  description = "owner/repo allowed to deploy through Workload Identity Federation."
  type        = string
  default     = "juanalmada8/oral-odonto-agenda"
}

variable "image" {
  description = "Initial image. The real one is pushed by the Deploy workflow, which Terraform then ignores."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "custom_domain" {
  description = "Custom domain (e.g. turnos.oral.com.ar). Empty = use the run.app URL."
  type        = string
  default     = ""
}

variable "custom_domain_mode" {
  description = <<-EOT
    How the custom domain reaches Cloud Run:
      mapping       – Cloud Run domain mapping. Free, but only in the regions listed in
                      DOMAIN_MAPPING_REGIONS (São Paulo is not one of them).
      load_balancer – Global HTTPS load balancer with a managed certificate. Works in every
                      region and adds roughly USD 18/month for the forwarding rule.
  EOT
  type        = string
  default     = "mapping"

  validation {
    condition     = contains(["mapping", "load_balancer"], var.custom_domain_mode)
    error_message = "custom_domain_mode must be \"mapping\" or \"load_balancer\"."
  }
}

# ----------------------------------------------------------------- database

variable "db_tier" {
  description = "Cloud SQL machine type. db-f1-micro is the cheapest (~USD 9/month, 25 connections)."
  type        = string
  default     = "db-f1-micro"
}

variable "db_deletion_protection" {
  description = "Refuse to delete the database instance."
  type        = bool
  default     = true
}

variable "db_backup_start_time" {
  description = "Daily backup window, UTC (06:00 UTC = 03:00 in Buenos Aires)."
  type        = string
  default     = "06:00"
}

# ----------------------------------------------------------------- runtime

variable "min_instances" {
  description = "0 costs nothing while idle but the first request pays a cold start; 1 keeps the site warm."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Upper bound. Keep max_instances x (DB_POOL_SIZE + DB_MAX_OVERFLOW) under the instance connection limit."
  type        = number
  default     = 3
}

variable "db_pool_size" {
  type    = number
  default = 3
}

variable "db_max_overflow" {
  type    = number
  default = 2
}

variable "scheduler_cron" {
  description = "How often holds are expired, reminders queued and pending messages retried."
  type        = string
  default     = "*/10 * * * *"
}

# ----------------------------------------------------------------- application settings

variable "clinic_name" {
  type    = string
  default = "ORAL odontología familiar"
}

variable "clinic_address" {
  type    = string
  default = ""
}

variable "clinic_phone" {
  type    = string
  default = ""
}

variable "deposit_default_amount" {
  description = "Deposit in ARS for online bookings. Keep 0 until the Mercado Pago token is loaded, otherwise the app refuses to start."
  type        = string
  default     = "0"
}

variable "smtp_host" {
  type    = string
  default = ""
}

variable "smtp_port" {
  type    = string
  default = "587"
}

variable "smtp_username" {
  type    = string
  default = ""
}

variable "email_from" {
  type    = string
  default = ""
}

variable "whatsapp_phone_number_id" {
  type    = string
  default = ""
}

variable "optional_secrets" {
  description = <<-EOT
    Secrets to expose to the service, after loading a value with:
      gcloud secrets versions add NAME --data-file=-
    Available: MERCADOPAGO_ACCESS_TOKEN, MERCADOPAGO_WEBHOOK_SECRET, SMTP_PASSWORD,
    WHATSAPP_ACCESS_TOKEN, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN.
  EOT
  type        = list(string)
  default     = []
}

variable "alert_email" {
  description = "Email for the uptime alert. Empty disables monitoring."
  type        = string
  default     = ""
}
