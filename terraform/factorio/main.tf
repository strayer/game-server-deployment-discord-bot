terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.47.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }

  backend "s3" {
    # set endpoint via AWS_S3_ENDPOINT env
    # set region via AWS_REGION env
    # set access_key via AWS_ACCESS_KEY_ID env
    # set secret_access_key via AWS_SECRET_ACCESS_KEY env
    # set bucket via terraform init -backend-config="bucket=..." CLI option

    key = "factorio"

    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    force_path_style            = true
  }
}

variable "hcloud_token" {
  sensitive = true
}

variable "cloudflare_email" {
  sensitive = true
}

variable "cloudflare_api_key" {
  sensitive = true
}

variable "zone_name" {
  sensitive = true
}

variable "factorio_server_subdomain" {
  sensitive = true
}

variable "restic_factorio_repo" {
  sensitive = true
}

variable "restic_factorio_password" {
  sensitive = true
}

variable "restic_factorio_aws_access_key_id" {
  sensitive = true
}

variable "restic_factorio_aws_secret_access_key" {
  sensitive = true
}

variable "factorio_save_name" {
  sensitive = true
}

variable "factorio_discord_channel_webhook" {
  sensitive = true
}

variable "ssh_pubkey" {
  sensitive = true
}

# Configure the Hetzner Cloud Provider
provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  email   = var.cloudflare_email
  api_key = var.cloudflare_api_key
}

data "cloudflare_zone" "zone" {
  name = var.zone_name
}

resource "cloudflare_record" "factorio_server_ipv4" {
  zone_id = data.cloudflare_zone.zone.zone_id
  name    = var.factorio_server_subdomain
  value   = hcloud_server.factorio-server.ipv4_address
  type    = "A"
  ttl     = 60
}

resource "cloudflare_record" "factorio_server_ipv6" {
  zone_id = data.cloudflare_zone.zone.zone_id
  name    = var.factorio_server_subdomain
  value   = hcloud_server.factorio-server.ipv6_address
  type    = "AAAA"
  ttl     = 60
}

resource "hcloud_ssh_key" "discord_bot" {
  name       = "factorio-discord-bot"
  public_key = var.ssh_pubkey
}

data "hcloud_ssh_keys" "all_keys" {
  depends_on = [
    hcloud_ssh_key.discord_bot,
  ]
}

resource "hcloud_firewall" "factorio-firewall" {
  name = "factorio-firewall"

  rule {
    direction = "in"
    protocol  = "icmp"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  rule {
    direction = "in"
    protocol  = "udp"
    port      = "60001-60999"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  rule {
    direction = "in"
    protocol  = "udp"
    port      = "34197"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
}

data "hcloud_image" "debian-12" {
  name              = "debian-12"
  with_architecture = "x86"
}

resource "hcloud_server" "factorio-server" {
  name        = "factorio-server"
  image       = data.hcloud_image.debian-12.id
  server_type = "ccx13"
  location    = "nbg1"

  ssh_keys     = data.hcloud_ssh_keys.all_keys.ssh_keys.*.name
  firewall_ids = [hcloud_firewall.factorio-firewall.id]
  user_data = templatefile("${path.module}/cloud-init.tftpl", {
    restic_factorio_repo                  = var.restic_factorio_repo,
    restic_factorio_password              = var.restic_factorio_password,
    restic_factorio_aws_access_key_id     = var.restic_factorio_aws_access_key_id,
    restic_factorio_aws_secret_access_key = var.restic_factorio_aws_secret_access_key,
    factorio_save_name                    = var.factorio_save_name,
    factorio_discord_channel_webhook      = var.factorio_discord_channel_webhook
  })
}

resource "hcloud_rdns" "factorio-server-ipv4" {
  server_id  = hcloud_server.factorio-server.id
  ip_address = hcloud_server.factorio-server.ipv4_address
  dns_ptr    = cloudflare_record.factorio_server_ipv4.hostname
}

output "server_ip" { value = hcloud_server.factorio-server.ipv4_address }
