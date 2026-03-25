# NEXUS

Sistema multiagente de desarrollo y diseño asistido por IA.

Orquestador central (n8n) + cerebro multiagente (Python/LangGraph) + aprobaciones humanas vía Discord.

---

## Requisitos previos

- **Docker** y **Docker Compose** v2+
- **Python 3.11+** (para desarrollo de agentes)
- **Node.js 18+** (para extensiones de n8n, si aplica)

---

## Arranque en 3 pasos

```bash
# 1. Clonar y configurar entorno
git clone <repo>
cd nexus
cp .env.example .env
# Edita .env con tus credenciales reales

# 2. Levantar infraestructura
docker compose up -d

# 3. Verificar que todo está sano
docker compose ps
```

| Servicio   | URL                    |
|------------|------------------------|
| n8n        | http://localhost:5678   |
| PostgreSQL | localhost:5432          |
| Redis      | localhost:6379          |

---

## Estructura

```
nexus/
├── agents/
│   ├── analyst/       # Agente analista
│   ├── developer/     # Agente desarrollador
│   ├── designer/      # Agente diseñador
│   └── reviewer/      # Agente revisor
├── shared/
│   └── prompts/       # Prompts y schemas compartidos
├── infra/
│   ├── postgres/      # init.sql
│   ├── redis/         # redis.conf
│   └── n8n/           # Configuración adicional de n8n
├── .github/
│   └── workflows/     # CI/CD
└── docs/              # Documentación detallada
```

Consulta [docs/](docs/) para documentación técnica detallada.

---

## Flujo de trabajo

```
Jira Issue
  └─► Analista  ──► [Aprobación humana: arquitectura y alcance]
        └─► Developer + Diseñador  ──► [Aprobación humana: datos y seguridad]
                  └─► Reviewer  ──► [Aprobación humana: entregable final]
```

---

## Base de datos

| Tabla                    | Descripción                          |
|--------------------------|--------------------------------------|
| `nexus_jobs`             | Registro maestro de ejecuciones      |
| `nexus_agent_results`    | Outputs de cada agente               |
| `nexus_decisions`        | Historial de decisiones humanas      |
| `nexus_context_summary`  | Resumen de contexto por issue Jira   |

---

## ⚠️ No-deploy policy

Este proyecto **nunca** despliega automáticamente a producción.

- El CI ejecuta lint y tests, pero **no** hace deploy.
- Todo merge a `main` requiere Pull Request aprobado.
- Las API keys y secrets **nunca** se hardcodean ni se comitean.
- Las migraciones SQL ya ejecutadas **nunca** se eliminan.
