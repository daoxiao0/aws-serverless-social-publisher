output "content_bucket" {
  description = "Bucket the CI mirror writes to."
  value       = aws_s3_bucket.content.id
}

output "state_table" {
  description = "DynamoDB table holding publication state."
  value       = aws_dynamodb_table.state.name
}

output "token_secret_id" {
  description = "Populate this with the access token before the first run."
  value       = aws_secretsmanager_secret.linkedin_token.name
}

output "function_name" {
  value = aws_lambda_function.publisher.function_name
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "mirror_role_arn" {
  description = "Role for the content repository's GitHub Actions workflow."
  value       = local.mirror_enabled ? aws_iam_role.mirror[0].arn : null
}
