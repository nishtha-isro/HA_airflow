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