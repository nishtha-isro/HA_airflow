# Comprehensive Guide: Highly Available Apache Airflow Cluster

This documentation provides an end-to-end technical overview of the codebase. It details the High Availability (HA) Apache Airflow cluster setup, which uses the Celery Executor and distributes all workloads across multiple nodes.

If you are new to this repository, reading through this document will quickly orient you to how the different Docker containers interact to create a fault-tolerant system.

---

## 1. Core Architecture Pattern

This project implements a fully distributed data pipeline orchestration engine. To prevent **Single Points of Failure (SPOF)**, standard single-container services (like Postgres or Redis) have been replaced with their cluster equivalents (Patroni, Redis Sentinel). 

There are 7 distinct architectural layers:

1.  **Metadata Database Layer**: `PostgreSQL` + `Patroni` + `Etcd` + `HAProxy`
2.  **Message Broker Layer**: `Redis` + `Redis Sentinel`
3.  **Orchestration Layer**: `Airflow Scheduler` (Active-Active)
4.  **Execution Layer**: `Airflow Celery Workers`
5.  **Storage Layer**: `MinIO` (S3 API Log Storage)
6.  **Code Distribution Layer**: `Git-Sync`
7.  **Monitoring Layer**: `Prometheus` + `Grafana` + `Flower` + `Exporters`

All of these are managed collectively within a single **`docker-compose.yml`** file holding 20+ service definitions.

---

## 2. Layer Definitions & Interactivity

### A. Metadata Database Layer (Postgres HA)
By default, Airflow uses a single PostgreSQL database to store its state (Task states, DAG definitions). If it crashes, Airflow dies. This project uses **Patroni**, a template for creating HA PostgreSQL clusters.
*   **`etcd1, etcd2, etcd3`**: The distributed "brain". Patroni nodes use `etcd` to establish consensus and hold elections to decide which node is the database "Primary".
*   **`pg-node1, pg-node2, pg-node3`**: Three isolated Postgres databases. One is active (Primary) and accepts reads/writes. The other two constantly copy data from the Primary.
*   **`haproxy`**: A smart load balancer operating on port `5432`. Airflow does not connect to the nodes directly. It connects to HAProxy. HAProxy interrogates the cluster and routes Airflow's traffic exclusively to whichever Postgres node currently holds the Primary designation.

### B. Message Broker Layer (Redis HA)
Because we are using the `Celery Executor`, Schedulers place "Tasks" into a queue, and Workers consume them. We use a **Redis** cluster to hold this queue.
*   **`redis-primary`**: The initial master node holding the task queue in memory.
*   **`redis-replica1, redis-replica2`**: Exact clones of the primary node. 
*   **`redis-sentinel1, redis-sentinel2, redis-sentinel3`**: Observers. They ping the primary. If the primary crashes, the Sentinels hold a vote (quorum) and promote a replica to become the new primary seamlessly.
*   *Implementation detail*: Check `airflow.cfg` and you'll note `broker_url` uses a special `sentinel://...` scheme. Airflow queries the Sentinels for the master IP rather than hardcoding it.

### C. Orchestration & Execution Layer (Airflow Core)
*   **`scheduler, scheduler2`**: Since Airflow 2.x, we run multiple schedulers simultaneously. They use database-row-level locking in Postgres to ensure they do not accidentally schedule the exact same task twice. 
*   **`worker, worker2, worker3`**: The "muscle". They independently boot up, connect to the Redis broker, pull task instructions, execute your Python code, and report success/failure back to the Postgres database.
*   **`webserver`**: The UI endpoint (`http://localhost:8085`).

### D. Storage Layer (MinIO Remote Logging)
If `worker2` runs a task and then crashes, the local text log file is destroyed. To prevent data loss, we implement **Remote Logging**.
*   **`minio`**: A self-hosted Amazon S3 alternative. 
*   **`minio-setup`**: A transient script that runs once during startup to automatically create the `airflow-logs` bucket. Make sure to check `airflow.cfg`, which uses `remote_logging = True` and sets the storage backend to our `minio_s3_conn` connection in Airflow.

### E. Code Distribution Layer (Git-Sync)
To ensure that all 5 Airflow nodes (2 Schedulers, 3 Workers) are evaluating the exact same DAG code:
*   **`git-sync`**: Periodically (e.g., every 30 seconds) pulls `.py` DAG files from a remote GitHub repository into a shared volume block mounted centrally across all containers. 

### F. Monitoring & Observability Layer
If a worker gets overloaded, we need to see it before it fails. 
*   **`prometheus`**: The data collector. It scrapes metrics across the Docker network every 15 seconds. (Configured in `monitoring/prometheus.yml`).
*   **`grafana`**: The dashboard viewer (`http://localhost:3000`). It translates Prometheus data into beautiful interactive graphs.
*   **Exporters**: Redis and Postgres don't natively output metrics formatted for Prometheus. `redis-exporter` and `postgres-exporter` bridge the gap.
*   **`flower`**: A dedicated Celery dashboard (`http://localhost:5557`) focused solely on worker queue latency.

 
## 3. How to Use & Debug the Codebase

### Core Commands
1.  **Boot System**: `docker-compose up -d --build` (Be patient, >20 containers are booting).
2.  **Tear Down**: `docker-compose down -v` (Use `-v` to wipe orphaned volumes).
3.  **Logs**: If you get a "DNS Resolve" or "Temporary Failure in Name Resolution" error, Airflow containers may have booted before `haproxy` initialized. Check `docker-compose logs --tail=50 webserver`.

### Key Developer Files
*   `docker-compose.yml`: The master architect document defining all network logic.
*   `dockerfiles/Dockerfile`: Ensures we append extra tools (like `boto3`, `pandas`) to the official `apache/airflow:2.7.3` image alongside Celery providers.
*   `config/airflow.cfg`: Contains critical adjustments defining connection pooling, heartbeat thresholds, and timeout retries.

### Failure Simulation Process
To understand the redundancy natively, you can simulate catastrophic failures:
1. Trigger a massive DAG via the Webserver.
2. While the DAG is processing, run `docker stop redis-primary` or `docker stop scheduler`. 
3. Watch the pipeline temporarily halt (15-30s) while heartbeats fail, Sentinels conduct elections, and failovers complete. Operations will then gracefully resume without any human intervention.
