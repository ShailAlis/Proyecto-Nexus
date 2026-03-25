# NEXUS

Sistema multiagente de desarrollo y diseño asistido por IA.

Orquestador central (n8n) + cerebro multiagente (Python/LangGraph) + aprobaciones humanas vía Discord.

---

## Stack

| Componente | Tecnología |
|---|---|
| Orquestación | n8n (Docker) |
| Agentes | Python 3.11 + LangGraph + LangChain |
| LLMs | OpenAI GPT-4o · Anthropic Claude |
| Base de datos | PostgreSQL 15 |
| Cache / Estado | Redis 7 |
| Notificaciones | Discord bot |
| CI/CD | GitHub Actions |
| Tareas | Jira |

---

## Estructura

```
nexus/
├── agents/
│   ├── analyst/       # Agente analista (arquitectura y alcance)
│   ├── developer/     # Agente desarrollador
│   ├── designer/      # Agente diseñador
│   └── reviewer/      # Agente revisor (Claude)
├── shared/
│   └── prompts/       # Prompts y schemas compartidos
├── infra/
│   ├── postgres/      # init.sql y migraciones
│   └── redis/         # redis.conf
├── .github/
│   └── workflows/     # CI/CD pipelines
└── docs/              # Documentación técnica
```

---

## Inicio rápido

### 1. Clonar y configurar entorno

```bash
git clone <repo>
cd nexus
cp .env.example .env
# Edita .env con tus credenciales reales
```

### 2. Levantar infraestructura

```bash
docker compose up -d
```

Servicios disponibles tras el arranque:

| Servicio | URL |
|---|---|
| n8n | http://localhost:5678 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

### 3. Verificar healthchecks

```bash
docker compose ps
```

---

## Flujo de trabajo

```
Jira Issue
    └─► Analista  ──► [Aprobación humana: arquitectura]
            └─► Developer + Diseñador  ──► [Aprobación humana: datos/seguridad]
                        └─► Reviewer  ──► [Aprobación humana: entregable final]
```

Las aprobaciones se gestionan via Discord bot. Sin aprobación, el flujo se detiene.

---

## Base de datos — tablas principales

| Tabla | Descripción |
|---|---|
| `nexus_jobs` | Registro maestro de ejecuciones |
| `nexus_agent_results` | Outputs de cada agente |
| `nexus_decisions` | Historial de decisiones humanas |
| `nexus_context_summary` | Resumen de contexto por issue Jira |

---

## Reglas críticas

- **NO** desplegar automáticamente a producción
- **NO** hacer merge directo a `main` sin PR aprobado
- **NO** hardcodear API keys o secrets
- **NO** eliminar migraciones SQL ya ejecutadas

---

## Ramas

| Rama | Propósito |
|---|---|
| `main` | Producción |
| `develop` | Integración |
| `feature/nexus-*` | Desarrollo de funcionalidades |