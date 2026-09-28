# Optional custom domain. Two ways in:
#   - domain mapping: free, Cloud Run issues and renews the certificate, but only available in
#     some regions (checked below, since a wrong region fails silently at apply time);
#   - load balancer: works anywhere and costs about USD 18/month for the forwarding rule.
# Without a custom domain the site is served from the run.app URL.

locals {
  # https://cloud.google.com/run/docs/mapping-custom-domains
  domain_mapping_regions = [
    "asia-east1", "asia-northeast1", "asia-southeast1",
    "europe-north1", "europe-west1", "europe-west4",
    "us-central1", "us-east1", "us-east4", "us-west1",
  ]

  use_mapping       = var.custom_domain != "" && var.custom_domain_mode == "mapping"
  use_load_balancer = var.custom_domain != "" && var.custom_domain_mode == "load_balancer"
}

resource "terraform_data" "domain_mapping_region_check" {
  count = local.use_mapping ? 1 : 0

  lifecycle {
    precondition {
      condition     = contains(local.domain_mapping_regions, var.region)
      error_message = "Cloud Run domain mapping is not available in ${var.region}. Use one of ${join(", ", local.domain_mapping_regions)}, or set custom_domain_mode = \"load_balancer\"."
    }
  }
}

resource "google_cloud_run_domain_mapping" "web" {
  count    = local.use_mapping ? 1 : 0
  name     = var.custom_domain
  location = var.region

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.web.name
  }

  depends_on = [terraform_data.domain_mapping_region_check]
}

resource "google_compute_region_network_endpoint_group" "web" {
  count                 = local.use_load_balancer ? 1 : 0
  name                  = "${var.service_name}-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.web.name
  }
}

resource "google_compute_backend_service" "web" {
  count                 = local.use_load_balancer ? 1 : 0
  name                  = "${var.service_name}-backend"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.web[0].id
  }

  log_config {
    enable      = true
    sample_rate = 1
  }
}

resource "google_compute_url_map" "web" {
  count           = local.use_load_balancer ? 1 : 0
  name            = "${var.service_name}-urlmap"
  default_service = google_compute_backend_service.web[0].id
}

resource "google_compute_managed_ssl_certificate" "web" {
  count = local.use_load_balancer ? 1 : 0
  name  = "${var.service_name}-cert"

  managed {
    domains = [var.custom_domain]
  }
}

resource "google_compute_target_https_proxy" "web" {
  count            = local.use_load_balancer ? 1 : 0
  name             = "${var.service_name}-https-proxy"
  url_map          = google_compute_url_map.web[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.web[0].id]
}

resource "google_compute_global_address" "web" {
  count = local.use_load_balancer ? 1 : 0
  name  = "${var.service_name}-ip"
}

resource "google_compute_global_forwarding_rule" "https" {
  count                 = local.use_load_balancer ? 1 : 0
  name                  = "${var.service_name}-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  target                = google_compute_target_https_proxy.web[0].id
  port_range            = "443"
  ip_address            = google_compute_global_address.web[0].id
}

# Plain HTTP only redirects to HTTPS.
resource "google_compute_url_map" "redirect" {
  count = local.use_load_balancer ? 1 : 0
  name  = "${var.service_name}-redirect"

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  count   = local.use_load_balancer ? 1 : 0
  name    = "${var.service_name}-http-proxy"
  url_map = google_compute_url_map.redirect[0].id
}

resource "google_compute_global_forwarding_rule" "http" {
  count                 = local.use_load_balancer ? 1 : 0
  name                  = "${var.service_name}-http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  target                = google_compute_target_http_proxy.redirect[0].id
  port_range            = "80"
  ip_address            = google_compute_global_address.web[0].id
}
