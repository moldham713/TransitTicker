# Data access layer for user accounts and saved station preferences,
# backed by DynamoDB. app.py's /auth/* routes use get_or_create_user and
# get_user_by_id; /preferences uses save_preferences; the /device/* routes
# use set_device_token, clear_device_token, and get_user_by_device_token.
#
# A user's device_token is deliberately not the same value as their
# user_id: the device_token is what an embedded device presents to the API
# to fetch its owner's saved departures, with no login/session involved.
# If that were the same value used to identify the logged-in account, a
# guessable or leaked user_id would expose someone's saved home/work
# stations - their commute pattern - to anyone who could guess it. Keeping
# them separate means the device only ever knows an opaque token, never an
# identity.

import os
import secrets
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# Set only for local development (docker-compose) to point at DynamoDB
# Local instead of the real AWS service. Left unset in production, where
# boto3 picks up real credentials from the backend's ECS task role
# automatically (see infra/ecs.tf's aws_iam_role.backend_task).
DYNAMODB_ENDPOINT_URL = os.environ.get('DYNAMODB_ENDPOINT_URL')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME', 'transitticker-users')

_resource_kwargs = {'region_name': AWS_REGION}
if DYNAMODB_ENDPOINT_URL:
    _resource_kwargs['endpoint_url'] = DYNAMODB_ENDPOINT_URL
    # DynamoDB Local doesn't validate credentials at all, but boto3 still
    # needs some access key present to construct a request rather than
    # trying (and failing) to find real AWS credentials that don't exist
    # in a local dev container.
    _resource_kwargs['aws_access_key_id'] = 'local'
    _resource_kwargs['aws_secret_access_key'] = 'local'

dynamodb = boto3.resource('dynamodb', **_resource_kwargs)
table = dynamodb.Table(TABLE_NAME)


def ensure_table_exists() -> None:
    """
    Create the users table against DynamoDB Local if it doesn't already
    exist, matching the same key schema and GSI infra/dynamodb.tf defines
    for the real table. Only ever does anything when DYNAMODB_ENDPOINT_URL
    is set (local dev) - production always targets the table Terraform
    already created, and application code never attempts to create or
    modify infrastructure there.
    """
    if not DYNAMODB_ENDPOINT_URL:
        return
    try:
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{'AttributeName': 'user_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'user_id', 'AttributeType': 'S'},
                {'AttributeName': 'device_token', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'device_token-index',
                'KeySchema': [{'AttributeName': 'device_token', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'},
            }],
            BillingMode='PAY_PER_REQUEST',
        )
        table.wait_until_exists()
        print(f"Created local DynamoDB table '{TABLE_NAME}'.")
    except ClientError as exc:
        if exc.response['Error']['Code'] != 'ResourceInUseException':
            raise
        # Table already exists from a previous run - nothing to do.


def _normalize_user(item: Optional[dict]) -> Optional[dict]:
    """
    Convert a user record read from DynamoDB into plain Python types.

    boto3 returns every DynamoDB number as decimal.Decimal, and Flask's JSON
    encoder serializes Decimal as a string. Left as-is, a saved direction of
    1 reaches the browser as "1", and the browser then sends that string
    back on the next save, where /preferences validation rejects it. Every
    read path in this module returns records through here so callers only
    ever see an int direction.
    """
    if not item:
        return item
    item['preferences'] = [
        {**pref, 'direction': int(pref['direction'])}
        for pref in item.get('preferences', [])
    ]
    return item


def generate_device_token() -> str:
    """A long, random, opaque token unrelated to a user's login identity -
    see this module's docstring for why that separation matters. Exposed
    publicly (not a device_token setter itself) so callers like the
    pairing-claim flow can generate a candidate token, attempt the claim
    that actually authorizes it, and only persist it via set_device_token
    on success - never the other way around."""
    return secrets.token_urlsafe(24)


def get_or_create_user(oauth_provider: str, oauth_subject: str) -> dict:
    """
    Look up the user record for a given OAuth identity, creating one with
    empty preferences on first login. No device_token is assigned here -
    an account starts with no device paired at all, and only ever gets one
    through a successful pairing claim (see pairing.py and app.py's
    /device/pair/claim route). That keeps "logged in" and "has a paired
    device" fully independent: signing in never silently issues a
    credential nobody asked for.

    Args:
        oauth_provider (str): e.g. "google".
        oauth_subject (str): the provider's unique, stable identifier for
            this account (Google's `sub` claim).

    Returns:
        dict: the user record - {"user_id", "oauth_provider",
        "oauth_subject", "preferences"}, plus "device_token" once one has
        been paired.
    """
    user_id = f"{oauth_provider}#{oauth_subject}"
    existing = table.get_item(Key={'user_id': user_id}).get('Item')
    if existing:
        return _normalize_user(existing)

    new_user = {
        'user_id': user_id,
        'oauth_provider': oauth_provider,
        'oauth_subject': oauth_subject,
        'preferences': [],
    }
    try:
        # Only write if this user_id doesn't already exist, so two
        # concurrent first-logins for the same account can't race and
        # silently discard one request's view of the record.
        table.put_item(Item=new_user, ConditionExpression='attribute_not_exists(user_id)')
        return new_user
    except ClientError as exc:
        if exc.response['Error']['Code'] == 'ConditionalCheckFailedException':
            # Someone else's concurrent request created it a moment ago -
            # read back what they actually wrote.
            return _normalize_user(table.get_item(Key={'user_id': user_id})['Item'])
        raise


def set_device_token(user_id: str, device_token: str) -> None:
    """Store a specific, already-issued device token on a user's record,
    replacing whatever token (if any) they previously had. Takes the token
    as a parameter rather than generating one itself, so a caller can
    generate a candidate token, confirm it via a successful pairing claim,
    and only persist it here once that's confirmed."""
    table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='SET device_token = :t',
        ExpressionAttributeValues={':t': device_token},
    )


def clear_device_token(user_id: str) -> None:
    """Remove a user's device token entirely - self-service "unlink my
    device": no device can fetch this account's departures until a new one
    is paired, while saved preferences are untouched, since those belong
    to the account, not to whichever physical device happens to be reading
    them. Removing the attribute outright (rather than setting it to an
    empty string) is also what keeps this user out of the device_token-
    index GSI - DynamoDB only projects items that have a non-null value
    for every attribute in a GSI's key schema."""
    table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='REMOVE device_token',
    )


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Look up a user by their internal user_id - the same value used as
    the Flask session identity and the table's primary key."""
    return _normalize_user(table.get_item(Key={'user_id': user_id}).get('Item'))


def get_user_by_device_token(device_token: str) -> Optional[dict]:
    """
    Look up a user by their device token - the lookup path an embedded
    device actually uses, via the device_token-index GSI rather than the
    table's primary key.

    Returns:
        dict or None: the user record, or None if no user has this token.
    """
    response = table.query(
        IndexName='device_token-index',
        KeyConditionExpression=Key('device_token').eq(device_token),
    )
    items = response.get('Items', [])
    return _normalize_user(items[0]) if items else None


def save_preferences(user_id: str, preferences: list) -> None:
    """
    Overwrite a user's saved station/direction preferences.

    Args:
        user_id (str): as returned in a user record's "user_id" field.
        preferences (list): up to 3 entries, each
            {"route": str, "stop": str, "direction": int}.
    """
    table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='SET preferences = :p',
        ExpressionAttributeValues={':p': preferences},
    )
