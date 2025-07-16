import os
import json
import uuid
import boto3
import hcl2

# Configuration
SQS_QUEUE_URL = "https://sqs.us-west-2.amazonaws.com/530256939043/aft-account-request.fifo"
MESSAGE_GROUP_ID = "account-request"
REGION = "us-west-2"
DDB_TABLE_NAME = "aft-request"

def extract_hcl_block(filepath):
    try:
        with open(filepath, "r") as f:
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
    email = request_data["control_tower_parameters"]["SSOUserEmail"]
    item = {
        "id": {"S": email},
        "account_request": {"S": json.dumps(request_data)},
        "operation": {"S": "ADD"}
    }
    try:
        print(f"📝 Writing to DynamoDB: {email}")
        ddb.put_item(TableName=DDB_TABLE_NAME, Item=item)
    except KeyError as e:
        print(f"⚠️ Skipping DynamoDB write — missing key: {e}")

def main():
    account_requests_root = "./account-requests/terraform"
    print(f"🔍 Scanning directory: {account_requests_root}")

    sqs = boto3.client("sqs", region_name=REGION)
    ddb = boto3.client("dynamodb", region_name=REGION)

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

                else:
                    print(f"⚠️ Skipping file: {file} — no valid request block found.")

if __name__ == "__main__":
    main()
