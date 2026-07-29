# Lets the content repository push its posts into the mirror bucket from CI,
# authenticating with GitHub OIDC instead of a long-lived access key.
#
# Optional: set mirror_github_repository to enable. The OIDC provider is
# account-wide, so it is only created if it does not already exist.

locals {
  mirror_enabled = var.mirror_github_repository != ""
  create_oidc    = local.mirror_enabled && var.create_github_oidc_provider

  mirror_subjects = length(var.mirror_subject_patterns) > 0 ? var.mirror_subject_patterns : [
    "repo:${var.mirror_github_repository}:*"
  ]

  github_oidc_arn = local.mirror_enabled ? (
    local.create_oidc
    ? aws_iam_openid_connect_provider.github[0].arn
    : data.aws_iam_openid_connect_provider.github[0].arn
  ) : null
}

# AWS validates GitHub's certificate against its own trusted CA library and
# fills in a thumbprint by itself. Pinning one here would produce a permanent
# diff, and would break the day GitHub rotates its certificate.
resource "aws_iam_openid_connect_provider" "github" {
  count          = local.create_oidc ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  lifecycle {
    ignore_changes = [thumbprint_list]
  }
}

data "aws_iam_openid_connect_provider" "github" {
  count = local.mirror_enabled && !local.create_oidc ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "mirror" {
  count = local.mirror_enabled ? 1 : 0
  name  = "${local.name}-mirror"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        # Pinned to one repository. A bare wildcard here would let any
        # repository in any account assume this role.
        StringLike = {
          "token.actions.githubusercontent.com:sub" = local.mirror_subjects
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "mirror" {
  count = local.mirror_enabled ? 1 : 0
  name  = "${local.name}-mirror"
  role  = aws_iam_role.mirror[0].id

  # Both content prefixes: the CI workflow syncs LinkedIn posts and Threads
  # derivatives in the same job (mirror-aws-posts.yml, content repository).
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:DeleteObject"]
        Resource = [
          "${aws_s3_bucket.content.arn}/${var.content_prefix}*",
          "${aws_s3_bucket.content.arn}/${var.threads_content_prefix}*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.content.arn
      },
    ]
  })
}
