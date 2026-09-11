# Optional custom domain: global HTTPS load balancer in front of Cloud Run with a Google-managed
# certificate. Without it the site is served from the run.app URL.

locals {
  use_load_balancer = var.custom_domain != ""
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
