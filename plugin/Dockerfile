FROM python:3.15-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY mcp_server/requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY mcp_server ./mcp_server

# Streamable HTTP is the production transport; compose/env override the rest.
ENV CANOPY_MCP_TRANSPORT=http \
    CANOPY_MCP_HOST=0.0.0.0 \
    CANOPY_MCP_PORT=8765 \
    CANOPY_MCP_PATH=/mcp

EXPOSE 8765
CMD ["python", "mcp_server/server.py"]
