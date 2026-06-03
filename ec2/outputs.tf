output "ec2_public_ip" {
  value       = aws_instance.keycloak.public_ip
  description = "Use this IP to SSH and to access Keycloak in browser"
}

# Output the public IP so you know where to access Keycloak
output "keycloak_url" {
  value = "http://${aws_instance.keycloak.public_ip}:8080"
}

output "ssh_command" {
  value = "ssh -i ${path.module}/keycloak-demo-key.pem ubuntu@${aws_instance.keycloak.public_ip}"
}