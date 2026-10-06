FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN pip install --no-cache-dir --no-deps --no-build-isolation .
EXPOSE 8000 8001 8501
CMD ["python", "-m", "uvicorn", "releaseguard.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
