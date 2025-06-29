FROM python:3.13-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV TZ="Europe/Berlin"

# Create app directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    rsync \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create the statichosts directory
RUN mkdir -p /statichosts/pages

# Copy application code and configuration
COPY app.py .
COPY gunicorn_config.py .
COPY startup.sh .

# Create non-root user for security
RUN groupadd --gid 1000 -r statichosts && useradd --uid 1000 -r -g statichosts statichosts && \
    groupadd --gid 988 -r docker && \
    chown -R statichosts:statichosts /app && \
    usermod -aG docker statichosts && \
    chmod +x startup.sh

# Switch to non-root user
USER statichosts

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the application with startup script
CMD ["./startup.sh"]
