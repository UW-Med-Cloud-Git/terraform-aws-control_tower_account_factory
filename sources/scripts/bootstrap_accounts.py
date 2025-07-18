# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import boto3
import hcl2
import json
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def send_sqs_message(session, queue_url, message_body, message_group_id):
    sqs = session.client("sqs")
    try:
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message_body),
            MessageGroupId=message_group_id
        )
        logger.info(f"SQS send_message response: {response}")
        return response
    except ClientError as e:
        logger.error(f"Failed to send message to SQS queue {queue_url}: {e}")
        raise

def provision_account(session, product_id, provisioning_artifact_id, account_name, ct_params, path_id):
    sc = session.client("servicecatalog")
    try:
        logger.info(f"Attempting to provision product using PathId: {path_id}")
        
        # MODIFICATION: Use the correct parameter keys expected by Service Catalog
        response = sc.provision_product(
            ProductId=product_id,
            ProvisioningArtifactId=provisioning_artifact_id,
            PathId=path_id,
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

    ct_management_region = os.environ["CT_MGMT_REGION"]
    sqs_queue_url = os.environ.get("SQS_QUEUE_URL")
    sc_product_id = os.environ.get("SC_PRODUCT_ID")
    sc_provisioning_artifact_id = os.environ.get("SC_PROVISIONING_ARTIFACT_ID")
    sc_launch_path_id = os.environ.get("SC_LAUNCH_PATH_ID")
    ct_launch_role_arn = os.environ.get("CT_LAUNCH_ROLE_ARN")

    if not all([sqs_queue_url, sc_product_id, sc_provisioning_artifact_id, sc_launch_path_id, ct_launch_role_arn]):
        logger.error("Missing required environment variables, including CT_LAUNCH_ROLE_ARN")
        raise ValueError("Missing required environment variables.")

    aft_session = boto3.Session(region_name=ct_management_region)
    sts = aft_session.client("sts")

    try:
        logger.info(f"Assuming launch role {ct_launch_role_arn} in CT account...")
        assumed_role_object = sts.assume_role(
            RoleArn=ct_launch_role_arn,
            RoleSessionName="AFT-SC-Launch-Session"
        )
        credentials = assumed_role_object['Credentials']
        
        ct_session = boto3.Session(
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken'],
            region_name=ct_management_region
        )
        logger.info("✅ Successfully assumed launch role.")

    except ClientError as e:
        logger.error(f"Failed to assume role {ct_launch_role_arn}: {e}")
        raise

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

                    ct_params = request.get("control_tower_parameters", {})
                    account_tags = request.get("account_tags", {})
                    custom_fields = request.get("custom_fields", {})
                    account_email = ct_params.get("AccountEmail")

                    if not account_email:
                        logger.warning(f"Missing 'AccountEmail' in {filename}. Skipping.")
                        continue

                    sqs_payload = {
                        "control_tower_parameters": ct_params,
                        "account_tags": account_tags,
                        "custom_fields": custom_fields
                    }
                    
                    logger.info(f"✅ Preparing to send request from: {filename}")
                    
                    send_sqs_message(ct_session, sqs_queue_url, sqs_payload, message_group_id=account_email)
                    
                    account_name = ct_params["AccountName"]
                    logger.info(f"🔧 Calling provision_account for {account_name}")
                    
                    provision_account(
                        ct_session,
                        sc_product_id,
                        sc_provisioning_artifact_id,
                        account_name,
                        ct_params,
                        sc_launch_path_id
                    )
                except Exception as e:
                    logger.error(f"Error processing file {filepath}: {e}")
                    continue

    logger.info("✅ bootstrap_accounts.py completed")

if __name__ == "__main__":
    main()
