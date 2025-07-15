import os
import json
import re
import boto3

# Adjust these for your region and queue
SQS_QUEUE_URL = "https://sqs.us-west-2.amazonaws.com/530256939043/aft-account-request.fifo"
MESSAGE_GROUP_ID = "account-request"
REGION = "us-west-2"

def extract_locals_block(file_contents):
    match = re.search(r"locals\s*{([^}]+)}", file_contents, re.DOTALL)
    if match:
        try:
            json_block = re.search(r"account_request\s*=\s*({.*})", match.group(1), re.DOTALL).group(1)
            json_block_cleaned = json_block.replace("=", ":").replace("}", "},").replace(",,", ",")
            return json.loads(json_block_cleaned.rstrip(","))
        except Exception as e:
            print(f"❌ Failed to parse account_request block: {e}")
    return None

def main():
    account_requests_root = "./account-requests"

    for root, _, files in os.walk(account_requests_root):
        for file in files:
            if file.endswith(".tf"):
                full_path = os.path.join(root, file)
                with open(full_path, "r") as f:
                    contents = f.read()
                request_data = extract_locals_block(contents)
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

if __name__ == "__main__":
    main()
