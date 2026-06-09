variable "aws_region" {
  description = "AWS region to deploy all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used as a prefix for all resource names"
  type        = string
  default     = "stock-pipeline"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "massive_api_key" {
  description = "Massive.com API key for fetching stock OHLC data. Set via TF_VAR_massive_api_key."
  type        = string
  sensitive   = true
}

variable "watchlist" {
  description = "Ticker symbols to track for daily top-mover analysis"
  type        = list(string)
  default     = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]
}

variable "cron_schedule" {
  description = "EventBridge schedule expression for the daily ingestion Lambda"
  type        = string
  # 10 PM UTC = after 4 PM ET market close (accommodates both EDT and EST)
  default = "cron(0 22 * * ? *)"
}

variable "ttl_days" {
  description = "Number of days before DynamoDB records are automatically deleted"
  type        = number
  default     = 30
}

variable "admin_email" {
  description = "Email address to receive critical system alerts (optional)"
  type        = string
  default     = ""
}

