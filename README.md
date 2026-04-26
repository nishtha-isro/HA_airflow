# Airflow Celery Tutorial 2

This project demonstrates a production-ready Apache Airflow setup using the **Celery Executor**. It utilizes Docker Compose to orchestrate multiple services including a webserver, scheduler, worker, Redis (as a broker), and PostgreSQL (as a metadata database).

## Project Overview

This setup is designed to handle distributed task execution. Unlike the Sequential or Local executors, the **Celery Executor** allows tasks to be distributed across multiple worker nodes, making it suitable for high-throughput and complex workflows.

### Architecture Components
- **Airflow Webserver**: The UI for managing, monitoring, and triggering DAGs.
- **Airflow Scheduler**: Monitors DAGs and schedules tasks based on dependencies and triggers.
- **Airflow Worker**: Executes the actual tasks. In this setup, it communicates with the scheduler via Redis.
- **Flower**: A real-time monitoring tool for Celery workers and tasks.
- **Redis**: Acts as the message broker between the scheduler and workers.
- **PostgreSQL**: Stores all Airflow metadata (DAG definitions, task states, variables, etc.).

## Features
- **Custom Docker Image**: Uses a custom [Dockerfile](./dockerfiles/Dockerfile) to install extra dependencies like `pandas`, `boto3`, and `apache-airflow[s3]`.
- **Port Mapping**: Configured to avoid common port conflicts (Webserver on 8085, Flower on 5557).
- **Volume Mounting**: DAGs and configuration are mounted locally for easy development.

---

## How to Run the Project

### Option 1: Locally with Docker Desktop
1.  **Navigate to the project directory**:
    ```bash
    cd "Tutorial2"
    ```
2.  **Build and Start the Containers**:
    ```bash
    docker-compose up --build -d
    ```
3.  **Access the Services**:
    - **Airflow Webserver**: [http://localhost:8085](http://localhost:8085)
    - **Flower**: [http://localhost:5557](http://localhost:5557)

### Option 2: GitHub Codespaces (Recommended for Remote)
This project is configured for **GitHub Codespaces**.
1.  **Open in Codespaces**: Click the "Code" button on your GitHub repository and select "Open with Codespaces".
2.  **Wait for Build**: The environment will automatically set up Docker-in-Docker and start the Airflow services.
3.  **Port Forwarding**: Codespaces will automatically forward ports **8085** and **5557**. You will receive a notification to open them in your browser.
4.  **Manage Manually**: If services don't start automatically, open a terminal in Codespaces and run:
    ```bash
    docker-compose up -d
    ```

---

## Codespaces vs Local Setup
The setup works almost identically in both environments because it is container-based. However, in Codespaces:
- **Automatic Setup**: The `.devcontainer` configuration handles the Docker installation and starts the services for you.
- **Dynamic URLs**: Instead of `localhost`, Codespaces provides a secure URL (e.g., `https://...-8085.app.github.dev`).
- **Resource Limits**: Ensure your Codespace has at least 4GB of RAM (2-core machine minimum) as running Airflow + Celery + Redis + Postgres is resource-intensive.

---

## Project Structure Walkthrough

- **`dags/`**: Contains your Python DAG files (e.g., [first_dag.py](./dags/first_dag.py)). These are automatically synced with the containers.
- **`config/`**: Contains the [airflow.cfg](./config/airflow.cfg) file for fine-tuning Airflow settings.
- **`dockerfiles/`**: Contains the [Dockerfile](./dockerfiles/Dockerfile) used to build the custom Airflow image.
- **`docker-compose.yml`**: The main orchestration file that defines all services and their relationships.

## Stopping the Project
To stop and remove all containers, run:
```bash
docker-compose down
```
