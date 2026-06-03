import boto3
import json
import os
import secrets
import urllib.request
import urllib.parse
import urllib.error

KEYCLOAK_URL   = os.environ["KEYCLOAK_URL"]
KEYCLOAK_REALM = os.environ["KEYCLOAK_REALM"]
CLIENT_ID      = os.environ["KEYCLOAK_CLIENT_ID"]


# ── Logging helper ─────────────────────────────────────────────────────────────

def log(level, step, message):
    """
    Structured log line — shows up clearly in CloudWatch.
    Format: [LEVEL] [STEP] message
    """
    print(f"[{level}] [{step}] {message}")


# ── Entry point ────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Entry point. AWS Secrets Manager calls this function 4 times per rotation,
    once for each step: createSecret, setSecret, testSecret, finishSecret.
    """
    arn   = event["SecretId"]
    token = event["ClientRequestToken"]
    step  = event["Step"]

    log("INFO", step, f"Starting | SecretId={arn} | Token={token}")

    client = boto3.client("secretsmanager")

    # Make sure this rotation token is valid and belongs to this secret
    metadata = client.describe_secret(SecretId=arn)
    if token not in metadata.get("VersionIdsToStages", {}):
        log("ERROR", step, f"Token {token} not found in secret versions — aborting")
        raise ValueError(f"Token {token} not found in secret {arn}")

    # If this token is already AWSCURRENT, rotation already finished — skip
    if "AWSCURRENT" in metadata["VersionIdsToStages"].get(token, []):
        log("INFO", step, "Token is already AWSCURRENT — rotation already complete, skipping")
        return

    log("INFO", step, f"Routing to step handler")

    if step == "createSecret":
        create_secret(client, arn, token)
    elif step == "setSecret":
        set_secret(client, arn, token)
    elif step == "testSecret":
        test_secret(client, arn, token)
    elif step == "finishSecret":
        finish_secret(client, arn, token)
    else:
        log("ERROR", step, f"Unknown step: {step}")
        raise ValueError(f"Unknown step: {step}")

    log("INFO", step, "Finished successfully")


# ── Helper functions ───────────────────────────────────────────────────────────

def get_admin_token(admin_user, admin_pass, step="setSecret"):
    """
    Log into Keycloak as admin and return a short-lived access token.
    All Admin API calls need this token in their Authorization header.
    """
    url = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    log("INFO", step, f"Requesting admin token from Keycloak | URL={url}")

    data = urllib.parse.urlencode({
        "client_id":  "admin-cli",
        "username":   admin_user,
        "password":   admin_pass,
        "grant_type": "password"
    }).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            token = json.loads(resp.read())["access_token"]
            log("INFO", step, "Admin token obtained successfully")
            return token
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log("ERROR", step, f"Failed to get admin token — HTTP {e.code}: {body}")
        raise
    except Exception as e:
        log("ERROR", step, f"Failed to get admin token — {e}")
        raise


def get_client_uuid(admin_token, step="setSecret"):
    """
    Keycloak identifies clients by UUID internally, not by clientId name.
    Look up the client by name and return its internal UUID.
    """
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients?clientId={CLIENT_ID}"
    log("INFO", step, f"Looking up client UUID for clientId={CLIENT_ID}")

    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {admin_token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            clients = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log("ERROR", step, f"Failed to look up client UUID — HTTP {e.code}: {body}")
        raise

    if not clients:
        log("ERROR", step, f"No client found with clientId={CLIENT_ID} in realm={KEYCLOAK_REALM}")
        raise ValueError(f"Client {CLIENT_ID} not found in realm {KEYCLOAK_REALM}")

    uuid = clients[0]["id"]
    log("INFO", step, f"Found client UUID={uuid}")
    return uuid


def set_client_secret(admin_token, new_secret, step="setSecret"):
    """
    Push a specific secret value to Keycloak via Admin API.

    IMPORTANT: Keycloak's PUT /clients/{uuid} requires the FULL client
    representation — not just the fields you want to change. We first GET
    the current config, update only the 'secret' field, then PUT it back.
    Sending a partial payload can silently reset other settings (e.g. disabling
    service accounts), which causes 403s in testSecret.
    """
    client_uuid = get_client_uuid(admin_token, step)
    base_url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_uuid}"

    # Step A: GET full client representation
    log("INFO", step, f"Fetching full client config from Keycloak | URL={base_url}")
    get_req = urllib.request.Request(
        base_url,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    try:
        with urllib.request.urlopen(get_req) as resp:
            client_rep = json.loads(resp.read())
        log("INFO", step, f"Fetched client config — serviceAccountsEnabled={client_rep.get('serviceAccountsEnabled')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log("ERROR", step, f"Failed to GET client config — HTTP {e.code}: {body}")
        raise

    # Step B: Update only the secret field
    client_rep["secret"] = new_secret
    log("INFO", step, "Updated 'secret' field in client representation")

    # Step C: PUT the full representation back
    log("INFO", step, f"Pushing updated client config back to Keycloak (PUT)")
    put_req = urllib.request.Request(
        base_url,
        data=json.dumps(client_rep).encode(),
        method="PUT",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Content-Type":  "application/json"
        }
    )
    try:
        with urllib.request.urlopen(put_req) as resp:
            log("INFO", step, f"Keycloak PUT successful — HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log("ERROR", step, f"Failed to PUT updated client secret — HTTP {e.code}: {body}")
        raise


# ── 4-step rotation functions ──────────────────────────────────────────────────

def create_secret(client, arn, token):
    """
    Step 1 — Generate a new random secret and store it as AWSPENDING.
    Keycloak is NOT updated here — that happens in setSecret.
    """
    step = "createSecret"
    log("INFO", step, "=== CREATE SECRET START ===")

    # If AWSPENDING already exists for this exact token, this is a Lambda retry — skip
    try:
        existing = client.get_secret_value(SecretId=arn, VersionStage="AWSPENDING")
        if existing.get("VersionId") == token:
            log("INFO", step, "AWSPENDING already exists for this token (Lambda retry) — skipping")
            return
        else:
            log("INFO", step, f"AWSPENDING exists but for a different token ({existing.get('VersionId')}) — proceeding")
    except client.exceptions.ResourceNotFoundException:
        log("INFO", step, "No existing AWSPENDING found — proceeding to create")
    except Exception as e:
        log("WARN", step, f"Could not check existing AWSPENDING ({e}) — proceeding anyway")

    # Read current secret — copy all fields, only update the client secret
    log("INFO", step, "Reading AWSCURRENT secret")
    current = json.loads(
        client.get_secret_value(SecretId=arn, VersionStage="AWSCURRENT")["SecretString"]
    )
    log("INFO", step, f"AWSCURRENT has keys: {list(current.keys())}")

    # Generate new secret
    new_secret = secrets.token_urlsafe(32)
    log("INFO", step, f"Generated new secret (length={len(new_secret)})")

    # Update only the client secret field, keep all other fields identical
    current["KEYCLOAK_CLIENT_SECRET"] = new_secret

    # Store as AWSPENDING
    client.put_secret_value(
        SecretId=arn,
        ClientRequestToken=token,
        SecretString=json.dumps(current),
        VersionStages=["AWSPENDING"],
    )
    log("INFO", step, "New secret stored as AWSPENDING successfully")
    log("INFO", step, "=== CREATE SECRET FINISH ===")


def set_secret(client, arn, token):
    """
    Step 2 — Push the AWSPENDING secret value to Keycloak.
    Uses GET + PUT so we send the full client representation, not a partial payload.
    """
    step = "setSecret"
    log("INFO", step, "=== SET SECRET START ===")

    # Read the pending secret
    log("INFO", step, "Reading AWSPENDING secret")
    pending = json.loads(
        client.get_secret_value(SecretId=arn, VersionStage="AWSPENDING")["SecretString"]
    )
    log("INFO", step, f"AWSPENDING has keys: {list(pending.keys())}")

    # Login to Keycloak as admin
    log("INFO", step, f"Logging into Keycloak as admin user={pending['KEYCLOAK_ADMIN_USER']}")
    admin_token = get_admin_token(
        pending["KEYCLOAK_ADMIN_USER"],
        pending["KEYCLOAK_ADMIN_PASS"],
        step
    )

    # Push the new secret to Keycloak using full GET + PUT
    set_client_secret(admin_token, pending["KEYCLOAK_CLIENT_SECRET"], step)

    log("INFO", step, "=== SET SECRET FINISH ===")


def test_secret(client, arn, token):
    """
    Step 3 — Verify the new secret actually works in Keycloak.
    Uses the AWSPENDING secret to request a token via client_credentials grant.
    If Keycloak returns an access_token, the secret is valid and rotation continues.
    If not, rotation aborts here and AWSCURRENT is never touched.
    """
    step = "testSecret"
    log("INFO", step, "=== TEST SECRET START ===")

    log("INFO", step, "Reading AWSPENDING secret")
    pending = json.loads(
        client.get_secret_value(SecretId=arn, VersionStage="AWSPENDING")["SecretString"]
    )

    url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    log("INFO", step, f"Testing client_credentials grant | URL={url} | client_id={pending['KEYCLOAK_CLIENT_ID']}")

    data = urllib.parse.urlencode({
        "client_id":     pending["KEYCLOAK_CLIENT_ID"],
        "client_secret": pending["KEYCLOAK_CLIENT_SECRET"],
        "grant_type":    "client_credentials"
    }).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log("ERROR", step, f"Keycloak returned HTTP {e.code} — Response body: {body}")
        log("ERROR", step, (
            "Possible causes: "
            "(1) setSecret did not update Keycloak correctly, "
            "(2) service accounts not enabled for this client, "
            "(3) client_credentials grant type not allowed"
        ))
        raise
    except Exception as e:
        log("ERROR", step, f"Unexpected error during token request: {e}")
        raise

    if "access_token" not in result:
        log("ERROR", step, f"No access_token in Keycloak response — keys returned: {list(result.keys())}")
        raise ValueError("testSecret failed — Keycloak did not return an access_token")

    log("INFO", step, "Keycloak returned access_token — new secret is valid!")
    log("INFO", step, "=== TEST SECRET FINISH ===")


def finish_secret(client, arn, token):
    """
    Step 4 — Promote AWSPENDING to AWSCURRENT.
    Old AWSCURRENT automatically becomes AWSPREVIOUS (kept as a fallback).
    Rotation is complete after this step.
    """
    step = "finishSecret"
    log("INFO", step, "=== FINISH SECRET START ===")

    # Find which version is currently labeled AWSCURRENT
    metadata = client.describe_secret(SecretId=arn)
    versions = metadata["VersionIdsToStages"]
    log("INFO", step, f"Current version stages: { {v: s for v, s in versions.items()} }")

    current_version = [
        v for v, stages in versions.items()
        if "AWSCURRENT" in stages
    ][0]
    log("INFO", step, f"Current AWSCURRENT version={current_version} | Promoting token={token}")

    # Promote AWSPENDING → AWSCURRENT; old AWSCURRENT → AWSPREVIOUS
    client.update_secret_version_stage(
        SecretId=arn,
        VersionStage="AWSCURRENT",
        MoveToVersionId=token,
        RemoveFromVersionId=current_version,
    )

    log("INFO", step, f"Promoted token={token} to AWSCURRENT | Old version={current_version} moved to AWSPREVIOUS")
    log("INFO", step, "=== FINISH SECRET FINISH — ROTATION COMPLETE ===")