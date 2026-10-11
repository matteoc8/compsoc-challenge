# Hosting on a new DigitalOcean droplet

Everything runs on one droplet with Docker Compose: Caddy (HTTPS), the site (Next.js), the
backend (FastAPI), Postgres, and Judge0 (which runs the code in a sandbox). About an hour the
first time.

> **Not yet tried on a real server.** The app and its tests run on Windows with the local
> judge, but the Docker images and Judge0 have never been run. Steps 8–9 check them: do
> them well before an event.

## 1. Which droplet

For **up to 10 teams at once**, where a few seconds' wait for a result is fine:

| Plan (Basic, Regular SSD) | Price* | Verdict |
|---|---|---|
| 1 GB / 1 vCPU | ~$6/mo | Too small: Judge0 alone needs more memory. |
| 2 GB / 1 vCPU | ~$12/mo | Fine for the problem of the week and the rest of the site. Too tight for a live event. |
| 2 GB / 2 vCPU | ~$18/mo | Works for 10 teams with the 2 GB swap file below, but with little memory to spare. |
| **4 GB / 2 vCPU** | **~$24/mo** | **The cheapest I'd trust for an event.** |

\*At the time of writing; check the Create Droplet page.

Why: Judge0 (its server, workers, its own Postgres and Redis) plus this app's Postgres, backend,
site and Caddy use roughly 1.5 GB doing nothing. Each submission runs up to 128 MB per test, 4 at
a time. Two CPUs keep the speed tests at the end of a Fastest Code / Best Time Complexity round
steadier, because measuring one team's code doesn't fight with everything else for a single CPU.

**Cheapest way to run it all year:** create the droplet on the **2 GB / 1 vCPU** plan and use it
like that for the problem of the week. The day before an event, **Resize → CPU and RAM only** to
**4 GB / 2 vCPU**, and size it back down afterwards. Resizing needs the droplet off for a minute or
two. Billing is hourly, so an event day costs pennies extra. ("CPU and RAM only" keeps the
original disk, which is what lets you go back down.)

## 2. Create it

DigitalOcean → **Create → Droplets**:

- **Region:** London (LON1).
- **Image:** **Ubuntu 22.04 (LTS) x64**. Not 24.04: Judge0 1.13.1 needs the older cgroup v1
  setup, which is simplest to switch on in 22.04.
- **Size:** Basic → Regular → as above.
- **Authentication:** SSH key (add yours), not a password.
- **Monitoring:** tick it (free). Backups are optional (+20%); step 10 covers your own.
- **Hostname:** e.g. `compsoc`.

Then **Networking → Firewalls → Create firewall**: inbound TCP 22 (ideally only from your IP),
80 and 443, all outbound. Apply it to the droplet.

**Domain (strongly recommended):** point an `A` record (e.g. `compsoc.yourdomain.org`) at the
droplet's IP. Caddy then gets an HTTPS certificate by itself. Without a domain the site works
over plain `http://<ip>`, but school filters are more likely to block it.

## 3. Prepare the server

```bash
ssh root@<droplet-ip>
apt update && apt -y upgrade

# 2 GB swap: a safety net on the smaller plans
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Judge0 needs cgroup v1
sed -i 's/^GRUB_CMDLINE_LINUX="\(.*\)"/GRUB_CMDLINE_LINUX="\1 systemd.unified_cgroup_hierarchy=0"/' /etc/default/grub
update-grub && reboot
```

Log back in after a minute and check that this prints **`tmpfs`** (not `cgroup2fs`):

```bash
stat -fc %T /sys/fs/cgroup/
```

## 4. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
docker compose version      # should print v2.x
```

## 5. Get the code

```bash
cd /opt
git clone https://github.com/matteoc8/compsoc-challenge.git
cd compsoc-challenge
```

If the repository is private, make a GitHub fine-grained token with read access to it and use
`git clone https://<token>@github.com/matteoc8/compsoc-challenge.git` (or add a deploy key).

## 6. Settings

```bash
cp .env.example .env
openssl rand -hex 24   # run 4 times: a password for each of the four "change-me"s below
nano .env
```

In `.env`, set:

- `SITE_ADDRESS=compsoc.yourdomain.org` and `COOKIE_SECURE=true`. With no domain, leave
  `SITE_ADDRESS=:80` and `COOKIE_SECURE=false`.
- `POSTGRES_PASSWORD`, `SECRET_KEY`, `ADMIN_PASSWORD`: new random values.
- `JUDGE0_AUTH_TOKEN`: a new random value, the same one you put in `judge0.conf` next.
- `SCHOOL_EMAIL_DOMAIN`, `CONTACT_EMAIL`: already set for St Paul's.
- `SMTP_*`: optional, see *Email replies* in the README.

Then in `judge0.conf` replace all three `change-me` values: `AUTHN_TOKEN` (the same as
`JUDGE0_AUTH_TOKEN` above), `REDIS_PASSWORD` and `POSTGRES_PASSWORD` (new random values, used
only inside Judge0):

```bash
nano judge0.conf
grep -n change-me .env judge0.conf   # should print nothing
```

On the 2 GB plans, set `COUNT=2` in `judge0.conf` (2 programs at once instead of 4) to save
memory. Put it back to 4 for events on the 4 GB plan.

## 7. Start it

```bash
docker compose -f docker-compose.yml -f docker-compose.judge0.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.judge0.yml ps     # everything "running" / "healthy"
curl -s http://localhost/api/health      # {"ok":true,"judge":true,...}
```

The first build takes 5–10 minutes. Judge0 can take another minute before `"judge": true`.

## 8. First login and checks

1. Open `https://compsoc.yourdomain.org/admin`. Log in as `admin` with your `ADMIN_PASSWORD`
   and choose a new password.
2. On the sample quiz press **Verify all**. This runs every reference solution and a speed test on
   Judge0. If it passes, Judge0 works.
3. From your own computer (in `backend/`, with its virtualenv), throw bad programs at the sandbox,
   then simulate 10 teams:

   ```bash
   .venv/Scripts/python scripts/sandbox_check.py --base https://compsoc.yourdomain.org --password <admin password>
   .venv/Scripts/python scripts/load_test.py --base https://compsoc.yourdomain.org --password <admin password> --teams 10
   ```

   Both print PASS or FAIL. They leave a couple of test games in the Games list, which is harmless.
4. Open the site on a school computer on the school network: the home page, `/join` and a
   projector link. Check that nothing (WebSockets especially) is blocked. If it is, ask IT to
   allow the domain.

## 9. If something's wrong

```bash
cd /opt/compsoc-challenge
C="docker compose -f docker-compose.yml -f docker-compose.judge0.yml"
$C logs --tail=100 backend
$C logs --tail=100 judge0-server judge0-workers
$C restart backend
```

- **`"judge": false` / submissions stuck:** check `stat -fc %T /sys/fs/cgroup/` says `tmpfs`
  (step 3), and that `JUDGE0_AUTH_TOKEN` in `.env` matches `AUTHN_TOKEN` in `judge0.conf`.
- **No HTTPS:** the domain's `A` record must point at the droplet, and ports 80 and 443 must be
  open, before Caddy can get a certificate (`$C logs caddy`).
- **Python version:** Judge0 CE runs **Python 3.8**, so solutions can't use 3.9+ syntax such as
  `list[int]`. `JUDGE0_PYTHON_ID=71` is right for Judge0 CE 1.13.1.

## 10. Updating and backups

**Update to the latest code:**

```bash
cd /opt/compsoc-challenge && git pull
docker compose -f docker-compose.yml -f docker-compose.judge0.yml up -d --build
```

Database changes apply by themselves when the backend starts.

**Back up the database** (quizzes, games, weekly entries and people):

```bash
docker compose exec -T postgres pg_dump -U compsoc compsoc > ~/compsoc-$(date +%F).sql
```

Do it before and after every event, and copy the file off the server
(`scp root@<ip>:~/compsoc-*.sql .`). For a nightly copy run `crontab -e` and add:

```
0 3 * * * cd /opt/compsoc-challenge && docker compose exec -T postgres pg_dump -U compsoc compsoc > /root/compsoc-nightly.sql
```

A DigitalOcean **snapshot** before an event is a quick way back for the whole machine. Snapshots
cost a little per GB per month, so delete old ones.

**Restore:** `docker compose exec -T postgres psql -U compsoc compsoc < compsoc-YYYY-MM-DD.sql`
into an empty database.

## Event day

See *Event-day runbook* in the README. In short: resize up the day before, check `/api/health`
and **Verify all** half an hour before, take a backup, open the projector from the console, and
resize back down afterwards.
