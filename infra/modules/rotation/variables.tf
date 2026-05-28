variable "aws_region"         { type = string }
variable "aws_account_id"     { type = string }
variable "secret_arn"         { type = string }
variable "secret_name"        { type = string }
variable "keycloak_url"       { type = string }
variable "keycloak_realm"     { type = string }
variable "keycloak_client_id" { type = string }
variable "rotation_days"      { type = number }