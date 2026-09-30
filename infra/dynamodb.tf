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
