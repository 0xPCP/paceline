# DigitalOcean Secret Restore Checklist

The checked-in `.do/app.yaml` intentionally omits encrypted secret values. Do
not add secret placeholders to that file: DigitalOcean App Platform treats them
as real values and can overwrite the live secrets when the spec is applied.

Set or verify these secrets in the DigitalOcean console before production
launch:

| Secret | Purpose |
|---|---|
| `DATABASE_URL` | Managed PostgreSQL connection string |
| `SECRET_KEY` | Flask session signing key |
| `RESEND_API_KEY` | Transactional email through Resend |
| `SPACES_ACCESS_KEY` | DigitalOcean Spaces media storage |
| `SPACES_SECRET_KEY` | DigitalOcean Spaces media storage |
| `GOOGLE_OAUTH_CLIENT_ID` | Google sign-in and registration |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google sign-in and registration |
| `STRIPE_SECRET_KEY` | Paceline Stripe platform key |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | Connect webhook signing secret |

Non-secret launch values that should also be checked:

| Variable | Expected |
|---|---|
| `COOKIE_SECURE` | `true` |
| `SUPERADMIN_EMAILS` | `phil@pcp.dev` |
| `EMAIL_PROVIDER` | `resend` |
| `MAIL_DEFAULT_SENDER` | `Paceline <noreply@paceline.club>` |
| `STRIPE_PLATFORM_FEE_CENTS` | `100` |
| `STRIPE_PUBLISHABLE_KEY` | Optional; only needed for future client-side Stripe flows |
| `SPACES_BUCKET` | `paceline-media` |
| `SPACES_REGION` | `nyc3` |
| `SPACES_ENDPOINT` | `https://nyc3.digitaloceanspaces.com` |

For public launch, remove `BETA_PASSWORD` or leave it only if the beta gate is
intentionally still enabled.
