# Lets the content repository push its posts into the mirror bucket from CI,
# authenticating with GitHub OIDC instead of a long-lived access key.
#
# Optional: set mirror_github_repository to enable. The OIDC provider is
# account-wide, so it is only created if it does not already exist.

locals {
  mirror_enabled = var.mirror_github_repository != ""
}

data "aws_iam_openid_connect_provider" "github" {
  count = local.mirror_enabled ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "mirror" {
  count = local.mirror_enabled ? 1 : 0
  name  = "${local.name}-mirror"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github[0].arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        # Pinned to one repository. A wildcard here would let any repository
        # in any account assume this role.
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.mirror_github_repository}:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "mirror" {
  count = local.mirror_enabled ? 1 : 0
  name  = "${local.name}-mirror"
  role  = aws_iam_role.mirror[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.content.arn}/${var.content_prefix}*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.content.arn
      },
    ]
  })
}
