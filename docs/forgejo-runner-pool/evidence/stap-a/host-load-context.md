# Hostlast tijdens de stap-A-metingen (2026-09-01)

Gemeten met de metingen van Task 7 (workload) en Task 8 (hostfeiten).

## scrum4me-server (22 containers)
```
compose-worker-deploy-1	scrum4me-agent-runner:idea
compose-worker-deploy-2	scrum4me-agent-runner:idea
compose-worker-docs-1	scrum4me-agent-runner:idea
compose-worker-idea-51	scrum4me-agent-runner:idea
compose-worker-idea-52	scrum4me-agent-runner:idea
digiplein	digiplein:latest
scrum4me-agent-codex	scrum4me-agent-codex:local
scrum4me-caddy	caddy:2
scrum4me-copilot	scrum4me-copilot:latest
scrum4me-forgejo	codeberg.org/forgejo/forgejo:15.0.2
scrum4me-forgejo-dind	docker:dind
scrum4me-forgejo-runner	code.forgejo.org/forgejo/runner:12
scrum4me-mcp-http	scrum4me-mcp-http:latest
scrum4me-ops-dashboard	ops-dashboard:latest
scrum4me-postgres	postgres:17
scrum4me-workers	scrum4me-workers:latest
scrum4us-cleanup-sidecar	scrum4us-cleanup-sidecar
scrum4us-core-api	scrum4us-core-api
scrum4us-litellm	c2b7aba0e3eb
scrum4us-postgres	pgvector/pgvector:0.8.5-pg17-trixie
scrum4us-tei	8de25e75ce39
scrum4us-worker	scrum4us-worker
```

## max2 (11 containers, onder eigen productielast)
```
media-organizer-postgres	postgres:17
media-organizer-web	media-organizer-web
scraper	scraper-scraper
scrum4me-agent-codex	scrum4me-agent-codex:local
scrum4me-caddy	caddy:2
scrum4me-ops-dashboard	ops-dashboard:latest
scrum4me-postgres	postgres:17
scrum4me-worker-idea-1	scrum4me-agent-runner:idea
scrum4me-worker-idea-2	scrum4me-agent-runner:idea
scrum4me-workers	scrum4me-workers:latest
tei-gpu	aedf3b34836d
```
