# Files Required — 2-Server Phase 1 Deployment
# ISRO Airflow HA — Phase 1 File Reference

> **Servers:**  
> `10.61.241.85` → MAIN server (build + image registry only)  
> `10.61.247.142` → HA server (all Airflow services)

---

## MAIN SERVER — `10.61.241.85`

```
/home/user/airflow/
└── docker-compose.yml          ← only 1 file needed
```

> No config folders needed. Registry and pgAdmin use standard images with no custom config.

---

### FILE 1 — `docker-compose.yml` (on MAIN server)

**Full path on server:** `/home/user/airflow/docker-compose.yml`  
**Source file in repo:** `isro-distributed/2server-main-compose.yml`

```yaml
# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — 2-SERVER SETUP
# SERVER: MAIN (10.61.241.85)
# Roles: Local Docker Registry (:5000), Registry UI (:5001), pgAdmin (:5050)
#
# This server does NOT run Airflow workloads.
# It is the build/image distribution server.
# ═══════════════════════════════════════════════════════════════════════════════

services:

  # ── Local Docker Registry (so HA server can pull images) ───────────────────
  registry:
    image: registry:2
    restart: always
    ports:
      - "5000:5000"
    volumes:
      - registry-data:/var/lib/registry

  registry-ui:
    image: joxit/docker-registry-ui:latest
    restart: always
    ports:
      - "5001:80"
    environment:
      - REGISTRY_URL=http://10.61.241.85:5000
      - REGISTRY_TITLE=ISRO Airflow Registry
      - DELETE_IMAGES=true

  # ── pgAdmin (DB management GUI — optional but useful) ──────────────────────
  pgadmin:
    image: dpage/pgadmin4:latest
    restart: always
    ports:
      - "5050:80"
    environment:
      - PGADMIN_DEFAULT_EMAIL=admin@isro.gov.in
      - PGADMIN_DEFAULT_PASSWORD=admin123
    volumes:
      - pgadmin-data:/var/lib/pgadmin

volumes:
  registry-data:
  pgadmin-data:
```

---

### FILE 2 — `Dockerfile` (on MAIN server — for building the Airflow image)

**Full path on server:** `/home/user/airflow/dockerfiles/Dockerfile`  
**Source file in repo:** `dockerfiles/Dockerfile`

> This file is used ONCE on MAIN server to build the custom Airflow image,
> which is then pushed to the local registry and pulled by the HA server.

```dockerfile
FROM apache/airflow:2.7.3
USER root
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
USER airflow
RUN pip install --no-cache-dir \
    requests \
    pandas \
    boto3 \
    apache-airflow-providers-amazon \
    apache-airflow-providers-celery
```

**Commands to build and push after placing this file:**

```bash
# On MAIN server (10.61.241.85)
cd /home/user/airflow
docker build -t airflow-ha:2.7.3 -f dockerfiles/Dockerfile .
docker tag airflow-ha:2.7.3 10.61.241.85:5000/airflow-ha:2.7.3
docker push 10.61.241.85:5000/airflow-ha:2.7.3
```

---
---

## HA SERVER — `10.61.247.142`

```
/home/user/airflow/
├── docker-compose.yml                  ← FILE 3
├── config/
│   └── airflow.cfg                     ← FILE 4
├── haproxy/
│   └── haproxy.cfg                     ← FILE 5  (renamed from haproxy-2server.cfg)
├── redis-config/
│   └── sentinel.conf                   ← FILE 6  (renamed from sentinel-2server.conf)
└── monitoring/
    └── prometheus.yml                  ← FILE 7
```

> `minio-data/` folder is auto-created by Docker when MinIO starts. No need to create it manually.

---

### FILE 3 — `docker-compose.yml` (on HA server)

**Full path on server:** `/home/user/airflow/docker-compose.yml`  
**Source file in repo:** `isro-distributed/2server-ha-compose.yml`

```yaml
# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — 2-SERVER SETUP
# SERVER: HA (10.61.247.142)
# Roles: ALL Airflow services on ONE server
# ═══════════════════════════════════════════════════════════════════════════════

x-airflow-common: &airflow-common
  image: airflow-ha:2.7.3
  environment: &airflow-env
    - AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@10.61.247.142:5432/airflow
    - AIRFLOW__CELERY__RESULT_BACKEND=db+postgresql://airflow:airflow@10.61.247.142:5432/airflow
    - AIRFLOW__CELERY__BROKER_URL=sentinel://10.61.247.142:26379/0
    - AIRFLOW__CELERY__BROKER_TRANSPORT_OPTIONS={"master_name":"mymaster","sentinel_kwargs":{"password":"redispassword"}}
    - AIRFLOW__CORE__EXECUTOR=CeleryExecutor
    - AIRFLOW__CORE__FERNET_KEY=46BKJoQYlPPOexq0OhDZnIlNepKFf87WFwLbfzqDDho=
    - AIRFLOW__WEBSERVER__SECRET_KEY=9a8b7c6d5e4f3g2h1i0j9k8l7m6n5o4p
    - AIRFLOW__WEBSERVER__WORKERS=2
    - AIRFLOW__LOGGING__REMOTE_LOGGING=True
    - AIRFLOW__LOGGING__REMOTE_LOG_CONN_ID=minio_s3_conn
    - AIRFLOW__LOGGING__REMOTE_BASE_LOG_FOLDER=s3://airflow-logs
  volumes:
    - dags-volume:/opt/airflow/dags
    - ./config/airflow.cfg:/opt/airflow/airflow.cfg

services:

  # ── etcd SINGLE NODE ─────────────────────────────────────────────────────────
  etcd1:
    image: quay.io/coreos/etcd:v3.5.12
    restart: always
    ports:
      - "2379:2379"
      - "2380:2380"
    environment:
      - ETCD_NAME=etcd1
      - ETCD_INITIAL_CLUSTER=etcd1=http://10.61.247.142:2380
      - ETCD_INITIAL_CLUSTER_STATE=new
      - ETCD_LISTEN_PEER_URLS=http://0.0.0.0:2380
      - ETCD_LISTEN_CLIENT_URLS=http://0.0.0.0:2379
      - ETCD_ADVERTISE_CLIENT_URLS=http://10.61.247.142:2379
      - ETCD_INITIAL_ADVERTISE_PEER_URLS=http://10.61.247.142:2380
      - ETCD_ALLOW_NONE_AUTHENTICATION=yes
    volumes:
      - etcd-data:/etcd-data

  # ── Postgres SINGLE NODE with Patroni ─────────────────────────────────────────
  fix-permissions:
    image: busybox
    user: root
    volumes:
      - pgdata1:/data1
      - pg-sockets:/run-postgresql
    command: sh -c "chown -R 1000:1000 /data1 /run-postgresql"

  pg-node1:
    image: ongres/patroni:latest
    restart: always
    ports:
      - "5433:5432"
      - "8008:8008"
    depends_on:
      fix-permissions:
        condition: service_completed_successfully
      etcd1:
        condition: service_started
    environment:
      PATRONI_NAME: pg-node1
      PATRONI_CONFIGURATION: |
        scope: airflow
        name: pg-node1
        etcd3:
          hosts: 10.61.247.142:2379
        bootstrap:
          method: initdb
          dcs:
            ttl: 30
            loop_wait: 10
            retry_timeout: 10
            maximum_lag_on_failover: 1048576
            postgresql:
              use_pg_rewind: true
              parameters:
                wal_level: replica
                hot_standby: "on"
                max_wal_senders: 10
                max_replication_slots: 10
                max_connections: 200
              pg_hba:
                - host replication replicator 0.0.0.0/0 md5
                - host all all 0.0.0.0/0 md5
                - local all all trust
        postgresql:
          listen: 0.0.0.0:5432
          connect_address: 10.61.247.142:5433
          data_dir: /data/db
          bin_dir: /usr/lib/postgresql/17.2/bin
          pgpass: /tmp/pgpass
          authentication:
            replication: {username: replicator, password: replicatorpassword}
            superuser: {username: airflow, password: airflow}
        restapi:
          listen: 0.0.0.0:8008
          connect_address: 10.61.247.142:8008
    command: patroni
    volumes:
      - pgdata1:/data
      - pg-sockets:/run/postgresql

  # ── HAProxy ──────────────────────────────────────────────────────────────────
  haproxy:
    image: haproxy:latest
    restart: always
    ports:
      - "5432:5432"
      - "7000:7000"
    volumes:
      - ./haproxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg
    depends_on:
      - pg-node1

  # ── Redis Primary ─────────────────────────────────────────────────────────────
  redis-primary:
    image: redis:7.0
    restart: always
    ports:
      - "6379:6379"
    command: redis-server --requirepass redispassword --save 60 1 --appendonly yes
    volumes:
      - redis-data:/data

  # ── Redis Sentinel (single, quorum=1) ─────────────────────────────────────────
  redis-sentinel1:
    image: redis:7.0
    restart: always
    ports:
      - "26379:26379"
    volumes:
      - ./redis-config/sentinel.conf:/etc/sentinel.conf
    command: redis-sentinel /etc/sentinel.conf
    depends_on:
      - redis-primary

  # ── MinIO ─────────────────────────────────────────────────────────────────────
  minio:
    image: minio/minio:latest
    restart: always
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin123
    volumes:
      - ./minio-data:/data
    command: server /data --console-address ':9001'

  minio-setup:
    image: minio/mc:latest
    depends_on:
      - minio
    entrypoint: >
      /bin/sh -c "sleep 5;
        mc alias set local http://minio:9000 minioadmin minioadmin123;
        mc mb local/airflow-logs --ignore-existing;
        mc anonymous set download local/airflow-logs;"

  # ── git-sync ──────────────────────────────────────────────────────────────────
  git-sync:
    image: registry.k8s.io/git-sync/git-sync:v4.2.1
    restart: always
    environment:
      - GITSYNC_REPO=https://github.com/nishtha-isro/my-airflow-dags.git
      - GITSYNC_BRANCH=main
      - GITSYNC_PERIOD=30s
      - GITSYNC_ROOT=/git
      - GITSYNC_DEST=dags
    volumes:
      - dags-volume:/git

  # ── Airflow Init (run ONCE) ────────────────────────────────────────────────────
  airflow-init:
    <<: *airflow-common
    command: >
      sh -c "until nc -z 10.61.247.142 5432; do echo 'Waiting for DB...'; sleep 3; done;
             airflow db migrate &&
             airflow users create --username admin --password admin
               --firstname Admin --lastname User --role Admin --email admin@isro.gov.in"
    depends_on:
      - haproxy

  # ── Webserver ─────────────────────────────────────────────────────────────────
  webserver:
    <<: *airflow-common
    restart: always
    ports:
      - "8085:8080"
    command: >
      sh -c "until nc -z 10.61.247.142 5432; do echo 'Waiting...'; sleep 2; done;
             airflow webserver"
    depends_on:
      - airflow-init
    healthcheck:
      test: ["CMD-SHELL", "[ -f /opt/airflow/airflow-webserver.pid ]"]
      interval: 30s
      timeout: 30s
      retries: 3

  # ── Scheduler 1 ───────────────────────────────────────────────────────────────
  scheduler:
    <<: *airflow-common
    restart: always
    command: >
      sh -c "until nc -z 10.61.247.142 5432; do echo 'Waiting...'; sleep 2; done;
             airflow scheduler"
    depends_on:
      - webserver

  # ── Scheduler 2 (Active-Active HA) ───────────────────────────────────────────
  scheduler2:
    <<: *airflow-common
    restart: always
    command: >
      sh -c "until nc -z 10.61.247.142 5432; do echo 'Waiting...'; sleep 2; done;
             airflow scheduler"
    depends_on:
      - webserver

  # ── Worker 1 ──────────────────────────────────────────────────────────────────
  worker:
    <<: *airflow-common
    restart: always
    environment:
      <<: *airflow-env
      AIRFLOW__CELERY__WORKER_CONCURRENCY: "4"
    command: >
      sh -c "until nc -z 10.61.247.142 5432; do echo 'Waiting...'; sleep 2; done;
             airflow celery worker -q default"

  # ── Worker 2 ──────────────────────────────────────────────────────────────────
  worker2:
    <<: *airflow-common
    restart: always
    environment:
      <<: *airflow-env
      AIRFLOW__CELERY__WORKER_CONCURRENCY: "4"
    command: >
      sh -c "until nc -z 10.61.247.142 5432; do echo 'Waiting...'; sleep 2; done;
             airflow celery worker -q default"

  # ── Flower ────────────────────────────────────────────────────────────────────
  flower:
    <<: *airflow-common
    restart: always
    ports:
      - "5557:5555"
    command: >
      sh -c "until nc -z 10.61.247.142 5432; do echo 'Waiting...'; sleep 2; done;
             airflow celery flower"
    depends_on:
      - redis-sentinel1

  # ── Prometheus ────────────────────────────────────────────────────────────────
  prometheus:
    image: prom/prometheus:latest
    restart: always
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml

  # ── Grafana ───────────────────────────────────────────────────────────────────
  grafana:
    image: grafana/grafana:latest
    restart: always
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin123
    volumes:
      - grafana-data:/var/lib/grafana

volumes:
  dags-volume:
  pgdata1:
  pg-sockets:
  redis-data:
  etcd-data:
  grafana-data:
```

---

### FILE 4 — `config/airflow.cfg` (on HA server)

**Full path on server:** `/home/user/airflow/config/airflow.cfg`  
**Source file in repo:** `config/airflow.cfg`

> This is a large file (995 lines). Below are the **critical lines** you must verify are correct.
> Copy the full file from the repo — the following sections were already updated:

**Key section to verify — `[celery]` (around line 464):**

```ini
[celery]
task_acks_late = True
worker_prefetch_multiplier = 1

# Phase 1 (2-server): single sentinel on HA server
broker_url = sentinel://10.61.247.142:26379/0
# Phase 2 (Month 1): uncomment and replace below
# broker_url = sentinel://10.61.247.142:26379/0;sentinel://10.61.247.143:26379/0
broker_transport_options = {"master_name": "mymaster", "sentinel_kwargs": {"password": "redispassword"}}

result_backend = db+postgresql://airflow:airflow@10.61.247.142:5432/airflow
```

**Key section to verify — `[core]` (top of file):**

```ini
[core]
dags_folder = /opt/airflow/dags
remote_logging = True
remote_log_conn_id = minio_s3_conn
remote_base_log_folder = s3://airflow-logs
executor = CeleryExecutor
```

> ⚠️ The compose file sets most settings via environment variables which override `airflow.cfg`.
> The cfg file acts as a fallback. The two lines above (broker_url, result_backend) are the critical ones.

---

### FILE 5 — `haproxy/haproxy.cfg` (on HA server)

**Full path on server:** `/home/user/airflow/haproxy/haproxy.cfg`  
**Source file in repo:** `haproxy/haproxy-2server.cfg`  
**⚠️ Rename to `haproxy.cfg` when copying to server**

```
# haproxy.cfg
# Phase 1: Single PostgreSQL backend (pg-node1 on same server)
# Phase 2: Add pg-node2 when server 3 arrives
# Phase 3: Add pg-node3 when server 4 arrives

global
    maxconn 200

defaults
    log global
    mode tcp
    retries 2
    timeout client 30m
    timeout connect 4s
    timeout server 30m
    timeout check 5s

# ── Stats dashboard ──────────────────────────────────────────
listen stats
    mode http
    bind *:7000
    stats enable
    stats uri /
    stats refresh 5s
    stats show-legends

# ── PostgreSQL entry point ────────────────────────────────────
# Patroni REST API on port 8008 returns 200 only for the leader.
# HAProxy uses this health check — always routes to the active primary.
listen postgres_primary
    bind *:5432
    option httpchk OPTIONS /master
    http-check expect status 200
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions

    # Phase 1: Only pg-node1 (port 5433 = Patroni native port)
    server pg1 10.61.247.142:5433 maxconn 100 check port 8008

    # Phase 2 (Month 1): Uncomment when server 3 arrives (replace XXX with real IP)
    # server pg2 10.61.247.XXX:5432 maxconn 100 check port 8008

    # Phase 3 (Month 2): Uncomment when server 4 arrives (replace YYY with real IP)
    # server pg3 10.61.247.YYY:5432 maxconn 100 check port 8008
```

---

### FILE 6 — `redis-config/sentinel.conf` (on HA server)

**Full path on server:** `/home/user/airflow/redis-config/sentinel.conf`  
**Source file in repo:** `redis-config/sentinel-2server.conf`  
**⚠️ Rename to `sentinel.conf` when copying to server**

```
# sentinel.conf
# Phase 1: Single sentinel (quorum=1)
# redis-primary is on the same Docker network — use Docker service name
# When server 3 arrives: add sentinel2 there with quorum=2
# When server 4 arrives: add sentinel3 there with quorum=2

sentinel resolve-hostnames yes
sentinel announce-hostnames yes

# quorum=1 means 1 sentinel must agree to trigger failover
sentinel monitor mymaster redis-primary 6379 1

sentinel auth-pass mymaster redispassword
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 10000
sentinel parallel-syncs mymaster 1
```

---

### FILE 7 — `monitoring/prometheus.yml` (on HA server)

**Full path on server:** `/home/user/airflow/monitoring/prometheus.yml`  
**Source file in repo:** `monitoring/prometheus.yml`

```yaml
# prometheus.yml
# Phase 1 (2-server): scraping Airflow, Flower, HAProxy.
# All services are on the same Docker network — service names resolve correctly.

global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # Airflow built-in metrics endpoint
  - job_name: 'airflow'
    static_configs:
      - targets: ['webserver:8080']
    metrics_path: '/metrics'

  # Flower (Celery task monitor)
  - job_name: 'flower'
    static_configs:
      - targets: ['flower:5555']

  # HAProxy stats
  - job_name: 'haproxy'
    static_configs:
      - targets: ['haproxy:7000']

  # Phase 2 (Month 1): add redis-exporter and postgres-exporter sidecars
  # - job_name: 'redis'
  #   static_configs:
  #     - targets: ['redis-exporter:9121']
  # - job_name: 'postgres'
  #   static_configs:
  #     - targets: ['postgres-exporter:9187']
```

---

## One-Command SCP to Transfer All Files

Run these commands **from your Windows development machine** to push all files to both servers:

```bash
# ── MAIN server (10.61.241.85) ───────────────────────────────────────────────
scp isro-distributed/2server-main-compose.yml   user@10.61.241.85:/home/user/airflow/docker-compose.yml
scp dockerfiles/Dockerfile                       user@10.61.241.85:/home/user/airflow/dockerfiles/Dockerfile

# ── HA server (10.61.247.142) ────────────────────────────────────────────────
scp isro-distributed/2server-ha-compose.yml      user@10.61.247.142:/home/user/airflow/docker-compose.yml
scp config/airflow.cfg                           user@10.61.247.142:/home/user/airflow/config/airflow.cfg
scp haproxy/haproxy-2server.cfg                  user@10.61.247.142:/home/user/airflow/haproxy/haproxy.cfg
scp redis-config/sentinel-2server.conf           user@10.61.247.142:/home/user/airflow/redis-config/sentinel.conf
scp monitoring/prometheus.yml                    user@10.61.247.142:/home/user/airflow/monitoring/prometheus.yml
```

---

## Quick Summary Table

| # | File on Server | Renamed From (repo) | Server |
|---|---------------|---------------------|--------|
| 1 | `docker-compose.yml` | `2server-main-compose.yml` | MAIN (85) |
| 2 | `dockerfiles/Dockerfile` | `dockerfiles/Dockerfile` | MAIN (85) |
| 3 | `docker-compose.yml` | `2server-ha-compose.yml` | HA (142) |
| 4 | `config/airflow.cfg` | `config/airflow.cfg` | HA (142) |
| 5 | `haproxy/haproxy.cfg` | `haproxy/haproxy-2server.cfg` | HA (142) |
| 6 | `redis-config/sentinel.conf` | `redis-config/sentinel-2server.conf` | HA (142) |
| 7 | `monitoring/prometheus.yml` | `monitoring/prometheus.yml` | HA (142) |

> **Total: 2 files on MAIN server, 5 files on HA server.**  
> All Docker images are pulled automatically — no manual image installation needed.

---

## Docker daemon.json — Required on HA Server

Before pulling the image from MAIN server's insecure registry, add this on HA server:

**File:** `/etc/docker/daemon.json`

```json
{
  "insecure-registries": ["10.61.241.85:5000"]
}
```

Then restart Docker:
```bash
sudo systemctl restart docker
```

Pull and tag the image:
```bash
docker pull 10.61.241.85:5000/airflow-ha:2.7.3
docker tag  10.61.241.85:5000/airflow-ha:2.7.3 airflow-ha:2.7.3
```
