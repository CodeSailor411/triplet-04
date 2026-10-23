# Guardian action token

Guardian alone holds the Ed25519 private key and signs action authorization. Brain does not sign. Twin is expected to verify the signature, expiry, action intent, containment state, and its own caps before execution; that peer behavior still requires joint validation.

## Wire format and claims

The token keeps the `g1` wire layout:

`g1.<base64url(canonical UTF-8 JSON claims)>.<base64url(Ed25519 signature)>`

The signature input is the ASCII bytes `g1.<payload-segment>`. The canonical compact JSON claims bind `v`, `kid`, `token_id`, `iss`, `aud`, `run_id`, normalized `action`, `targets`, `params`, `idempotency_key`, `reading_ids`, `preview_id`, `iat`, `exp`, `trust_score`, and `risk_level`. The exact action intent is signed. Expiry is 60 simulated seconds after Twin time; the local wall clock is not substituted. Guardian refuses issue when the Twin clock cannot be discovered and parsed. `preview_id` is currently null because safe preview is not implemented; R3 and grid authorization are refused.

Verification binds action and parameters and can also bind targets and idempotency key. Token IDs are consumed once per in-process replay store. Deployments with multiple workers need a shared replay store before relying on one-time use across workers.

## Key setup

```powershell
New-Item -ItemType Directory -Force secrets | Out-Null
.\.venv\Scripts\python.exe .\src\generate_token_keys.py `
  --private .\secrets\guardian-ed25519-private.pem `
  --public .\secrets\guardian-ed25519-public.pem
$env:GUARDIAN_TOKEN_PRIVATE_KEY = (Join-Path (Get-Location) 'secrets\guardian-ed25519-private.pem')
$env:GUARDIAN_TOKEN_PUBLIC_KEY = (Join-Path (Get-Location) 'secrets\guardian-ed25519-public.pem')
$env:GUARDIAN_TOKEN_KID = 'partner-confirmed-key-id'
```

Never commit the private key. Guardian publishes the public PEM and key ID through capability output when configured. The key ID registration and Twin-side verifier remain **PROPOSED / NOT YET JOINTLY TESTED**.

Standalone verifier: `verify_token_example.py`.
