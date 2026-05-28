output "ec2_public_ip" {
  value       = aws_instance.keycloak.public_ip
  description = "Use this IP to SSH and to access Keycloak in browser"
}

output "keycloak_url" {
  value       = "http://${aws_instance.keycloak.public_ip}:8080"
  description = "Open this in browser to access Keycloak"
}

output "ssh_command" {
  value       = "ssh -i ${path.module}/keycloak-demo-key.pem ubuntu@${aws_instance.keycloak.public_ip}"
  description = "Run this command to SSH into the EC2 instance"
}