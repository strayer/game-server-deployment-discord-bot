terraform {
  required_version = "1.10.5"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.49.1"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "5.0.0"
    }
  }

  backend "s3" {
    # set endpoint via AWS_S3_ENDPOINT env
    # set region via AWS_REGION env
    # set access_key via AWS_ACCESS_KEY_ID env
    # set secret_access_key via AWS_SECRET_ACCESS_KEY env
    # set bucket via terraform init -backend-config="bucket=..." CLI option

    key = "abiotic-factor"

    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_s3_checksum            = true
    use_path_style              = true
  }
}

variable "hcloud_token" {
  type      = string
  sensitive = true
}

variable "cloudflare_email" {
  type      = string
  sensitive = true
}

variable "cloudflare_api_key" {
  type      = string
  sensitive = true
}

variable "zone_name" {
  type = string
}

data "cloudflare_zones" "search" {
  name = var.zone_name
}

data "cloudflare_zone" "zone" {
  zone_id = data.cloudflare_zones.search.result.0.id
}

variable "abiotic_factor_server_subdomain" {
  type = string
}

variable "restic_abiotic_factor_repo" {
  type = string
}

variable "restic_abiotic_factor_password" {
  type      = string
  sensitive = true
}

variable "restic_abiotic_factor_aws_access_key_id" {
  type = string
}

variable "restic_abiotic_factor_aws_secret_access_key" {
  type      = string
  sensitive = true
}

variable "abiotic_factor_server_name" {
  type = string
}

variable "abiotic_factor_server_password" {
  type      = string
  sensitive = true
}

variable "abiotic_factor_world_save_name" {
  type    = string
  default = "Cascade"
}

variable "abiotic_factor_max_players" {
  type    = number
  default = 6
}

variable "abiotic_factor_discord_channel_webhook" {
  type      = string
  sensitive = true
}

variable "ssh_pubkey" {
  type      = string
  sensitive = true
}

variable "bot_server_started_message" {
  type = string
}

variable "bot_server_ready_message" {
  type = string
}

variable "abiotic_factor_server_type" {
  type    = string
  default = "ccx23"
}

variable "abiotic_factor_location" {
  type    = string
  default = "nbg1"
}

# Configure the Hetzner Cloud Provider
provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  email   = var.cloudflare_email
  api_key = var.cloudflare_api_key
}


resource "cloudflare_dns_record" "abiotic_factor_server_ipv4" {
  zone_id = data.cloudflare_zone.zone.zone_id
  name    = var.abiotic_factor_server_subdomain
  content = hcloud_server.abiotic-factor-server.ipv4_address
  type    = "A"
  ttl     = 60
}

# Abiotic Factor may not support IPv6 - commenting out for now
# resource "cloudflare_dns_record" "abiotic_factor_server_ipv6" {
#   zone_id = data.cloudflare_zone.zone.zone_id
#   name    = var.abiotic_factor_server_subdomain
#   content = hcloud_server.abiotic-factor-server.ipv6_address
#   type    = "AAAA"
#   ttl     = 60
# }

resource "hcloud_ssh_key" "discord_bot" {
  name       = "abiotic-factor-discord-bot"
  public_key = var.ssh_pubkey
}

data "hcloud_ssh_keys" "all_keys" {
  depends_on = [
    hcloud_ssh_key.discord_bot,
  ]
}

resource "hcloud_firewall" "abiotic-factor-firewall" {
  name = "abiotic-factor-firewall"

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
    port      = "7777"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  rule {
    direction = "in"
    protocol  = "udp"
    port      = "27015"
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

resource "hcloud_server" "abiotic-factor-server" {
  name        = "abiotic-factor-server"
  image       = data.hcloud_image.debian-12.id
  server_type = var.abiotic_factor_server_type
  location    = var.abiotic_factor_location

  ssh_keys     = data.hcloud_ssh_keys.all_keys.ssh_keys.*.name
  firewall_ids = [hcloud_firewall.abiotic-factor-firewall.id]
  user_data = templatefile("${path.module}/cloud-init.tftpl", {
    restic_abiotic_factor_repo                  = var.restic_abiotic_factor_repo,
    restic_abiotic_factor_password              = var.restic_abiotic_factor_password,
    restic_abiotic_factor_aws_access_key_id     = var.restic_abiotic_factor_aws_access_key_id,
    restic_abiotic_factor_aws_secret_access_key = var.restic_abiotic_factor_aws_secret_access_key,
    abiotic_factor_server_name                  = var.abiotic_factor_server_name,
    abiotic_factor_server_password              = var.abiotic_factor_server_password,
    abiotic_factor_world_save_name              = var.abiotic_factor_world_save_name,
    abiotic_factor_max_players                  = var.abiotic_factor_max_players,
    abiotic_factor_discord_channel_webhook      = var.abiotic_factor_discord_channel_webhook
    bot_server_started_message                  = var.bot_server_started_message,
    bot_server_ready_message                    = var.bot_server_ready_message,
  })
}

resource "hcloud_rdns" "abiotic-factor-server-ipv4" {
  server_id  = hcloud_server.abiotic-factor-server.id
  ip_address = hcloud_server.abiotic-factor-server.ipv4_address
  dns_ptr    = "${var.abiotic_factor_server_subdomain}.${var.zone_name}"
}

output "server_ip" { value = hcloud_server.abiotic-factor-server.ipv4_address }
