terraform {
  required_version = "1.10.5"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.49.1"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "5.15.0"
    }
  }

  backend "s3" {
    # set endpoint via AWS_S3_ENDPOINT env
    # set region via AWS_REGION env
    # set access_key via AWS_ACCESS_KEY_ID env
    # set secret_access_key via AWS_SECRET_ACCESS_KEY env
    # set bucket via terraform init -backend-config="bucket=..." CLI option

    key = "enshrouded"

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

variable "enshrouded_server_subdomain" {
  type = string
}

variable "restic_enshrouded_repo" {
  type = string
}

variable "restic_enshrouded_password" {
  type      = string
  sensitive = true
}

variable "restic_enshrouded_aws_access_key_id" {
  type = string
}

variable "restic_enshrouded_aws_secret_access_key" {
  type      = string
  sensitive = true
}

variable "enshrouded_server_name" {
  type = string
}

variable "enshrouded_server_password" {
  type      = string
  sensitive = true
}

variable "enshrouded_discord_channel_webhook" {
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

variable "enshrouded_server_type" {
  type    = string
  default = "ccx23"
}

variable "enshrouded_location" {
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


resource "cloudflare_dns_record" "enshrouded_server_ipv4" {
  zone_id = data.cloudflare_zone.zone.zone_id
  name    = var.enshrouded_server_subdomain
  content = hcloud_server.enshrouded-server.ipv4_address
  type    = "A"
  ttl     = 60
}

# At time of writing Enshrouded does not support IPv6
# resource "cloudflare_dns_record" "enshrouded_server_ipv6" {
#   zone_id = data.cloudflare_zone.zone.zone_id
#   name    = var.enshrouded_server_subdomain
#   content = hcloud_server.enshrouded-server.ipv6_address
#   type    = "AAAA"
#   ttl     = 60
# }

resource "hcloud_ssh_key" "discord_bot" {
  name       = "enshrouded-discord-bot"
  public_key = var.ssh_pubkey
}

data "hcloud_ssh_keys" "all_keys" {
  depends_on = [
    hcloud_ssh_key.discord_bot,
  ]
}

resource "hcloud_firewall" "enshrouded-firewall" {
  name = "enshrouded-firewall"

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
    port      = "15636-15637"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "15636-15637"
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

resource "hcloud_server" "enshrouded-server" {
  name        = "enshrouded-server"
  image       = data.hcloud_image.debian-12.id
  server_type = var.enshrouded_server_type
  location    = var.enshrouded_location

  ssh_keys     = data.hcloud_ssh_keys.all_keys.ssh_keys.*.name
  firewall_ids = [hcloud_firewall.enshrouded-firewall.id]
  user_data = templatefile("${path.module}/cloud-init.tftpl", {
    restic_enshrouded_repo                  = var.restic_enshrouded_repo,
    restic_enshrouded_password              = var.restic_enshrouded_password,
    restic_enshrouded_aws_access_key_id     = var.restic_enshrouded_aws_access_key_id,
    restic_enshrouded_aws_secret_access_key = var.restic_enshrouded_aws_secret_access_key,
    enshrouded_server_name                  = var.enshrouded_server_name,
    enshrouded_server_password              = var.enshrouded_server_password,
    enshrouded_discord_channel_webhook      = var.enshrouded_discord_channel_webhook
    bot_server_started_message              = var.bot_server_started_message,
    bot_server_ready_message                = var.bot_server_ready_message,
  })
}

resource "hcloud_rdns" "enshrouded-server-ipv4" {
  server_id  = hcloud_server.enshrouded-server.id
  ip_address = hcloud_server.enshrouded-server.ipv4_address
  dns_ptr    = "${var.enshrouded_server_subdomain}.${var.zone_name}"
}

output "server_ip" { value = hcloud_server.enshrouded-server.ipv4_address }
