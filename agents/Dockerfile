FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .

RUN pip install --no-cache-dir \
    "discord.py>=2.3.0" \
    python-dotenv \
    fastapi \
    uvicorn \
    psycopg2-binary \
    redis \
    pydantic \
    langchain \
    langchain-ollama \
    langchain-anthropic \
    langgraph \
    httpx

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
