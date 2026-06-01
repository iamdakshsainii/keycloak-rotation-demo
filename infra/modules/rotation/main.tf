# it creates 5 resources


# Zips rotation.py so Terraform can upload it to Lambda
data "archive_file" "rotation_lambda" {
  type        = "zip"
  source_file = "${path.module}/lambda/rotation.py"
  output_path = "${path.module}/lambda/rotation.zip"
}

# IAM role Lambda executes under
resource "aws_iam_role" "lambda_rotation" {
  name = "keycloak-rotation-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Lambda needs: read/write secret versions + write logs
resource "aws_iam_role_policy" "lambda_rotation" {
  name = "keycloak-rotation-lambda-policy"
  role = aws_iam_role.lambda_rotation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:DescribeSecret",
          "secretsmanager:UpdateSecretVersionStage"
        ]
        Resource = "${var.secret_arn}*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "rotation" {
  filename         = data.archive_file.rotation_lambda.output_path
  function_name    = "keycloak-secrets-rotation"
  role             = aws_iam_role.lambda_rotation.arn
  handler          = "rotation.lambda_handler"   // rotation.lambda_handler = file rotation.py, function lambda_handler
  runtime          = "python3.11"  // run it with Python 3.11
  source_code_hash = data.archive_file.rotation_lambda.output_base64sha256  // if code changes, Terraform detects it and re-uploads
  timeout          = 60

  environment {
    variables = {
      SECRET_ARN         = var.secret_arn
      REGION             = var.aws_region
      KEYCLOAK_URL       = var.keycloak_url
      KEYCLOAK_REALM     = var.keycloak_realm
      KEYCLOAK_CLIENT_ID = var.keycloak_client_id
    }
  }

  tags = { ManagedBy = "terraform" }
}

# Without this, Secrets Manager cannot invoke Lambda and rotation silently does nothing
resource "aws_lambda_permission" "secrets_manager" {
  statement_id  = "AllowSecretsManagerInvocation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rotation.function_name
  principal     = "secretsmanager.amazonaws.com"
  source_arn    = var.secret_arn
}


# This tells Secrets Manager:
# "Every X days, automatically call this Lambda to rotate this secret"

resource "aws_secretsmanager_secret_rotation" "keycloak" {
  secret_id           = var.secret_arn
  rotation_lambda_arn = aws_lambda_function.rotation.arn

  rotation_rules {
    automatically_after_days = var.rotation_days
  }

  depends_on = [aws_lambda_permission.secrets_manager]
}