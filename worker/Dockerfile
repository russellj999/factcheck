FROM python:3.11-slim
WORKDIR /app

# Install dependencies from repo root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the API app so worker can import config, db, models
COPY api/app ./app

# Overlay worker-specific code into the same package
COPY worker/app/worker.py ./app/worker.py

CMD ["python", "-m", "app.worker"]