# Serverless Stock Tracker Pipeline

A fully automated, production-grade serverless data pipeline that tracks tech stocks, identifies the daily top mover by percentage change, and displays a rolling 7-day history on a public dashboard. 

Built strictly on **AWS Free Tier** services using clean, modular Infrastructure as Code (IaC) and a decoupled, resilient architecture.

---

## Architecture Overview

This project is built with a strict **Separation of Concerns** to ensure high reliability, decoupling the scheduled data collector from the public-facing client API.

```
EventBridge (Cron) ──► Lambda (Ingestion) ──► Massive.com API
                             │
                             ▼
                         DynamoDB
                             ▲
                             │
                      Lambda (Query API) ◄── API Gateway ◄── S3 Frontend (Public Website)
```

1. **Ingestion (Cron-driven)**: Runs daily to query stock OHLC data, calculate percentage changes, find the top mover, and write it to DynamoDB.
2. **Retrieval (On-demand)**: Serves a public JSON endpoint via API Gateway to fetch the last 7 days of winners from DynamoDB with optimal caching headers.
3. **Frontend Dashboard**: A responsive, clean HTML5/CSS3 dashboard that queries the API Gateway and visualizes the results using Chart.js.

---

## Prerequisites

You only need three things installed locally to deploy this stack:
1. [AWS CLI](https://aws.amazon.com/cli/) (configured with administrator credentials)
2. [Terraform](https://www.terraform.io/) (version 1.5 or newer)
3. [Python 3.12](https://www.python.org/downloads/) (or newer)

---

## Step-by-Step Deployment Guide

Deploying the entire stack takes less than 2 minutes using the helper `Makefile` commands.

### 1. Set Up Your Environment Variables
You will need a free API key from [Massive.com](https://massive.com/). Once you have it, set it as a local environment variable so Terraform can securely store it in AWS Secrets Manager:

```bash
export TF_VAR_massive_api_key="your_actual_massive_api_key_here"
```

### 2. Initialize and Deploy the AWS Resources
Run these commands from the root directory of the project:

```bash
# Initialize Terraform and download AWS providers
make init

# Preview the infrastructure resources to be built
make plan

# Deploy the entire stack to your AWS account
make apply
```
When `make apply` finishes, it will print your live S3 website URL (`s3_website_url`) and API Gateway URL (`api_gateway_url`).

### 3. Deploy the Frontend Dashboard
Now, publish your static website code to the S3 bucket:

```bash
make frontend-deploy
```
This automatically updates your HTML configuration with your live API URL and syncs all frontend files to your S3 hosting bucket. Your website is now live!

---

## Testing & Verifying

*   **Manually Trigger Ingestion**: Run `make trigger` to invoke the ingestion Lambda immediately (useful for testing without waiting for the daily cron).
*   **Test the API Response**: Query your live API endpoint directly via your browser or terminal to inspect the JSON:
    ```bash
    curl -s "https://your-api-gateway-url/movers"
    ```
*   **Wipe Everything**: When you are finished with the assessment, run `make destroy` to clean up and delete all AWS resources.

---

## Architectural Highlights

*   **Robust Error Handling**:
    *   **Rate Limits**: The Ingestion Lambda features active request pacing (13-second delays between ticker queries) to stay under Free Tier limits, and dynamically handles API `429 Too Many Requests` responses by reading `Retry-After` headers.
    *   **Transient Errors**: Uses exponential backoff to handle transient network errors.
    *   **Alerts**: If the ingestion fails or the API gateway returns 5XX responses, CloudWatch Alarms immediately publish alerts to an SNS topic, emailing the administrator.
*   **Decoupled IAM Security**:
    *   The Ingestion Lambda has write-only DynamoDB permissions and Secrets Manager read permissions.
    *   The API Lambda has read-only DynamoDB permissions and is blocked from accessing Secrets Manager or any external network.
*   **Optimized Performance**:
    *   The query API avoids full-table scans by performing a targeted `BatchGetItem` for a rolling date range, handling holidays and weekends gracefully.


