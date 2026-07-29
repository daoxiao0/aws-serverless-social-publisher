# The deployment package carries no third-party code: boto3 ships with the
# runtime and the LinkedIn client uses urllib, so zipping the source is enough.
data "archive_file" "function" {
  type        = "zip"
  source_dir  = "${path.module}/../../src"
  output_path = "${path.module}/.build/function.zip"
  excludes    = ["**/__pycache__/**"]
}

resource "aws_lambda_function" "publisher" {
  function_name    = local.name
  role             = aws_iam_role.lambda.arn
  handler          = "publisher.handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.function.output_path
  source_code_hash = data.archive_file.function.output_base64sha256

  # Generous for one HTTP call, but LinkedIn occasionally responds slowly and
  # a timeout mid-publish leaves a post claimed but not sent.
  timeout     = 30
  memory_size = 256

  environment {
    variables = {
      CONTENT_BUCKET  = aws_s3_bucket.content.id
      CONTENT_PREFIX  = var.content_prefix
      STATE_TABLE     = aws_dynamodb_table.state.name
      TOKEN_SECRET_ID = aws_secretsmanager_secret.linkedin_token.name
      ALERT_TOPIC_ARN = aws_sns_topic.alerts.arn
      POST_VISIBILITY = var.post_visibility
      DRY_RUN         = var.dry_run ? "true" : "false"
    }
  }

  depends_on = [aws_cloudwatch_log_group.publisher]
}

# Created explicitly so the retention setting applies from the first
# invocation, instead of Lambda creating it with retention set to "never".
resource "aws_cloudwatch_log_group" "publisher" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 30
}

resource "aws_iam_role" "lambda" {
  name = "${local.name}-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${local.name}-lambda"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.publisher.arn}:*"
      },
      {
        Sid      = "ReadContent"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.content.arn}/${var.content_prefix}*"
      },
      {
        Sid      = "ListContent"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.content.arn
        Condition = {
          StringLike = { "s3:prefix" = ["${var.content_prefix}*"] }
        }
      },
      {
        Sid      = "PublicationState"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.state.arn
      },
      {
        Sid      = "ReadToken"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.linkedin_token.arn
      },
      {
        Sid      = "Alerts"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.alerts.arn
      },
      {
        # PutMetricData takes no resource, so the namespace condition is the
        # only thing keeping this from being "write any metric anywhere".
        Sid       = "TokenLifetimeMetric"
        Effect    = "Allow"
        Action    = "cloudwatch:PutMetricData"
        Resource  = "*"
        Condition = { StringEquals = { "cloudwatch:namespace" = "SocialPublisher" } }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Threads publisher
#
# A second, independent function rather than a branch inside "publisher" —
# see ADR-0007. Own role, own least-privilege policy, own schedule
# (scheduler.tf): a bug in one platform's IAM policy or cron expression
# cannot touch the other's.
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "threads_publisher" {
  function_name    = "${local.name}-threads"
  role             = aws_iam_role.threads_lambda.arn
  handler          = "publisher.threads_handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.function.output_path
  source_code_hash = data.archive_file.function.output_base64sha256

  timeout     = 30
  memory_size = 256

  environment {
    variables = {
      CONTENT_BUCKET  = aws_s3_bucket.content.id
      CONTENT_PREFIX  = var.threads_content_prefix
      STATE_TABLE     = aws_dynamodb_table.state.name
      TOKEN_SECRET_ID = aws_secretsmanager_secret.threads_token.name
      ALERT_TOPIC_ARN = aws_sns_topic.alerts.arn
      DRY_RUN         = var.threads_dry_run ? "true" : "false"
    }
  }

  depends_on = [aws_cloudwatch_log_group.threads_publisher]
}

resource "aws_cloudwatch_log_group" "threads_publisher" {
  name              = "/aws/lambda/${local.name}-threads"
  retention_in_days = 30
}

resource "aws_iam_role" "threads_lambda" {
  name = "${local.name}-threads-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "threads_lambda" {
  name = "${local.name}-threads-lambda"
  role = aws_iam_role.threads_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.threads_publisher.arn}:*"
      },
      {
        Sid      = "ReadContent"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.content.arn}/${var.threads_content_prefix}*"
      },
      {
        Sid      = "ListContent"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.content.arn
        Condition = {
          StringLike = { "s3:prefix" = ["${var.threads_content_prefix}*"] }
        }
      },
      {
        Sid      = "PublicationState"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.state.arn
      },
      {
        # Threads tokens are refreshable, unlike LinkedIn's (ADR-0007), so
        # this role writes the secret as well as reading it.
        Sid      = "ReadWriteToken"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
        Resource = aws_secretsmanager_secret.threads_token.arn
      },
      {
        Sid      = "Alerts"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.alerts.arn
      },
      {
        Sid       = "PublishedAndTokenMetrics"
        Effect    = "Allow"
        Action    = "cloudwatch:PutMetricData"
        Resource  = "*"
        Condition = { StringEquals = { "cloudwatch:namespace" = "SocialPublisher" } }
      },
    ]
  })
}
