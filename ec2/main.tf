# Generate SSH key pair locally
# creates both private and public key in memory during terraform apply
resource "tls_private_key" "keycloak" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

# Save private key to your machine
# you use this file to SSH into EC2
# file_permission 0400 = only you can read it, no one else
resource "local_file" "private_key" {
  content         = tls_private_key.keycloak.private_key_pem
  filename        = "${path.module}/keycloak-demo-key.pem"
  file_permission = "0400"
}

# Upload public key to AWS
# EC2 stores this, when you SSH it matches against your private key
resource "aws_key_pair" "keycloak" {
  key_name   = "keycloak-demo-key"
  public_key = tls_private_key.keycloak.public_key_openssh
}

# Security group — controls who can reach EC2 on which ports
resource "aws_security_group" "keycloak" {
  name        = "keycloak-demo-sg"
  description = "Keycloak rotation demo"

  # SSH access — only your machine can SSH in
  # your_ip comes from variables.tf
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${var.your_ip}/32"]
  }

  # Keycloak port — open to everyone
  # Lambda has no fixed IP so we cannot restrict it
  # every time Lambda runs AWS gives it a random IP
  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # all outbound traffic allowed
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    ManagedBy = "terraform"
    Project   = "keycloak-rotation-demo"
  }
}

# Data source — does not create anything
# just looks up the latest Ubuntu 24.04 AMI ID from AWS
# 099720109477 is Canonical's official AWS account ID
# * wildcard matches any patch version
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

# EC2 instance running Keycloak via Docker
resource "aws_instance" "keycloak" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = "t3.small"
  key_name                    = aws_key_pair.keycloak.key_name
  vpc_security_group_ids      = [aws_security_group.keycloak.id]
  associate_public_ip_address = true

  # runs once on first boot automatically
  # installs Docker, starts Keycloak with HTTP enabled
  user_data = <<-EOT
    #!/bin/bash
    apt-get update -y
    apt-get install -y docker.io
    systemctl start docker
    systemctl enable docker

    docker run -d \
      --name keycloak \
      --restart unless-stopped \
      -p 8080:8080 \
      -e KEYCLOAK_ADMIN=admin \
      -e KEYCLOAK_ADMIN_PASSWORD=Admin@1234 \
      -e KC_HTTP_ENABLED=true \
      -e KC_HOSTNAME_STRICT=false \
      -e KC_HOSTNAME_STRICT_HTTPS=false \
      -e KC_PROXY=edge \
      quay.io/keycloak/keycloak:latest \
      start-dev

    # wait for Keycloak to fully start before disabling SSL
    sleep 60

    # disable SSL requirement in master realm
    # so admin console works over plain HTTP
    docker exec keycloak /opt/keycloak/bin/kcadm.sh \
      config credentials \
      --server http://localhost:8080 \
      --realm master \
      --user admin \
      --password Admin@1234

    docker exec keycloak /opt/keycloak/bin/kcadm.sh \
      update realms/master \
      -s sslRequired=NONE
  EOT

  tags = {
    Name      = "keycloak-rotation-demo"
    ManagedBy = "terraform"
    Project   = "keycloak-rotation-demo"
  }
}

