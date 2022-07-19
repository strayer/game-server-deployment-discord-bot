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

    key = "zomboid"

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

variable "zomboid_server_subdomain" {
  sensitive = true
}

variable "zomboid_restic_repo" {
  sensitive = true
}

variable "zomboid_restic_password" {
  sensitive = true
}

variable "zomboid_restic_aws_access_key_id" {
  sensitive = true
}

variable "zomboid_restic_aws_secret_access_key" {
  sensitive = true
}

variable "s3_hostname" {
  sensitive = true
}

variable "s3_ip" {
  sensitive = true
}

variable "zomboid_wireguard_private_key" {
  sensitive = true
}

variable "zomboid_wireguard_restic_peer_psk" {
  sensitive = true
}

variable "zomboid_wireguard_address" {
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

variable "zomboid_servername" {
  sensitive = true
}

variable "zomboid_adminpassword" {
  sensitive = true
}

variable "zomboid_discord_channel_webhook" {
  sensitive = true
}

variable "ssh_pubkey" {
  sensitive = true
}

variable "zomboid_hcloud_volume_name" {
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

data "hcloud_volume" "zomboid_data" {
  name = var.zomboid_hcloud_volume_name
}

resource "cloudflare_record" "zomboid_server_ipv4" {
  zone_id = data.cloudflare_zone.zone.zone_id
  name    = var.zomboid_server_subdomain
  value   = hcloud_server.zomboid-server.ipv4_address
  type    = "A"
  ttl     = 60
}

resource "cloudflare_record" "zomboid_server_ipv6" {
  zone_id = data.cloudflare_zone.zone.zone_id
  name    = var.zomboid_server_subdomain
  value   = hcloud_server.zomboid-server.ipv6_address
  type    = "AAAA"
  ttl     = 60
}

resource "hcloud_ssh_key" "discord_bot" {
  name       = "zomboid-discord-bot"
  public_key = var.ssh_pubkey
}

data "hcloud_ssh_keys" "all_keys" {
  depends_on = [
    hcloud_ssh_key.discord_bot,
  ]
}

resource "hcloud_firewall" "zomboid-firewall" {
  name = "zomboid-firewall"

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
    port      = "8766"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  rule {
    direction = "in"
    protocol  = "udp"
    port      = "8767"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  rule {
    direction = "in"
    protocol  = "udp"
    port      = "16261"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "16262-16272"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
}

resource "hcloud_server" "zomboid-server" {
  name        = "zomboid-server"
  image       = "debian-11"
  server_type = "ccx22"
  location    = "nbg1"

  ssh_keys     = data.hcloud_ssh_keys.all_keys.ssh_keys.*.name
  firewall_ids = [hcloud_firewall.zomboid-firewall.id]
  user_data    = templatefile("${path.module}/cloud-init.tftpl", {
    zomboid_restic_repo = var.zomboid_restic_repo,
    zomboid_restic_password = var.zomboid_restic_password,
    zomboid_restic_aws_access_key_id = var.zomboid_restic_aws_access_key_id,
    zomboid_restic_aws_secret_access_key = var.zomboid_restic_aws_secret_access_key,
    s3_hostname = var.s3_hostname,
    s3_ip = var.s3_ip,
    zomboid_wireguard_address = var.zomboid_wireguard_address,
    zomboid_wireguard_private_key = var.zomboid_wireguard_private_key,
    wireguard_restic_peer_public_key = var.wireguard_restic_peer_public_key,
    zomboid_wireguard_restic_peer_psk = var.zomboid_wireguard_restic_peer_psk,
    wireguard_restic_peer_addresses = var.wireguard_restic_peer_addresses,
    wireguard_restic_peer_endpoint = var.wireguard_restic_peer_endpoint,
    volume_device_path = data.hcloud_volume.zomboid_data.linux_device,
    zomboid_servername = var.zomboid_servername,
    zomboid_adminpassword = var.zomboid_adminpassword,
    zomboid_discord_channel_webhook = var.zomboid_discord_channel_webhook
  })
}

resource "hcloud_rdns" "zomboid-server-ipv4" {
  server_id  = hcloud_server.zomboid-server.id
  ip_address = hcloud_server.zomboid-server.ipv4_address
  dns_ptr    = cloudflare_record.zomboid_server_ipv4.hostname
}


resource "hcloud_volume_attachment" "zomboid_data-to-server" {
  volume_id = data.hcloud_volume.zomboid_data.id
  server_id = hcloud_server.zomboid-server.id
  automount = false
}

output "server_ip" { value = hcloud_server.zomboid-server.ipv4_address }
