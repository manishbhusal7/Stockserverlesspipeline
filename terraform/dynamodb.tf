resource "aws_dynamodb_table" "top_movers" {
  name         = "${local.name_prefix}-top-movers"
  billing_mode = "PAY_PER_REQUEST" # On-demand; 25 GB free tier
  hash_key     = "date"

  attribute {
    name = "date"
    type = "S" # YYYY-MM-DD string; one record per trading day
  }

  # Auto-expire records after var.ttl_days to keep storage minimal
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false # Not needed at this scale; keeps cost at zero
  }
}
