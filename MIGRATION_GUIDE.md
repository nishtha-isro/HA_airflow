# Airflow Migration Guide: v1.5 (Single Node) → v2.7 (HA Multi-Node)

> **Context:** This guide explains the differences between the old ISRO deployment (Airflow 1.5 Celery,
> single Redis, host Postgres) and the new HA architecture (Airflow 2.7, Patroni PostgreSQL cluster,
> Redis Sentinel, etcd, HAProxy, MinIO).

---

## 1. Side-by-Side Architecture Comparison

| Component | OLD (Airflow 1.5) | NEW (Airflow 2.7 HA) | Why Changed |
|---|---|---|---|
| **Airflow Version** | `1.5.x` (puckel image) | `2.7.3` (apache/airflow) | Bug fixes, security, API stability |
| **Database** | External `host.docker.internal:5432` (bare Postgres on host) | 3x Patroni nodes behind HAProxy | **True DB HA** — auto failover if DB dies |
| **DB Config Key** | `AIRFLOW__CORE__SQL_ALCHEMY_CONN` | `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` | Config key namespace changed in v2.x |
| **Redis** | Single Redis `redis:5.0.5` (no HA) | Redis Primary + 2 Replicas + 3 Sentinels | **Broker HA** — auto failover if Redis dies |
| **Redis Version** | `5.0.5` | `7.0` | Stability, Sentinel improvements |
| **Broker URL** | `redis://redis:6379/0` (simple) | `sentinel://...:26379` (Sentinel URL) | Celery connects to Sentinel, not Redis directly |
| **Images** | `localhost/tutorial2-*` (4 separate images) | Single `apache/airflow:2.7.3` custom build | One image for all roles (role set via `command:`) |
| **Scheduler** | 1 scheduler | 2 schedulers (active-active) | Scheduler HA added in Airflow 2.x |
| **Workers** | 1 worker | 3 workers | More parallelism |
| **Logging** | Local files on container | MinIO (S3-compatible) remote logging | Central log store accessible from all nodes |
| **DAGs** | `./dags` volume mount | git-sync (auto-pull from GitHub) | Keeps all workers in sync automatically |
| **Monitoring** | None | Prometheus + Grafana + Flower | Observability |

---

## 2. Critical Config Key Renames (Airflow 1.x → 2.x)

This is the most common breakage when migrating. **These keys MUST be updated.**

```ini
# ❌ OLD (Airflow 1.x) — Will not work in Airflow 2.x
AIRFLOW__CORE__SQL_ALCHEMY_CONN = ...
AIRFLOW__CORE__FERNET_KEY       = ...

# ✅ NEW (Airflow 2.x) — Correct namespaces
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN = ...
AIRFLOW__CORE__FERNET_KEY           = ...   ← this one stayed in [core]
```

| Old Key | New Key | Section |
|---|---|---|
| `AIRFLOW__CORE__SQL_ALCHEMY_CONN` | `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` | `[database]` |
| `AIRFLOW__CORE__RESULT_BACKEND` | `AIRFLOW__CELERY__RESULT_BACKEND` | `[celery]` |
| `AIRFLOW__CORE__BROKER_URL` | `AIRFLOW__CELERY__BROKER_URL` | `[celery]` |

---

## 3. Redis Broker URL Change (Simple → Sentinel)

### OLD (no HA): Direct Redis connection
```yaml
- AIRFLOW__CELERY__BROKER_URL=redis://redis:6379/0
```
- Simple, but if the Redis container dies → **all task queuing stops**.

### NEW (HA): Celery connects to all 3 Sentinels
```yaml
- AIRFLOW__CELERY__BROKER_URL=sentinel://redis-sentinel1:26379/0;sentinel://redis-sentinel2:26379/0;sentinel://redis-sentinel3:26379/0
- AIRFLOW__CELERY__BROKER_TRANSPORT_OPTIONS={"master_name":"mymaster","sentinel_kwargs":{"password":"redispassword"}}
```
- Celery asks Sentinels "who is the current Redis master?" before sending tasks.
- If Redis primary dies → Sentinels elect a new master → Celery reconnects automatically.

---

## 4. Database Connection Change (Host Postgres → Patroni + HAProxy)

### OLD: Connecting to Postgres running on the host machine
```yaml
- AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@host.docker.internal:5432/airflow
```
- `host.docker.internal` is a Docker-for-Desktop shortcut to reach the host OS.
- This Postgres has **no replication, no failover** — single point of failure.

### NEW: Connecting through HAProxy (which knows the current DB leader)
```yaml
- AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@haproxy/airflow
```
- HAProxy continuously health-checks all 3 Patroni nodes via their REST API (port 8008).
- It routes traffic only to the current **leader** node.
- If the leader crashes → Patroni elects a new leader via etcd → HAProxy detects it and reroutes.

---

## 5. Image Change: 4 Separate Images → 1 Unified Image

### OLD: You built 4 separate images (one per role)
```yaml
webserver:  image: localhost/tutorial2-webserver
flower:     image: localhost/tutorial2-flower
scheduler:  image: localhost/tutorial2-scheduler
worker:     image: localhost/tutorial2-worker
```
These were separate images from the `puckel/docker-airflow` era.

### NEW: One image, different `command:`
```yaml
# In new docker-compose.yml (Dockerfile builds ONE image)
webserver:
  build:
    dockerfile: dockerfiles/Dockerfile   # → apache/airflow:2.7.3 + pip packages
  command: airflow webserver

scheduler:
  build:
    dockerfile: dockerfiles/Dockerfile   # Same image
  command: airflow scheduler

worker:
  build:
    dockerfile: dockerfiles/Dockerfile   # Same image
  command: airflow celery worker
```
The same Docker image handles all roles — only the `command:` changes.

---

## 6. How to Run the NEW docker-compose.yml on ISRO Servers

### Step 1: Transfer the image tar to all servers
```bash
# On main server 10.61.241.85 — Save the built image
docker save <image_name> -o airflow-27-ha.tar

# Transfer to all three servers via scp
scp airflow-27-ha.tar user@10.61.247.142:/home/user/
scp airflow-27-ha.tar user@10.61.247.143:/home/user/
scp airflow-27-ha.tar user@10.61.247.144:/home/user/
```

### Step 2: Load the image on each server
```bash
# Run this on 10.61.247.142, 10.61.247.143, 10.61.247.144
docker load -i airflow-27-ha.tar

# Verify it's loaded
docker images
# You should see: final_airflow_multinode_celery-webserver   latest   ...
```

### Step 3: Update docker-compose.yml to use loaded image (not `build:`)
In the new docker-compose.yml, replace the `build:` section with `image:` pointing to the loaded image name:

```yaml
# BEFORE (builds from Dockerfile — needs source code)
webserver:
  build:
    context: .
    dockerfile: dockerfiles/Dockerfile

# AFTER (uses pre-loaded image from tar — use this on ISRO servers)
webserver:
  image: final_airflow_multinode_celery-webserver  # ← name from `docker images`
```

### Step 4: Copy required config files to each server
```bash
# These files must exist at the same relative path on every server
./config/airflow.cfg
./redis-config/sentinel.conf
./haproxy/haproxy.cfg
./dags/          (if not using git-sync)
```

### Step 5: Start the stack
```bash
# On the server where you copied the docker-compose.yml
docker compose up -d
```

---

## 7. Startup Order (CRITICAL)

The new HA stack has strict dependency ordering. Start in this sequence:

```
1. etcd cluster (all 3 nodes)         ← Patroni needs this first
        ↓
2. fix-permissions (one-shot job)      ← Sets pgdata folder permissions
        ↓
3. pg-node1/2/3 (Patroni Postgres)    ← One will become leader
        ↓
4. haproxy                             ← Routes to DB leader
        ↓
5. redis-primary + replicas + sentinels ← Message broker cluster
        ↓
6. minio + minio-setup                 ← Remote logging store
        ↓
7. git-sync                            ← Pull DAGs
        ↓
8. webserver → scheduler → worker      ← Airflow services
```

All `depends_on:` in the docker-compose.yml already enforce this order.

---

## 8. What Breaks If You Mix Old Config with New Image

| Old Config | New Image Behaviour |
|---|---|
| `AIRFLOW__CORE__SQL_ALCHEMY_CONN` | **Ignored silently** — DB connection fails at startup |
| `broker_url = redis://redis:6379/0` in `airflow.cfg` | Workers never receive tasks from queue |
| `command: webserver` (old puckel style) | ✅ Still works — Airflow 2.x CLI is compatible |
| `localhost/tutorial2-worker` image | Cannot use Airflow 2.7 features; may have Python/pip conflicts |

---

## 9. Quick Verification After Deployment

```bash
# 1. Check all containers are running
docker compose ps

# 2. Check Patroni elected a DB leader
docker exec -it <pg-node1-container> patronictl -c /etc/patroni/config.yml list

# 3. Check Redis Sentinel knows the master
docker exec -it <redis-sentinel1-container> redis-cli -p 26379 sentinel masters

# 4. Check Airflow webserver is healthy
curl http://10.61.247.142:8085/health

# 5. Check a worker is connected in Flower UI
open http://10.61.247.142:5557
```

---

## 10. Summary: What You Need to Do at ISRO

| Task | Action |
|---|---|
| Load tar image | `docker load -i airflow-27-ha.tar` on all 3 servers |
| Replace `build:` with `image:` | In docker-compose.yml, use loaded image name |
| Open firewall ports | `5432, 6379, 26379, 2379, 2380, 8008, 9000` between servers |
| Copy config files | `airflow.cfg`, `sentinel.conf`, `haproxy.cfg` to all servers |
| Start in correct order | etcd → patroni → haproxy → redis → minio → airflow |
| Verify HA | Kill pg-node1 → check if HAProxy routes to pg-node2 automatically |
