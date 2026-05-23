FROM python:3.11-slim

# Install Node.js 20 for GitLab MCP server
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install GitLab MCP server globally (@zereight/mcp-gitlab — free-tier compatible, PAT auth)
RUN npm install -g @zereight/mcp-gitlab

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY agent/ ./agent/

RUN mkdir -p outputs/necro

ENV APP_PORT=8080
EXPOSE 8080

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
