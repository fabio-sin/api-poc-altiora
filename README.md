## Lancer le projet from scratch

### 1. Cloner le repo et préparer les données

```bash
git clone <repo>
cd poc-altiora
```

Ajouter les PDFs dans `data/cvs/` et créer `data/cvs/metadata.json` :

```json
{
  "cv_jean_dupont.pdf": {
    "classification": "restricted",
    "modified_by": "rh@altiora.com"
  },
  "cv_marie_curie.pdf": {
    "classification": "public",
    "modified_by": "rh@altiora.com"
  }
}
```

> Si un fichier PDF n'est pas dans `metadata.json`, la classification sera `restricted` par défaut (comportement sécurisé).

### 2. Configurer `.env`

```env
QDRANT_HOST=localhost
QDRANT_PORT=6333
REDIS_URL=redis://localhost:6379
COLLECTION_NAME=cvs
LITELLM_URL=http://litellm:4000   # URL de LiteLLM (à aligner avec le collègue)
CACHE_TTL=3600
```

> Dans les conteneurs Docker, les hosts sont les noms de services (`qdrant`, `redis`, `litellm`). Le `.env` sert pour les runs locaux hors Docker.

### 3. Démarrer l'infrastructure

```bash
docker compose up -d
```

Vérifie que tout tourne :

```bash
docker compose ps
curl http://localhost:6333/healthz   # Qdrant → "healthz check passed"
docker exec redis redis-cli ping     # Redis  → "PONG"
curl http://localhost:8000/health    # API    → {"status":"ok"}
```

### 4. Indexer les CVs

```bash
docker compose run indexer
```

Logs attendus :

```
2026-03-09T14:00:01 INFO     Chargement du modèle d'embedding...
2026-03-09T14:00:03 INFO     Connexion à Qdrant sur qdrant:6333...
2026-03-09T14:00:03 INFO     Collection 'cvs' créée.
2026-03-09T14:00:03 INFO     Delta — à indexer: 2, à supprimer: 0, déjà indexés: 0
2026-03-09T14:00:04 INFO     'cv_jean_dupont.pdf' indexé — 8 vecteurs, classification: restricted
2026-03-09T14:00:04 INFO     Indexation terminée.
```

> Relancer l'indexer est idempotent : seuls les nouveaux fichiers sont indexés, les fichiers supprimés sont retirés de Qdrant.

---

## Utilisation de l'API

### Headers requis sur tous les endpoints

| Header                      | Exemple                   | Description            |
| --------------------------- | ------------------------- | ---------------------- |
| `x-user-name`               | `Jean Dupont`             | Nom de l'utilisateur   |
| `x-user-email`              | `jean.dupont@altiora.com` | Email (clé de session) |
| `x-user-department`         | `RH`                      | Département            |
| `x-user-max-classification` | `restricted`              | Niveau d'accès max     |

> En production, ces headers seront extraits du JWT Azure AD par le middleware d'authentification.

### Niveaux de classification

Du moins au plus sensible : `public` → `restricted` → `confidential` → `secret`

Le système applique automatiquement le niveau le plus restrictif entre le profil utilisateur et la requête. Un utilisateur avec `max_classification: restricted` ne pourra jamais accéder à des documents `confidential` même s'il le demande.

---

### `GET /health`

```bash
curl http://localhost:8000/health
```

```json
{ "status": "ok" }
```

---

### `POST /search`

Recherche sémantique dans Qdrant. Ne fait pas appel au LLM.

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -H "x-user-name: Jean Dupont" \
  -H "x-user-email: jean.dupont@altiora.com" \
  -H "x-user-department: RH" \
  -H "x-user-max-classification: restricted" \
  -d '{"query": "candidat avec expérience Python", "top_k": 3}'
```

Réponse :

```json
{
  "query": "candidat avec expérience Python",
  "results": [
    {
      "filename": "cv_karim_benali.pdf",
      "filepath": "/data/cvs/cv_karim_benali.pdf",
      "text": "Python (pandas, scikit-learn)...",
      "score": 0.336,
      "classification": "restricted",
      "modified_by": "rh@altiora.com"
    }
  ],
  "applied_classification": "restricted"
}
```

---

### `POST /chat`

Recherche sémantique + appel LiteLLM + gestion de session. Nécessite que LiteLLM soit disponible.

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "x-user-name: Jean Dupont" \
  -H "x-user-email: jean.dupont@altiora.com" \
  -H "x-user-department: RH" \
  -H "x-user-max-classification: restricted" \
  -d '{"query": "Quel candidat a le plus d'\''expérience en gestion de projet ?", "top_k": 5}'
```

---

### `GET /session`

Consulte l'historique de conversation d'un utilisateur.

```bash
curl http://localhost:8000/session \
  -H "x-user-email: jean.dupont@altiora.com"
```

```json
{
  "email": "jean.dupont@altiora.com",
  "exchanges": 2,
  "history": [
    { "role": "user", "content": "Quel candidat a de l'expérience Python ?" },
    { "role": "assistant", "content": "D'après les CVs disponibles..." }
  ]
}
```

---

### `DELETE /session`

Efface l'historique de conversation d'un utilisateur.

```bash
curl -X DELETE http://localhost:8000/session \
  -H "x-user-email: jean.dupont@altiora.com"
```

---

## Documentation interactive

FastAPI génère automatiquement une UI Swagger accessible sur :

```
http://localhost:8000/docs
```

---

## Comportement du cache Redis

| Clé               | TTL   | Contenu                 |
| ----------------- | ----- | ----------------------- |
| `session:{email}` | 30min | Historique conversation |

---

## Relancer uniquement l'indexer

```bash
docker compose run indexer
```

## Rebuilder l'API après modification du code

Le code `app/` est monté en volume — les modifications sont prises en compte automatiquement grâce au `--reload` d'uvicorn. Un rebuild n'est nécessaire que si tu modifies `app/requirements.txt` ou `app/Dockerfile` :

```bash
docker compose up -d --build api
```

## Voir les logs

```bash
docker logs api -f
docker logs indexer
```

---
