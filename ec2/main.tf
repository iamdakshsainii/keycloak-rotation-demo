# Generate SSH key pair locally
resource "tls_private_key" "keycloak" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

# Save private key to your machine
resource "local_file" "private_key" {
  content         = tls_private_key.keycloak.private_key_pem
  filename        = "${path.module}/keycloak-demo-key.pem"
  file_permission = "0400"
}

# Upload public key to AWS
resource "aws_key_pair" "keycloak" {
  key_name   = "keycloak-demo-key"
  public_key = tls_private_key.keycloak.public_key_openssh
}

# Security group
resource "aws_security_group" "keycloak" {
  name        = "keycloak-demo-sg"
  description = "Keycloak rotation demo"

  # SSH - your IP only
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${var.your_ip}/32"]  // ip is from variable and it is of machine to tell SG to only allow my machine to knock on port 22
  }

  # Keycloak - open to all because Lambda IPs are not fixed it is picked from pool everytime it execute - traffic coming into your EC2
  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # All outbound allowed
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

# EC2 instance - Ubuntu 24.04, t3.small
# Docker is installed automatically via user_data - no manual SSH needed for setup
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "aws_instance" "keycloak" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = "t3.small"
  key_name                    = aws_key_pair.keycloak.key_name
  vpc_security_group_ids      = [aws_security_group.keycloak.id]
  associate_public_ip_address = true

  # Runs on first boot - installs Docker and starts Keycloak automatically
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
      quay.io/keycloak/keycloak:latest \
      start-dev
  EOT

  tags = {
    Name      = "keycloak-rotation-demo"
    ManagedBy = "terraform"
    Project   = "keycloak-rotation-demo"
  }
}