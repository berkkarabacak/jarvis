# Cloud Scheduler example

Daily run at 07:00 America/Los_Angeles:

```bash
gcloud scheduler jobs create http grok-automater-daily \
  --location=us-central1 \
  --schedule="0 7 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://YOUR_DOMAIN/api/jobs/JOB_UUID/run" \
  --http-method=POST \
  --headers="X-Api-Key=YOUR_API_SECRET,Idempotency-Key=JOB_UUID-$(date +%F),Content-Type=application/json" \
  --attempt-deadline=900s
```

Notes:
- Idempotency-Key should include the calendar date so retries the same day reuse the run.
- Scheduler cannot easily template the date in headers; use a fixed key pattern and rotate via a thin proxy, or omit and rely on careful schedule + short retry window.
- Prefer a Cloud Function/proxy that sets `Idempotency-Key: {job_id}-{YYYY-MM-DD}` if exact daily uniqueness is required.
