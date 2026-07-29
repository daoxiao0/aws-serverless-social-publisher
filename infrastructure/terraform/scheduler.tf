resource "aws_scheduler_schedule" "publish" {
  name       = "${local.name}-publish"
  group_name = "default"

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.publisher.arn
    role_arn = aws_iam_role.scheduler.arn

    # A failed invocation is not retried into oblivion: publishing is
    # idempotent by state, and a same-day retry storm would only produce more
    # 401s if the cause is an expired token.
    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name = "${local.name}-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "${local.name}-scheduler"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.publisher.arn
    }]
  })
}

# ---------------------------------------------------------------------------
# Threads schedule — own rule, own role, so a change to one platform's
# schedule or invoke permission cannot affect the other's.
# ---------------------------------------------------------------------------

resource "aws_scheduler_schedule" "threads_publish" {
  name       = "${local.name}-threads-publish"
  group_name = "default"

  schedule_expression          = var.threads_schedule_expression
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.threads_publisher.arn
    role_arn = aws_iam_role.threads_scheduler.arn

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}

resource "aws_iam_role" "threads_scheduler" {
  name = "${local.name}-threads-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "threads_scheduler" {
  name = "${local.name}-threads-scheduler"
  role = aws_iam_role.threads_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.threads_publisher.arn
    }]
  })
}
