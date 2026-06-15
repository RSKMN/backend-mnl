import sys
import time
from app.core.celery_app import celery_app

@celery_app.task(name="test_health_task")
def test_health_task():
    return "SUCCESS"

def run_test():
    print("Dispatching test task...")
    try:
        # Dispatch the task
        result = test_health_task.delay()
        print(f"Task dispatched with ID: {result.id}")
        
        # Wait for completion
        print("Waiting for task to complete...")
        for _ in range(10):
            if result.ready():
                break
            time.sleep(1)
            print("...")
            
        if result.ready():
            print(f"Task completed with status: {result.status}")
            print(f"Task result: {result.result}")
            return True
        else:
            print("Task did not complete within 10 seconds.")
            return False
            
    except Exception as e:
        print(f"Failed to dispatch or execute task: {e}")
        return False

if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
