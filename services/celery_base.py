import os
from celery import Celery

# Get the Redis host from the environment, defaulting to 'redis' for Docker
REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')  # Defaults to 'localhost' if not set

celery = Celery(
    'myapp',
    broker=f'redis://{REDIS_HOST}:6379/0',  # Updated to use the dynamic Redis host
    backend=f'redis://{REDIS_HOST}:6379/0',  # Same for the result backend
    include=['services.tasks']
)

def init_celery(app):
    # Update Celery config
    celery.conf.update(app.config)

    # Wrap task execution in Flask app context
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
