# CLAUDE.md — Atlan AI Agent Guidelines

> **Applies To:** `atlan-aws-utilities`
> **Full security policy:** See `AGENTS.md`

---

## Security

`atlan-aws-utilities` contains AWS infrastructure utility scripts. Key surfaces: IAM role assumptions, S3 operations, credential handling.

### General Invariants
- **[MUST]** No AWS access keys or secrets committed — use IAM roles and instance profiles.
- **[MUST]** All S3 operations use server-side encryption. No public buckets.
- **[SHOULD]** Scripts verify assumed role with `aws sts get-caller-identity` at startup.
