# Zip the ingestion Lambda source directory at plan time
data "archive_file" "ingestion" {
  type        = "zip"
  source_dir  = "${path.root}/../backend/ingestion"
  output_path = "${path.root}/ingestion.zip"
}

resource "aws_lambda_function" "ingestion" {
  function_name    = "${local.name_prefix}-ingestion"
  description      = "Fetches daily OHLC data from Massive API, finds the top mover, and stores in DynamoDB"
  filename         = data.archive_file.ingestion.output_path
  source_code_hash = data.archive_file.ingestion.output_base64sha256
  role             = aws_iam_role.ingestion.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 180 # Allows pacing for Massive free-tier rate limits
  memory_size      = 256

  environment {
    variables = {
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.top_movers.name
      MASSIVE_SECRET_NAME = aws_secretsmanager_secret.massive_api_key.name
      WATCHLIST           = join(",", var.watchlist)
      TTL_DAYS            = tostring(var.ttl_days)
      MASSIVE_REQUEST_DELAY_SECONDS = "13"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ingestion]
}

# ── EventBridge schedule ────────────────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "daily_ingestion" {
  name                = "${local.name_prefix}-daily-ingestion"
  description         = "Triggers the stock ingestion Lambda on a daily schedule"
  schedule_expression = var.cron_schedule
}

resource "aws_cloudwatch_event_target" "ingestion_lambda" {
  rule = aws_cloudwatch_event_rule.daily_ingestion.name
  arn  = aws_lambda_function.ingestion.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestion.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_ingestion.arn
}
