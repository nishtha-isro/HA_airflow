# ISRO Distributed HA Airflow — Deployment Guide

> **Cluster:** 3 servers running distributed Airflow 2.7.3 with HA PostgreSQL, Redis Sentinel, and etcd.

---

## Server Role Assignment

| Server IP | File | Key Roles |
|---|---|---|
| `10.61.241.85` | `main-server-compose.yml` | **Build server** — Local Docker Registry (:5000), Registry UI (:5001), pgAdmin (:5050) |
| `10.61.247.142` | `server1-compose.yml` | etcd1, pg-node1 (**DB leader**), HAProxy, Redis Primary, Sentinel1, Webserver, Scheduler, Flower, MinIO |
| `10.61.247.143` | `server2-compose.yml` | etcd2, pg-node2 (replica), Redis Replica1, Sentinel2, Scheduler2, Worker1, Worker2 |
| `10.61.247.144` | `server3-compose.yml` | etcd3, pg-node3 (replica), Redis Replica2, Sentinel3, Worker3, Prometheus, Grafana |

---

## Architecture Flow

```
                        ┌─────────────────────────────────┐
                        │   ALL AIRFLOW SERVICES connect  │
                        │   DB  →  10.61.247.142:5432     │  (HAProxy)
                        │   Broker → Sentinels on :26379  │
                        └─────────────────────────────────┘

  SERVER 1 (142)          SERVER 2 (143)          SERVER 3 (144)
  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
  │ etcd1       │◄───────►│ etcd2       │◄───────►│ etcd3       │  ← Patroni coordination
  │ pg-node1(L) │◄───────►│ pg-node2(R) │         │ pg-node3(R) │  ← L=Leader, R=Replica
  │ HAProxy:5432│         └─────────────┘         └─────────────┘
  │ redis-pri   │◄── replication ──────────────────────────────►│
  │ sentinel1   │         sentinel2                sentinel3      ← Sentinel quorum
  │ MinIO:9000  │                                               ← Central log store
  │ Webserver   │         Scheduler2               Worker3
  │ Scheduler   │         Worker1, Worker2         Prometheus
  │ Flower      │                                  Grafana
  └─────────────┘
```

---

## Step 1 — Copy Files to Each Server

From your main server `10.61.241.85`, copy these files to all 3 servers:

```bash
# Files needed on ALL 3 servers (same relative path)
./config/airflow.cfg
./redis-config/sentinel.conf        # ← MODIFY for Server 2 & 3 (see Step 3)
./monitoring/prometheus.yml         # Only needed on Server 3

# Files needed only on Server 1
./haproxy/haproxy.cfg               # ← MODIFY (see Step 2)
```

```bash
# SCP example (run from 10.61.241.85)
scp -r config/ user@10.61.247.142:/home/user/airflow/
scp -r redis-config/ user@10.61.247.142:/home/user/airflow/
scp -r haproxy/ user@10.61.247.142:/home/user/airflow/

scp -r config/ user@10.61.247.143:/home/user/airflow/
scp -r redis-config/ user@10.61.247.143:/home/user/airflow/

scp -r config/ user@10.61.247.144:/home/user/airflow/
scp -r redis-config/ user@10.61.247.144:/home/user/airflow/
scp -r monitoring/ user@10.61.247.144:/home/user/airflow/
```

---

## Step 2 — Update haproxy.cfg on Server 1

The existing `haproxy.cfg` uses Docker service names. Since pg-node2 and pg-node3 are now on **different physical servers**, replace with real IPs:

```
# haproxy/haproxy.cfg  (on Server 1 ONLY)
global
    maxconn 100

defaults
    log global
    mode tcp
    retries 2
    timeout client 30m
    timeout connect 4s
    timeout server 30m

listen stats
    mode http
    bind *:7000
    stats enable
    stats uri /

listen postgres_primary
    bind *:5432
    option httpchk OPTIONS /master
    server pg1 10.61.247.142:5432 maxconn 100 check port 8008
    server pg2 10.61.247.143:5432 maxconn 100 check port 8008
    server pg3 10.61.247.144:5432 maxconn 100 check port 8008
```

> **Why:** HAProxy checks port `8008` (Patroni REST API) on each pg-node.
> Patroni returns `200 OK` only on the current leader — so HAProxy always routes to the live primary.

---

## Step 3 — Update sentinel.conf on Server 2 & 3

The existing `sentinel.conf` uses the Docker service name `redis-primary`. On Server 2 and 3, there is no container named `redis-primary` — use the **real IP** of Server 1 instead:

```conf
# redis-config/sentinel.conf  (on Server 2 and Server 3 ONLY — change line 5)
sentinel resolve-hostnames yes
sentinel announce-hostnames yes

# CHANGED: "redis-primary" → real IP of Server 1
sentinel monitor mymaster 10.61.247.142 6379 2

sentinel auth-pass mymaster redispassword
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 10000
sentinel parallel-syncs mymaster 1
```

> **Server 1** can keep the original `redis-primary` hostname (it's in the same Docker network).

---

## Step 4 — Load the Image on All 3 Servers

```bash
# Copy tar from main server to each ISRO server (run on 10.61.241.85)
scp airflow-ha.tar user@10.61.247.142:/home/user/
scp airflow-ha.tar user@10.61.247.143:/home/user/
scp airflow-ha.tar user@10.61.247.144:/home/user/

# On EACH server, load and tag the image
docker load -i airflow-ha.tar
docker images   # note the image name
docker tag <IMAGE_ID> airflow-ha:2.7.3
```

---

## Step 5 — Open Firewall Ports Between Servers

Run on all 3 servers (or ask your network admin):

```bash
# Required inter-server ports
firewall-cmd --permanent --add-port=2379/tcp   # etcd client
firewall-cmd --permanent --add-port=2380/tcp   # etcd peer
firewall-cmd --permanent --add-port=5432/tcp   # PostgreSQL / HAProxy
firewall-cmd --permanent --add-port=8008/tcp   # Patroni REST API
firewall-cmd --permanent --add-port=6379/tcp   # Redis primary
firewall-cmd --permanent --add-port=26379/tcp  # Redis Sentinel
firewall-cmd --permanent --add-port=9000/tcp   # MinIO S3 API
firewall-cmd --reload
```

---

## Step 6 — Startup Sequence (CRITICAL — follow this order)

### Phase 1: Start etcd cluster on ALL 3 servers simultaneously
```bash
# Run on Server 1, 2, 3 at roughly the same time
# (etcd needs quorum — all 3 must start together)
docker compose -f server1-compose.yml up -d etcd1  # on Server 1
docker compose -f server2-compose.yml up -d etcd2  # on Server 2
docker compose -f server3-compose.yml up -d etcd3  # on Server 3

# Verify etcd cluster is healthy (run on any server)
docker exec -it <etcd1-container> etcdctl member list
```

### Phase 2: Start Postgres cluster
```bash
# Server 1 first (it will become the leader)
docker compose -f server1-compose.yml up -d fix-permissions pg-node1

# Then Server 2 and 3
docker compose -f server2-compose.yml up -d fix-permissions pg-node2
docker compose -f server3-compose.yml up -d fix-permissions pg-node3

# Verify Patroni leader election (on Server 1)
docker exec -it <pg-node1-container> patronictl -c /etc/patroni/config.yml list
```

### Phase 3: Start HAProxy (Server 1 only)
```bash
docker compose -f server1-compose.yml up -d haproxy
```

### Phase 4: Start Redis cluster
```bash
# Server 1 first (primary)
docker compose -f server1-compose.yml up -d redis-primary redis-sentinel1

# Then Server 2 and 3 (replicas + sentinels)
docker compose -f server2-compose.yml up -d redis-replica1 redis-sentinel2
docker compose -f server3-compose.yml up -d redis-replica2 redis-sentinel3

# Verify sentinel knows the master (on Server 1)
docker exec -it <sentinel1-container> redis-cli -p 26379 sentinel masters
```

### Phase 5: Start MinIO and git-sync (Server 1)
```bash
docker compose -f server1-compose.yml up -d minio minio-setup git-sync
```

### Phase 6: Run DB init ONCE (Server 1 only)
```bash
docker compose -f server1-compose.yml up airflow-init
# Wait for it to complete (creates DB tables + admin user)
```

### Phase 7: Start all Airflow services
```bash
# Server 1: webserver, scheduler, flower
docker compose -f server1-compose.yml up -d webserver scheduler flower

# Server 2: git-sync, scheduler2, workers
docker compose -f server2-compose.yml up -d git-sync scheduler2 worker worker2

# Server 3: git-sync, worker3, monitoring
docker compose -f server3-compose.yml up -d git-sync worker3 prometheus grafana
```

---

## Step 7 — Access Points

| Service | URL |
|---|---|
| Airflow UI | http://10.61.247.142:8085 (admin/admin) |
| Flower (Celery Monitor) | http://10.61.247.142:5557 |
| HAProxy Stats | http://10.61.247.142:7000 |
| MinIO Console | http://10.61.247.142:9001 (minioadmin/minioadmin123) |
| Grafana | http://10.61.247.144:3000 (admin/admin123) |
| Prometheus | http://10.61.247.144:9090 |

---

## Step 8 — Test HA (Failover Verification)

### Test DB Failover
```bash
# 1. Check current Patroni leader
docker exec -it <pg-node1> patronictl -c /etc/patroni/config.yml list

# 2. Kill the leader (pg-node1 on Server 1)
docker stop <pg-node1-container>

# 3. Wait 15-30 seconds, then check — pg-node2 or pg-node3 should become leader
docker exec -it <pg-node2> patronictl -c /etc/patroni/config.yml list

# 4. Verify Airflow UI still works — HAProxy reroutes automatically
curl http://10.61.247.142:8085/health
```

### Test Redis Failover
```bash
# 1. Kill redis-primary on Server 1
docker stop <redis-primary-container>

# 2. Check which sentinel elected new master
docker exec -it <sentinel2-container> redis-cli -p 26379 sentinel masters
# "ip" field should now show 10.61.247.143 or 10.61.247.144

# 3. Submit a DAG run — tasks should still queue and execute
```

### Test Worker Failover
```bash
# Kill a worker on Server 2
docker stop <worker-container>

# Check Flower — worker should disappear
# Remaining workers (worker2 on 143, worker3 on 144) continue processing
```

---

## Common Issues

| Problem | Cause | Fix |
|---|---|---|
| etcd won't start | All 3 must start within ~60s of each other | Start etcd on all 3 servers in quick succession |
| Patroni stuck at "starting" | etcd cluster not healthy | Check etcd member list first |
| Redis sentinel can't find master | sentinel.conf uses wrong IP on Server 2/3 | Change `redis-primary` → `10.61.247.142` in sentinel.conf |
| Airflow workers can't connect | Firewall blocking port 26379 or 5432 | Open ports between servers (Step 5) |
| Logs not showing in UI | MinIO S3 connection not set | Add `minio_s3_conn` in Airflow Connections UI |
