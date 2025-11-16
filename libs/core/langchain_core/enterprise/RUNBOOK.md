## LangChain Enterprise Operations Runbook

Operational procedures for managing LangChain enterprise deployments.

## Table of Contents

1. [System Health Monitoring](#system-health-monitoring)
2. [Incident Response](#incident-response)
3. [Common Issues](#common-issues)
4. [Maintenance Procedures](#maintenance-procedures)
5. [Disaster Recovery](#disaster-recovery)
6. [Performance Tuning](#performance-tuning)

---

## System Health Monitoring

### Key Metrics to Monitor

#### Application Health

```promql
# Request rate
rate(langchain_llm_requests_total[5m])

# Error rate
rate(langchain_llm_errors_total[5m]) / rate(langchain_llm_requests_total[5m])

# P95 latency
histogram_quantile(0.95, langchain_llm_latency_seconds_bucket)

# Active requests
langchain_active_requests
```

#### Cost Metrics

```promql
# Cost rate (USD/hour)
rate(langchain_llm_cost_usd_total[1h]) * 3600

# Cost by tenant
sum by (tenant_id) (langchain_llm_cost_usd_total)

# Token usage
rate(langchain_llm_tokens_total[5m])
```

#### Circuit Breaker Status

```bash
# Check circuit breaker state in logs
grep "circuit_breaker_opened" /var/log/langchain/app.log

# Circuit breaker metrics (if exposed)
langchain_circuit_breaker_state{name="openai_api"}
```

### Alerting Rules

#### Critical Alerts

```yaml
# High error rate
- alert: HighLLMErrorRate
  expr: rate(langchain_llm_errors_total[5m]) / rate(langchain_llm_requests_total[5m]) > 0.05
  for: 5m
  severity: critical
  annotations:
    summary: "LLM error rate above 5%"

# Circuit breaker open
- alert: CircuitBreakerOpen
  expr: langchain_circuit_breaker_state == 1  # OPEN state
  for: 2m
  severity: critical
  annotations:
    summary: "Circuit breaker {{ $labels.name }} is OPEN"

# Cost limit approaching
- alert: CostLimitApproaching
  expr: langchain_cost_utilization > 0.8
  for: 10m
  severity: warning
  annotations:
    summary: "Cost limit 80% utilized for tenant {{ $labels.tenant_id }}"
```

#### Warning Alerts

```yaml
# High latency
- alert: HighLLMLatency
  expr: histogram_quantile(0.95, langchain_llm_latency_seconds_bucket) > 5.0
  for: 10m
  severity: warning
  annotations:
    summary: "P95 latency above 5 seconds"

# PII detection rate spike
- alert: PIIDetectionSpike
  expr: rate(langchain_pii_detected_total[5m]) > 10
  for: 5m
  severity: warning
  annotations:
    summary: "Unusual PII detection rate"
```

---

## Incident Response

### Circuit Breaker Open

**Symptoms:**
- `CircuitBreakerError` exceptions in logs
- "Circuit breaker 'X' is OPEN" messages
- Requests failing fast

**Diagnosis:**

```bash
# Check circuit breaker logs
grep "circuit_breaker" /var/log/langchain/app.log | tail -100

# Check underlying service health
curl -I https://api.openai.com/v1/models
curl -I https://api.anthropic.com/v1/messages

# Check recent error patterns
grep "error" /var/log/langchain/app.log | tail -50
```

**Resolution:**

1. **Verify Underlying Service:**
   ```bash
   # Test API connectivity
   curl -X POST https://api.openai.com/v1/chat/completions \
     -H "Authorization: Bearer $OPENAI_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "test"}]}'
   ```

2. **Manual Circuit Reset (if service is healthy):**
   ```python
   from langchain_core.enterprise import CircuitBreaker

   circuit = CircuitBreaker("openai_api")
   circuit.reset()
   ```

3. **Temporary Workaround:**
   - Enable fallback to alternative provider
   - Serve cached responses if applicable
   - Enable degraded mode

### Cost Limit Exceeded

**Symptoms:**
- `CostLimitExceededError` exceptions
- "Cost limit exceeded" in logs

**Immediate Action:**

```python
from langchain_core.enterprise import CostTracker

tracker = CostTracker.get_instance()

# Check current usage
summary = tracker.get_summary(hours=24)
print(f"24h cost: ${summary.total_cost_usd:.2f}")
print(f"By model: {summary.cost_by_model}")

# Temporarily increase limit (if approved)
tracker.daily_limit_usd = 150.0
```

**Investigation:**

```bash
# Find top cost consumers
grep "cost_recorded" /var/log/langchain/app.log | \
  jq -r '[.tenant_id, .cost_usd] | @csv' | \
  awk -F, '{sums[$1]+=$2} END {for (i in sums) print i, sums[i]}' | \
  sort -k2 -rn | head -10

# Check for unusual activity
grep "llm_invocation" /var/log/langchain/app.log | \
  grep -E "tokens_used\":[0-9]{5,}" | \
  tail -20
```

**Resolution:**

1. Contact high-usage tenants
2. Adjust per-tenant limits
3. Implement usage alerts
4. Review and optimize prompts

### PII Leak Incident

**Symptoms:**
- PII detected in logs
- Compliance alert triggered
- Customer report

**Immediate Response:**

```bash
# STOP - Do not share logs externally
# Isolate affected logs
sudo cp /var/log/langchain/app.log /secure/incident-$(date +%Y%m%d-%H%M%S).log
sudo truncate -s 0 /var/log/langchain/app.log

# Notify security team
./scripts/notify-security.sh "PII leak detected"
```

**Investigation:**

```python
from langchain_core.enterprise import PIIDetector, AuditLogger

detector = PIIDetector()
audit = AuditLogger()

# Scan recent data
with open('/secure/incident.log') as f:
    for line in f:
        matches = detector.detect(line)
        if matches:
            # Log incident
            audit.log_gdpr_event(
                gdpr_action="data_breach",
                subject_id="unknown",
                metadata={"pii_types": [m.pii_type for m in matches]},
            )
```

**Remediation:**

1. Enable PII detection middleware globally
2. Audit all recent outputs
3. Notify affected users (GDPR requirement)
4. Update data handling procedures

### High Latency

**Symptoms:**
- P95 latency > 5 seconds
- User complaints about slow responses

**Diagnosis:**

```bash
# Check system resources
top
free -h
df -h

# Check database connections
netstat -an | grep :5432 | wc -l

# Check LLM API latency
curl -w "@curl-format.txt" -o /dev/null -s https://api.openai.com/v1/models
```

**Resolution:**

1. **Check Rate Limiting:**
   ```python
   from langchain_core.enterprise import RedisRateLimiter

   limiter = RedisRateLimiter(redis_url="redis://localhost:6379")
   usage = limiter.get_current_usage()
   print(f"Rate limiter: {usage}")
   ```

2. **Scale Resources:**
   ```bash
   # Horizontal scaling (Kubernetes)
   kubectl scale deployment langchain-api --replicas=10

   # Check autoscaling
   kubectl get hpa langchain-api
   ```

3. **Enable Caching:**
   ```python
   from langchain_core.caches import RedisCache

   cache = RedisCache(redis_url="redis://localhost:6379")
   llm.cache = cache
   ```

---

## Common Issues

### Issue: Redis Connection Failure

**Error:**
```
ConnectionError: Error connecting to Redis
```

**Fix:**

```bash
# Check Redis status
redis-cli ping

# Restart Redis
sudo systemctl restart redis

# Check connection string
echo $REDIS_URL

# Test connection
python -c "import redis; r = redis.from_url('$REDIS_URL'); print(r.ping())"
```

### Issue: Vault Authentication Failure

**Error:**
```
ValueError: Failed to authenticate with Vault
```

**Fix:**

```bash
# Check Vault status
vault status

# Verify token
vault token lookup

# Renew token
vault token renew

# Update application config
export VAULT_TOKEN=$(vault token create -ttl=24h -format=json | jq -r .auth.client_token)
```

### Issue: Metrics Not Appearing

**Diagnosis:**

```bash
# Check if Prometheus is scraping
curl http://localhost:8000/metrics

# Check Prometheus targets
# Open http://prometheus:9090/targets
```

**Fix:**

```python
from prometheus_client import start_http_server
from langchain_core.enterprise import MetricsCollector

# Ensure metrics server is started
start_http_server(8000)

metrics = MetricsCollector()
# Metrics should now be available
```

---

## Maintenance Procedures

### Secret Rotation

**Schedule:** Every 90 days

**Procedure:**

```python
from langchain_core.enterprise import SecretsManager

secrets = SecretsManager(provider="vault")

# Check rotation needed
if secrets.check_rotation_needed("openai/api_key", max_age_days=90):
    # Generate new key in OpenAI dashboard
    new_key = "sk-new-key-xxxxx"

    # Rotate secret
    secrets.rotate("openai/api_key", new_value=new_key)

    # Restart application to pick up new key
    # kubectl rollout restart deployment langchain-api
```

### Log Rotation

**Schedule:** Daily

```bash
# Configure logrotate
cat > /etc/logrotate.d/langchain <<EOF
/var/log/langchain/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 langchain langchain
    sharedscripts
    postrotate
        systemctl reload langchain-api
    endscript
}
EOF
```

### Database Cleanup

**Schedule:** Weekly

```python
from langchain_core.enterprise import CostTracker, AuditLogger
from datetime import datetime, timedelta

# Clean old cost entries (keep 90 days)
cutoff = datetime.utcnow() - timedelta(days=90)
tracker = CostTracker()
tracker._entries = [e for e in tracker._entries if e.timestamp > cutoff]

# Archive audit logs to S3/GCS
audit = AuditLogger()
# Implementation depends on your audit storage backend
```

---

## Disaster Recovery

### Backup Procedures

**What to Backup:**
- Application configuration
- Secrets (encrypted)
- Audit logs
- Cost tracking data
- Tenant configurations

**Backup Script:**

```bash
#!/bin/bash
# backup-langchain.sh

BACKUP_DIR="/backup/langchain/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Backup configuration
cp -r /etc/langchain "$BACKUP_DIR/config"

# Backup Redis data
redis-cli --rdb "$BACKUP_DIR/redis-dump.rdb"

# Backup audit logs
tar -czf "$BACKUP_DIR/audit-logs.tar.gz" /var/log/langchain/audit/

# Backup to S3
aws s3 sync "$BACKUP_DIR" "s3://backups/langchain/$(date +%Y%m%d)/"
```

### Recovery Procedures

**Scenario: Complete System Failure**

1. **Restore Infrastructure:**
   ```bash
   # Deploy from IaC
   terraform apply

   # Deploy application
   kubectl apply -f k8s/
   ```

2. **Restore Configuration:**
   ```bash
   aws s3 cp s3://backups/langchain/latest/config/ /etc/langchain/ --recursive
   ```

3. **Restore Data:**
   ```bash
   # Restore Redis
   redis-cli --rdb /path/to/redis-dump.rdb
   ```

4. **Verify:**
   ```bash
   # Health check
   curl http://localhost:8000/health

   # Check metrics
   curl http://localhost:8000/metrics
   ```

---

## Performance Tuning

### Rate Limiter Optimization

```python
from langchain_core.enterprise import RedisRateLimiter

# Adjust based on load
limiter = RedisRateLimiter(
    redis_url="redis://localhost:6379",
    requests_per_second=100,  # Increase for high load
    burst_size=200,  # 2x requests_per_second
)
```

### Circuit Breaker Tuning

```python
from langchain_core.enterprise import CircuitBreaker

circuit = CircuitBreaker(
    "api",
    failure_threshold=10,  # More tolerant
    timeout_seconds=30,  # Faster recovery
    half_open_max_calls=5,  # More test calls
)
```

### Cost Tracker Performance

```python
from langchain_core.enterprise import CostTracker

# Use periodic cleanup
tracker = CostTracker(daily_limit_usd=100.0)

# Cleanup old entries (keep last 7 days)
def cleanup_old_costs():
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=7)
    tracker._entries = [e for e in tracker._entries if e.timestamp > cutoff]

# Schedule cleanup every 24h
import schedule
schedule.every().day.at("02:00").do(cleanup_old_costs)
```

---

## Contact Information

**On-Call Escalation:**
1. Platform Team: platform-oncall@example.com
2. Security Team: security@example.com
3. Engineering Manager: eng-manager@example.com

**Emergency Procedures:**
- P1 incidents: Page on-call immediately
- P2 incidents: Create ticket, notify in Slack
- P3 incidents: Create ticket for next business day

**Documentation:**
- Internal Wiki: https://wiki.example.com/langchain
- Architecture Docs: https://docs.example.com/architecture
- API Docs: https://api.example.com/docs
