# TRE Stock Serverless Pipeline

A fully automated, serverless data pipeline that tracks a watchlist of tech stocks, identifies the daily top mover by percentage change, and displays a rolling 7-day history on a public website — all running on the **AWS Free Tier**.

**Live Demo:** *(set after first deploy — see Deliverables section)*

---

## Architecture

```
EventBridge Cron (10 PM UTC daily)
        │
        ▼
Lambda: Ingestion ──► Massive.com API (/v2/aggs/ticker/{ticker}/prev)
        │              (AAPL · MSFT · GOOGL · AMZN · TSLA · NVDA)
        │
        │  pick max |% change| winner
        ▼
DynamoDB  stock-pipeline-prod-top-movers
   (date PK · TTL 30 days)
        ▲
        │
Lambda: API  ◄──  API Gateway HTTP API  GET /movers
        │          (last 7 days, CORS + Cache-Control)
        ▲
        │
S3 Static Website  ──fetch──►  Chart.js bar chart + mover cards
```

### AWS Services Used (all Free Tier)

| Service | Role |
|---|---|
| **Lambda** | Ingestion (daily cron) + API (on-demand) |
| **EventBridge** | Cron trigger — `cron(0 22 * * ? *)` |
| **DynamoDB** | Storage — one record per trading day |
| **API Gateway** | HTTP API v2 — `GET /movers` with execution logs enabled |
| **S3** | Static website hosting for the SPA |
| **Secrets Manager** | Secure storage for the Massive API key (no hardcoded keys in repo) |
| **CloudWatch** | 14-day log retention + alarms for Ingestion errors and API Gateway 5XX errors |
| **SNS** | Alert topic for real-time notification dispatch (emails) |
| **IAM** | Least-privilege roles per Lambda |

---

## Repository Structure

```
.
├── .github/
│   └── workflows/
│       └── deploy.yml          # CI/CD: Terraform + S3 sync on push to main
├── terraform/
│   ├── main.tf                 # Provider + locals
│   ├── variables.tf            # Input variables
│   ├── outputs.tf              # API URL, S3 URL, table name
│   ├── dynamodb.tf             # DynamoDB table with TTL
│   ├── iam.tf                  # Least-privilege IAM roles (one per Lambda)
│   ├── secrets.tf              # Secrets Manager secret
│   ├── lambda_ingestion.tf     # Ingestion Lambda + EventBridge rule
│   ├── lambda_api.tf           # API Lambda + API Gateway HTTP API
│   ├── s3.tf                   # S3 frontend bucket + static website config
│   ├── cloudwatch.tf           # Log groups + error alarm
│   └── terraform.tfvars.example
├── backend/
│   ├── ingestion/
│   │   └── handler.py          # Fetches OHLC, finds winner, writes DynamoDB
│   └── api/
│       └── handler.py          # Reads last 7 days from DynamoDB, returns JSON
├── frontend/
│   ├── index.html              # SPA shell
│   ├── styles.css              # Dark-theme responsive CSS
│   ├── app.js                  # Fetch + Chart.js + mover cards
│   └── config.js               # Runtime API URL (injected by CI/CD)
├── Makefile                    # Developer shortcuts
└── README.md
```

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| **Terraform** | ≥ 1.5 | [terraform.io/downloads](https://developer.hashicorp.com/terraform/downloads) |
| **AWS CLI** | ≥ 2 | [docs.aws.amazon.com/cli](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| **Python** | ≥ 3.12 | [python.org](https://www.python.org/downloads/) |

---

## Step 1 — AWS Setup

### 1a. Create an IAM User for deployment

1. Sign in to [AWS Console](https://console.aws.amazon.com) → **IAM** → **Users** → **Create user**
2. Name: `stock-pipeline-deploy`
3. Attach policy: `AdministratorAccess` *(scope down to least-privilege after the project is stable)*
4. Open the user → **Security credentials** → **Create access key** → choose **CLI**
5. Download the CSV — you will need **Access Key ID** and **Secret Access Key**

### 1b. Configure the AWS CLI

```bash
aws configure
# AWS Access Key ID:     <paste from CSV>
# AWS Secret Access Key: <paste from CSV>
# Default region name:   us-east-1
# Default output format: json
```

Verify it works:
```bash
aws sts get-caller-identity
```

---

## Step 2 — Massive.com API Key

1. Go to [massive.com/dashboard/signup](https://massive.com/dashboard/signup) and create a free account
2. Navigate to **Dashboard → API Keys** and copy your key
3. **Never commit this key to git** — store it as an environment variable:

```bash
export TF_VAR_massive_api_key="your-key-here"
```

Or add it to `~/.bashrc` / `~/.zshrc` for persistence.

---

## Step 3 — Deploy Infrastructure

```bash
# 1. Clone the repo (if not already local)
git clone https://github.com/manishbhusal7/Stockserverlesspipeline.git
cd Stockserverlesspipeline

# 2. Initialise Terraform
make init

# 3. Preview what will be created
make plan

# 4. Apply (creates ~15 AWS resources, takes ~2 minutes)
make apply
```

After `apply` completes, Terraform prints:

```
api_gateway_url    = "https://xxxxxxxxx.execute-api.us-east-1.amazonaws.com/movers"
s3_website_url     = "http://stock-pipeline-prod-frontend-xxxxxxxx.s3-website-us-east-1.amazonaws.com"
dynamodb_table_name = "stock-pipeline-prod-top-movers"
```

---

## Step 4 — Deploy Frontend

```bash
make frontend-deploy
```

This injects the API URL into `frontend/config.js` and syncs the SPA to S3.

---

## Step 5 — Test the Pipeline

### Manually trigger the ingestion Lambda after deploy
```bash
make trigger
```
Calls the Massive API for real and writes one record to DynamoDB. Run this after 4 PM ET on a trading day.

### Test the API directly
```bash
curl -s "$(cd terraform && terraform output -raw api_gateway_url)" | python3 -m json.tool
```

---

## Step 6 — CI/CD (Auto-deploy on push)

Add the following secrets to **GitHub → Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | From the IAM user CSV |
| `AWS_SECRET_ACCESS_KEY` | From the IAM user CSV |
| `MASSIVE_API_KEY` | From your Massive dashboard |

Every push to `main` will now:
1. Run `terraform apply` (updates infra + Lambda code)
2. Inject the API URL into `config.js`
3. Sync the frontend to S3

---

## How It Works

### Ingestion Lambda

Triggered by EventBridge at `cron(0 22 * * ? *)` (10 PM UTC = after US market close).

For each ticker in the watchlist, it calls:
```
GET https://api.massive.com/v2/aggs/ticker/{TICKER}/prev
Authorization: Bearer <api_key>
```

Response contains `o` (open) and `c` (close). The percentage change is:
```
pct_change = ((close - open) / open) × 100
```

The ticker with the highest `abs(pct_change)` is written to DynamoDB:

```json
{
  "date":        "2026-06-07",
  "ticker":      "NVDA",
  "pct_change":  4.2300,
  "close_price": 902.50,
  "open_price":  865.80,
  "expires_at":  1752614400,
  "ingested_at": "2026-06-07T22:00:12+00:00"
}
```

### API Lambda

Responds to `GET /movers`. Builds a wider calendar lookback to tolerate weekends and market holidays, reads those date keys from DynamoDB, retries any `UnprocessedKeys`, sorts by date, and returns the latest 7 stored winners:

```json
{
  "status": "success",
  "count": 5,
  "data": [
    { "date": "2026-06-07", "ticker": "NVDA", "pct_change": 4.23, "close_price": 902.50, "open_price": 865.80, "direction": "gain" },
    ...
  ]
}
```

### Weekend & Holiday Handling

- The ingestion Lambda runs daily but the Massive `/prev` endpoint returns the most recent **trading** day's data. On weekends it returns Friday's bar.
- DynamoDB `PutItem` is idempotent on the same `date` key — running the Lambda on Saturday and Sunday both write/overwrite the same Friday record harmlessly.
- The API returns however many records exist; missing days are simply omitted.

### Error Handling & Alerts

| Scenario | Behaviour |
|---|---|
| Massive API rate-limit (429) | Exponential back-off, up to 3 retries per ticker |
| Massive API auth failure (401/403) | Immediate raise → Ingestion CloudWatch alarm fires |
| No valid ticker data returned | Lambda raises error so EventBridge retries → CloudWatch alarm fires |
| API Lambda DynamoDB error | Returns HTTP 500 with structured JSON error |
| API Gateway 5XX Error | API Gateway alarm fires on any server/lambda errors |
| `config.js` URL not set | Frontend shows clear error panel with "API URL is not configured" |

#### [ALERTS] Monitoring & Alerting
1. **CloudWatch Metrics**: Alarms monitor Lambda execution metrics (`Errors` for Ingestion) and API Gateway (`5XXError` over a 5-minute window).
2. **SNS Notifications**: When any alarm breaches its threshold, it automatically triggers an SNS Topic (`stock-pipeline-prod-alerts-topic`). 
3. **Email Subscriptions**: An administrator email can be registered with the topic by setting the `admin_email` Terraform variable, sending real-time notification alerts if any critical subsystem experiences downtime.

---

## Local Development

### Test Lambda functions locally

```bash
# Ingestion handler
cd backend/ingestion
DYNAMODB_TABLE_NAME=local-test \
MASSIVE_SECRET_NAME=test-secret \
python3 -c "
import handler, json
# Mock event / context
print(handler.lambda_handler({}, {}))
"
```

### Browse the S3 website locally

```bash
cd frontend
python3 -m http.server 8080
# open http://localhost:8080
# Update config.js with your API URL for real data
```

---

## Trade-offs & Design Decisions

| Decision | Rationale |
|---|---|
| **HTTP API (v2) over REST API (v1)** | Lower latency, simpler config, cheaper pricing, CORS built-in |
| **DynamoDB PAY_PER_REQUEST** | Zero cost at low volume; no capacity planning needed |
| **`date` as the partition key** | Each trading day has exactly one winner; O(1) lookups |
| **`BatchGetItem` vs Scan** | Reads a bounded date lookback; avoids full-table scans while still handling weekends and holidays |
| **urllib over `requests`** | No Lambda layer / dependencies needed — stdlib only |
| **Local Terraform state (default)** | Simpler initial setup; remote S3 backend instructions provided |
| **Vanilla JS frontend** | No build step = simpler S3 deployment; Chart.js from CDN |
| **TTL 30 days on DynamoDB** | Automatic cleanup keeps storage within free tier |
| **Separate IAM roles per Lambda** | Least-privilege: ingestion can only PutItem; API can only BatchGetItem |

---

## Tear Down

```bash
make destroy
```

All AWS resources are removed. The Terraform state will show 0 resources.

---

## Deliverables

- **GitHub Repository:** https://github.com/manishbhusal7/Stockserverlesspipeline
- **Live Frontend URL:** *(printed by `make apply` and `make frontend-deploy`)*
- **API Endpoint:** `GET {api_gateway_url}` returns JSON
