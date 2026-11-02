# Security review: `dump.rdb` committed to Git

- **What:** a Redis RDB snapshot (301 bytes) was committed in `00c7008` by mistake (Redis was started from the repository directory and the snapshot was staged by `git add -A`). Present on the pushed branch `claude/peaceful-mendel-j30y5u`; never on `main`.
- **Assessment (contents not reproduced here):** Redis metadata plus two rate-limit buckets keyed by synthetic test-user UUIDs. No tokens, passwords, API keys or credential-shaped strings found in the snapshot or via a credential-pattern scan of the full Git history.
- **Severity:** low (synthetic local data), but the file class (state dumps) is high-risk if repeated.
- **Remediation:** untracked and deleted in the working tree; `*.rdb`, `*.aof`, `appendonlydir/`, `*.pid`, `*.sqlite*` added to `.gitignore`; local Redis now runs with `--dir` outside the repo and persistence disabled.
- **History:** NOT rewritten (no authorization; no credential exposure to justify it). The file remains in history at `00c7008` and contains only synthetic UUID-keyed counters. If you want it purged anyway, that needs a coordinated force-push of the branch.
- **Credentials to rotate:** none identified.
- **Scanner:** `.secrets.baseline` holds only 10 reviewed placeholders (local-dev DB passwords, CI service password, fake log-redaction test strings). Verified that a planted AWS-style key and a GitHub-token-style string make `detect-secrets-hook` fail with the baseline applied.
