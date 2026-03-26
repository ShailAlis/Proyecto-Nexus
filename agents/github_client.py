import os
import base64

import httpx
from dotenv import load_dotenv

load_dotenv()

GIT_TOKEN = os.getenv("GIT_TOKEN")
GIT_REPO = os.getenv("GIT_REPO")  # formato: usuario/nexus
GITHUB_API = "https://api.github.com"


def get_headers():
    return {
        "Authorization": f"Bearer {GIT_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }


def get_default_branch() -> str:
    """Obtiene la rama por defecto del repo"""
    response = httpx.get(
        f"{GITHUB_API}/repos/{GIT_REPO}",
        headers=get_headers()
    )
    return response.json().get("default_branch", "main")


def get_branch_sha(branch: str) -> str:
    """Obtiene el SHA del ultimo commit de una rama"""
    response = httpx.get(
        f"{GITHUB_API}/repos/{GIT_REPO}/git/ref/heads/{branch}",
        headers=get_headers()
    )
    return response.json()["object"]["sha"]


def create_branch(branch_name: str, from_branch: str = None) -> bool:
    """Crea una rama nueva desde from_branch"""
    if not from_branch:
        from_branch = get_default_branch()
    sha = get_branch_sha(from_branch)
    response = httpx.post(
        f"{GITHUB_API}/repos/{GIT_REPO}/git/refs",
        headers=get_headers(),
        json={
            "ref": f"refs/heads/{branch_name}",
            "sha": sha
        }
    )
    print(f">>> GitHub create_branch {branch_name}: {response.status_code}", flush=True)
    return response.status_code in (200, 201, 422)


def commit_files(branch_name: str, files: list, commit_message: str) -> bool:
    """
    Commitea multiples archivos a una rama.
    files: lista de {"path": "src/auth.py", "content": "codigo aqui"}
    """
    try:
        # Obtener el SHA del arbol actual
        branch_sha = get_branch_sha(branch_name)

        # Obtener el commit actual
        commit_resp = httpx.get(
            f"{GITHUB_API}/repos/{GIT_REPO}/git/commits/{branch_sha}",
            headers=get_headers()
        )
        tree_sha = commit_resp.json()["tree"]["sha"]

        # Crear blobs para cada archivo
        blobs = []
        for file in files:
            content = file.get("content", "")
            if not isinstance(content, str):
                content = str(content)

            blob_resp = httpx.post(
                f"{GITHUB_API}/repos/{GIT_REPO}/git/blobs",
                headers=get_headers(),
                json={
                    "content": base64.b64encode(content.encode()).decode(),
                    "encoding": "base64"
                }
            )
            blobs.append({
                "path": file["path"],
                "mode": "100644",
                "type": "blob",
                "sha": blob_resp.json()["sha"]
            })

        # Crear nuevo arbol
        tree_resp = httpx.post(
            f"{GITHUB_API}/repos/{GIT_REPO}/git/trees",
            headers=get_headers(),
            json={"base_tree": tree_sha, "tree": blobs}
        )
        new_tree_sha = tree_resp.json()["sha"]

        # Crear commit
        commit_resp = httpx.post(
            f"{GITHUB_API}/repos/{GIT_REPO}/git/commits",
            headers=get_headers(),
            json={
                "message": commit_message,
                "tree": new_tree_sha,
                "parents": [branch_sha]
            }
        )
        new_commit_sha = commit_resp.json()["sha"]

        # Actualizar la referencia de la rama
        update_resp = httpx.patch(
            f"{GITHUB_API}/repos/{GIT_REPO}/git/refs/heads/{branch_name}",
            headers=get_headers(),
            json={"sha": new_commit_sha}
        )
        print(f">>> GitHub commit en {branch_name}: {update_resp.status_code}", flush=True)
        return update_resp.status_code == 200

    except Exception as e:
        print(f">>> ERROR en commit_files: {e}", flush=True)
        return False


def create_pull_request(branch_name: str, title: str, body: str, base: str = None) -> dict:
    """Crea un PR desde branch_name hacia base"""
    if not base:
        base = get_default_branch()
    response = httpx.post(
        f"{GITHUB_API}/repos/{GIT_REPO}/pulls",
        headers=get_headers(),
        json={
            "title": title,
            "body": body,
            "head": branch_name,
            "base": base,
            "draft": False
        }
    )
    print(f">>> GitHub PR creado: {response.status_code}", flush=True)
    if response.status_code in (200, 201):
        return {
            "number": response.json()["number"],
            "url": response.json()["html_url"]
        }
    return {}
