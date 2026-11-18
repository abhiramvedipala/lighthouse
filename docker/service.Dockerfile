# One image for gateway, orders and inventory; the service is chosen with SERVICE.
# Build from the repo root: docker build -f docker/service.Dockerfile -t lighthouse-service .
FROM python:3.12-slim
WORKDIR /app
COPY docker/requirements-services.txt .
RUN pip install --no-cache-dir -r requirements-services.txt
COPY lighthouse/__init__.py lighthouse/__init__.py
COPY lighthouse/services lighthouse/services
COPY lighthouse/sim lighthouse/sim
COPY config config
ENV PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000
CMD ["python", "-m", "lighthouse.services"]
