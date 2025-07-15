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

            if "locals" in obj:
                locals_block = obj["locals"]

                # If 'locals' is a list of dicts
                if isinstance(locals_block, list):
                    for block in locals_block:
                        if "account_request" in block:
                            print(f"🔎 'account_request' found (list) in: {filepath}")
                            return block["account_request"]

                # If 'locals' is a flat dict
                elif isinstance(locals_block, dict):
                    if "account_request" in locals_block:
                        print(f"🔎 'account_request' found (dict) in: {filepath}")
                        return locals_block["account_request"]

            print(f"⚠️ No 'account_request' block in: {filepath}")
    except Exception as e:
        print(f"❌ Error parsing {filepath}: {e}")
    return None

def main():
    account_requests_root = "./account-requests/terraform"
    print(f"🔍 Scanning directory: {account_requests_root}")

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
                    sqs = boto3.client("sqs", region_name=REGION)
                    sqs.send_message(
                        QueueUrl=SQS_QUEUE_URL,
                        MessageBody=json.dumps(message_body),
                        MessageGroupId=MESSAGE_GROUP_ID
                    )
                else:
                    print(f"⚠️ Skipping file: {file} — no valid request block found.")

if __name__ == "__main__":
    main()
