#!/usr/bin/env bash
# Update the live site to the latest code on GitHub. Run on the droplet:
#
#   cd /opt/compsoc-challenge && bash deploy.sh
#
# 1. backs up the database (~/backups), 2. pulls the code, 3. rebuilds and restarts the
# containers (database changes apply by themselves when the backend starts), 4. waits until
# /api/health says the site and the judge are up. If anything fails it stops and says so;
# the backup from step 1 is there to restore.
set -euo pipefail

cd "$(dirname "$0")"
C="docker compose -f docker-compose.yml -f docker-compose.judge0.yml"

echo "== 1/4 Backing up the database"
mkdir -p ~/backups
backup=~/backups/compsoc-$(date +%F-%H%M).sql
$C exec -T postgres pg_dump -U compsoc compsoc > "$backup"
[ -s "$backup" ] || { echo "The backup is empty: stopping before changing anything."; exit 1; }
echo "   saved $backup ($(du -h "$backup" | cut -f1))"
ls -1t ~/backups/compsoc-*.sql | tail -n +21 | xargs -r rm --  # keep the last 20

echo "== 2/4 Pulling the latest code"
before=$(git rev-parse --short HEAD)
git pull --ff-only
after=$(git rev-parse --short HEAD)
if [ "$before" = "$after" ]; then
  echo "   already up to date ($after); rebuilding anyway"
else
  git log --oneline "$before..$after" | sed 's/^/   /'
fi

echo "== 3/4 Rebuilding and restarting (a few minutes)"
$C up -d --build
docker image prune -f > /dev/null  # old images fill the disk otherwise

echo "== 4/4 Waiting for the site to come back"
for i in $(seq 1 60); do
  # Ask the backend from inside its container: Caddy only answers for SITE_ADDRESS, so
  # http://localhost doesn't reach it once the site has a domain.
  health=$($C exec -T backend python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health', timeout=5).read().decode())" 2>/dev/null || true)
  if echo "$health" | grep -q '"judge": *true'; then
    echo "   $health"
    echo "Done: $before -> $after. Backup: $backup"
    exit 0
  fi
  sleep 5
done
echo "The site didn't report healthy within 5 minutes. Last answer: ${health:-none}"
echo "Look at:  $C logs --tail=100 backend"
echo "To go back:  git checkout $before && $C up -d --build"
echo "(and if the database needs it:  $C exec -T postgres psql -U compsoc compsoc < $backup  into an empty database)"
exit 1
