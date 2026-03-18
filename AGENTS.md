# AGENTS.md — Atlan AI Agent Guidelines

> **Applies To:** `atlan-aws-utilities`
> **Companion file:** See `CLAUDE.md` for the lean summary.

---

## Security

`atlan-aws-utilities` contains AWS infrastructure utility scripts.

### Security Contact
`#bu-security-and-it` on Slack.

---

### AWS Credential Handling

```bash
# ❌ Never commit AWS credentials
export AWS_ACCESS_KEY_ID=AKIA...

# ✅ Use IAM roles; verify at script start
aws sts get-caller-identity
```

**[MUST]** All scripts use IAM roles/instance profiles.

---

### General Invariants

- **[MUST]** No AWS credentials in source — IAM roles only.
- **[MUST]** S3 buckets: public access blocked, SSE enabled.
- **[SHOULD]** IAM policies scoped to specific resources and regions.
