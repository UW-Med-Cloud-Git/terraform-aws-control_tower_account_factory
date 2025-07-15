import os
import json
import boto3
import hcl2

# Configuration
SQS_QUEUE_URL = "https://sqs.us-west-2.amazonaws.com/530256939043/aft-account-request.fifo"
MESSAGE_GROUP_ID = "account-request"
REGION = "us-west-2"

def extract_hcl_block(filepath):
    try:
        with open(filepath, "r") as f:
            obj = hcl2.load(f)
            for block in obj.get("locals", []):
                if "account_request" in block:
                    return block["account_request"]
    except Exception as e:
        print(f"❌ Error parsing {filepath}: {e}")
    return None

def main():
    account_requests_root = "./AWS-AFT-Account-Requests/terraform"
    print(f"🔍 Searching for .tf files in: {account_requests_root}")

    for root, _, files in os.walk(account_requests_root):
        for file in files:
            if file.endswith(".tf"):
                full_path = os.path.join(root, file)
                print(f"📁 Scanning: {full_path}")
                request_data = extract_hcl_block(full_path)
                if request_data and "control_tower_parameters" in request_data:
                    message_body = {
                        "operation": "ADD",
                        "control_tower_parameters": request_data.get("control_tower_parameters"),
                        "account_tags": request_data.get("account_tags", {}),
                        "custom_fields": request_data.get("custom_fields", {})
                    }
                    print(f"✅ Sending request from: {file}")
                    sqs = boto3.client("sqs", region_name=REGION)
                    sqs.send_message(
                        QueueUrl=SQS_QUEUE_URL,
                        MessageBody=json.dumps(message_body),
                        MessageGroupId=MESSAGE_GROUP_ID
                    )
                else:
                    print(f"⚠️ No valid account_request block in: {file}")

if __name__ == "__main__":
    main()
