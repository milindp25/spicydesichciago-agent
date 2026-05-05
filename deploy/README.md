# Oracle Cloud Deploy Runbook

End-to-end deploy guide for putting the Spicy Desi voice agent on an Oracle Cloud Always Free ARM VM.

## Architecture

```
                        Internet
                           │
                  ┌────────┴────────┐
                  │  api.spicy...   │   agent.spicy...
                  └────────┬────────┘   ┌────────┐
                           │            │        │
                  ┌────────▼────────────▼────┐
                  │         Caddy            │  ← TLS, reverse proxy
                  └────────┬────────────┬────┘
                           │            │
                ┌──────────▼────┐  ┌────▼─────────┐
                │ api (uvicorn) │  │ agent (...)  │
                │  :8080        │  │  :8090       │
                └───────────────┘  └──────────────┘
                           │
                  ┌────────▼────────┐
                  │  /var/lib/      │
                  │  spicy-desi/    │  ← JSONL events, pickup state
                  │  data/          │
                  └─────────────────┘
```

## Prereqs

- An Oracle Cloud VM (Ubuntu 24.04 ARM, A1.Flex 2/12 GB)
- The VM's public IP
- SSH access via the key from `~/.ssh/spicy-desi-oracle`
- DNS access for `spicydesichciago.com`
- Firewall ingress rules in Oracle (Networking → Subnet → Default Security List → Add Ingress Rules):
  - TCP 22 from `0.0.0.0/0` (SSH — usually already there)
  - TCP 80 from `0.0.0.0/0` (HTTP — for Let's Encrypt challenge)
  - TCP 443 from `0.0.0.0/0` (HTTPS — for actual traffic)

## Step 1: Point DNS

In your DNS provider, create two `A` records:

| Name | Type | Value |
|---|---|---|
| `api.spicydesichciago.com` | A | `<VM_PUBLIC_IP>` |
| `agent.spicydesichciago.com` | A | `<VM_PUBLIC_IP>` |

TTL 300s is fine. Do this **before** starting Caddy so Let's Encrypt can validate.

## Step 2: SSH in and run the setup script

```bash
ssh -i ~/.ssh/spicy-desi-oracle ubuntu@<VM_PUBLIC_IP>

# On the VM:
curl -sSL https://raw.githubusercontent.com/milindp25/spicydesichciago-agent/main/deploy/setup.sh -o setup.sh
bash setup.sh
```

The script:
- Installs Python 3.12, build deps, Caddy, ufw
- Clones the repo to `~/spicydesichciago-agent`
- Sets up venvs in `api/.venv` and `agent/.venv`
- Symlinks `api/data` → `/var/lib/spicy-desi/data` so JSONL persists across redeploys
- Copies `.env.example` → `.env` for both services (you fill these in next)
- Installs systemd units and the Caddyfile
- Opens ports 80/443 in ufw + iptables (Oracle adds default-deny rules; the script bypasses them)

Idempotent — re-run any time.

## Step 3: Fill in the env files

```bash
nano ~/spicydesichciago-agent/api/.env
```

Required values:
```bash
TOOLS_SHARED_SECRET=<32+ char random — same on both sides>
SQUARE_ACCESS_TOKEN=<your Square production access token>
SQUARE_ENVIRONMENT=production
SQUARE_WEBHOOK_SIGNATURE_KEY=<from Square webhook subscription>
SQUARE_WEBHOOK_URL=https://api.spicydesichciago.com/api/webhooks/square

OWNER_PHONE=+1XXXXXXXXXX           # E.164 — owner's cell
ORDER_URL=https://order.spicydesi.com

TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=<your auth token>
TWILIO_FROM_NUMBER=+1XXXXXXXXXX    # your purchased Twilio number

AGENT_PUBLIC_URL=https://agent.spicydesichciago.com

# CORS for any future admin frontend
CORS_ORIGINS=https://spicydesichciago.com
```

Then the agent:
```bash
nano ~/spicydesichciago-agent/agent/.env
```

Required:
```bash
TOOLS_API_BASE=http://127.0.0.1:8080
TOOLS_SHARED_SECRET=<same as api/.env>

GROQ_API_KEY=<your Groq key>
DEEPGRAM_API_KEY=<your Deepgram key>
CARTESIA_API_KEY=<your Cartesia key>
CARTESIA_VOICE_ID=<your picked voice>

LLM_MODEL=openai/gpt-oss-120b      # recommended over default

TWILIO_AUTH_TOKEN=<same as api/.env>
```

## Step 4: Start everything

```bash
sudo systemctl start spicy-desi-api spicy-desi-agent caddy
sudo systemctl status spicy-desi-api spicy-desi-agent caddy
```

All three should show `active (running)`. Caddy will provision Let's Encrypt certs on first request — give it ~30 seconds and check:
```bash
curl https://api.spicydesichciago.com/healthz
# Expected: {"ok":true}
```

If certs aren't provisioning, check:
```bash
sudo journalctl -u caddy -n 100 --no-pager
```

Most common issue: DNS hasn't propagated. Verify with `dig api.spicydesichciago.com`.

## Step 5: Update Twilio webhooks

In Twilio Console → Phone Numbers → your number → Voice & Fax:

| Setting | Value |
|---|---|
| A call comes in | **Webhook** |
| URL | `https://agent.spicydesichciago.com/twilio/inbound` |
| HTTP | **POST** |

Save. Make a test call to your Twilio number — you should hear the greeting.

## Step 6: Watch logs

```bash
# All three services live tail
sudo journalctl -u spicy-desi-api -u spicy-desi-agent -u caddy -f

# Just the agent (for call debugging)
sudo journalctl -u spicy-desi-agent -f

# Last hour of errors
sudo journalctl --since "1 hour ago" -p err
```

## Updating

After pushing changes to `main`:
```bash
ssh -i ~/.ssh/spicy-desi-oracle ubuntu@<VM_PUBLIC_IP>
cd ~/spicydesichciago-agent
git pull
# Reinstall any new deps
cd api && .venv/bin/pip install -e .
cd ../agent && .venv/bin/pip install -e .
sudo systemctl restart spicy-desi-api spicy-desi-agent
```

To skip the manual step, the setup script can be re-run — it's idempotent.

## Troubleshooting

**Service won't start**
```bash
sudo systemctl status spicy-desi-api
sudo journalctl -u spicy-desi-api -n 100 --no-pager
```
Most often: missing env var, wrong path in the unit file, or Python import error.

**Calls connect but no audio / one-way audio**
Check Caddy WebSocket config — the `transport http` block in the Caddyfile is required for Twilio Media Streams.

**Let's Encrypt fails**
- Check ufw: `sudo ufw status`
- Check iptables: `sudo iptables -L INPUT -n | grep -E '80|443'`
- Try manually: `sudo caddy reload --config /etc/caddy/Caddyfile`

**JSONL data missing after redeploy**
The setup script symlinks `api/data` → `/var/lib/spicy-desi/data`. If it didn't, redo manually:
```bash
cd ~/spicydesichciago-agent/api
rm -rf data
ln -s /var/lib/spicy-desi/data data
```

## Capacity tuning

Single VM handles ~5-10 concurrent calls. To go higher:
1. Spin up a second VM with the same setup
2. Replace `127.0.0.1:8090` in Caddy with `127.0.0.1:8090, <VM2_IP>:8090` (round-robin)
3. Or front Caddy with a real load balancer

Plan 1 API state lives in `/var/lib/spicy-desi/data/` — for true multi-VM you'd migrate to Firestore (see PLAN_3.md when written).
