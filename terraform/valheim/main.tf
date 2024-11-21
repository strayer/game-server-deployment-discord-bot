terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.49.1"
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

    key = "valheim"

    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    force_path_style            = true
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
  type      = string
  sensitive = true
}

variable "valheim_server_subdomain" {
  type      = string
  sensitive = true
}

variable "restic_valheim_repo" {
  type      = string
  sensitive = true
}

variable "restic_valheim_password" {
  type      = string
  sensitive = true
}

variable "restic_valheim_aws_access_key_id" {
  type      = string
  sensitive = true
}

variable "restic_valheim_aws_secret_access_key" {
  type      = string
  sensitive = true
}

variable "valheim_server_name" {
  type      = string
  sensitive = true
}

variable "valheim_server_world" {
  type      = string
  sensitive = true
}

variable "valheim_server_password" {
  type      = string
  sensitive = true
}

variable "valheim_discord_channel_webhook" {
  type      = string
  sensitive = true
}

variable "ssh_pubkey" {
  type      = string
  sensitive = true
}

variable "game_persona_bot_name" {
  type = string
}

variable "game_persona_bot_avatar_url" {
  type = string
}

variable "bot_server_started_message" {
  type = string
}

variable "bot_server_ready_message" {
  type = string
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

resource "cloudflare_record" "valheim_server_ipv4" {
  zone_id = data.cloudflare_zone.zone.zone_id
  name    = var.valheim_server_subdomain
  value   = hcloud_server.valheim-server.ipv4_address
  type    = "A"
  ttl     = 60
}

resource "cloudflare_record" "valheim_server_ipv6" {
  zone_id = data.cloudflare_zone.zone.zone_id
  name    = var.valheim_server_subdomain
  value   = hcloud_server.valheim-server.ipv6_address
  type    = "AAAA"
  ttl     = 60
}

resource "hcloud_ssh_key" "discord_bot" {
  name       = "valheim-discord-bot"
  public_key = var.ssh_pubkey
}

data "hcloud_ssh_keys" "all_keys" {
  depends_on = [
    hcloud_ssh_key.discord_bot,
  ]
}

resource "hcloud_firewall" "valheim-firewall" {
  name = "valheim-firewall"

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
    port      = "2456-2457"
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

resource "hcloud_server" "valheim-server" {
  name        = "valheim-server"
  image       = data.hcloud_image.debian-12.id
  server_type = "ccx23"
  location    = "nbg1"

  ssh_keys     = data.hcloud_ssh_keys.all_keys.ssh_keys.*.name
  firewall_ids = [hcloud_firewall.valheim-firewall.id]
  user_data = templatefile("${path.module}/cloud-init.tftpl", {
    restic_valheim_repo                  = var.restic_valheim_repo,
    restic_valheim_password              = var.restic_valheim_password,
    restic_valheim_aws_access_key_id     = var.restic_valheim_aws_access_key_id,
    restic_valheim_aws_secret_access_key = var.restic_valheim_aws_secret_access_key,
    valheim_server_name                  = var.valheim_server_name,
    valheim_server_world                 = var.valheim_server_world,
    valheim_server_password              = var.valheim_server_password,
    valheim_discord_channel_webhook      = var.valheim_discord_channel_webhook
    game_persona_bot_name                = var.game_persona_bot_name,
    game_persona_bot_avatar_url          = var.game_persona_bot_avatar_url,
    bot_server_started_message           = var.bot_server_started_message,
    bot_server_ready_message             = var.bot_server_ready_message,
  })
}

resource "hcloud_rdns" "valheim-server-ipv4" {
  server_id  = hcloud_server.valheim-server.id
  ip_address = hcloud_server.valheim-server.ipv4_address
  dns_ptr    = cloudflare_record.valheim_server_ipv4.hostname
}

output "server_ip" { value = hcloud_server.valheim-server.ipv4_address }
