locals {
  name = "${var.project}-${var.environment}"
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Content mirror
#
# A copy of the content repository, refreshed by CI on push. Nothing here is
# authoritative: the bucket can be emptied and rebuilt from the repository.
# See docs/adr/0001-content-source-is-mirrored-to-s3.md.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "content" {
  bucket = "${local.name}-content-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "content" {
  bucket                  = aws_s3_bucket.content.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "content" {
  bucket = aws_s3_bucket.content.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "content" {
  bucket = aws_s3_bucket.content.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ---------------------------------------------------------------------------
# Publication state
#
# Authoritative answer to "has this already gone out?".
# See docs/adr/0002-publication-state-lives-in-dynamodb.md.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "state" {
  name         = "${local.name}-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------------------------------------------------------------------------
# Access token
#
# Terraform creates the container, never the value. Putting the token in a
# resource argument would write it to state in plain text. Populate it with:
#
#   aws secretsmanager put-secret-value \
#     --secret-id <name> \
#     --secret-string '{"access_token":"...","expires_at":"2026-09-24T00:00:00Z"}'
#
# See docs/setup-linkedin-app.md.
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "linkedin_token" {
  name        = "${local.name}/linkedin-token"
  description = "LinkedIn access token and its expiry. Populated out of band."

  # Short window so a mistaken destroy can be undone, without leaving the
  # name reserved for a month if it was intentional.
  recovery_window_in_days = 7
}
