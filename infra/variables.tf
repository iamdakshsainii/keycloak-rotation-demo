variable "aws_region" {
  type    = string
  default = "eu-north-1"
}

variable "aws_account_id" {
  type    = string
  default = "905418385260"
}

variable "secret_name" {
  type    = string
  default = "keycloak-rotation-demo/client-secret"
}

variable "keycloak_url" {
  description = "Public URL of your Keycloak EC2 — from ec2 terraform output"
  type        = string
}

variable "keycloak_realm" {
  type    = string
  default = "demo"
}

variable "keycloak_client_id" {
  type    = string
  default = "demo-app"
}

variable "rotation_days" {
  type    = number
  default = 1
}