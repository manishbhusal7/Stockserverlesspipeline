output "api_gateway_url" {
  description = "Full URL for the GET /movers endpoint"
  value       = "${trimsuffix(aws_apigatewayv2_stage.api.invoke_url, "/")}/movers"
}

output "s3_website_url" {
  description = "Public URL of the S3 static website"
  value       = "http://${aws_s3_bucket_website_configuration.frontend.website_endpoint}"
}

output "s3_bucket_name" {
  description = "S3 bucket name (used by CI/CD to sync frontend files)"
  value       = aws_s3_bucket.frontend.id
}

output "dynamodb_table_name" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.top_movers.name
}

output "ingestion_lambda_name" {
  description = "Ingestion Lambda function name (for manual triggers)"
  value       = aws_lambda_function.ingestion.function_name
}

output "api_lambda_name" {
  description = "API Lambda function name"
  value       = aws_lambda_function.api.function_name
}

output "secret_arn" {
  description = "ARN of the Secrets Manager secret holding the Massive API key"
  value       = aws_secretsmanager_secret.massive_api_key.arn
  sensitive   = true
}
