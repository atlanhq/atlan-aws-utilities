import json
import os
import boto3

sqs = boto3.client('sqs')
WEBHOOK_SECRET = os.environ['WEBHOOK_SECRET']
SQS_QUEUE_URL = os.environ['SQS_QUEUE_URL']

def lambda_handler(event, context):

    # --- Bypass auth for dummy payload validation request
    dummy_body = json.loads(event.get('body', '{}'))

    if "atlan-webhook" in dummy_body:
        if dummy_body["atlan-webhook"] == "Hello, humans of data! It worked. Excited to see what you build!":
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'OK'})
            }

    # --- Auth check ---
    # Atlan's webhook delivery pipeline sends the signing secret in the
    # x-atlan-signing-secret header (API Gateway HTTP APIs lowercase header
    # names). 'secret-key' is kept as a fallback for callers configured
    # against the previous behavior.
    headers = event.get('headers', {})
    provided_key = headers.get('x-atlan-signing-secret', '') or headers.get('secret-key', '')

    if provided_key != WEBHOOK_SECRET:
        return {
            'statusCode': 403,
            'body': json.dumps({'error': 'Forbidden. Webhook Receiver Lambda cannot be executed'})
        }
    
    # --- Validate payload ---
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid JSON Body'})
        }
    
    # --- Validate request type ---
    
    request_type = body.get('type', None)

    if request_type != 'DATA_ACCESS_REQUEST':
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Invalid request type: {request_type}. Must be DATA_ACCESS_REQUEST'})
        }
    
    asset_details = body.get('payload', {}).get('asset_details', {})

    asset_name = asset_details.get('name', None)
    asset_qualified_name = asset_details.get('qualified_name', None)
    asset_type = asset_details.get('type_name', None)

    workflow_run_guid = body.get('payload', {}).get('workflow_run_guid', None)

    # Approver-selected SMUS asset filter (row/column scope), when one was chosen.
    # Absent = full access (unchanged behaviour).
    approval_details = body.get('payload', {}).get('approval_details', {})
    selected_filter = approval_details.get('selected_filter', None)

    if not all([asset_name, asset_qualified_name, asset_type, workflow_run_guid]):
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing asset / governance workflow details : name, qualified_name, type_name and workflow_run_guid are required fields'})
        }
    
    target_project_details = None
    subscription_reason = ""

    response_forms = body.get('payload', {}).get('forms', [])
    for f in response_forms:
        target_project_details = f.get('response', {}).get('Project', None)
        subscription_reason = f.get('response', {}).get('Reason', "")
    
    # --- If no subscription reason provided for the request, default to the below reason
    if subscription_reason == "":
        subscription_reason = f"Auto-subscription via Atlan webhook"
    
    # --- Validate target project details present ---
    
    if not target_project_details:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing target Project details in the request received from Atlan'})
        }
    
    # --- Validate target project details JSON payload ---
    try:
        target_project_details_body = json.loads(target_project_details)
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid JSON Body for target Project details in the request received from Atlan'})
        } 
    
    asset_id = asset_qualified_name.split('/')[-1]
    owning_project_id = asset_qualified_name.split('/')[-3]
    domain_id = asset_qualified_name.split('/')[-5]

    target_project_id = target_project_details_body.get('smusProjectId', None)
    target_project_name = target_project_details_body.get('name', None)


    print("Enqueing message to SQS ...")
    
    # --- Enqueue for processing ---
    sqs.send_message(
        QueueUrl=SQS_QUEUE_URL,
        MessageBody=json.dumps({
            'asset_id': asset_id,
            'asset_name': asset_name,
            'owning_project_id': owning_project_id,
            'target_project_id': target_project_id,
            'domain_id': domain_id,
            'request_reason': subscription_reason,
            'correlation_id': workflow_run_guid,
            'selected_filter': selected_filter,
        })
    )
    
    return {
        'statusCode': 202,
        'body': json.dumps({'message': f'Subscription Request queued of {asset_name} Published Asset for {target_project_name} Project'})
    }