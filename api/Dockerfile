FROM python:3.11-slim
WORKDIR /app

# Make Python logs unbuffered so docker logs show immediately
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app sources and entrypoint
COPY . .
COPY entrypoint.sh /app/entrypoint.sh

# Remove BOM if present and strip Windows CRLF, then make executable
RUN sed -i '1s/^\xEF\xBB\xBF//' /app/entrypoint.sh \
 && sed -i 's/\r$//' /app/entrypoint.sh \
 && chmod +x /app/entrypoint.sh

# Run the entrypoint via sh to avoid exec-format issues
ENTRYPOINT ["sh", "/app/entrypoint.sh"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]