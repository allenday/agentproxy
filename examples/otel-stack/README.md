# AgentProxy OTEL Stack Example

This directory contains a complete observability stack for AgentProxy using OpenTelemetry, Tempo, Prometheus, and Grafana.

## Quick Start

1. **Start the stack**:
   ```bash
   docker-compose up -d
   ```

2. **Enable telemetry in AgentProxy**:
   ```bash
   export AGENTPROXY_ENABLE_TELEMETRY=1
   export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
   export OTEL_SERVICE_NAME=agentproxy
   export OTEL_SERVICE_NAMESPACE=dev
   ```

3. **Run AgentProxy**:
   ```bash
   pa "Create a hello world script"
   ```

4. **View telemetry**:
   - Grafana: http://localhost:3000 (login: admin/admin)
   - Prometheus: http://localhost:9090
   - Tempo: http://localhost:3200

## Stack Components

### OTEL Collector (Port 4317, 4318, 8889)
- Receives telemetry from AgentProxy via OTLP
- Routes traces to Tempo
- Exports metrics to Prometheus

### Tempo (Port 3200)
- Stores distributed traces
- Provides trace search and visualization
- Linked from Grafana

### Prometheus (Port 9090)
- Scrapes metrics from OTEL Collector
- Time-series storage
- Query interface

### Grafana (Port 3000)
- Unified visualization dashboard
- Pre-configured datasources for Prometheus and Tempo
- Pre-loaded AgentProxy dashboard

## What You'll See

### Traces
- `pa.run_task` - Full task execution trace
  - `pa.reasoning_loop` - PA decision-making spans
    - `gemini.api.call` - Gemini API calls
  - `claude.subprocess` - Claude Code execution spans
  - `pa.function.*` - Function execution (verify, test, etc.)

### Metrics
- Task counts and durations
- PA decision distributions
- Verification pass/fail rates
- Active session counts
- API call latencies

## Configuration

All services are configured via YAML files in this directory:
- `docker-compose.yml` - Stack orchestration
- `otel-collector-config.yaml` - OTEL routing
- `tempo.yaml` - Trace storage
- `prometheus.yml` - Metric scraping
- `grafana/provisioning/` - Auto-configured datasources and dashboards

## Customization

### Change Retention
Edit `tempo.yaml`:
```yaml
compactor:
  compaction:
    block_retention: 24h  # Change from 1h to 24h
```

### Add More Metrics
Edit `prometheus.yml` to add scrape targets:
```yaml
scrape_configs:
  - job_name: 'my-app'
    static_configs:
      - targets: ['my-app:8080']
```

### Custom Dashboard
1. Create dashboard in Grafana UI
2. Export JSON
3. Save to `grafana/dashboards/my-dashboard.json`
4. Restart Grafana: `docker-compose restart grafana`

### Enable OTLP Authentication
For production or when exposing OTLP endpoints, add authentication to `otel-collector-config.yaml`:

```yaml
extensions:
  headers_setter:
    headers:
      - key: Authorization
        from_context: authorization

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        auth:
          authenticator: headers_setter

service:
  extensions: [headers_setter]
```

Then configure clients with authentication headers:
```bash
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer your-token-here"
```

## Troubleshooting

### No traces appearing
1. Check OTEL collector logs: `docker-compose logs otel-collector`
2. Verify endpoint: `echo $OTEL_EXPORTER_OTLP_ENDPOINT`
3. Verify telemetry enabled: `echo $AGENTPROXY_ENABLE_TELEMETRY`

### No metrics appearing
1. Check Prometheus targets: http://localhost:9090/targets
2. Check OTEL collector metrics endpoint: http://localhost:8889/metrics
3. Verify scrape config in `prometheus.yml`

### Grafana not connecting to datasources
1. Check datasource config: `cat grafana/provisioning/datasources/datasources.yaml`
2. Verify network connectivity: `docker-compose exec grafana ping prometheus`

## Stopping the Stack

```bash
# Stop but keep data
docker-compose down

# Stop and remove data
docker-compose down -v
```

## ⚠️ Security Warnings

**This configuration is for LOCAL DEVELOPMENT ONLY**. While basic security measures are in place, additional hardening is required for production use:

### Security Configuration Status

1. **TLS Communication** (`otel-collector-config.yaml`):
   - ✅ TLS enabled for collector-to-Tempo communication
   - ⚠️ Uses system certificates (adequate for local Docker network)
   - **For production**: Configure mTLS with custom certificates and certificate validation

2. **Grafana Authentication** (`docker-compose.yml`):
   - ✅ Basic authentication enabled (default: admin/admin)
   - ⚠️ Using default credentials
   - **For production**: Change default password, enable OAuth/LDAP/SAML, implement RBAC

3. **OTLP Endpoint Authentication**:
   - ⚠️ OTLP endpoints (ports 4317, 4318) are unauthenticated
   - Suitable for local development with trusted applications
   - **For production**: Configure OTEL collector authentication using headers or mTLS

4. **Container Security** (`docker-compose.yml`):
   - ✅ Tempo runs as non-root user
   - ✅ Using official images
   - **For production**: Pin image versions, scan for vulnerabilities, use minimal base images

5. **Network Isolation**:
   - ✅ Services run on isolated Docker bridge network
   - ⚠️ Ports exposed to localhost
   - **For production**: Use private networks, implement firewall rules, do not expose ports publicly

## Production Notes

This example stack provides basic security suitable for **local development**. For production deployment:

1. **Enhance TLS/SSL**:
   - Generate and configure custom TLS certificates for all services
   - Configure mTLS (mutual TLS) for service-to-service communication
   - Enable certificate validation and pinning
   - Use cert-manager or similar for certificate lifecycle management

2. **Strengthen Authentication & Authorization**:
   - Change Grafana default password immediately
   - Enable Grafana SSO (OAuth, LDAP, SAML)
   - Configure OTEL collector authentication (see "Enable OTLP Authentication" section)
   - Use API keys or OAuth tokens for service access
   - Implement role-based access control (RBAC)
   - Enable audit logging

3. **Use External Storage**:
   - Configure Tempo with S3/GCS backend
   - Use managed Prometheus or remote write

4. **Network Security**:
   - Use private networks or VPNs
   - Implement firewall rules and security groups
   - Do not expose ports publicly

5. **Scale Collectors**:
   - Run multiple OTEL collectors behind load balancer
   - Configure high availability

6. **Configure Retention**:
   - Adjust based on your data volume and compliance requirements

7. **Add Alerting**:
   - Configure Prometheus Alertmanager
   - Set up alerts for security and operational issues

8. **Monitor the Stack**:
   - Add health checks and monitoring for OTEL components
   - Implement audit logging

9. **Container Security**:
   - Run containers as non-root users
   - Use minimal base images
   - Regularly update images for security patches
   - Scan images for vulnerabilities

10. **Secrets Management**:
    - Use Docker secrets or external secrets managers
    - Never commit credentials to version control

## Further Reading

- [OpenTelemetry Docs](https://opentelemetry.io/docs/)
- [Tempo Docs](https://grafana.com/docs/tempo/latest/)
- [Prometheus Docs](https://prometheus.io/docs/)
- [Grafana Docs](https://grafana.com/docs/grafana/latest/)
