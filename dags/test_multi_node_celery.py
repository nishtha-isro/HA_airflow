from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from datetime import datetime
import socket
import time

def worker_task(duration):
    hostname = socket.gethostname()
    print(f"Task executing on worker node / hostname: {hostname}")
    print(f"Sleeping for {duration} seconds to simulate processing time...")
    time.sleep(duration)
    print("Task completed.")

with DAG(
    dag_id='test_multi_node_celery',
    start_date=datetime(2023, 1, 1),
    schedule_interval=None,
    catchup=False,
    tags=['testing', 'celery'],
    description='DAG to test multi-node execution with Celery Executor'
) as dag:

    task1 = PythonOperator(
        task_id='task_1',
        python_callable=worker_task,
        op_kwargs={'duration': 5}
    )

    task2 = PythonOperator(
        task_id='task_2',
        python_callable=worker_task,
        op_kwargs={'duration': 7}
    )

    task3 = PythonOperator(
        task_id='task_3',
        python_callable=worker_task,
        op_kwargs={'duration': 10}
    )

    task4 = PythonOperator(
        task_id='task_4',
        python_callable=worker_task,
        op_kwargs={'duration': 6}
    )

    task5 = PythonOperator(
        task_id='task_5',
        python_callable=worker_task,
        op_kwargs={'duration': 4}
    )

    # Define task dependencies
    # Task 1 runs first
    # Task 2 and Task 3 run in parallel after Task 1
    # Then Task 4 runs
    # Finally Task 5 runs
    task1 >> [task2, task3] >> task4 >> task5
