---
description: How to run and test the Multi-Node Celery Execution
---

This workflow explains how to run the multi-node testing DAG (`test_multi_node_celery`) in your local Docker environment and observe parallel task execution across distributed workers.

### 1. Start the Airflow Environment

Make sure you are in your project folder (`Tutorial2`) and start all Docker services (PostgreSQL, Redis, Webserver, Scheduler, Worker, and Flower):

```bash
docker-compose up --build -d
```

Wait a minute or two for the services to build, initialize, and become healthy.

### 2. Verify Services are Running

Access your web interfaces in your browser:
- **Airflow Webserver**: [http://localhost:8085](http://localhost:8085)
- **Flower (Celery Monitor)**: [http://localhost:5557](http://localhost:5557)

In the Airflow Webserver UI, find the `test_multi_node_celery` DAG and **unpause it** by toggling the switch next to it.

### 3. Trigger the DAG Multiple Times via CLI

Because Airflow is running inside Docker containers, you should trigger the DAG from your local host by executing the command inside the `webserver` container. 

Open a terminal in the `Tutorial2` directory and run:

**For Windows (Command Prompt):**
```cmd
for /l %x in (1, 1, 10) do docker-compose exec webserver airflow dags trigger test_multi_node_celery
```

**For Windows (PowerShell):**
```powershell
1..10 | ForEach-Object { docker-compose exec webserver airflow dags trigger test_multi_node_celery }
```

**For Git Bash / Linux / macOS:**
```bash
for i in {1..10}; do docker-compose exec webserver airflow dags trigger test_multi_node_celery; done
```

### 4. What to Observe

**In the Airflow Webserver UI (http://localhost:8085):**
1. Navigate to the `test_multi_node_celery` DAG.
2. Go to the **Gantt Chart** or **Graph View**. You will distinctly see `task_2` and `task_3` starting simultaneously in parallel natively after `task_1` completes. `task_4` will wait until the longest parallel task (`task_3` at 10s) finishes.
3. Check the **Task Logs** for any python task. Look for the print statement `Task executing on worker node / hostname: <hostname>`. You'll see different container IDs / Hostnames handling different tasks.

**In the Flower UI (http://localhost:5557):**
1. Check the **Dashboard** to see the online Celery worker nodes.
2. Go to the **Tasks** tab. Because we triggered 10 DAGs at once (50 tasks), you will observe tasks dynamically entering the queue and being processed. Depending on worker concurrency limits, some tasks will remain queued until worker slots are free.
