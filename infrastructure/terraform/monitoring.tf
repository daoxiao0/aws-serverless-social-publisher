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
