# ── Lambda log groups ───────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "ingestion" {
  name              = "/aws/lambda/${local.name_prefix}-ingestion"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name_prefix}-api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${local.name_prefix}"
  retention_in_days = 14
}

# ── Alarm: alert when ingestion Lambda errors spike ─────────────────────────
# (No SNS topic for now; visible in CloudWatch console)

resource "aws_cloudwatch_metric_alarm" "ingestion_errors" {
  alarm_name          = "${local.name_prefix}-ingestion-errors"
  alarm_description   = "Ingestion Lambda is erroring — check CloudWatch Logs for details"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 86400 # evaluate over a 24-hour window
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.ingestion.function_name
  }
}
