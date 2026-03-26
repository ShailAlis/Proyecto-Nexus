# NEXUS — GitHub Actions

## Workflows

### 1. CI (`.github/workflows/ci.yml`)

Pipeline de integración continua que se ejecuta en cada Pull Request a `main` o `develop`.

**Jobs:**
- **lint-python**: Ejecuta `ruff check agents/` para validar estilo y errores.
- **lint-docker**: Ejecuta `hadolint` sobre `agents/Dockerfile`.
- **test-python**: Ejecuta `pytest agents/tests/` con cobertura mínima del 70%.

**Política de no-deploy:** Este pipeline NUNCA despliega a ningún entorno. Solo valida calidad de código.

### 2. NEXUS - Create PR (`.github/workflows/nexus-pr.yml`)

Crea un Pull Request automáticamente tras la aprobación final (visual) de un job NEXUS.

**Trigger:** `workflow_dispatch` (manual o via API).

**Inputs:**
| Input | Descripción | Requerido |
|-------|-------------|-----------|
| `job_id` | ID del job NEXUS | Sí |
| `jira_issue` | Clave del issue Jira | Sí |
| `branch_name` | Nombre de la rama | Sí |
| `pr_title` | Título del PR | Sí |
| `pr_body` | Descripción del PR | No |

**Cómo disparar manualmente:**
1. Ir a Actions > "NEXUS - Create PR" > "Run workflow"
2. Rellenar los campos y ejecutar

**Via API (usado por approval_handler):**
```bash
curl -X POST \
  -H "Authorization: Bearer $GIT_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/OWNER/REPO/actions/workflows/nexus-pr.yml/dispatches \
  -d '{
    "ref": "develop",
    "inputs": {
      "job_id": "abc-123",
      "jira_issue": "NEXUS-42",
      "branch_name": "abc-123",
      "pr_title": "feat: implementar login social",
      "pr_body": "Descripcion del cambio"
    }
  }'
```

**Política:** NO hace merge automático. Un revisor humano debe aprobar el PR.

### 3. Notify Discord (`.github/workflows/notify-discord.yml`)

Notifica el resultado del CI a un canal de Discord via webhook.

**Trigger:** Se ejecuta automáticamente cuando el workflow CI termina.

**Información enviada:**
- Estado (pass/fail) con emoji visual
- Rama afectada
- Enlace al run de GitHub Actions

## Secrets necesarios en GitHub

Configurar en Settings > Secrets and variables > Actions:

| Secret | Descripción | Ejemplo |
|--------|-------------|---------|
| `GIT_TOKEN` | Personal Access Token de GitHub para crear PRs y ramas | `ghp_...` |
| `GIT_REPO` | Repositorio en formato `owner/repo` | `usuario/nexus` |
| `DISCORD_WEBHOOK_URL` | Webhook de Discord para notificaciones CI | `https://discord.com/api/webhooks/...` |

## Flujo completo

```
PR abierto → CI (lint + test) → Resultado a Discord
                                        ↓
Job NEXUS aprobado (visual) → workflow_dispatch → nexus-pr.yml → PR creado
                                                                    ↓
                                                            Revisión humana → Merge manual
```

## Regla fundamental

**NEXUS nunca despliega automáticamente a producción.** Los workflows solo validan código y crean PRs. Todo merge y deploy requiere intervención humana explícita.
