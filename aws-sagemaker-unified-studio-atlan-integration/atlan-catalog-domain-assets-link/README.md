# AWS SageMaker Unified Studio - Atlan Domain Linking Script

## Overview

When AWS SageMaker Unified Studio assets are cataloged into Atlan using the AWS SageMaker Unified Studio connector, the **Domain** information associated with Projects, Published Assets, and Subscribed Assets is captured as metadata. However, this domain information is not automatically linked to the corresponding **Data Domains** in Atlan's governance hierarchy.

This script bridges that gap by programmatically establishing the relationship between cataloged AWS SageMaker Unified Studio assets and their respective Atlan Data Domains.

## Why is this script needed?

The AWS SageMaker Unified Studio connector extracts domain metadata from your AWS environment and stores it as custom attributes on the cataloged assets. While this metadata is valuable, it exists as plain text and is not connected to Atlan's Data Domain governance structure.

**This script automates the following:**

1. **Discovers all Data Domains** defined in your Atlan instance
2. **Identifies AWS SageMaker Unified Studio Project assets** that contain domain information in their custom attributes
3. **Links each Project asset** to its corresponding Atlan Data Domain based on the domain name
4. **Propagates the domain linkage** to all Published Assets and Subscribed Assets associated with each Project

By running this script, you ensure that your AWS SageMaker Unified Studio assets are properly governed under the correct Data Domains in Atlan, enabling:

- Unified domain-based governance across your data catalog
- Streamlined data discovery within domain boundaries

---

## Prerequisites

### 1. Atlan API Key with Metadata Policy

The Atlan API Key used while running the AWS SageMaker Unified Studio connector **must be updated** to include a **metadata policy** that grants access to the AWS SageMaker Unified Studio connection assets.

Ensure the API key has the following permissions:
- **Read** access to AWS SageMaker Unified Studio connection assets
- **Write** access to update domain linkages on the cataloged assets
- **Read** access to Data Domains in your Atlan instance

### 2. Python Dependencies

Install the required Python packages:

```bash
pip install pyatlan requests
```

### 3. Environment Variables

Before running the script, set the following environment variables in your terminal:

| Variable | Description | Example |
|----------|-------------|---------|
| `ATLAN_BASE_URL` | The base URL of your Atlan instance | `https://xyz.atlan.com/` |
| `ATLAN_API_KEY` | The API key for authenticating with Atlan | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `SMUS_CONNECTION_QUALIFIED_NAME` | The qualified name of the AWS SageMaker Unified Studio connection. If not set, the script will process all AWS SageMaker Unified Studio connections. | `default/aws-smus/1765552936` |

**Setting environment variables:**

```bash
# Linux/macOS
export ATLAN_BASE_URL="https://your-tenant.atlan.com/"
export ATLAN_API_KEY="your-api-key-here"
export SMUS_CONNECTION_QUALIFIED_NAME="default/aws-smus/1234567890"
```

```powershell
# Windows PowerShell
$env:ATLAN_BASE_URL = "https://your-tenant.atlan.com/"
$env:ATLAN_API_KEY = "your-api-key-here"
$env:SMUS_CONNECTION_QUALIFIED_NAME = "default/aws-smus/1234567890"
```

---

## Usage

Once the prerequisites are in place, run the script:

```bash
python atlan-catalog-domain-assets-linking-script.py
```

### What the script does:

1. **Initializes the Atlan SDK client** using the provided credentials
2. **Fetches all Data Domains** from your Atlan instance and builds a lookup map
3. **Searches for AWS SageMaker Unified Studio Project assets** that have domain information in their custom attributes
4. **For each Project asset:**
   - Retrieves the domain name from custom attributes
   - Looks up the corresponding Atlan Data Domain GUID
   - Updates the Project asset with the domain linkage
   - Fetches all associated Published Assets and Subscribed Assets
   - Updates each associated asset with the same domain linkage
5. **Saves all updates** to Atlan in batches of 50 assets

### Sample Output:

```
SDK Client initialialized for tenant https://your-tenant.atlan.com/
Looking up Domains...
Domain info lookup complete. Found 5 Domain definitions!!
Looking up SMUS Assets...
SMUS Project Asset Name: DataProject1; GUID: abc123; QN: default/aws-smus/...; Domain: None
-> Accounting for Domain update on the Project asset...
-> Accounting for Domain update on the constituent Published/Subscribed assets ...
->-> Looking up 3 assets associated with the Project...
->->-> Asset Name: PublishedDataset1; Type: SageMakerUnifiedStudioPublishedAsset; GUID: def456; ...
Totally 4 to enrich...
Asset enrichment complete!!
```

---

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| `KeyError: 'domainUnitName'` | The Project asset does not have domain information in its custom attributes. Ensure the AWS SageMaker Unified Studio connector has successfully synced domain metadata. |
| `KeyError` when looking up domain | The domain name in the AWS SageMaker Unified Studio asset does not match any Data Domain in Atlan. Create the matching Data Domain in Atlan before running the script. |
| Authentication errors | Verify that `ATLAN_BASE_URL` and `ATLAN_API_KEY` are correctly set and the API key has the required permissions. |

---

## Notes

- This script performs **batch updates** in groups of 50 assets to optimize API performance
- The script only processes **active assets** (not archived or deleted assets)
- If `SMUS_CONNECTION_QUALIFIED_NAME` is not set, all AWS SageMaker Unified Studio connections will be processed
- Re-running the script is safe; it will update domain linkages idempotently

---

## License

This script is provided as part of the Atlan AWS Utilities repository.

