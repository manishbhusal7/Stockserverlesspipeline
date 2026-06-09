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

# ── SNS alerts topic for notifications ───────────────────────────────────────

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts-topic"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.admin_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.admin_email
}

# ── Alarm: alert when ingestion Lambda errors spike ─────────────────────────

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

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# ── Alarm: alert when API Gateway 5XX errors spike ──────────────────────────

resource "aws_cloudwatch_metric_alarm" "api_gateway_errors" {
  alarm_name          = "${local.name_prefix}-api-gateway-errors"
  alarm_description   = "API Gateway returned 5XX server errors — check CloudWatch logs for details"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "5XXError"
  namespace           = "AWS/ApiGateway"
  period              = 300 # 5-minute evaluation period
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    ApiId = aws_apigatewayv2_api.main.id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

