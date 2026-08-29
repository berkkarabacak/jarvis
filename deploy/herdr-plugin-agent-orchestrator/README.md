# Herdr plugin: Agent Orchestrator

Skeleton plugin so a Herdr session can fire orchestrator jobs.

## Config

In the plugin config directory (see Herdr docs):

```env
ORCH_URL=https://berkkarabacak.com/agent-orchestrator
ORCH_API_KEY=your-api-secret
```

## Link

```bash
herdr plugin link ./deploy/herdr-plugin-agent-orchestrator
```

## Action: run-job

```bash
curl -sS -X POST "$ORCH_URL/api/jobs/$JOB_ID/run" \
  -H "X-Api-Key: $ORCH_API_KEY" \
  -H "Idempotency-Key: herdr-$(date +%s)"
```

Replace `$JOB_ID` with a job that has `"runner": "herdr"` or `"runner": "llm"`.
