# Stock Serverless Pipeline — Interview Preparation & Architecture Guide

This guide provides an end-to-end walkthrough of the project's architecture, design decisions, implementation steps, and typical technical interview questions. Use it to prepare for a 1-hour deep-dive system design or implementation interview.

---

## 1. Project Goal & Overview

The objective is to build a fully automated, production-grade, and cost-effective stock analytics dashboard that:
1. Tracks a watchlist of high-volume tech stocks (`AAPL`, `MSFT`, `GOOGL`, `AMZN`, `TSLA`, `NVDA`).
2. Identifies the daily "Winning Stock" (the ticker with the highest absolute percentage price movement) after the US market closes.
3. Exposes a secure REST API endpoint (`GET /movers`) to retrieve the last 7 trading sessions.
4. Renders a premium, dark-mode Single Page Application (SPA) with historical charts, metrics, and network diagnostics.
5. Operates entirely within the **AWS Free Tier** and deploys automatically via a **CI/CD pipeline**.

### System Architecture Flow

```
1. INGESTION (Cron Trigger)
   EventBridge (10 PM UTC Daily) ──► Ingestion Lambda ──► Fetch prev close (Massive API)
                                                                 │
                                                       Calculate mover wins
                                                                 │
                                                                 ▼
2. DATABASE                                              Write to DynamoDB
                                                   (date PK, TTL 30-day auto-expiry)
                                                                 ▲
                                                                 │
3. API LAYER (On-Demand)                                     BatchGetItem
   GET /movers ──► API Gateway (HTTP v2) ──► API Lambda ─────────┘
                                                 │
                                           JSON + ETag Headers
                                                 │
                                                 ▼
4. FRONTEND                                S3 Static Web Hosting (SPA, Chart.js)
```

---

## 2. Component Design & Implementation

### A. Ingestion Layer (Lambda + Secrets Manager + EventBridge)
* **Trigger**: Amazon EventBridge Scheduler rule configured with a cron expression: `cron(0 22 * * ? *)` (10 PM UTC / 6 PM EST, after US markets close).
* **Secrets Management**: The Massive API key is stored securely in **AWS Secrets Manager**. At runtime, the Lambda requests the secret using the standard AWS SDK (`boto3`) to avoid exposing credentials in the codebase or environment variables.
* **API Ingest & Math**: 
  * Queries the Massive aggregate preview endpoint: `https://api.massive.com/v2/aggs/ticker/{ticker}/prev`
  * Extracts Open Price (`o`) and Close Price (`c`).
  * Calculates daily percentage change: 
    $$\text{Percentage Change} = \frac{\text{Close} - \text{Open}}{\text{Open}} \times 100$$
  * Finds the absolute maximum mover (e.g. $+5.2\%$ beats $-2.1\%$, but $-6.5\%$ beats $+5.2\%$).
  * Writes the winning record to DynamoDB.

### B. Storage Layer (DynamoDB)
* **Schema Design**:
  * **Table Name**: `stock-pipeline-prod-top-movers`
  * **Partition Key (PK)**: `date` (String, format `YYYY-MM-DD`). Since there is exactly one winner per trading day, using `date` as the partition key ensures highly optimized, direct O(1) point lookups.
* **Cost Optimization**:
  * Mode: **On-Demand (PAY_PER_REQUEST)**. Costs are \$0.00 when the system is idle.
  * **Time-to-Live (TTL)**: Enabled on the `expires_at` attribute. DynamoDB automatically deletes records older than 30 days, keeping storage footprint within the AWS Free Tier.

### C. API Layer (API Gateway v2 + Lambda)
* **Endpoint**: `GET /movers`
* **API Gateway Type**: **HTTP API (v2)**. Chosen over REST API (v1) because it has lower latency, lower costs, and built-in CORS configuration natively supported by Terraform.
* **Backend Logic**:
  * Generates a lookback calendar of the last 21 calendar days (to guarantee coverage of weekends and market holidays).
  * Performs a single `BatchGetItem` request to DynamoDB for these 21 date partition keys.
  * Sorts the matched records by date descending, limits the response to the latest 7 trading days, and formats the output into clean JSON.
  * Generates an **ETag header** based on a SHA-256 hash of the JSON content to support client-side caching.

### D. Frontend Presentation (S3 + Vanilla JS)
* **Hosting**: Configured as a public static website in an S3 Bucket.
* **UI/UX Aesthetics**: Premium financial terminal style featuring a glassmorphism sidebar, CSS grid cards, responsive flex layouts, and a Chart.js historical visualization.
* **Client-Side ETag Caching**:
  * When fetching `/movers`, the frontend checks its local `localStorage` cache. If cached data exists, it sends an `If-None-Match: <etag>` request header.
  * If the data hasn't changed, the backend API immediately returns a `304 Not Modified` response with an empty body, saving significant bandwidth and API Gateway execution costs.

---

## 3. Core Infrastructure as Code (Terraform)

The architecture is provisioned modularly across dedicated Terraform resource files:
* `main.tf`: Defines the AWS provider version limits and local environment naming prefixes.
* `variables.tf` & `outputs.tf`: Handles inputs (watchlist tickers, environment) and outputs (S3 URL, API endpoint URL).
* `iam.tf`: Restricts each Lambda role to the absolute minimum permissions (**Least Privilege Principle**):
  * **Ingestion Lambda** has write-only access to the specific DynamoDB table and read access to the Secrets Manager secret.
  * **API Lambda** has read-only access (`BatchGetItem`) to the DynamoDB table.
* `secrets.tf`: Creates the AWS Secrets Manager container for the Massive API key.
* `dynamodb.tf`: Configures the DynamoDB table with TTL enabled.
* `lambda_ingestion.tf` & `lambda_api.tf`: Deploys Lambda resources, sets runtimes to Python 3.12, defines environment variables, and links EventBridge rules and API Gateway integrations.
* `s3.tf`: Standardizes S3 website configuration, public access blocks, and bucket policies.
* `cloudwatch.tf`: Integrates alarms.
  * Sets up CloudWatch Metric Alarms on Lambda `Errors` and API Gateway `5XXError`.
  * Triggers an **SNS Topic** to dispatch alert emails to the administrator on failure.

---

## 4. Key Design Decisions ("Why" We Built It This Way)

| Design Choice | Rationale | Alternatives Considered |
| :--- | :--- | :--- |
| **Serverless Architecture** | Extremely low cost (completely free under low usage thresholds), zero server maintenance, and automated scaling. | Running on a continuous VM (EC2) or container (ECS), which incurs ongoing hourly costs. |
| **DynamoDB over SQL** | Simple key-value access patterns make NoSQL much faster and cheaper. A single table with `date` as the partition key allows highly optimized writes and reads. | RDS PostgreSQL, which requires managing VPCs, connection pools, and database instances. |
| **`BatchGetItem` vs `Scan`** | Scanning a database retrieves all historical records, which gets slower and more expensive as the table grows. `BatchGetItem` queries specific partition keys in a single round-trip with $O(1)$ efficiency. | DynamoDB Scan operations (poor practice for structured analytics). |
| **urllib (Stdlib) over requests** | Using Python's built-in standard library avoids packaging large third-party ZIP layers, reducing cold start latencies and deployment complexity. | Third-party libraries like `requests` or `urllib3`. |

---

## 5. Typical Interview Questions & Answers

### Q1: How does your pipeline handle weekends and market holidays?
> **Answer:** 
> The Ingestion Lambda runs daily. Massive's `/prev` endpoint returns data for the *most recent completed trading day*. On Saturday and Sunday, it returns Friday's trading bar. 
> Because DynamoDB writes are **idempotent** on the partition key (`date`), running the Lambda on Saturday and Sunday simply overwrites the Friday record harmlessly.
> To handle the API response, our Lambda generates a lookback calendar of 21 calendar days and queries the database. Weekend dates will return empty blocks (no records exist), and the API automatically filters out those empty entries, returning exactly the 7 most recent trading days.

### Q2: What happens if the Massive API key is missing or invalid?
> **Answer:** 
> The code retrieves the API key directly from AWS Secrets Manager at startup. If the key is missing, invalid, or expired, the `_get_api_key()` function throws an error, and the Lambda fails immediately. 
> This failure triggers the `stock-pipeline-prod-ingestion-errors` CloudWatch Alarm, which sends an alert to our Amazon SNS topic, notifying the developer via email. We intentionally removed mock fallbacks to guarantee strict API data integrity.

### Q3: What is the purpose of the ETag / conditional caching mechanism?
> **Answer:** 
> It optimizes bandwidth and processing overhead. When the client makes a request, the API returns a unique ETag hash of the response data. On subsequent requests, the browser sends that ETag in the `If-None-Match` header. 
> If the database has not changed, the Lambda returns an HTTP `304 Not Modified` response with zero body content. This avoids serializing and transferring data, reducing API Gateway egress fees.

### Q4: How would you scale this pipeline to handle 10,000 tickers instead of 6?
> **Answer:** 
> If the watchlist scales to 10,000 tickers, sequential HTTP requests in a single Lambda would exceed the maximum 15-minute execution timeout. To scale:
> 1. **Decouple the process**: Have a master Lambda queue ticker names into an **Amazon SQS Queue**.
> 2. **Parallel Workers**: Have worker Lambdas consume from the queue in parallel batches, fetching data and writing to DynamoDB using `BatchWriteItem`.
> 3. **API Optimization**: Querying DynamoDB for 10,000 tickers should be done using a DynamoDB Secondary Index (GSI) or caching the aggregated API results in **Amazon ElastiCache (Redis)** or **API Gateway Cache** to protect DynamoDB from read limits.

### Q5: Why is Terraform used for this project?
> **Answer:** 
> Terraform provides **Infrastructure as Code (IaC)**. It ensures that our environment (Lambda, IAM policies, DynamoDB, API Gateway, S3) is fully reproducible, version-controlled, and easily deployable across different stages (e.g. dev, staging, prod) with zero manual console configurations.
