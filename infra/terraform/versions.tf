terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.3"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State lives in a GCS bucket; pass it at init time:
  #   terraform init -backend-config="bucket=oral-tfstate" -backend-config="prefix=prod"
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
