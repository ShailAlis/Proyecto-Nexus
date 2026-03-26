FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .

RUN pip install --no-cache-dir \
    discord.py==2.3.2 \
    python-dotenv==1.0.1 \
    fastapi==0.115.0 \
    uvicorn==0.32.0 \
    psycopg2-binary==2.9.10 \
    redis==5.2.0 \
    pydantic==2.9.2 \
    langchain==0.3.7 \
    langchain-openai==0.2.9 \
    langchain-anthropic==0.3.0 \
    langchain-ollama==0.2.0 \
    langgraph==0.2.53 \
    httpx==0.27.2 \
    aiohttp==3.11.7

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
