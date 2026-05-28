import boto3
import json
import os
import urllib.request
import urllib.parse

KEYCLOAK_URL   = os.environ["KEYCLOAK_URL"]
KEYCLOAK_REALM = os.environ["KEYCLOAK_REALM"]
CLIENT_ID      = os.environ["KEYCLOAK_CLIENT_ID"]


def lambda_handler(event, context):
    arn   = event["SecretId"]
    token = event["ClientRequestToken"]
    step  = event["Step"]

    client = boto3.client("secretsmanager")

    metadata = client.describe_secret(SecretId=arn)
    if token not in metadata.get("VersionIdsToStages", {}):
        raise ValueError(f"Token {token} not found in secret {arn}")

    if "AWSCURRENT" in metadata["VersionIdsToStages"].get(token, []):
        return

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


def get_admin_token(admin_user, admin_pass):
    url = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    data = urllib.parse.urlencode({
        "client_id":  "admin-cli",
        "username":   admin_user,
        "password":   admin_pass,
        "grant_type": "password"
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


def get_client_uuid(admin_token):
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients?clientId={CLIENT_ID}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {admin_token}"})
    with urllib.request.urlopen(req) as resp:
        clients = json.loads(resp.read())
    if not clients:
        raise ValueError(f"Client {CLIENT_ID} not found in realm {KEYCLOAK_REALM}")
    return clients[0]["id"]


def regenerate_keycloak_secret(admin_token):
    client_uuid = get_client_uuid(admin_token)
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_uuid}/client-secret"
    req = urllib.request.Request(
        url, data=b"", method="POST",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["value"]


def create_secret(client, arn, token):
    # If AWSPENDING already exists for this token, skip
    try:
        existing = client.get_secret_value(SecretId=arn, VersionStage="AWSPENDING")
        if existing.get("VersionId") == token:
            return
    except Exception:
        pass

    # Read current secret to get admin credentials
    current = json.loads(
        client.get_secret_value(SecretId=arn, VersionStage="AWSCURRENT")["SecretString"]
    )

    # Regenerate secret in Keycloak and get the new value back
    admin_token = get_admin_token(current["KEYCLOAK_ADMIN_USER"], current["KEYCLOAK_ADMIN_PASS"])
    new_secret = regenerate_keycloak_secret(admin_token)

    # Store the new secret as AWSPENDING
    current["KEYCLOAK_CLIENT_SECRET"] = new_secret
    client.put_secret_value(
        SecretId=arn,
        ClientRequestToken=token,
        SecretString=json.dumps(current),
        VersionStages=["AWSPENDING"],
    )


def set_secret(client, arn, token):
    # Keycloak already updated in createSecret, nothing to do here
    pass


def test_secret(client, arn, token):
    pending = json.loads(
        client.get_secret_value(SecretId=arn, VersionStage="AWSPENDING")["SecretString"]
    )
    url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    data = urllib.parse.urlencode({
        "client_id":     pending["KEYCLOAK_CLIENT_ID"],
        "client_secret": pending["KEYCLOAK_CLIENT_SECRET"],
        "grant_type":    "client_credentials"
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if "access_token" not in result:
        raise ValueError("testSecret failed - Keycloak did not return an access_token")


def finish_secret(client, arn, token):
    metadata = client.describe_secret(SecretId=arn)
    current_version = [
        v for v, stages in metadata["VersionIdsToStages"].items()
        if "AWSCURRENT" in stages
    ][0]
    client.update_secret_version_stage(
        SecretId=arn,
        VersionStage="AWSCURRENT",
        MoveToVersionId=token,
        RemoveFromVersionId=current_version,
    )