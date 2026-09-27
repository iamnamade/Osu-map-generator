Role: Application Security & Systems Reliability Engineer.
Task: Perform a security and resource lifecycle audit on the local API and runner. Do not write or edit production code.

Investigate:
1. Endpoint & Input Security:
   - Audit `tools/local_api/`: Are file uploads strictly validated for MIME type, magic bytes, and size limits?
   - Are there Path Traversal or Arbitrary File Overwrite risks during workspace creation or zip extraction?
2. Resource Exhaustion & Timeouts:
   - Are there execution timeouts and memory limits on heavy stages (audio analysis, candidate evolution)?
3. Workspace Cleanup & Concurrency:
   - How is `.tmp-e2e-generation/` managed? Is there automated garbage collection for stale runs, or do temp files leak disk storage?
   - Does concurrent job processing cause workspace collision or race conditions?

Output Requirement:
Save the complete diagnostic report with code references directly to `audit_reports/phase_4_security_api.md`.
Also print a brief terminal summary and end with: "Phase 4 Complete. Saved to audit_reports/phase_4_security_api.md. Ready for Phase 5."