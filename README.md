# Flask Hugo Deployer

**Flask Hugo Deployer** is a lightweight backend service to deploy static websites built with [Hugo](https://gohugo.io/).  
It pulls a Git repository, builds the content using Hugo in a Docker container, and serves it under a domain-specific directory for use with a static web server like [Caddy](https://caddyserver.com/).

---

## Features

- ✅ Secure deployment via HTTP endpoint with secret key
- 🐳 Docker-powered Git Pull, Hugo build, and Rsync sync
- 📂 Per-domain logging of deploy runs
- 🔐 Caddy-compatible endpoint for on-demand TLS
- 📈 Health and status checks for observability

---

## Directory Structure

```text
/statichosts/pages/
  └── <domain>/
        ├── repository/   # Git content is cloned here
        ├── public/       # Hugo build output
        └── logs/         # Deployment logs
```

---

## Getting Started

### Prerequisites

- [Docker](https://www.docker.com/)
- [Docker Compose](https://docs.docker.com/compose/)
- A Git repository with Hugo content (branch: `release`)

### Installation

1. Clone the repository:

   ```bash
   git clone https://your-git-server.com/your-repo.git
   cd your-repo
   ```

2. Start the application with Docker Compose:

   ```bash
   docker-compose up --build -d
   ```

---

## Environment Variables

| Variable         | Description                                           | Default           |
|------------------|-------------------------------------------------------|-------------------|
| `SECRET_KEY`     | Token required for all protected endpoints            | `SuperSecret_25`  |
| `TZ`             | Container timezone                                    | `Europe/Berlin`   |
| `FLASK_ENV`      | Flask environment                                     | `production`      |
| `WEB_CONCURRENCY`| Gunicorn worker override (optional)                  | `1`               |

---

## API Endpoints

### `POST /deploy/<domain>?secret=...`

Triggers a full deployment:
- Git pull (`release` branch)
- Hugo build
- Rsync to public directory

---

### `GET /logs/<domain>?secret=...`

Returns the most recent deployment log for a domain (plain text).

---

### `GET /logs/<domain>/<deploy_id>?secret=...`

Returns a specific deployment log by ID.

---

### `GET /status/<domain>?secret=...`

Returns domain status including:
- Folder existence
- Git commit info
- Last deployment timestamp

---

### `GET /caddy-check?domain=<domain>`

Used by [Caddy's on-demand TLS](https://caddyserver.com/docs/automatic-https#on-demand-tls) to verify if a domain is ready.

Returns `200 OK` if `/public` directory exists for the domain.

---

### `GET /health`

Returns service and Docker availability:

```json
{
  "status": "OK",
  "docker": "OK",
  "compiler_config": { ... }
}
```

---

## Deployment Workflow

1. Git repository is pulled into `repository/` folder.
2. Hugo builds the static site into `repository/public/`.
3. Output is synced to `public/` for web serving.
4. Logs are written to `logs/deploy_<id>.log`.

---

## Integration with Caddy

Caddy can use the `/caddy-check` endpoint to issue TLS certificates dynamically:

Example Caddy config block:

```caddyfile
{
  on_demand_tls {
    ask http://localhost:8080/caddy-check
  }
}
http://localhost:8081 {
  root * /statichosts/

  @deny not file /{query.domain}/
  respond @deny 404
}
:443 {
  tls {
    on_demand
  }

  log {
    output file /statichosts/access.log
  }

  root * /statichosts/pages/{host}/public
  file_server
}

:80 {
  redir https://{host}{uri}
}

```

---

## License

AGPL-3.0 license  
© Datentechnik Warnat – Simplified static site deployment.

---
