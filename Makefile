# ── Stock Serverless Pipeline — Makefile ───────────────────────────────────
#
# Prerequisites: AWS CLI, Terraform ≥ 1.5, Python 3.12+
# Usage: make <target>

.PHONY: help init validate plan apply destroy \
        frontend-deploy trigger \
        create-state-bucket logs-ingestion logs-api

SHELL := /bin/bash
TF_DIR := terraform

# Resolve outputs lazily (only when Terraform state exists)
_tf_out = $(shell cd $(TF_DIR) && terraform output -raw $(1) 2>/dev/null)

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Terraform lifecycle ────────────────────────────────────────────────────

init: ## Initialise Terraform providers and modules
	cd $(TF_DIR) && terraform init

validate: ## Validate Terraform configuration
	cd $(TF_DIR) && terraform validate

plan: ## Preview infrastructure changes (reads TF_VAR_massive_api_key from env)
	cd $(TF_DIR) && terraform plan

apply: ## Deploy / update all infrastructure
	cd $(TF_DIR) && terraform apply

destroy: ## Tear down all AWS resources (irreversible!)
	@read -p "[WARNING] This will destroy ALL resources. Type 'yes' to confirm: " confirm && \
	  [ "$$confirm" = "yes" ] && cd $(TF_DIR) && terraform destroy

# ── Frontend ───────────────────────────────────────────────────────────────

frontend-deploy: ## Inject API URL into config.js and sync frontend to S3
	$(eval API_URL  := $(call _tf_out,api_gateway_url))
	$(eval S3_BUCKET := $(call _tf_out,s3_bucket_name))
	@if [ -z "$(API_URL)" ]; then echo "[ERROR] Run 'make apply' first"; exit 1; fi
	@cp frontend/config.js /tmp/config.js.bak
	@sed -i "s|PLACEHOLDER_API_URL|$(API_URL)|g" frontend/config.js
	@aws s3 sync frontend/ "s3://$(S3_BUCKET)/" --delete --cache-control "max-age=300, public"
	@cp /tmp/config.js.bak frontend/config.js   # restore placeholder for local dev
	@echo "[SUCCESS] Frontend live at: $(call _tf_out,s3_website_url)"

# ── Lambda helpers ─────────────────────────────────────────────────────────

trigger: ## Manually invoke the ingestion Lambda (test run)
	$(eval FUNC := $(call _tf_out,ingestion_lambda_name))
	@if [ -z "$(FUNC)" ]; then echo "[ERROR] Run 'make apply' first"; exit 1; fi
	@echo "[RUN] Invoking $(FUNC)..."
	@aws lambda invoke \
	  --function-name "$(FUNC)" \
	  --log-type Tail \
	  --payload '{}' \
	  /tmp/ingestion-response.json \
	  --query LogResult \
	  --output text | base64 --decode
	@echo ""
	@echo "── Response ──────────────────────────────"
	@cat /tmp/ingestion-response.json | python3 -m json.tool

# ── Logs ──────────────────────────────────────────────────────────────────

logs-ingestion: ## Tail ingestion Lambda logs in real-time
	$(eval FUNC := $(call _tf_out,ingestion_lambda_name))
	@aws logs tail "/aws/lambda/$(FUNC)" --follow

logs-api: ## Tail API Lambda logs in real-time
	$(eval FUNC := $(call _tf_out,api_lambda_name))
	@aws logs tail "/aws/lambda/$(FUNC)" --follow

# ── Remote state bootstrap ─────────────────────────────────────────────────

create-state-bucket: ## Create S3 + DynamoDB for Terraform remote state (run once)
	@read -p "Enter your AWS account ID: " ACCT && \
	BUCKET="stock-pipeline-tf-state-$$ACCT" && \
	REGION="us-east-1" && \
	aws s3api create-bucket --bucket "$$BUCKET" --region "$$REGION" && \
	aws s3api put-bucket-versioning --bucket "$$BUCKET" \
	  --versioning-configuration Status=Enabled && \
	aws s3api put-bucket-encryption --bucket "$$BUCKET" \
	  --server-side-encryption-configuration \
	  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' && \
	aws dynamodb create-table --table-name stock-pipeline-tf-locks \
	  --attribute-definitions AttributeName=LockID,AttributeType=S \
	  --key-schema AttributeName=LockID,KeyType=HASH \
	  --billing-mode PAY_PER_REQUEST \
	  --region "$$REGION" && \
	echo "" && \
	echo "[SUCCESS] State bucket:  $$BUCKET" && \
	echo "[SUCCESS] Lock table:    stock-pipeline-tf-locks" && \
	echo "" && \
	echo "Uncomment the backend block in terraform/main.tf and set:" && \
	echo '  bucket = "'$$BUCKET'"'
