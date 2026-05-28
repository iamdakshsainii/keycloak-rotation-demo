module "secrets" {
  source         = "./modules/secrets"
  aws_region     = var.aws_region
  aws_account_id = var.aws_account_id
  secret_name    = var.secret_name
}

module "rotation" {
  source             = "./modules/rotation"
  aws_region         = var.aws_region
  aws_account_id     = var.aws_account_id
  secret_arn         = module.secrets.secret_arn
  secret_name        = var.secret_name
  keycloak_url       = var.keycloak_url
  keycloak_realm     = var.keycloak_realm
  keycloak_client_id = var.keycloak_client_id
  rotation_days      = var.rotation_days
}