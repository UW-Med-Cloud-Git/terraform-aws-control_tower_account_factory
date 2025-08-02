# Copyright Amazon.com, Inc. or its affiliates. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
locals {
  state_machine_source = "${path.module}/states/aft_account_provisioning_framework.asl.json"
  replacements_map = {
    current_partition                                 = data.aws_partition.current.partition
    persist_metadata_function_arn                     = aws_lambda_function.persist_metadata.arn
    create_role_function_arn                          = aws_lambda_function.create_role.arn
    tag_account_function_arn                          = aws_lambda_function.tag_account.arn
    account_metadata_ssm_function_arn                 = aws_lambda_function.account_metadata_ssm.arn
    aft_features_sfn_arn                              = "arn:${data.aws_partition.current.partition}:states:${data.aws_region.aft_management.name}:${data.aws_caller_identity.aft_management.account_id}:stateMachine:${var.aft_features_sfn_name}"
    
    account_customizations_sfn_arn                    = "arn:${data.aws_partition.current.partition}:states:${data.aws_region.aft_management.name}:${data.aws_caller_identity.aft_management.account_id}:stateMachine:aft-account-provisioning-framework"
    
    aft_notification_arn                              = var.aft_sns_topic_arn
    aft_failure_notification_arn                      = var.aft_failure_sns_topic_arn
  }
}

resource "aws_sfn_state_machine" "aft_account_provisioning_framework_sfn" {
  name       = var.aft_account_provisioning_framework_sfn_name
  role_arn   = aws_iam_role.aft_states.arn
  definition = templatefile(local.state_machine_source, local.replacements_map)
}
