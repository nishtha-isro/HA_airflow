# HA Airflow — Step-by-Step Implementation Guide

> **Servers:**
> - `10.61.241.85` — Main/Build server (image source)
> - `10.61.247.142` — Server 1 (DB leader, Webserver, Scheduler, Redis Primary)
> - `10.61.247.143` — Server 2 (DB replica, Scheduler2, Worker1, Worker2)
> - `10.61.247.144` — Server 3 (DB replica, Worker3, Monitoring)

---

## PRE-REQUISITES (On 10.61.241.85 — Main Server)

### Step 1 — Save your built image as a tar

```bash
# Find the image name
docker images

# Save it to a tar file
docker save <image-name> -o airflow-ha.tar
```

---

### Step 2 — Copy all required files to each server

```bash
# ── Server 1 (10.61.247.142) ──────────────────────────────────
scp airflow-ha.tar             user@10.61.247.142:~/airflow/
scp server1-compose.yml        user@10.61.247.142:~/airflow/docker-compose.yml
scp -r config/                 user@10.61.247.142:~/airflow/
scp -r haproxy/                user@10.61.247.142:~/airflow/
scp -r redis-config/           user@10.61.247.142:~/airflow/
scp -r monitoring/             user@10.61.247.142:~/airflow/

# ── Server 2 (10.61.247.143) ──────────────────────────────────
scp airflow-ha.tar             user@10.61.247.143:~/airflow/
scp server2-compose.yml        user@10.61.247.143:~/airflow/docker-compose.yml
scp -r config/                 user@10.61.247.143:~/airflow/
scp -r redis-config/           user@10.61.247.143:~/airflow/

# ── Server 3 (10.61.247.144) ──────────────────────────────────
scp airflow-ha.tar             user@10.61.247.144:~/airflow/
scp server3-compose.yml        user@10.61.247.144:~/airflow/docker-compose.yml
scp -r config/                 user@10.61.247.144:~/airflow/
scp -r redis-config/           user@10.61.247.144:~/airflow/
scp -r monitoring/             user@10.61.247.144:~/airflow/
```

---

## ON SERVER 1 (10.61.247.142)

### Step 3 — Load and tag the image

```bash
cd ~/airflow
docker load -i airflow-ha.tar
docker images                         # note the image name/id
docker tag <IMAGE_ID> airflow-ha:2.7.3
```

---

### Step 4 — Fix haproxy.cfg (replace service names with real IPs)

Edit `~/airflow/haproxy/haproxy.cfg` and update the backend servers section:

```
listen postgres_primary
    bind *:5432
    option httpchk OPTIONS /master
    server pg1 10.61.247.142:5432 maxconn 100 check port 8008
    server pg2 10.61.247.143:5432 maxconn 100 check port 8008
    server pg3 10.61.247.144:5432 maxconn 100 check port 8008
```

> **Why:** HAProxy health-checks port `8008` (Patroni REST API) on each node.
> It only routes DB traffic to the current Patroni leader.

---

## ON SERVER 2 & 3 (10.61.247.143 and 10.61.247.144)

### Step 5 — Load and tag the image (run on each server)

```bash
cd ~/airflow
docker load -i airflow-ha.tar
docker tag <IMAGE_ID> airflow-ha:2.7.3
```

---

### Step 6 — Fix sentinel.conf (Server 2 & 3 ONLY)

Edit `~/airflow/redis-config/sentinel.conf` and change line 5:

```bash
# CHANGE THIS (uses Docker service name — won't work across servers):
sentinel monitor mymaster redis-primary 6379 2

# TO THIS (use the real IP of Server 1 where Redis Primary runs):
sentinel monitor mymaster 10.61.247.142 6379 2
```

> **Why:** On Server 2 & 3, there is no container named `redis-primary`.
> The sentinel must find Redis using its real IP address.

---

## ON ALL 3 SERVERS

### Step 7 — Open firewall ports

Run these commands on **Server 1, 2, and 3**:

```bash
sudo firewall-cmd --permanent --add-port=2379/tcp    # etcd client
sudo firewall-cmd --permanent --add-port=2380/tcp    # etcd peer sync
sudo firewall-cmd --permanent --add-port=5432/tcp    # PostgreSQL / HAProxy
sudo firewall-cmd --permanent --add-port=8008/tcp    # Patroni REST API
sudo firewall-cmd --permanent --add-port=6379/tcp    # Redis
sudo firewall-cmd --permanent --add-port=26379/tcp   # Redis Sentinel
sudo firewall-cmd --permanent --add-port=9000/tcp    # MinIO S3
sudo firewall-cmd --reload
```

---

## STARTUP SEQUENCE (Follow this order exactly)

### Step 8 — Start etcd cluster (ALL 3 servers simultaneously)

> etcd needs a quorum — all 3 nodes must start within ~60 seconds of each other.

```bash
# Server 1
docker compose up -d etcd1

# Server 2
docker compose up -d etcd2

# Server 3
docker compose up -d etcd3

# Verify etcd is healthy (run on any server)
docker exec -it $(docker ps -qf name=etcd) etcdctl member list
# Expected: 3 members listed, all "started"
```

---

### Step 9 — Start PostgreSQL Patroni cluster

```bash
# Server 1 FIRST (it will elect itself as DB leader)
docker compose up -d fix-permissions pg-node1

# Then Server 2
docker compose up -d fix-permissions pg-node2

# Then Server 3
docker compose up -d fix-permissions pg-node3

# Verify Patroni leader elected (run on Server 1)
docker exec -it $(docker ps -qf name=pg-node1) patronictl -c /etc/patroni/config.yml list
# Expected: pg-node1 = Leader, pg-node2/3 = Replica
```

---

### Step 10 — Start HAProxy (Server 1 only)

```bash
# Server 1
docker compose up -d haproxy

# Verify HAProxy is routing correctly
curl http://10.61.247.142:7000    # should open stats page
```

---

### Step 11 — Start Redis cluster

```bash
# Server 1 — Redis Primary + Sentinel 1
docker compose up -d redis-primary redis-sentinel1

# Server 2 — Redis Replica + Sentinel 2
docker compose up -d redis-replica1 redis-sentinel2

# Server 3 — Redis Replica + Sentinel 3
docker compose up -d redis-replica2 redis-sentinel3

# Verify sentinel knows the master (run on Server 1)
docker exec -it $(docker ps -qf name=redis-sentinel1) redis-cli -p 26379 sentinel masters
# Expected: "ip" = 10.61.247.142, "flags" = master
```

---

### Step 12 — Start MinIO and git-sync (Server 1 only)

```bash
docker compose up -d minio minio-setup git-sync
# MinIO console: http://10.61.247.142:9001 (minioadmin / minioadmin123)
```

---

### Step 13 — Initialize Airflow DB (Server 1 only — run ONCE)

```bash
docker compose up airflow-init
# Wait until you see: "Admin user 'admin' created"
# This creates all Airflow DB tables and the admin login
```

---

### Step 14 — Start Airflow services

```bash
# Server 1 — Webserver, Scheduler, Flower
docker compose up -d webserver scheduler flower

# Server 2 — Scheduler2 (HA), Workers
docker compose up -d git-sync scheduler2 worker worker2

# Server 3 — Worker3, Monitoring
docker compose up -d git-sync worker3 prometheus grafana
```

---

## VERIFICATION

### Step 15 — Confirm everything is running

```bash
# Check all containers on each server
docker compose ps

# All should show "running" or "healthy"
```

| Service | URL | Credentials |
|---|---|---|
| Airflow UI | http://10.61.247.142:8085 | admin / admin |
| Flower (Celery Monitor) | http://10.61.247.142:5557 | — |
| HAProxy Stats | http://10.61.247.142:7000 | — |
| MinIO Console | http://10.61.247.142:9001 | minioadmin / minioadmin123 |
| Grafana | http://10.61.247.144:3000 | admin / admin123 |
| Prometheus | http://10.61.247.144:9090 | — |

---

## QUICK HA FAILOVER TEST

### Test 1 — DB Failover (kill Postgres leader)
```bash
# Kill pg-node1 on Server 1
docker stop $(docker ps -qf name=pg-node1)

# Wait 15-30 seconds, then check — pg-node2 or pg-node3 becomes leader
docker exec -it $(docker ps -qf name=pg-node2) patronictl -c /etc/patroni/config.yml list

# Airflow UI should still be accessible — HAProxy rerouted automatically
curl http://10.61.247.142:8085/health
```

### Test 2 — Redis Failover (kill Redis Primary)
```bash
# Kill redis-primary on Server 1
docker stop $(docker ps -qf name=redis-primary)

# Wait 10 seconds, check which sentinel elected new master
docker exec -it $(docker ps -qf name=redis-sentinel2) redis-cli -p 26379 sentinel masters
# "ip" should now show 10.61.247.143 or 10.61.247.144

# Submit a DAG run — tasks should still execute via new master
```

### Test 3 — Worker Failover (kill a worker)
```bash
# Kill worker on Server 2
docker stop $(docker ps -qf name=^worker$)

# Check Flower — worker2 and worker3 continue processing tasks
# http://10.61.247.142:5557
```

---

## CRITICAL REMINDERS

> [!IMPORTANT]
> **Step 4 (haproxy.cfg IPs)** and **Step 6 (sentinel.conf IP)** are the two most common
> mistakes. If skipped, the DB and Redis HA won't work across servers.

> [!IMPORTANT]
> **Step 8 (etcd)** — all 3 etcd nodes must start at roughly the same time.
> If only 1 or 2 start, etcd won't reach quorum and Patroni will not start.

> [!IMPORTANT]
> **Step 13 (airflow-init)** — run this **only once**, only on Server 1.
> Running it again on another server will attempt to re-init the DB.
