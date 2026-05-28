resource "aws_secretsmanager_secret" "keycloak" {
  name                    = var.secret_name
  description             = "Keycloak client secret for rotation demo"
  recovery_window_in_days = 7

  tags = {
    ManagedBy = "terraform"
    Project   = "keycloak-rotation-demo"
  }
}

# Placeholder values — you replace these in AWS Console after terraform apply
# Real secrets must never go into Terraform state or Git
resource "aws_secretsmanager_secret_version" "placeholder" {
  secret_id = aws_secretsmanager_secret.keycloak.id

  secret_string = jsonencode({
    KEYCLOAK_URL           = "REPLACE_ME"
    KEYCLOAK_REALM         = "REPLACE_ME"
    KEYCLOAK_CLIENT_ID     = "REPLACE_ME"
    KEYCLOAK_CLIENT_SECRET = "REPLACE_ME"
    KEYCLOAK_ADMIN_USER    = "REPLACE_ME"
    KEYCLOAK_ADMIN_PASS    = "REPLACE_ME"
  })

  # Without this, terraform apply would overwrite your real values every time
  lifecycle {
    ignore_changes = [secret_string]
  }
}