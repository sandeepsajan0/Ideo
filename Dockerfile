FROM python:3.11-slim

# Install system dependencies (ffmpeg is required for video assembly)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create the output directory and make it fully writable
# This is important for Hugging Face Spaces since the app writes files here
RUN mkdir -p /app/output && chmod 777 /app/output

# Hugging Face Spaces expect apps to run on port 7860
EXPOSE 7860

# Start the FastAPI server using Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
