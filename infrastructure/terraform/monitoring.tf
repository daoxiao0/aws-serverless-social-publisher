resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "publish_failed" {
  alarm_name          = "${local.name}-publish-failed"
  alarm_description   = "The publisher function raised an error."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.publisher.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# Nothing being published is not an error, so nothing else notices it. A
# selection bug once made every run return "already published" and exit
# cleanly; without this alarm the pipeline would have gone quiet for good
# while reporting success.
#
# Three consecutive empty days, so a weekend on a weekday schedule does not
# fire it: Saturday and Sunday are two, and Monday publishing clears them.
# Running out of backlog also fires this, which is intended.
resource "aws_cloudwatch_metric_alarm" "nothing_published" {
  alarm_name          = "${local.name}-nothing-published"
  alarm_description   = "No post has gone out for three days. The pipeline may be failing silently."
  namespace           = "SocialPublisher"
  metric_name         = "PostsPublished"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"

  # No metric at all is the failure being watched for, not an absence of
  # information.
  treat_missing_data = "breaching"
  alarm_actions      = [aws_sns_topic.alerts.arn]
}

# The token cannot be refreshed programmatically, so this alarm is the only
# thing standing between an expiry and a week of silent 401s.
# See docs/adr/0004-access-token-lifecycle.md.
resource "aws_cloudwatch_metric_alarm" "token_expiring" {
  alarm_name          = "${local.name}-token-expiring"
  alarm_description   = "The LinkedIn access token expires soon. Re-authorize by hand."
  namespace           = "SocialPublisher"
  metric_name         = "DaysUntilTokenExpiry"
  statistic           = "Minimum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = var.token_expiry_warning_days
  comparison_operator = "LessThanOrEqualToThreshold"

  # Missing data means the function has not run, which is itself worth
  # knowing: the metric is only published during an invocation.
  treat_missing_data = "breaching"
  alarm_actions      = [aws_sns_topic.alerts.arn]
}

# ---------------------------------------------------------------------------
# Threads — the same two alarms, under Threads-specific metric names
# (threads_handler.py) so one platform going quiet or expiring cannot hide
# behind the other's healthy metrics.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "threads_publish_failed" {
  alarm_name          = "${local.name}-threads-publish-failed"
  alarm_description   = "The Threads publisher function raised an error."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.threads_publisher.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "threads_nothing_published" {
  alarm_name          = "${local.name}-threads-nothing-published"
  alarm_description   = "No Threads post has gone out for three days. The pipeline may be failing silently."
  namespace           = "SocialPublisher"
  metric_name         = "ThreadsPostsPublished"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# Set well above token_expiry_warning_days in practice: refresh_handler
# refreshes at REFRESH_MARGIN_DAYS (14) remaining, so this firing at all
# means the automatic refresh itself has been failing quietly — the alarm
# a human actually needs to act on is threads_token_refresh_failed below.
# Kept anyway, as the last line of defense if that one is ever misconfigured.
resource "aws_cloudwatch_metric_alarm" "threads_token_expiring" {
  alarm_name          = "${local.name}-threads-token-expiring"
  alarm_description   = "The Threads access token expires soon and has not been auto-refreshed. Investigate before it lapses."
  namespace           = "SocialPublisher"
  metric_name         = "ThreadsDaysUntilTokenExpiry"
  statistic           = "Minimum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = var.token_expiry_warning_days
  comparison_operator = "LessThanOrEqualToThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
