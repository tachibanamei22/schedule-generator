FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create uploads directory
RUN mkdir -p uploads

# Railway sets PORT env variable automatically
ENV PORT=8000

WORKDIR /app/backend

CMD uvicorn main:app --host 0.0.0.0 --port $PORT
