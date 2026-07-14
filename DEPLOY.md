# Deployment Guide — AI Database Optimizer

Deploy a **public demo** of the optimizer for free, or run the production stack on
any server. This is the exact, tested path — including every issue we hit and how
to fix it.

> **Command legend**
> - 🪟 **Windows** = your PC, in **Command Prompt (cmd.exe)**
> - ☁️ **VM** = inside the Ubuntu server, after you SSH in (Linux shell)
>
> The server is Linux, so on-VM commands are Linux. Only the local steps use cmd.exe.

---

## 1. What gets deployed

Five containers, orchestrated by [`docker-compose.prod.yml`](docker-compose.prod.yml):

| Service | Image / build | Role |
|---|---|---|
| `postgres` | pgvector/pgvector (PG16) | optimizer storage + bundled demo DB |
| `ai-service` | `./ai-service` | local embeddings (sentence-transformers) |
| `backend` | `./backend` (FastAPI) | audit / analyze / API |
| `frontend` | `./frontend/Dockerfile.prod` | built Vue SPA served by nginx |
| `caddy` | caddy:2-alpine | reverse proxy + **automatic HTTPS** |

**Public safety is built in.** The prod stack sets `PUBLIC_DEMO=true`, so the backend:
- analyses **only the bundled demo DB** (never a real database), and
- returns **403** from `/api/target/connect` — visitors can't point the server at
  another host.

Self-hosters who want the full "connect your own DB" features use the dev stack
(`docker-compose.yml`) instead, or set `PUBLIC_DEMO=false`.

**One knob switches HTTP vs HTTPS:** `SITE_ADDRESS` in `.env`
- blank → plain HTTP on `:80` (local, or reach the VM by IP)
- a hostname → Caddy fetches a real Let's Encrypt cert automatically

---

## 2. Quick local test (optional, ~2 min)

Prove the production build works on your machine before touching a server.

```cmd
copy .env.prod.example .env
docker compose -f docker-compose.prod.yml up -d --build
```
Leave `SITE_ADDRESS` blank in `.env` → serves plain HTTP. Open **http://localhost**.
First boot loads the demo seed (~1–2 min); watch with:
```cmd
docker compose -f docker-compose.prod.yml logs -f
```
Tear down when done: `docker compose -f docker-compose.prod.yml down`

---

## 3. Deploy to a free VM (Oracle Cloud "Always Free")

Free forever: up to 4 ARM vCPU / 24 GB RAM. (A card is needed at signup; Always-Free
resources are never charged.) The stack needs ~1 GB RAM for the embedding model, so
the tiny 512 MB free tiers won't do — this VM is the zero-cost sweet spot.

### 3.1 🪟 Create an SSH key (Windows has SSH built in)
```cmd
if not exist "%USERPROFILE%\.ssh" mkdir "%USERPROFILE%\.ssh"
ssh-keygen -t ed25519 -f "%USERPROFILE%\.ssh\oracle_key" -N ""
type "%USERPROFILE%\.ssh\oracle_key.pub"
```
Copy the printed `ssh-ed25519 …` line.

### 3.2 Create the VM (Oracle web console)
1. <https://cloud.oracle.com> → **Compute → Instances → Create instance**.
2. **Image:** Ubuntu 22.04. **Shape:** *Change shape* → **Ampere / VM.Standard.A1.Flex**
   → 2 OCPU / 12 GB (Always Free).
3. **Add SSH keys → Paste public keys** → paste the line from 3.1. **Create**.
4. Copy the instance's **Public IP**.
5. **Cloud firewall:** Networking → your VCN → **Security Lists** → Default →
   **Add Ingress Rules**: source `0.0.0.0/0`, TCP, dest port **80**; repeat for **443**.

### 3.3 🪟 Connect from Windows
```cmd
icacls "%USERPROFILE%\.ssh\oracle_key" /inheritance:r
icacls "%USERPROFILE%\.ssh\oracle_key" /grant:r "%USERNAME%:R"
ssh -i "%USERPROFILE%\.ssh\oracle_key" ubuntu@YOUR_IP
```
Type `yes` at the prompt. You're now ☁️ on the VM.

### 3.4 ☁️ Open the OS firewall + install Docker
Oracle's Ubuntu also blocks 80/443 in its **local** iptables — the #1 "site won't
load" gotcha. Open them, then install Docker:
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save

curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```
Reconnect (🪟) so the docker group applies:
```cmd
ssh -i "%USERPROFILE%\.ssh\oracle_key" ubuntu@YOUR_IP
```

### 3.5 ☁️ Get the code and configure
```bash
git clone https://github.com/Tamilarasan-46/ai-db-optimizer.git
cd ai-db-optimizer
cp .env.prod.example .env
nano .env
```
Set in `.env` (Ctrl+O saves, Ctrl+X exits):
- **`SITE_ADDRESS`** for free HTTPS — sslip.io from your IP, dashes for dots.
  IP `152.67.10.20` → `SITE_ADDRESS=152-67-10-20.sslip.io`
  (or leave blank to serve plain HTTP at `http://YOUR_IP`).
- **`ALLOWED_ORIGINS=https://152-67-10-20.sslip.io`** (match SITE_ADDRESS; or `*`).
- **Passwords** — replace both `CHANGE_ME…`, and make `DATABASE_URL`'s password
  match `AI_OPTIMIZER_PASSWORD`.

### 3.6 ☁️ Launch
```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f     # Ctrl+C to stop watching
```
First boot builds images, seeds ~1.55M demo rows, and downloads the embedding
model (~3–5 min on ARM). Then open:
- HTTPS: `https://152-67-10-20.sslip.io`
- or plain HTTP: `http://YOUR_IP`

Verify all healthy:
```bash
docker compose -f docker-compose.prod.yml ps
curl -s http://localhost/api/health
```

---

## 4. Demo data

The demo DB **auto-seeds on first boot** (via `db-init-container/`), so you normally
don't run anything. Use these only to reload it.

**Reseed the running DB** (data already present → truncate first):
```bash
docker exec ai-opt-db psql -U postgres -d ai_optimizer_db -c "TRUNCATE customers, orders, events RESTART IDENTITY CASCADE;"
docker exec ai-opt-db psql -v ON_ERROR_STOP=1 -U postgres -d ai_optimizer_db -c "SET ROLE ai_optimizer_user;" -f /seed/seed-ai-optimizer-db.sql
```
> If tables are already empty, skip the TRUNCATE.
> On 🪟 Windows the `-f /seed/...` path works in **cmd.exe** (in Git Bash it gets
> mangled — use cmd.exe for that command).

**Full fresh (drop the DB volume → auto-reseeds on next boot):**
```bash
docker compose -f docker-compose.prod.yml down
docker volume rm ai-db-optimizer_pgdata_ai_optimizer_prod
docker compose -f docker-compose.prod.yml up -d --build
```

**Verify:**
```bash
docker exec ai-opt-db psql -U postgres -d ai_optimizer_db -c "SELECT (SELECT count(*) FROM orders) orders, (SELECT count(*) FROM pg_stat_statements WHERE mean_exec_time>100 AND dbid=(SELECT oid FROM pg_database WHERE datname='ai_optimizer_db')) slow_q;"
```
Expect `orders = 500000` and `slow_q >= 4`.

---

## 5. Everyday operations (☁️ on the VM)

```bash
cd ai-db-optimizer

# update to latest code
git pull && docker compose -f docker-compose.prod.yml up -d --build

# status / logs
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f backend

# stop / start / restart one service
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml restart caddy
```

---

## 6. Troubleshooting

Every problem below was hit and fixed during real deployment. Diagnose first, then apply the fix.

### Postgres: `database files are incompatible with server`
A data volume made by a different PG major version. The demo/self storage is
disposable — wipe and let it re-seed:
```bash
docker compose -f docker-compose.prod.yml down
docker volume rm ai-db-optimizer_pgdata_ai_optimizer_prod
docker compose -f docker-compose.prod.yml up -d --build
```
(The prod volume is isolated from the dev stacks so this can't happen from mixing them.)

### Build fails: `lookup registry-1.docker.io: no such host`
Docker can't reach Docker Hub — usually an intermittent **Docker-Desktop-on-WSL2 DNS
drop** (🪟 local), not your config. Reset:
```cmd
wsl --shutdown
```
Restart Docker Desktop, re-run the build. Durable fix: Docker Desktop → Settings →
Docker Engine, add `"dns": ["8.8.8.8","1.1.1.1"]`.

### `ai-opt-caddy` keeps **Restarting**
Bad Caddyfile. Check the reason:
```bash
docker logs ai-opt-caddy | tail -5
```
- `invalid port '80}'` / adapting config error → a malformed site address. The site
  address must come from `SITE_ADDRESS` (`:80` or a bare hostname) — don't wrap it in
  braces. Fix `.env`, then `docker compose -f docker-compose.prod.yml up -d`.

### Caddy returns **502 Bad Gateway** / `dial tcp backend:8000: connection refused`
The backend isn't answering yet. Check it:
```bash
docker compose -f docker-compose.prod.yml ps
docker logs ai-opt-backend | tail -20
```
- Still starting / DB seeding → wait; the backend now **retries the DB for ~2 min**
  and the DB healthcheck waits for **TCP**, so it self-heals. If it exited, it will
  restart on its own.

### Backend: `ConnectionRefusedError: [Errno 111]` at startup
It started before Postgres accepted TCP (fresh-boot seed window). This is handled by
the built-in retry + TCP healthcheck — it recovers once init finishes. If it persists,
the DB itself is unhealthy: `docker logs ai-opt-db | tail -30`.

### `psql: connection to server on socket ... failed: No such file or directory`
Postgres inside the container isn't ready (still initializing/restarting). Wait for
healthy, then retry:
```bash
docker exec ai-opt-db pg_isready -h 127.0.0.1 -U postgres -d ai_optimizer_db
```

### Dashboard shows **no demo data** (0 slow queries, empty tables)
The seed didn't load. Check init:
```bash
docker logs ai-opt-db | grep -iE "seed|violates|ERROR"
```
- `[init] demo workload seeded` with no error → it's fine; you may have TRUNCATEd it —
  reload via §4.
- a foreign-key/other error → reseed via §4 (the known FK off-by-one is already fixed).

### Slow-query list shows `EXPLAIN …` / `ANALYZE …` and clicking errors
Those are the optimizer's own meta-queries recorded in `pg_stat_statements`; they're
now filtered out of the slow-query surfaces. If you still see them, you're on an older
image — rebuild: `docker compose -f docker-compose.prod.yml up -d --build backend`.

### `Error ... port 80 ... address already in use`
Something else holds port 80. Find and stop it:
```bash
sudo ss -tlnp | grep :80          # often apache2
sudo systemctl disable --now apache2
```

### HTTPS certificate not issued
```bash
docker logs ai-opt-caddy | grep -i "certificate\|error"
```
- DNS must resolve to this server first. sslip.io is instant — confirm `SITE_ADDRESS`
  matches your real public IP (dashes for dots) and ports 80/443 are open in **both**
  the cloud Security List and the VM iptables (§3.2, §3.4). Let's Encrypt can't issue
  for a bare IP, which is why you use an sslip.io hostname.

### Site loads over HTTP but not HTTPS (or vice-versa)
`SITE_ADDRESS` decides: blank/`:80` = HTTP only; a hostname = HTTPS only (HTTP
auto-redirects). Set it, then `docker compose -f docker-compose.prod.yml up -d`.

---

## 7. Command cheat-sheet

```bash
# deploy / update
docker compose -f docker-compose.prod.yml up -d --build
# stop everything
docker compose -f docker-compose.prod.yml down
# wipe demo DB (drops data, re-seeds next up)
docker compose -f docker-compose.prod.yml down && docker volume rm ai-db-optimizer_pgdata_ai_optimizer_prod
# logs (all / one service)
docker compose -f docker-compose.prod.yml logs -f
docker compose -f docker-compose.prod.yml logs -f backend
# health checks
curl -s http://localhost/api/health
docker exec ai-opt-db pg_isready -h 127.0.0.1 -U postgres -d ai_optimizer_db
```

---

## 8. Optional: auto-deploy on push

A GitHub Actions workflow can SSH into the VM and run `git pull && docker compose … up
-d` on every push to `main`. Ask and it can be added as `.github/workflows/deploy.yml`
(SSH key stored as a repo secret). Not required to go live.
