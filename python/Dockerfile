FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Compile Protobuf schema used by Python and Java services
RUN python -m grpc_tools.protoc -I./proto --python_out=./schemas ./proto/chat.proto

# Create data directory for server persistence
RUN mkdir -p /data

# Set entrypoint (can be overridden by docker-compose)
ENTRYPOINT ["python"]
