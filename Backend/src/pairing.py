# Short-lived device pairing codes, backed by their own DynamoDB table
# separate from the one holding user accounts (see users.py) - these are
# high-churn, ephemeral records with a fundamentally different access
# pattern and lifecycle than a permanent account.
#
# How a device gets a working token: a device with no stored token calls
# POST /device/pair/start, gets back a short pairing code, and displays it
# on its own screen. It then polls GET /device/pair/status/<code> while a
# human reads that code and enters it into the web UI, which calls
# POST /device/pair/claim on their authenticated session. Only once that
# claim succeeds does a permanent device_token get created and handed back
# to the device on its next poll. The pairing code itself is never a
# usable credential for anything beyond that one claim - it's rejected the
# moment it's claimed or expires.

import os
import secrets
import time

import boto3
from botocore.exceptions import ClientError

# Set only for local development (docker-compose) to point at DynamoDB
# Local instead of the real AWS service - see users.py for the same
# pattern and why it's structured this way.
DYNAMODB_ENDPOINT_URL = os.environ.get('DYNAMODB_ENDPOINT_URL')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
TABLE_NAME = os.environ.get('PAIRING_CODES_TABLE_NAME', 'transitticker-pairing-codes')

# 6 characters, drawn from an alphabet that excludes visually ambiguous
# characters (0/O, 1/I, L) - a human reads this off a small LED matrix and
# types it into a form, so confusable characters cost real usability here.
CODE_LENGTH = 6
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_TTL_SECONDS = 600  # 10 minutes

_resource_kwargs = {'region_name': AWS_REGION}
if DYNAMODB_ENDPOINT_URL:
    _resource_kwargs['endpoint_url'] = DYNAMODB_ENDPOINT_URL
    _resource_kwargs['aws_access_key_id'] = 'local'
    _resource_kwargs['aws_secret_access_key'] = 'local'

dynamodb = boto3.resource('dynamodb', **_resource_kwargs)
table = dynamodb.Table(TABLE_NAME)


def ensure_table_exists() -> None:
    """
    Create the pairing codes table against DynamoDB Local if it doesn't
    already exist, matching the key schema infra/dynamodb.tf defines for
    the real table. Only ever does anything when DYNAMODB_ENDPOINT_URL is
    set (local dev) - production always targets the table Terraform
    already created.
    """
    if not DYNAMODB_ENDPOINT_URL:
        return
    try:
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{'AttributeName': 'pairing_code', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'pairing_code', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        table.wait_until_exists()
        print(f"Created local DynamoDB table '{TABLE_NAME}'.")
    except ClientError as exc:
        if exc.response['Error']['Code'] != 'ResourceInUseException':
            raise
        # Table already exists from a previous run - nothing to do.


def _new_pairing_code() -> str:
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def start_pairing() -> dict:
    """
    Generate a new pairing code for a device to display. Retries on the
    rare chance of colliding with another code that's still pending, since
    two devices simultaneously holding the same code would let either
    one's claim satisfy both.

    Returns:
        dict: {"pairing_code": str, "expires_in": int}
    """
    for _ in range(5):
        code = _new_pairing_code()
        expires_at = int(time.time()) + CODE_TTL_SECONDS
        try:
            table.put_item(
                Item={'pairing_code': code, 'status': 'pending', 'expires_at': expires_at},
                ConditionExpression='attribute_not_exists(pairing_code)',
            )
            return {"pairing_code": code, "expires_in": CODE_TTL_SECONDS}
        except ClientError as exc:
            if exc.response['Error']['Code'] != 'ConditionalCheckFailedException':
                raise
            # Collided with an existing pending code - loop and try a new one.
    raise RuntimeError("could not generate a unique pairing code after 5 attempts")


def get_pairing_status(pairing_code: str) -> dict:
    """
    What a device polls to learn whether its pairing code has been claimed.

    Returns:
        dict: one of
          {"status": "pending"}
          {"status": "claimed", "device_token": str}
          {"status": "not_found"}
        "not_found" covers both an unrecognized code and an expired one -
        a device can't tell "typo'd" from "timed out" apart, and doesn't
        need to; either way its own logic should just call
        POST /device/pair/start again for a fresh code.
    """
    item = table.get_item(Key={'pairing_code': pairing_code}).get('Item')
    if not item or item['expires_at'] < int(time.time()):
        # DynamoDB's TTL cleanup runs as an eventual, best-effort background
        # process - AWS documents actual deletion as lagging the expiry
        # timestamp by up to 48 hours, not happening instantly. An
        # expired-but-not-yet-deleted item is still explicitly rejected
        # here rather than relying on TTL alone to enforce the deadline.
        return {"status": "not_found"}
    if item['status'] == 'claimed':
        return {"status": "claimed", "device_token": item['device_token']}
    return {"status": "pending"}


def claim_pairing_code(pairing_code: str, device_token: str) -> bool:
    """
    Mark a pending, unexpired pairing code as claimed, recording the
    device_token a waiting device should receive next time it polls
    get_pairing_status.

    Returns:
        bool: True if the claim succeeded, False if the code doesn't
        exist, has expired, or was already claimed - the caller
        (app.py's /device/pair/claim route) turns False into a 4xx
        response and must not treat a failed claim as having done
        anything to the account it was attempted for.
    """
    try:
        table.update_item(
            Key={'pairing_code': pairing_code},
            # "status" is a DynamoDB reserved word, hence the #s alias.
            UpdateExpression='SET #s = :claimed, device_token = :token',
            ConditionExpression='attribute_exists(pairing_code) AND #s = :pending AND expires_at > :now',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':claimed': 'claimed',
                ':pending': 'pending',
                ':token': device_token,
                ':now': int(time.time()),
            },
        )
        return True
    except ClientError as exc:
        if exc.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return False
        raise
