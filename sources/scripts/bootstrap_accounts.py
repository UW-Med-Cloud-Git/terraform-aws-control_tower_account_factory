import os
import json
import uuid
import boto3
import hcl2

print("🚀 bootstrap_accounts.py started")

# Configuration
SQS_QUEUE_URL = "https://sqs.us-west-2.amazonaws.com/530256939043/aft-account-request.fifo"
MESSAGE_GROUP_ID = "account-request"
REGION = "us-west-2"
DDB_TABLE_NAME = "aft-request"

# 🔐 Replace with your actual Control Tower management account role ARN
CT_ROLE_ARN = "arn:aws:iam::533267033612:role/AWSAFTService"

# 🛠 Replace with your actual Account Factory product and artifact IDs
PRODUCT_ID = "prod-xkelkuina4o6m"
ARTIFACT_ID = "pa-r2duo7qrq4ya6"

def extract_hcl_block(filepath):
    """
    Parses an HCL file and extracts the 'account_request' block from a 'locals' block.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            obj = hcl2.load(f)

            if "locals" in obj:
                locals_block = obj["locals"]

                if isinstance(locals_block, list):
                    for block in locals_block:
                        if "account_request" in block:
                            print(f"🔎 'account_request' found (list) in: {filepath}")
                            return block["account_request"]

                elif isinstance(locals_block, dict):
                    if "account_request" in locals_block:
                        print(f"🔎 'account_request' found (dict) in: {filepath}")
                        return locals_block["account_request"]

            print(f"⚠️ No 'account_request' block in: {filepath}")
    except Exception as e:
        print(f"❌ Error parsing {filepath}: {e}")
    return None

def write_to_dynamodb(ddb, request_data):
    """
    Writes the account request details to a DynamoDB table.
    """
    try:
        email = request_data["control_tower_parameters"]["SSOUserEmail"]
        item = {
            "id": {"S": email},
            "account_request": {"S": json.dumps(request_data)},
            "operation": {"S": "ADD"}
        }
        print(f"📝 Writing to DynamoDB: {email}")
        ddb.put_item(TableName=DDB_TABLE_NAME, Item=item)
    except KeyError as e:
        print(f"⚠️ Skipping DynamoDB write — missing key: {e}")

def assume_ct_session():
    """
    Assumes the Control Tower management role to get temporary credentials.
    """
    sts = boto3.client("sts")
    try:
        response = sts.assume_role(
            RoleArn=CT_ROLE_ARN,
            RoleSessionName="AFTProvisioningSession"
        )
        creds = response["Credentials"]
        print(f"🔐 Assumed CT session with access key: {creds['AccessKeyId']}")
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=REGION
        )
    except Exception as e:
        print(f"❌ Failed to assume role {CT_ROLE_ARN}. Error: {e}")
        raise

def provision_account(session, account_name, email, ou, tags, acct):
    """
    Provisions a new account using the AWS Service Catalog.
    """
    sc = session.client("servicecatalog")
    try:
        # --- FIX: Get first and last name from the 'acct' dictionary ---
        # The 'acct' dictionary holds all control_tower_parameters from the HCL file.
        # We use .get() with a default value to make the script more robust.
        first_name = acct.get("SSOUserFirstName", "AFTUser")
        last_name = acct.get("SSOUserLastName", "AFTUser")

        print(f"📦 Submitting provisioning request for {account_name} to Service Catalog")
        response = sc.provision_product(
            ProductId=PRODUCT_ID,
            ProvisioningArtifactId=ARTIFACT_ID,
            ProvisionedProductName=account_name,
            ProvisioningParameters=[
                {"Key": "AccountName", "Value": account_name},
                {"Key": "SSOUserEmail", "Value": email},
                {"Key": "AccountEmail", "Value": email},
                {"Key": "ManagedOrganizationalUnit", "Value": ou},
                # --- FIX: Use the variables defined above from the 'acct' dict ---
                {"Key": "SSOUserFirstName", "Value": first_name},
                {"Key": "SSOUserLastName", "Value": last_name}
            ],
            Tags=[{"Key": k, "Value": v} for k, v in tags.items()]
        )
        record_id = response["RecordDetail"]["RecordId"]
        print(f"🚀 Provisioning request submitted. Record ID: {record_id}")
    except KeyError as e:
        print(f"❌ Failed to provision account. A required key is missing from the HCL parameters: {e}")
    except Exception as e:
        print(f"❌ Failed to provision account: {e}")

def main():
    """
    Main function to scan for account requests and process them.
    """
    account_requests_root = "./account-requests/terraform"
    print(f"🔍 Scanning directory: {account_requests_root}")

    sqs = boto3.client("sqs", region_name=REGION)
    ddb = boto3.client("dynamodb", region_name=REGION)
    ct_session = assume_ct_session()

    for root, _, files in os.walk(account_requests_root):
        for file in files:
            if file.endswith(".tf"):
                full_path = os.path.join(root, file)
                print(f"📄 Found .tf file: {full_path}")
                request_data = extract_hcl_block(full_path)

                if request_data and "control_tower_parameters" in request_data:
                    message_body = {
                        "operation": "ADD",
                        "control_tower_parameters": request_data.get("control_tower_parameters"),
                        "account_tags": request_data.get("account_tags", {}),
                        "custom_fields": request_data.get("custom_fields", {})
                    }

                    print(f"✅ Sending request from: {file}")
                    response = sqs.send_message(
                        QueueUrl=SQS_QUEUE_URL,
                        MessageBody=json.dumps(message_body),
                        MessageGroupId=MESSAGE_GROUP_ID,
                        MessageDeduplicationId=str(uuid.uuid4())
                    )
                    print(f"📨 SQS response: {response}")

                    write_to_dynamodb(ddb, message_body)

                    acct = message_body["control_tower_parameters"]
                    print(f"🔧 Calling provision_account for {acct['AccountName']}")
                    provision_account(
                        ct_session,
                        acct["AccountName"],
                        acct["SSOUserEmail"],
                        acct["ManagedOrganizationalUnit"],
                        message_body.get("account_tags", {}),
                        acct  # Pass the entire parameters dictionary
                    )
                else:
                    print(f"⚠️ Skipping file: {file} — no valid 'account_request' block found.")

if __name__ == "__main__":
    main()
    print("✅ bootstrap_accounts.py completed")