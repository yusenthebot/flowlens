# FlowLens Deployment Guide

Complete instructions for deploying FlowLens in development and production environments.

## Quick Start

### Local Development with Docker Compose

The easiest way to get FlowLens running locally:

```bash
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
docker compose up --build -d
```

This starts:
- **FlowLens Server** on `http://localhost:8585`
- **Web Dashboard** at `http://localhost:8585/dashboard`

Check health: `curl http://localhost:8585/health`

Shut down: `docker compose down`

---

## Docker Deployment

### Building the Docker Image

The `Dockerfile` uses a multi-stage build for security and minimal image size:

```bash
# Build the image
docker build --target runtime -t flowlens:latest .

# Run with default settings
docker run --rm \
  --name flowlens-server \
  -p 8585:8585 \
  -v flowlens-data:/data \
  flowlens:latest
```

### Environment Variables

Control FlowLens behavior via environment variables:

```bash
docker run --rm \
  --name flowlens-server \
  -p 8585:8585 \
  -v flowlens-data:/data \
  -e FLOWLENS_DB_PATH=/data/flowlens.db \
  -e FLOWLENS_HOST=0.0.0.0 \
  -e FLOWLENS_PORT=8585 \
  -e FLOWLENS_LOG_LEVEL=INFO \
  -e FLOWLENS_CORS_ORIGINS="http://localhost:3000,https://myapp.com" \
  -e FLOWLENS_RATE_LIMIT=120 \
  flowlens:latest
```

### Docker Compose

For local development or small deployments, use `docker-compose.yml`:

```yaml
version: "3.9"
services:
  flowlens-server:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    ports:
      - "8585:8585"
    volumes:
      - flowlens-data:/data
    environment:
      FLOWLENS_DB_PATH: /data/flowlens.db
      FLOWLENS_HOST: "0.0.0.0"
      FLOWLENS_PORT: "8585"
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8585/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    restart: unless-stopped

volumes:
  flowlens-data:
    driver: local
```

Common commands:

```bash
# Start in background
docker compose up -d

# View logs
docker compose logs -f flowlens-server

# Stop containers
docker compose down

# Stop and remove data volume
docker compose down -v
```

---

## Manual Installation

### Prerequisites

- Python 3.10 or higher
- pip

### Installation Steps

1. **Clone the repository:**

```bash
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
```

2. **Create a virtual environment:**

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install FlowLens:**

```bash
pip install -e .
```

For development with tests and linting:

```bash
pip install -e ".[dev]"
```

4. **Verify installation:**

```bash
# Run tests
pytest tests/ -v

# Check that import works
python -c "from flowlens import FlowLens; print('FlowLens imported successfully')"
```

5. **Start the server:**

```bash
python -m uvicorn flowlens.server.app:create_app \
  --factory \
  --host 0.0.0.0 \
  --port 8585 \
  --reload
```

Access the dashboard at `http://localhost:8585/dashboard`

---

## Environment Variables Reference

All FlowLens settings are configured via environment variables with the `FLOWLENS_` prefix.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `FLOWLENS_DB_PATH` | string | `./flowlens.db` | Path to SQLite database file. In Docker, use `/data/flowlens.db` |
| `FLOWLENS_HOST` | string | `0.0.0.0` | Server listen address. Use `127.0.0.1` for localhost only |
| `FLOWLENS_PORT` | integer | `8585` | Server port (1-65535) |
| `FLOWLENS_LOG_LEVEL` | string | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `FLOWLENS_CORS_ORIGINS` | string | `*` | CORS origins (comma-separated). Set to specific origins in production |
| `FLOWLENS_RATE_LIMIT` | integer | `120` | Rate limit: requests per minute per IP address |

### Examples

```bash
# Production-like setup
export FLOWLENS_DB_PATH=/var/lib/flowlens/flowlens.db
export FLOWLENS_HOST=127.0.0.1
export FLOWLENS_PORT=8585
export FLOWLENS_LOG_LEVEL=INFO
export FLOWLENS_CORS_ORIGINS="https://myapp.com,https://api.myapp.com"
export FLOWLENS_RATE_LIMIT=100

# Development setup
export FLOWLENS_LOG_LEVEL=DEBUG
export FLOWLENS_CORS_ORIGINS="*"
export FLOWLENS_RATE_LIMIT=1000
```

---

## Production Checklist

### Security

- [ ] **CORS**: Set `FLOWLENS_CORS_ORIGINS` to specific trusted domains, not `*`
  ```bash
  export FLOWLENS_CORS_ORIGINS="https://app.example.com"
  ```

- [ ] **Database Permissions**: Restrict SQLite file permissions
  ```bash
  chmod 600 /data/flowlens.db
  chown flowlens:flowlens /data/flowlens.db
  ```

- [ ] **Non-root User**: Run container as non-root
  ```bash
  docker run -u flowlens:flowlens ...
  ```

- [ ] **HTTPS**: Always use HTTPS in production (via reverse proxy)

### Database

- [ ] **SQLite WAL Mode**: Enable Write-Ahead Logging for concurrent access
  ```python
  # Automatically enabled in server initialization
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  ```

- [ ] **Backup Strategy**: Regular backups of `/data/flowlens.db`
  ```bash
  # Daily backup
  cp /data/flowlens.db /backups/flowlens-$(date +%Y%m%d).db
  ```

- [ ] **Database Maintenance**: Periodic vacuum and analysis
  ```bash
  sqlite3 /data/flowlens.db "VACUUM; ANALYZE;"
  ```

### Performance

- [ ] **Rate Limiting**: Set appropriate `FLOWLENS_RATE_LIMIT` for your traffic
  - Default: 120 requests/min/IP (suitable for small deployments)
  - High-traffic: 500-1000 requests/min/IP

- [ ] **Log Level**: Use `INFO` or `WARNING` in production (not `DEBUG`)
  ```bash
  export FLOWLENS_LOG_LEVEL=INFO
  ```

- [ ] **Trace Retention**: Implement periodic cleanup of old traces
  ```bash
  # Delete traces older than 30 days via API
  curl -X POST http://localhost:8585/v1/traces/cleanup \
    -H "Content-Type: application/json" \
    -d '{"days_to_keep": 30}'
  ```

- [ ] **Database Indexing**: Indexes are automatically created on startup

### Monitoring

- [ ] **Health Check**: Monitor the `/health` endpoint
  ```bash
  curl http://localhost:8585/health
  # Returns: {"status": "ok"}
  ```

- [ ] **Metrics**: Track via `/v1/stats` endpoint
  ```bash
  curl http://localhost:8585/v1/stats
  # Returns: trace_count, error_rate, total_cost
  ```

- [ ] **Logging**: Capture server logs
  ```bash
  docker compose logs -f flowlens-server > /var/log/flowlens.log
  ```

### Deployment

- [ ] **Container Image**: Use specific version tags, not `latest`
  ```bash
  docker build -t flowlens:v0.4.0 .
  docker run -d -t flowlens:v0.4.0
  ```

- [ ] **Resource Limits**: Set Docker memory and CPU limits
  ```bash
  docker run -d \
    --memory 512m \
    --cpus 1.0 \
    flowlens:latest
  ```

- [ ] **Restart Policy**: Use appropriate restart behavior
  ```bash
  docker run -d \
    --restart unless-stopped \
    flowlens:latest
  ```

---

## Reverse Proxy Setup

### Nginx Configuration

For production HTTPS deployment with Nginx as reverse proxy:

```nginx
# /etc/nginx/sites-available/flowlens
upstream flowlens_backend {
    server localhost:8585;
    keepalive 32;
}

server {
    listen 80;
    server_name observability.example.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name observability.example.com;

    # SSL certificates (use Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/observability.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/observability.example.com/privkey.pem;

    # SSL best practices
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Logging
    access_log /var/log/nginx/flowlens.access.log;
    error_log /var/log/nginx/flowlens.error.log;

    # Root location
    location / {
        proxy_pass http://flowlens_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;

        # WebSocket support
        proxy_read_timeout 86400;
        proxy_buffering off;
    }

    # API endpoints
    location /v1/ {
        proxy_pass http://flowlens_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Rate limiting at Nginx level
        limit_req zone=api burst=20 nodelay;
    }

    # Health check endpoint (internal only)
    location /health {
        proxy_pass http://flowlens_backend;
        access_log off;
    }
}

# Rate limiting zones
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
```

Enable and test:

```bash
# Create symlink
sudo ln -s /etc/nginx/sites-available/flowlens /etc/nginx/sites-enabled/

# Test Nginx config
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

### Apache Configuration

For Apache with mod_proxy:

```apache
<VirtualHost *:443>
    ServerName observability.example.com

    # SSL configuration
    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/observability.example.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/observability.example.com/privkey.pem

    # Enable required modules
    <IfModule mod_proxy.c>
        ProxyPreserveHost On
        ProxyPass / http://localhost:8585/
        ProxyPassReverse / http://localhost:8585/
    </IfModule>

    <IfModule mod_rewrite.c>
        RewriteEngine On
        RewriteCond %{HTTP:Upgrade} websocket [NC]
        RewriteCond %{HTTP:Connection} upgrade [NC]
        RewriteRule ^/?(.*) "ws://localhost:8585/$1" [P,L]
    </IfModule>

    # Security headers
    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
</VirtualHost>

<VirtualHost *:80>
    ServerName observability.example.com
    Redirect permanent / https://observability.example.com/
</VirtualHost>
```

---

## Common Deployment Scenarios

### Scenario 1: Single Server (Small Team)

```bash
# Install on Ubuntu 22.04
sudo apt-get update
sudo apt-get install -y docker.io docker-compose python3

# Clone and start
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
docker compose up -d

# Backup database daily via cron
echo "0 2 * * * cp /var/lib/docker/volumes/flowlens_flowlens-data/_data/flowlens.db /backups/flowlens-\$(date +\%Y\%m\%d).db" | sudo crontab -
```

### Scenario 2: High Availability with Load Balancer

```bash
# Run multiple FlowLens instances
for i in {1..3}; do
  docker run -d \
    --name flowlens-$i \
    -p 858${i}:8585 \
    -v flowlens-data:/data \
    -e FLOWLENS_DB_PATH=/data/flowlens.db \
    flowlens:latest
done

# Use Nginx to load balance (see reverse proxy section above)
```

### Scenario 3: Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flowlens
spec:
  replicas: 2
  selector:
    matchLabels:
      app: flowlens
  template:
    metadata:
      labels:
        app: flowlens
    spec:
      containers:
      - name: flowlens
        image: flowlens:v0.4.0
        ports:
        - containerPort: 8585
        env:
        - name: FLOWLENS_DB_PATH
          value: /data/flowlens.db
        - name: FLOWLENS_CORS_ORIGINS
          valueFrom:
            configMapKeyRef:
              name: flowlens-config
              key: cors_origins
        volumeMounts:
        - name: data
          mountPath: /data
        livenessProbe:
          httpGet:
            path: /health
            port: 8585
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8585
          initialDelaySeconds: 5
          periodSeconds: 10
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: flowlens-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: flowlens-service
spec:
  selector:
    app: flowlens
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8585
  type: LoadBalancer
```

Deploy with:

```bash
kubectl apply -f flowlens-deployment.yaml
kubectl get service flowlens-service
```

---

## Troubleshooting Deployment

### Container won't start

**Check logs:**
```bash
docker compose logs flowlens-server
```

**Common issues:**
- Port already in use: `docker ps` and kill other containers
- Volume permissions: `docker exec flowlens-server ls -la /data`
- Bad environment variable: Check syntax of `FLOWLENS_*` vars

### Database locked

**SQLite WAL mode helps but:**
```bash
# Stop the server
docker compose down

# Repair database
sqlite3 /path/to/flowlens.db "PRAGMA integrity_check;"

# Restart
docker compose up -d
```

### High memory usage

**Reduce trace retention:**
```bash
# Keep only 7 days of traces
curl -X POST http://localhost:8585/v1/traces/cleanup \
  -H "Content-Type: application/json" \
  -d '{"days_to_keep": 7}'
```

### Slow API responses

**Check database:**
```bash
# Analyze and vacuum
sqlite3 /data/flowlens.db "ANALYZE; VACUUM;"

# Increase rate limit if it's limiting requests
export FLOWLENS_RATE_LIMIT=500
```

---

## Updating FlowLens

### Docker

```bash
# Pull latest changes
git pull origin main

# Rebuild image
docker build -t flowlens:latest .

# Stop old container
docker compose down

# Start new container
docker compose up -d

# Verify health
curl http://localhost:8585/health
```

### Manual Install

```bash
# Update source
git pull origin main

# Reinstall (preserves database)
pip install -e .

# Run migrations (if any — currently none needed)
# Restart server
```

---

## Performance Tuning

### Database Optimization

```python
# Applied automatically, but can be run manually:
import sqlite3

conn = sqlite3.connect('/data/flowlens.db')
conn.execute('PRAGMA journal_mode = WAL')
conn.execute('PRAGMA synchronous = NORMAL')
conn.execute('PRAGMA cache_size = -64000')  # 64MB cache
conn.execute('PRAGMA temp_store = MEMORY')
conn.execute('VACUUM')
conn.execute('ANALYZE')
conn.close()
```

### Server Configuration

- Increase worker processes for high concurrency
- Use a production ASGI server (Gunicorn + Uvicorn)

```bash
pip install gunicorn

gunicorn \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8585 \
  flowlens.server.app:create_app
```

---

## Backup and Recovery

### Automated Backups

```bash
#!/bin/bash
# backup-flowlens.sh
BACKUP_DIR="/backups/flowlens"
mkdir -p $BACKUP_DIR

# Daily backup
cp /data/flowlens.db $BACKUP_DIR/flowlens-$(date +%Y%m%d-%H%M%S).db

# Keep only last 30 days
find $BACKUP_DIR -name "flowlens-*.db" -mtime +30 -delete
```

Add to crontab:
```bash
0 2 * * * /path/to/backup-flowlens.sh
```

### Recovery

```bash
# Stop the server
docker compose down

# Restore from backup
cp /backups/flowlens/flowlens-20260314.db /data/flowlens.db

# Restart
docker compose up -d
```

---

## Support

For deployment issues:
- Check `docs/troubleshooting.md` for common problems
- Review server logs: `docker compose logs -f`
- Open an issue on GitHub with error messages and version info
