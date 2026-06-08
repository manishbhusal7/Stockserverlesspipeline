resource "aws_secretsmanager_secret" "massive_api_key" {
  name        = "${local.name_prefix}/massive-api-key"
  description = "Massive.com (Polygon.io) API key used by the ingestion Lambda"

  # Allow immediate deletion during dev/tear-down; increase for production
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "massive_api_key" {
  secret_id = aws_secretsmanager_secret.massive_api_key.id

  # Stored as JSON so the Lambda can extend with additional fields if needed
  secret_string = jsonencode({
    api_key = var.massive_api_key
  })
}
