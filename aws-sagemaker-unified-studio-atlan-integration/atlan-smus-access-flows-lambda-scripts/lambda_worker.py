import json
import os
import urllib3
from botocore.exceptions import ClientError
import boto3

datazone = boto3.client('datazone')
http = urllib3.PoolManager()

CALLBACK_SECRET = os.environ.get('ATLAN_CALLBACK_SECRET', '')
CALLBACK_URL = os.environ.get('ATLAN_CALLBACK_URL', '')


def lambda_handler(event, context):
    """Triggered by SQS. Each record is one subscription request."""

    for record in event['Records']:
        payload = json.loads(record['body'])
        process_subscription(payload)


def process_subscription(payload):
    asset_id = payload['asset_id']
    asset_name = payload['asset_name']
    owning_project_id = payload['owning_project_id']
    target_project_id = payload['target_project_id']
    domain_id = payload['domain_id']
    request_reason = payload['request_reason']
    correlation_id = payload.get('correlation_id', '')

    result = {
        'status': None,
        'workflow_run_guid': correlation_id,
        'message': '',
        'details': {
            'asset_id': asset_id,
        },
    }

    try:
        # -------- STEP 1: Search Listings to get listing_id --------
        print(f"Searching listing for asset_id={asset_id}")

        search_response = datazone.search_listings(
            domainIdentifier=domain_id,
            additionalAttributes=['FORMS'],
            searchText=asset_name,
            filters={
                    "and": [{"filter": {"attribute": "owningProjectId", "value": owning_project_id}},
                    {"filter": {"attribute": "amazonmetadata.sourceCategory", "value": "asset"}}]
            }
        )

        listing_id = None

        for item in search_response.get('items', []):
            asset_listing = item.get('assetListing', {})
            if asset_listing.get('entityId') == asset_id:
                listing_id = asset_listing.get('listingId')
    

        if not listing_id:
            raise Exception(f"No listing found for asset_id={asset_id}")

        # -------- STEP 2: Check for existing subscription / pending request --------
        # Avoid creating duplicate subscriptions if one is already APPROVED
        # or a request is already PENDING for this (listing, target_project) pair.
        existing = find_existing_subscription(
            domain_id=domain_id,
            listing_id=listing_id,
            target_project_id=target_project_id,
        )

        if existing:
            print(
                f"Existing {existing['kind']} found for listing_id={listing_id}, "
                f"project={target_project_id}: id={existing['id']}. Skipping create."
            )
            result['status'] = 'SUCCESS'
            result['details'].update({
                'listing_id': listing_id,
                'already_exists': True,
                'existing_kind': existing['kind'],  # 'SUBSCRIPTION' or 'SUBSCRIPTION_REQUEST'
            })
            if existing['kind'] == 'SUBSCRIPTION':
                result['details']['subscription_id'] = existing['id']
                result['details']['subscription_request_id'] = existing.get('subscription_request_id')
                result['message'] = (
                    "An active subscription for this asset already exists for the "
                    "requesting project. No new subscription request was created; "
                    "the existing subscription remains in effect."
                )
            else:  # SUBSCRIPTION_REQUEST (PENDING)
                result['details']['subscription_request_id'] = existing['id']
                result['message'] = (
                    "A subscription request for this asset is already pending for "
                    "the requesting project. No new request was created; the "
                    "existing request will be processed."
                )

        else:

            # -------- STEP 3: Create Subscription Request --------
            # The Lambda execution role is attached to both the producer and the
            # subscriber projects, so DataZone auto-approves the request. We do
            # not call accept_subscription_request anymore; instead we create the
            # request as the default (execution-role) datazone client and then
            # confirm the resulting subscription is APPROVED.
            print(f"Creating subscription request for project={target_project_id}")

            sub_response = datazone.create_subscription_request(
                domainIdentifier=domain_id,
                requestReason=request_reason,
                subscribedPrincipals=[
                    {
                        'project': {
                            'identifier': target_project_id
                        }
                    }
                ],
                subscribedListings=[
                    {
                        'identifier': listing_id
                    }
                ]
            )

            subscription_request_id = sub_response['id']
            subscription_status = sub_response['status']

            print(
                f"Subscription request created: {subscription_request_id} "
                f"(status={subscription_status})"
            )

            # Confirm the auto-approved subscription exists and fetch its id.
            # verify_subscription_approved filters list_subscriptions by request
            # id + status=APPROVED and returns the subscription id, or None.
            approved_subscription_id = verify_subscription_approved(
                domain_id=domain_id,
                subscription_request_id=subscription_request_id,
            )

            if not approved_subscription_id and subscription_status != 'ACCEPTED':
                # Auto-approval did not take effect - treat as a real failure.
                raise Exception(
                    f"Subscription request {subscription_request_id} was not "
                    f"approved (status={subscription_status}); no APPROVED "
                    f"subscription found for it."
                )

            result['status'] = 'SUCCESS'
            result['details'].update({
                'listing_id': listing_id,
                'already_exists': False,
                'subscription_request_id': subscription_request_id,
            })

            if approved_subscription_id:
                result['details']['subscription_id'] = approved_subscription_id
            result['message'] = (
                "Subscription request was created and approved successfully. "
                "The requesting project now has access to the asset."
            )

    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)

        # For boto/AWS ClientError, surface the AWS error code as a first-class
        # field so the consumer can differentiate failure modes programmatically
        # (throttling vs validation vs access denied, etc).
        aws_error_code = None
        if isinstance(e, ClientError):
            aws_error_code = e.response.get('Error', {}).get('Code')

        print(
            f"ERROR processing subscription for asset_id={asset_id}, "
            f"target_project={target_project_id}: {error_type}: {error_msg}"
        )

        result['status'] = 'FAILURE'
        result['message'] = (
            f"Failed to provision subscription for asset {asset_id} in project "
            f"{target_project_id}. {error_type}: {error_msg}"
        )
        result['details']['error'] = {
            'type': error_type,
            'message': error_msg,
        }
        if aws_error_code:
            result['details']['error']['aws_error_code'] = aws_error_code

        # Notify Atlan of the failure before re-raising, so the workflow side
        # gets failure detail in real time rather than only learning about it
        # after SQS exhausts retries and the message lands in the DLQ.
        # notify_atlan swallows its own errors internally, so this will not
        # mask the original exception we are about to raise.
        if CALLBACK_URL:
            notify_atlan(CALLBACK_URL, result)

        raise

    # -------- STEP 4: Notify Atlan of completion --------
    if CALLBACK_URL:
        notify_atlan(CALLBACK_URL, result)

    return result


def verify_subscription_approved(domain_id, subscription_request_id):
    """
    Verify whether an APPROVED subscription exists for the given subscription
    request. Used to confirm that the auto-approval (driven by the shared role
    being attached to both projects) actually produced an APPROVED subscription.

    Returns:
        The subscription id (str) if an APPROVED subscription exists for this
        request, otherwise None.
    """
    resp = datazone.list_subscriptions(
        domainIdentifier=domain_id,
        subscriptionRequestIdentifier=subscription_request_id,
        status='APPROVED',
    )
    items = resp.get('items', [])
    if items:
        return items[0].get('id')
    return None


def find_existing_subscription(domain_id, listing_id, target_project_id):
    """
    Returns details of an existing APPROVED subscription or PENDING subscription
    request for the given (listing, target project) pair, if one exists.

    Returns:
        dict with keys: kind ('SUBSCRIPTION' | 'SUBSCRIPTION_REQUEST'),
                        id, and optionally subscription_request_id.
        None if no active subscription or pending request exists.
    """
    # 1. Check for APPROVED subscriptions first - this is the "live" state.
    #    `owningProjectId` on list_subscriptions refers to the project that holds
    #    the subscription (i.e. the subscriber / target project).
    print(
        f"Checking APPROVED subscriptions for listing_id={listing_id}, "
        f"owningProjectId={target_project_id}"
    )
    approved_resp = datazone.list_subscriptions(
        domainIdentifier=domain_id,
        subscribedListingId=listing_id,
        owningProjectId=target_project_id,
        status='APPROVED',
    )
    approved_items = approved_resp.get('items', [])
    if approved_items:
        sub = approved_items[0]
        return {
            'kind': 'SUBSCRIPTION',
            'id': sub.get('id'),
            'subscription_request_id': sub.get('subscriptionRequestId'),
        }

    # 2. No approved subscription - check for an in-flight PENDING request to
    #    avoid creating a duplicate request for the same listing/project pair.
    print(
        f"Checking PENDING subscription requests for listing_id={listing_id}, "
        f"owningProjectId={target_project_id}"
    )
    pending_resp = datazone.list_subscription_requests(
        domainIdentifier=domain_id,
        subscribedListingId=listing_id,
        owningProjectId=target_project_id,
        status='PENDING',
    )
    pending_items = pending_resp.get('items', [])
    if pending_items:
        req = pending_items[0]
        return {
            'kind': 'SUBSCRIPTION_REQUEST',
            'id': req.get('id'),
        }

    return None


def notify_atlan(callback_url, result):
    """POST the result back to Atlan using bearer token auth."""
    print(f"Notifying Atlan at {callback_url}")

    try:
        response = http.request(
            'POST',
            callback_url,
            body=json.dumps(result).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {CALLBACK_SECRET}',
            },
            timeout=10.0
        )
        print(f"Atlan callback response: {response.status}")
    except Exception as e:
        print(f"WARNING: Atlan callback failed: {str(e)}")