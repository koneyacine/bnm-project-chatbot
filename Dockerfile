# Use a slim Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies for psycopg2 (PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose the API port
EXPOSE 8021

# Command to run the application
# We'll use uvicorn directly for production-ready serving
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8021"]
