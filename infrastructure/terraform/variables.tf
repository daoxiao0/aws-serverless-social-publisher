variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "social-publisher"
}

variable "environment" {
  description = "Environment name, used in resource names and tags."
  type        = string
  default     = "prod"
}

variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-northeast-1"
}

variable "content_prefix" {
  description = "Key prefix inside the content bucket where LinkedIn posts are mirrored."
  type        = string
  default     = "posts/"
}

variable "threads_content_prefix" {
  description = "Key prefix inside the content bucket where Threads derivatives (/aws-shorts output) are mirrored."
  type        = string
  default     = "shorts/"
}

variable "schedule_expression" {
  description = "When to publish. Weekdays only by default."
  type        = string
  default     = "cron(0 8 ? * MON-FRI *)"
}

variable "schedule_timezone" {
  description = <<-EOT
    Timezone for schedule_expression. EventBridge Scheduler interprets cron in
    UTC unless this is set, which would silently shift an 08:00 schedule to
    17:00 local time in JST.
  EOT
  type        = string
  default     = "Asia/Tokyo"
}

variable "post_visibility" {
  description = "LinkedIn post visibility: PUBLIC or CONNECTIONS."
  type        = string
  default     = "PUBLIC"

  validation {
    condition     = contains(["PUBLIC", "CONNECTIONS"], var.post_visibility)
    error_message = "post_visibility must be PUBLIC or CONNECTIONS."
  }
}

variable "dry_run" {
  description = "Render and log the post without sending it to LinkedIn."
  type        = bool
  default     = false
}

variable "threads_schedule_expression" {
  description = <<-EOT
    When to publish to Threads. Offset five minutes from schedule_expression
    (LinkedIn) by default so the two platforms' CloudWatch log streams and
    alarm evaluations do not land in the same minute — they are independent
    Lambdas with no shared state to race over, this is purely for readability
    when reading logs later.
  EOT
  type        = string
  default     = "cron(5 8 ? * MON-FRI *)"
}

variable "threads_dry_run" {
  description = <<-EOT
    Render and log the Threads post without sending it. Defaults to true,
    independently of dry_run (LinkedIn) — a new platform's first deploy
    should not inherit an already-proven platform's "go live" setting.
  EOT
  type        = bool
  default     = true
}

variable "alert_email" {
  description = <<-EOT
    Address for failure and token-expiry alerts. Leave empty to create the SNS
    topic without a subscription and add one by hand later. AWS sends a
    confirmation mail that must be accepted before alerts arrive.
  EOT
  type        = string
  default     = ""
}

variable "token_expiry_warning_days" {
  description = "Alarm when fewer than this many days of token life remain."
  type        = number
  default     = 7
}

variable "mirror_github_repository" {
  description = <<-EOT
    "owner/repo" of the content repository allowed to write the S3 mirror via
    GitHub OIDC. Leave empty to skip creating the mirror role.
  EOT
  type        = string
  default     = ""
}

variable "mirror_subject_patterns" {
  description = <<-EOT
    Patterns the OIDC `sub` claim must match to assume the mirror role. Empty
    derives the legacy name-based pattern from mirror_github_repository.

    GitHub now issues subjects carrying immutable numeric IDs, such as
    "repo:owner@123/repo@456:ref:refs/heads/main". A trust policy written
    against the name-only form fails with "Not authorized to perform
    sts:AssumeRoleWithWebIdentity" against such a repository. Matching on the
    IDs is also the stronger choice: names can be released and re-registered
    by somebody else, IDs cannot.
  EOT
  type        = list(string)
  default     = []
}

variable "create_github_oidc_provider" {
  description = <<-EOT
    Create the GitHub OIDC provider. It is account-wide and only one may
    exist, so set this to false if another stack already created it, and the
    existing one will be looked up instead.
  EOT
  type        = bool
  default     = false
}
