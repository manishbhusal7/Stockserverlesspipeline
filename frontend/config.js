/**
 * Runtime configuration — injected by CI/CD or set manually after deployment.
 *
 * After running `terraform apply`, replace PLACEHOLDER_API_URL with the value
 * of the `api_gateway_url` Terraform output, or run:
 *
 *   make frontend-deploy
 *
 * which patches this file automatically before syncing to S3.
 */
window.APP_CONFIG = {
  apiUrl: "PLACEHOLDER_API_URL",
};
