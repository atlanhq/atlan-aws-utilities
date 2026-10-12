"""Tests for the SMUS access-flow worker: what it reports back to Atlan.

All AWS clients are mocks; nothing here touches the network. Run from this
folder with `python -m pytest tests` (needs pytest and boto3 installed).
"""

import os
import sys
from unittest import mock

import pytest
from botocore.exceptions import ClientError

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lambda_worker  # noqa: E402

DOMAIN_ID = "dzd_example0001"
OWNING_PROJECT_ID = "owning-project-0001"
TARGET_PROJECT_ID = "target-project-0001"
ASSET_ID = "asset-0001"
LISTING_ID = "listing-0001"
PENDING_REQUEST_ID = "request-pending-0001"
CALLER_ARN = "arn:aws:sts::000000000000:assumed-role/example-worker-role/example-session"


def _payload():
    return {
        "asset_id": ASSET_ID,
        "asset_name": "example_table",
        "owning_project_id": OWNING_PROJECT_ID,
        "target_project_id": TARGET_PROJECT_ID,
        "domain_id": DOMAIN_ID,
        "request_reason": "test",
        "correlation_id": "workflow-run-0001",
    }


def _datazone():
    dz = mock.MagicMock()
    dz.search_listings.return_value = {
        "items": [{"assetListing": {"entityId": ASSET_ID, "listingId": LISTING_ID}}]
    }
    return dz


@pytest.fixture
def notified(monkeypatch):
    """Capture every result the worker sends to Atlan."""
    sent = []
    monkeypatch.setattr(lambda_worker, "CALLBACK_URL", "https://callback.example.invalid/hook")
    monkeypatch.setattr(lambda_worker, "notify_atlan", lambda url, result: sent.append(result))
    return sent


@pytest.fixture
def sts(monkeypatch):
    sts_client = mock.MagicMock()
    sts_client.get_caller_identity.return_value = {"Arn": CALLER_ARN}
    real_client = lambda_worker.boto3.client

    def fake_client(service, *args, **kwargs):
        if service == "sts":
            return sts_client
        return real_client(service, *args, **kwargs)

    monkeypatch.setattr(lambda_worker.boto3, "client", fake_client)
    return sts_client


def _list_subscriptions(approved_for_listing=(), approved_for_request=()):
    def list_subscriptions(**kwargs):
        if "subscriptionRequestIdentifier" in kwargs:
            return {"items": list(approved_for_request)}
        return {"items": list(approved_for_listing)}

    return list_subscriptions


def test_existing_pending_request_not_approved_is_not_reported_as_success(monkeypatch, notified):
    dz = _datazone()
    dz.list_subscriptions.side_effect = _list_subscriptions()
    dz.list_subscription_requests.return_value = {"items": [{"id": PENDING_REQUEST_ID}]}
    monkeypatch.setattr(lambda_worker, "datazone", dz)

    result = lambda_worker.process_subscription(_payload())

    assert result["status"] != "SUCCESS"
    assert notified[-1]["status"] != "SUCCESS"
    assert PENDING_REQUEST_ID in notified[-1]["message"]
    dz.create_subscription_request.assert_not_called()


def test_existing_pending_request_already_approved_is_reported_as_success(monkeypatch, notified):
    dz = _datazone()
    dz.list_subscriptions.side_effect = _list_subscriptions(
        approved_for_request=[{"id": "subscription-0001"}]
    )
    dz.list_subscription_requests.return_value = {"items": [{"id": PENDING_REQUEST_ID}]}
    monkeypatch.setattr(lambda_worker, "datazone", dz)

    result = lambda_worker.process_subscription(_payload())

    assert result["status"] == "SUCCESS"
    assert notified[-1]["details"]["subscription_id"] == "subscription-0001"


def test_existing_approved_subscription_is_reported_as_success(monkeypatch, notified):
    dz = _datazone()
    dz.list_subscriptions.side_effect = _list_subscriptions(
        approved_for_listing=[{"id": "subscription-0001", "subscriptionRequestId": "request-0001"}]
    )
    monkeypatch.setattr(lambda_worker, "datazone", dz)

    result = lambda_worker.process_subscription(_payload())

    assert result["status"] == "SUCCESS"
    assert notified[-1]["details"]["existing_kind"] == "SUBSCRIPTION"


def _access_denied(operation):
    return ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        operation,
    )


def test_access_denied_reports_operation_code_caller_and_ids(monkeypatch, notified, sts):
    dz = _datazone()
    dz.list_subscriptions.side_effect = _list_subscriptions()
    dz.list_subscription_requests.return_value = {"items": []}
    dz.create_subscription_request.side_effect = _access_denied("CreateSubscriptionRequest")
    monkeypatch.setattr(lambda_worker, "datazone", dz)

    with pytest.raises(ClientError):
        lambda_worker.process_subscription(_payload())

    error = notified[-1]["details"]["error"]
    assert notified[-1]["status"] == "FAILURE"
    assert error["aws_error_code"] == "AccessDeniedException"
    assert error["operation"] == "CreateSubscriptionRequest"
    assert error["caller_arn"] == CALLER_ARN
    assert error["domain_id"] == DOMAIN_ID
    assert error["target_project_id"] == TARGET_PROJECT_ID
    assert error["owning_project_id"] == OWNING_PROJECT_ID
    assert error["listing_id"] == LISTING_ID
    assert "CreateSubscriptionRequest" in notified[-1]["message"]


def test_caller_identity_failure_does_not_mask_the_original_error(monkeypatch, notified, sts):
    sts.get_caller_identity.side_effect = RuntimeError("sts unreachable")
    dz = _datazone()
    dz.search_listings.side_effect = _access_denied("SearchListings")
    monkeypatch.setattr(lambda_worker, "datazone", dz)

    with pytest.raises(ClientError):
        lambda_worker.process_subscription(_payload())

    error = notified[-1]["details"]["error"]
    assert error["operation"] == "SearchListings"
    assert error["aws_error_code"] == "AccessDeniedException"
    assert error.get("caller_arn") is None
