# Holds each user's identity (from Google OAuth) and their saved station
# preferences. DynamoDB rather than a relational database: every access
# pattern here is a simple key lookup (by user_id, or by device_token via
# the GSI below), and it needs no VPC networking to reach - see the NAT
# Gateway cost note in vpc.tf for why avoiding that matters for this stack.
# PAY_PER_REQUEST billing scales cost with actual usage instead of a
# provisioned baseline, which stays close to zero at this project's scale.
resource "aws_dynamodb_table" "users" {
  name         = "${var.project_name}-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  # An embedded device authenticates with an opaque device_token, not the
  # account's OAuth identity (see Backend/src/users.py for why those are
  # kept separate), so preferences need to be findable by that token too -
  # this GSI is that lookup path.
  attribute {
    name = "device_token"
    type = "S"
  }

  global_secondary_index {
    name            = "device_token-index"
    hash_key        = "device_token"
    projection_type = "ALL"
  }

  # Cheap insurance against an accidental delete/overwrite of the one table
  # in this stack holding real user data.
  point_in_time_recovery {
    enabled = true
  }
}

# Short-lived pairing codes a device generates during setup and a logged-in
# human claims from the web UI - see Backend/src/pairing.py for the full
# flow. A separate table from `users` since these records are high-churn
# and ephemeral (minutes, not indefinite) rather than permanent accounts.
resource "aws_dynamodb_table" "pairing_codes" {
  name         = "${var.project_name}-pairing-codes"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pairing_code"

  attribute {
    name = "pairing_code"
    type = "S"
  }

  # DynamoDB's own TTL cleanup is eventual/best-effort (AWS documents
  # deletion as lagging up to 48 hours behind the expiry timestamp), so
  # this exists for storage hygiene, not as the enforcement mechanism -
  # pairing.py's get_pairing_status/claim_pairing_code check expiry
  # explicitly on every read rather than trusting an expired item to
  # already be gone.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
