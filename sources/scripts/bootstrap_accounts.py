# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This script is used to bootstrap AFT account requests.
# It parses Terraform files, sends the request to an SQS queue,
# and then provisions the account via AWS Service Catalog.

import os
import boto3
import hcl2
import json
import logging
from botocore.exceptions import ClientError

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_session(region):
    """Gets a boto3 session in the specified region."""
    return boto3.Session(region_name=region)

def send_sqs_message(session, queue_url, message_body):
    """Sends a message to the specified SQS queue."""
    sqs = session.client("sqs")
    try:
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message_body)
        )
        logger.info(f"SQS send_message response: {response}")
        return response
    except ClientError as e:
        logger.error(f"Failed to send message to SQS queue {queue_url}: {e}")
        raise

def provision_account(session, product_id, provisioning_artifact_id, account_name, ct_params):
    """Provisions a new account using AWS Service Catalog."""
    sc = session.client("servicecatalog")
    try:
        response = sc.provision_product(
            ProductId=product_id,
            ProvisioningArtifactId=provisioning_artifact_id,
            ProvisionedProductName=account_name,
            ProvisioningParameters=[
                {"Key": "AccountEmail", "Value": ct_params["AccountEmail"]},
                {"Key": "AccountName", "Value": ct_params["AccountName"]},
                {"Key": "ManagedOrganizationalUnit", "Value": ct_params["ManagedOrganizationalUnit"]},
                {"Key": "SSOUserEmail", "Value": ct_params["SSOUserEmail"]},
                {"Key": "SSOUserFirstName", "Value": ct_params["SSOUserFirstName"]},
                {"Key": "SSOUserLastName", "Value": ct_params["SSOUserLastName"]},
            ],
        )
        logger.info(f"Service Catalog provision_product response: {response}")
        return response
    except ClientError as e:
        logger.error(f"Failed to provision product for {account_name}: {e}")
        raise

def main():
    logger.info("🚀 bootstrap_accounts.py started")

    # Get environment variables
    ct_management_region = os.environ["CT_MGMT_REGION"]
    
    sqs_queue_url = os.environ.get("SQS_QUEUE_URL")
    sc_product_id = os.environ.get("SC_PRODUCT_ID")
    sc_provisioning_artifact_id = os.environ.get("SC_PROVISIONING_ARTIFACT_ID")

    if not all([sqs_queue_url, sc_product_id, sc_provisioning_artifact_id]):
        logger.error("Missing required environment variables: SQS_QUEUE_URL, SC_PRODUCT_ID, SC_PROVISIONING_ARTIFACT_ID")
        raise ValueError("Missing required environment variables.")

    # The buildspec already assumes the correct role.
    # Boto3 will automatically use the credentials from the environment variables.
    logger.info(f"Creating Boto3 session in {ct_management_region} using credentials from the environment.")
    ct_session = boto3.Session(region_name=ct_management_region)

    # Scan for account request files
    request_dir = "./account-requests/terraform"
    logger.info(f"🔍 Scanning directory: {request_dir}")
    
    for filename in os.listdir(request_dir):
        if filename.endswith(".tf"):
            filepath = os.path.join(request_dir, filename)
            logger.info(f"📄 Found .tf file: {filepath}")
            
            with open(filepath, "r") as f:
                try:
                    data = hcl2.load(f)
                    request = data.get("locals", [{}])[0].get("account_request", {})

                    if not request:
                        logger.warning(f"No 'account_request' block found in {filename}. Skipping.")
                        continue

                    # Extract all relevant sections from the request file
                    ct_params = request.get("control_tower_parameters", {})
                    account_tags = request.get("account_tags", {})
                    custom_fields = request.get("custom_fields", {})

                    if not ct_params.get("AccountEmail"):
                        logger.warning(f"Missing 'AccountEmail' in {filename}. Skipping.")
                        continue

                    # Construct the full payload for the SQS message
                    sqs_payload = {
                        "control_tower_parameters": ct_params,
                        "account_tags": account_tags,
                        "custom_fields": custom_fields
                    }
                    
                    logger.info(f"✅ Preparing to send request from: {filename}")
                    
                    # Send the enriched message to SQS for downstream processing
                    send_sqs_message(ct_session, sqs_queue_url, sqs_payload)
                    
                    # Provision the account via Service Catalog
                    account_name = ct_params["AccountName"]
                    logger.info(f"🔧 Calling provision_account for {account_name}")
                    provision_account(
                        ct_session,
                        sc_product_id,
                        sc_provisioning_artifact_id,
                        account_name,
                        ct_params
                    )
                    
                    # Here you might want to move or delete the processed .tf file
                    # to prevent it from being processed again on the next run.
                    # Example: os.remove(filepath)

                except Exception as e:
                    logger.error(f"Error processing file {filepath}: {e}")
                    continue

    logger.info("✅ bootstrap_accounts.py completed")

if __name__ == "__main__":
    main()
