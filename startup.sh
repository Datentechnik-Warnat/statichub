#!/bin/bash

# Startup script for Flask Hugo Deployer

# Create statichosts directory if it doesn't exist
mkdir -p /statichosts/pages

# Set proper permissions
chown -R statichost:statichost /statichosts/pages

# Check if running in development mode
if [ "$FLASK_ENV" = "development" ]; then
    echo "Starting in development mode..."
    exec python app.py
else
    echo "Starting in production mode with Gunicorn..."
    exec gunicorn --config gunicorn_config.py app:app
fi
