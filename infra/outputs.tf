output "secret_arn" {
  value = module.secrets.secret_arn
}

output "lambda_function_name" {
  value = module.rotation.lambda_function_name
}