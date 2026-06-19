terraform {
  required_version = "1.10.5"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.49.1"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "5.21.0"
    }
  }

  backend "local" {
    path = "/terraform/state/windrose/terraform.tfstate"
  }
}

variable "hcloud_token" {
  type      = string
  sensitive = true
}

variable "cloudflare_api_token" {
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

variable "windrose_server_subdomain" {
  type = string
}

variable "restic_windrose_repo" {
  type = string
}

variable "restic_windrose_password" {
  type      = string
  sensitive = true
}

variable "restic_windrose_aws_access_key_id" {
  type = string
}

variable "restic_windrose_aws_secret_access_key" {
  type      = string
  sensitive = true
}

variable "windrose_server_name" {
  type = string
}

variable "windrose_server_password" {
  type      = string
  sensitive = true
}

variable "windrose_max_players" {
  type    = number
  default = 10
}

variable "windrose_discord_channel_webhook" {
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

variable "windrose_server_type" {
  type    = string
  default = "ccx23"
}

variable "windrose_location" {
  type    = string
  default = "nbg1"
}

# Configure the Hetzner Cloud Provider
provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}


resource "cloudflare_dns_record" "windrose_server_ipv4" {
  zone_id = data.cloudflare_zone.zone.zone_id
  name    = var.windrose_server_subdomain
  content = hcloud_server.windrose-server.ipv4_address
  type    = "A"
  ttl     = 60
}

# Windrose direct connection is IPv4-only - no AAAA record.

resource "hcloud_ssh_key" "discord_bot" {
  name       = "windrose-discord-bot"
  public_key = var.ssh_pubkey
}

data "hcloud_ssh_keys" "all_keys" {
  depends_on = [
    hcloud_ssh_key.discord_bot,
  ]
}

resource "hcloud_firewall" "windrose-firewall" {
  name = "windrose-firewall"

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

  # Windrose direct connection requires the game port on both TCP and UDP.
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "7777"
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
}

data "hcloud_image" "debian-12" {
  name              = "debian-12"
  with_architecture = "x86"
}

data "hcloud_volume" "windrose_install" {
  name = "windrose-install"
}

resource "hcloud_server" "windrose-server" {
  name        = "windrose-server"
  image       = data.hcloud_image.debian-12.id
  server_type = var.windrose_server_type
  location    = var.windrose_location

  ssh_keys     = data.hcloud_ssh_keys.all_keys.ssh_keys.*.name
  firewall_ids = [hcloud_firewall.windrose-firewall.id]
  user_data = templatefile("${path.module}/cloud-init.tftpl", {
    restic_windrose_repo                  = var.restic_windrose_repo,
    restic_windrose_password              = var.restic_windrose_password,
    restic_windrose_aws_access_key_id     = var.restic_windrose_aws_access_key_id,
    restic_windrose_aws_secret_access_key = var.restic_windrose_aws_secret_access_key,
    windrose_server_name                  = var.windrose_server_name,
    windrose_server_password              = var.windrose_server_password,
    windrose_max_players                  = var.windrose_max_players,
    windrose_discord_channel_webhook      = var.windrose_discord_channel_webhook
    bot_server_started_message            = var.bot_server_started_message,
    bot_server_ready_message              = var.bot_server_ready_message,
    windrose_volume_id                    = data.hcloud_volume.windrose_install.id,
  })
}

resource "hcloud_volume_attachment" "windrose_install" {
  volume_id = data.hcloud_volume.windrose_install.id
  server_id = hcloud_server.windrose-server.id
  automount = false
}

resource "hcloud_rdns" "windrose-server-ipv4" {
  server_id  = hcloud_server.windrose-server.id
  ip_address = hcloud_server.windrose-server.ipv4_address
  dns_ptr    = "${var.windrose_server_subdomain}.${var.zone_name}"
}

output "server_ip" { value = hcloud_server.windrose-server.ipv4_address }
