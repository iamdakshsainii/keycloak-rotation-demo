import boto3
import json
import os
import secrets  # used to generate a random secret in Lambda
import urllib.request
import urllib.parse

KEYCLOAK_URL   = os.environ["KEYCLOAK_URL"]
KEYCLOAK_REALM = os.environ["KEYCLOAK_REALM"]
CLIENT_ID      = os.environ["KEYCLOAK_CLIENT_ID"]


def lambda_handler(event, context):
    """
    Entry point. AWS Secrets Manager calls this function 4 times per rotation,
    once for each step: createSecret, setSecret, testSecret, finishSecret.
    """
    arn   = event["SecretId"]
    token = event["ClientRequestToken"]
    step  = event["Step"]

    client = boto3.client("secretsmanager")

    # Make sure this rotation token is valid and belongs to this secret
    metadata = client.describe_secret(SecretId=arn)
    if token not in metadata.get("VersionIdsToStages", {}):
        raise ValueError(f"Token {token} not found in secret {arn}")

    # If this token is already AWSCURRENT, rotation already finished — skip
    if "AWSCURRENT" in metadata["VersionIdsToStages"].get(token, []):
        return

    # Route to the correct step function
    if step == "createSecret":
        create_secret(client, arn, token)
    elif step == "setSecret":
        set_secret(client, arn, token)
    elif step == "testSecret":
        test_secret(client, arn, token)
    elif step == "finishSecret":
        finish_secret(client, arn, token)
    else:
        raise ValueError(f"Unknown step: {step}")


# ── Helper functions ──────────────────────────────────────────────────────────

# Logs into Keycloak as admin and returns a temporary access token
def get_admin_token(admin_user, admin_pass):
    """
    Log into Keycloak as admin and return a short-lived access token.
    All Admin API calls need this token in their Authorization header.
    """
    url  = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    data = urllib.parse.urlencode({
        "client_id":  "admin-cli",
        "username":   admin_user,
        "password":   admin_pass,
        "grant_type": "password"
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]

# Looks up demo-app by name and returns its internal UUID that Keycloak uses

def get_client_uuid(admin_token):
    """
    Keycloak identifies clients by UUID internally, not by name.
    Look up demo-app by name and return its internal UUID.
    """
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients?clientId={CLIENT_ID}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {admin_token}"})
    with urllib.request.urlopen(req) as resp:
        clients = json.loads(resp.read())
    if not clients:
        raise ValueError(f"Client {CLIENT_ID} not found in realm {KEYCLOAK_REALM}")
    return clients[0]["id"]


# Pushes the Lambda-generated secret value to Keycloak via PUT API
def set_client_secret(admin_token, new_secret):
    """
    Push a specific secret value to Keycloak via Admin API (PUT).
    Unlike the old approach where Keycloak generated its own secret,
    here Lambda decides the value and tells Keycloak what to use.
    """
    client_uuid = get_client_uuid(admin_token)
    url  = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_uuid}"
    data = json.dumps({"secret": new_secret}).encode()
    req  = urllib.request.Request(
        url, data=data, method="PUT",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Content-Type":  "application/json"
        }
    )
    urllib.request.urlopen(req)


# ── 4-step rotation functions ─────────────────────────────────────────────────

def create_secret(client, arn, token):
    """
    Step 1 — Generate a new random secret and store it as AWSPENDING.
    Keycloak is NOT updated here — that happens in setSecret.
    This properly follows the AWS 4-step rotation design.
    """
    # If AWSPENDING already exists for this token, rotation already
    # started (e.g. Lambda retried) — skip to avoid generating a second secret
    try:
        existing = client.get_secret_value(SecretId=arn, VersionStage="AWSPENDING")
        if existing.get("VersionId") == token:
            return
    except Exception:
        pass

    # Read current secret — we need the full JSON to update just one field
    current = json.loads(
        client.get_secret_value(SecretId=arn, VersionStage="AWSCURRENT")["SecretString"]
    )

    # Lambda generates the new secret — we control the format and strength
    new_secret = secrets.token_urlsafe(32)

    # Update only the client secret field, keep everything else the same
    current["KEYCLOAK_CLIENT_SECRET"] = new_secret

    # Store as AWSPENDING — not active yet, just staged
    client.put_secret_value(
        SecretId=arn,
        ClientRequestToken=token,
        SecretString=json.dumps(current),
        VersionStages=["AWSPENDING"],
    )


def set_secret(client, arn, token):
    """
    Step 2 — Push the AWSPENDING secret value to Keycloak.
    This is where Keycloak actually gets updated with the new secret.
    Now this step has a real job, unlike the old approach where it was empty.
    """
    # Read the pending secret that was stored in createSecret
    pending = json.loads(
        client.get_secret_value(SecretId=arn, VersionStage="AWSPENDING")["SecretString"]
    )

    # Login to Keycloak as admin
    admin_token = get_admin_token(
        pending["KEYCLOAK_ADMIN_USER"],
        pending["KEYCLOAK_ADMIN_PASS"]
    )

    # Push the new secret to Keycloak
    set_client_secret(admin_token, pending["KEYCLOAK_CLIENT_SECRET"])


def test_secret(client, arn, token):
    """
    Step 3 — Verify the new secret actually works in Keycloak.
    Uses the AWSPENDING secret to request a token from Keycloak.
    If Keycloak returns an access_token, the secret is valid.
    If not, rotation aborts here and AWSCURRENT is never touched.
    """
    pending = json.loads(
        client.get_secret_value(SecretId=arn, VersionStage="AWSPENDING")["SecretString"]
    )

    url  = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    data = urllib.parse.urlencode({
        "client_id":     pending["KEYCLOAK_CLIENT_ID"],
        "client_secret": pending["KEYCLOAK_CLIENT_SECRET"],
        "grant_type":    "client_credentials"
    }).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())

    if "access_token" not in result:
        raise ValueError("testSecret failed — Keycloak did not return an access_token")


def finish_secret(client, arn, token):
    """
    Step 4 — Promote AWSPENDING to AWSCURRENT.
    Old AWSCURRENT automatically becomes AWSPREVIOUS (kept as fallback).
    Rotation is complete after this step.
    """
    # Find which version is currently labeled AWSCURRENT
    metadata = client.describe_secret(SecretId=arn)
    current_version = [
        v for v, stages in metadata["VersionIdsToStages"].items()
        if "AWSCURRENT" in stages
    ][0]

    # Promote: AWSPENDING → AWSCURRENT, old AWSCURRENT → AWSPREVIOUS
    client.update_secret_version_stage(
        SecretId=arn,
        VersionStage="AWSCURRENT",
        MoveToVersionId=token,
        RemoveFromVersionId=current_version,
    )