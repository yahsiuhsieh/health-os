# HealthOS

HealthOS is a Python-first personal health data pipeline:

1. Poll Google Health API on a cloud schedule.
2. Store only necessary raw/session records and daily rollups in Supabase.
3. Generate a short AI health coach email twice per day.
4. Keep Google Health / Fitbit as the UI.

No frontend, no webhook server, and no stored AI summary history are included in v1.

## Architecture

- Google Cloud project: OAuth client plus Google Health API and Gmail API access.
- Cloud runner: GitHub Actions scheduled workflows.
- Database: Supabase Postgres free tier.
- AI: provider adapter. The default is OpenRouter with `openrouter/free`; OpenAI is optional. AI returns a structured coach draft, not final HTML.
- Notification: Gmail API multipart email with an HTML report and plain text fallback.

## Setup

### 1. Create the Supabase tables

Run these migrations in the Supabase SQL editor:

```text
migrations/001_initial_schema.sql
migrations/002_email_ai_metadata.sql
```

Use the service role key for the scheduled job. Do not expose it in a frontend.

### 2. Configure Google OAuth

In your Google Cloud HealthOS project:

1. Enable Google Health API.
2. Enable Gmail API.
3. Configure the OAuth consent screen in testing mode.
4. Add your Google account as a test user.
5. Create an OAuth client.
6. Request these scopes for v1:
   - `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`
   - `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly`
   - `https://www.googleapis.com/auth/googlehealth.sleep.readonly`
   - `https://www.googleapis.com/auth/gmail.send`

To get a refresh token locally:

```bash
PYTHONPATH=src python -m healthos auth-local --redirect-uri http://127.0.0.1:8080/callback
```

Open the printed URL, approve access, and the command will print a refresh token.
Store that token in GitHub Actions Secrets as `GOOGLE_REFRESH_TOKEN`.

If you previously authorized HealthOS before Gmail sending existed, run `auth-local`
again and replace `GOOGLE_REFRESH_TOKEN`; the old refresh token does not include the
Gmail send scope.

HealthOS uses scoped access tokens from the same refresh token: Google Health calls
request only Health scopes, and Gmail send calls request only `gmail.send`.

### 3. Configure AI

For the personal MVP, the default provider is OpenRouter:

```text
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=openrouter/free
```

If OpenRouter is unavailable, rate limited, or returns unusable JSON, HealthOS falls
back to a rule-based draft so the daily job can still complete. To avoid external AI
calls entirely:

```text
AI_PROVIDER=rule_based
```

### 4. Configure email

HealthOS sends email through Gmail API:

```text
GMAIL_FROM_EMAIL=your-email@gmail.com
SUMMARY_RECIPIENT_EMAIL=your-email@gmail.com
```

### 5. Add GitHub Actions secrets

Add these secrets to the repository:

```text
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REFRESH_TOKEN
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
OPENROUTER_API_KEY
GMAIL_FROM_EMAIL
SUMMARY_RECIPIENT_EMAIL
```

Optional variables:

```text
AI_PROVIDER
OPENROUTER_MODEL
AI_MAX_OUTPUT_TOKENS
HEALTHOS_TIMEZONE
HEALTHOS_ACCOUNT_KEY
```

For local development, copy `.env.example` to `.env.local` and fill in your local
values. The CLI automatically loads `.env.local` and then `.env` before reading
settings. Existing shell environment variables take priority over file values.
Both `.env.local` and `.env` are ignored by git.

### 6. Run a local email test

```bash
PYTHONPATH=src AI_PROVIDER=rule_based python -m healthos run --mode morning --force
```

This sends a real Gmail API email, but uses the rule-based draft instead of calling an
external AI provider.

To test the default OpenRouter provider:

```bash
PYTHONPATH=src AI_PROVIDER=openrouter python -m healthos run --mode morning --force
```

### 7. Run tests

```bash
PYTHONPATH=src python -m unittest discover -s tests
PYTHONPATH=src python -m compileall src tests
```

## Commands

```bash
python -m healthos run --mode auto
python -m healthos run --mode morning
python -m healthos run --mode evening
python -m healthos sync --days 30
python -m healthos cleanup --raw-days 30
python -m healthos oauth-url --redirect-uri http://127.0.0.1:8080/callback
python -m healthos exchange-code --code CODE --redirect-uri http://127.0.0.1:8080/callback
python -m healthos auth-local --redirect-uri http://127.0.0.1:8080/callback
```

## Data philosophy

HealthOS stores daily rollups as the long-term product data. `health_records` is a
short-term raw debug buffer and should be cleaned with `healthos cleanup --raw-days 30`.
The cleanup command only deletes `health_records`; it does not delete
`daily_health_metrics`.

The email prompt receives daily metrics plus 7-day and 28-day baselines. It does not
send full `health_records.raw_json` payloads to the AI provider.

Daily reports use a fixed renderer instead of letting the AI produce the email layout.
The renderer shows top insight, key metrics, coach notes, and data quality. Sleep below
180 minutes is labeled as low-confidence data, and missing HRV/resting heart
rate/respiratory rate limits recovery confidence.

Optional Google Health data types can be missing on a given device/account. By default,
HealthOS skips a single unavailable data type and continues the run. Set
`HEALTHOS_STRICT_DATA_TYPES=true` if you want any data type failure to fail the job.

This project is not a medical device and does not provide diagnosis.
