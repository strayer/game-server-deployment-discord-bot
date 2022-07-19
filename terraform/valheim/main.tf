terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.35.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 3.0"
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

variable "valheim_server_subdomain" {
  sensitive = true
}

variable "valheim_restic_repo" {
  sensitive = true
}

variable "valheim_restic_password" {
  sensitive = true
}

variable "valheim_restic_aws_access_key_id" {
  sensitive = true
}

variable "valheim_restic_aws_secret_access_key" {
  sensitive = true
}

variable "s3_hostname" {
  sensitive = true
}

variable "s3_ip" {
  sensitive = true
}

variable "valheim_wireguard_private_key" {
  sensitive = true
}

variable "valheim_wireguard_restic_peer_psk" {
  sensitive = true
}

variable "valheim_wireguard_address" {
  sensitive = true
}

variable "wireguard_restic_peer_addresses" {
  sensitive = true
}

variable "wireguard_restic_peer_public_key" {
  sensitive = true
}

variable "wireguard_restic_peer_endpoint" {
  sensitive = true
}

variable "valheim_server_name" {
  sensitive = true
}

variable "valheim_server_world" {
  sensitive = true
}

variable "valheim_server_password" {
  sensitive = true
}

variable "valheim_discord_channel_webhook" {
  sensitive = true
}

variable "ssh_pubkey" {
  sensitive = true
}

variable "valheim_hcloud_volume_name" {
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

data "hcloud_volume" "valheim_data" {
  name = var.valheim_hcloud_volume_name
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

resource "hcloud_server" "valheim-server" {
  name        = "valheim-server"
  image       = "debian-11"
  server_type = "ccx12"
  location    = "nbg1"

  ssh_keys     = data.hcloud_ssh_keys.all_keys.ssh_keys.*.name
  firewall_ids = [hcloud_firewall.valheim-firewall.id]
  user_data    = templatefile("${path.module}/cloud-init.tftpl", {
    valheim_restic_repo = var.valheim_restic_repo,
    valheim_restic_password = var.valheim_restic_password,
    valheim_restic_aws_access_key_id = var.valheim_restic_aws_access_key_id,
    valheim_restic_aws_secret_access_key = var.valheim_restic_aws_secret_access_key,
    s3_hostname = var.s3_hostname,
    s3_ip = var.s3_ip,
    valheim_wireguard_address = var.valheim_wireguard_address,
    valheim_wireguard_private_key = var.valheim_wireguard_private_key,
    wireguard_restic_peer_public_key = var.wireguard_restic_peer_public_key,
    valheim_wireguard_restic_peer_psk = var.valheim_wireguard_restic_peer_psk,
    wireguard_restic_peer_addresses = var.wireguard_restic_peer_addresses,
    wireguard_restic_peer_endpoint = var.wireguard_restic_peer_endpoint,
    volume_device_path = data.hcloud_volume.valheim_data.linux_device,
    valheim_server_name = var.valheim_server_name,
    valheim_server_world = var.valheim_server_world,
    valheim_server_password = var.valheim_server_password,
    valheim_discord_channel_webhook = var.valheim_discord_channel_webhook
  })
}

resource "hcloud_rdns" "valheim-server-ipv4" {
  server_id  = hcloud_server.valheim-server.id
  ip_address = hcloud_server.valheim-server.ipv4_address
  dns_ptr    = cloudflare_record.valheim_server_ipv4.hostname
}


resource "hcloud_volume_attachment" "valheim_data-to-server" {
  volume_id = data.hcloud_volume.valheim_data.id
  server_id = hcloud_server.valheim-server.id
  automount = false
}

output "server_ip" { value = hcloud_server.valheim-server.ipv4_address }
