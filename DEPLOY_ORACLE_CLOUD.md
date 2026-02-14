# 🚀 Deploying WhatsApp Bot to Oracle Cloud (Free Forever)

This guide takes you from zero to a 24/7 running bot. No Docker experience needed.

---

## Step 1: Create an Oracle Cloud Account

1. Go to [cloud.oracle.com](https://cloud.oracle.com) and click **Sign Up**
2. Fill in your details — you'll need a credit card but **you will NOT be charged** (it's only for verification)
3. Select a **Home Region** close to you (e.g., `eu-frankfurt-1` or `me-jeddah-1`)
4. Wait for your account to be provisioned (usually 5–15 minutes)

---

## Step 2: Create a Free VM

1. Log in to the Oracle Cloud Console
2. Click the **hamburger menu** (☰) → **Compute** → **Instances**
3. Click **Create Instance**
4. Configure it:
   - **Name**: `whatsapp-bot`
   - **Image**: Click **Edit** → choose **Ubuntu 22.04** (or the latest Canonical Ubuntu)
   - **Shape**: Click **Change Shape** → **Ampere** → select `VM.Standard.A1.Flex`
     - Set **1 OCPU** and **6 GB RAM** (this is within the free tier)
   - **Networking**: Leave defaults (it auto-creates a VCN)
   - **SSH Key**: Click **Generate a key pair** → **Save Private Key** (download the `.key` file!)
     - Save this file somewhere safe, you'll need it to connect
5. Click **Create**
6. Wait until the instance shows **RUNNING** (1–3 minutes)
7. Copy the **Public IP Address** shown on the instance page

---

## Step 3: Connect to Your VM

### On Windows (using PowerShell):

```powershell
# Navigate to where you saved the SSH key
cd C:\Users\youss\Downloads

# Connect (replace <YOUR_IP> with the Public IP from Step 2)
ssh -i ssh-key-*.key ubuntu@<YOUR_IP>
```

> **If you get a "permissions too open" error**, run this first:
> ```powershell
> icacls "ssh-key-*.key" /inheritance:r /grant:r "$($env:USERNAME):(R)"
> ```

You should now see a terminal prompt like `ubuntu@whatsapp-bot:~$`. You're on the cloud server!

---

## Step 4: Install Docker on the VM

Copy and paste these commands one block at a time into the SSH terminal:

```bash
# Update the system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh

# Install Docker Compose
sudo apt install -y docker-compose

# Allow your user to run Docker without sudo
sudo usermod -aG docker $USER

# Apply the group change (or just log out and back in)
newgrp docker
```

Verify it works:
```bash
docker --version
# Should print: Docker version 24.x or 25.x
```

---

## Step 5: Upload Your Bot to the VM

### Option A: Using Git (Recommended)

If your project is on GitHub:
```bash
git clone https://github.com/YOUR_USERNAME/whatsapp-clawdbot.git
cd whatsapp-clawdbot/files
```

### Option B: Using SCP (Direct Upload from Your Laptop)

Open a **new PowerShell window on your laptop** (keep the SSH session open):

```powershell
# Upload from your laptop to the server
scp -i C:\Users\youss\Downloads\ssh-key-*.key -r D:\whatsapp-clawdbot\files ubuntu@<YOUR_IP>:~/whatsapp-bot
```

Then back in your SSH session:
```bash
cd ~/whatsapp-bot
```

---

## Step 6: Set Up Your Environment

```bash
# Create the .env file with your API keys
nano .env
```

Paste your `.env` contents (same as on your laptop). Press `Ctrl+X`, then `Y`, then `Enter` to save.

> **Important**: Make sure `GOOGLE_API_KEY` and `ADMIN_PHONE_NUMBERS` are set correctly.

---

## Step 7: Build and Run the Bot

```bash
# Build the Docker image (first time takes ~3-5 minutes)
docker-compose build

# Start the bot (the -d flag runs it in the background)
docker-compose up -d

# Watch the logs to scan the QR code
docker-compose logs -f
```

You'll see something like:
```
whatsapp-clawdbot  | Scan this QR code in WhatsApp:
whatsapp-clawdbot  | ▄▄▄▄▄▄▄▄▄▄▄▄▄
whatsapp-clawdbot  | █ ▄▄▄▄▄ █ ▀▀█
whatsapp-clawdbot  | ...
```

### Scan the QR Code:
1. Open WhatsApp on your phone
2. Go to **Settings** → **Linked Devices** → **Link a Device**
3. Scan the QR code shown in the terminal

After scanning, you'll see:
```
WhatsApp authenticated
WhatsApp ClawdBot ready!
```

Press `Ctrl+C` to stop watching logs (the bot keeps running in the background!).

---

## Step 8: Open Firewall (Oracle-Specific)

Oracle blocks all incoming traffic by default. This doesn't affect the bot (it only makes outgoing connections), but if you ever need port access:

1. Oracle Console → **Networking** → **Virtual Cloud Networks**
2. Click your VCN → **Security Lists** → **Default Security List**
3. Add an **Ingress Rule** for port 8000 if needed

**For the bot, you don't need to do this** — it works without any open ports.

---

## Everyday Commands (Cheat Sheet)

SSH into your server first, then:

```bash
# Navigate to bot directory
cd ~/whatsapp-bot            # or ~/whatsapp-clawdbot/files

# See if bot is running
docker-compose ps

# View live logs
docker-compose logs -f

# View last 50 lines of logs
docker-compose logs --tail 50

# Restart the bot
docker-compose restart

# Stop the bot
docker-compose down

# Start the bot again
docker-compose up -d

# Rebuild after code changes
docker-compose build && docker-compose up -d

# View how much disk/memory the bot uses
docker stats whatsapp-clawdbot
```

---

## Updating the Bot

When you make changes to the code on your laptop:

```powershell
# From your laptop — upload changes
scp -i C:\Users\youss\Downloads\ssh-key-*.key -r D:\whatsapp-clawdbot\files ubuntu@<YOUR_IP>:~/whatsapp-bot
```

Then on the server:
```bash
cd ~/whatsapp-bot
docker-compose build && docker-compose up -d
```

> **Your WhatsApp session is preserved** — you won't need to scan the QR code again because the `session/` folder is mounted as a volume.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| QR code doesn't appear | Run `docker-compose logs -f` and wait 30 seconds |
| Bot stops responding | `docker-compose restart` |
| "No space left on device" | `docker system prune -a` (cleans old images) |
| Session expired | `docker-compose down`, delete `session/` folder, `docker-compose up -d`, re-scan QR |
| Need to see what went wrong | `docker-compose logs --tail 100` |
| VM ran out of memory | Reduce ChromaDB usage or increase VM RAM to 6GB |

---

## Cost Summary

| Resource | Free Tier Allowance | Your Usage |
|----------|-------------------|------------|
| Compute (A1.Flex) | 4 OCPUs + 24GB RAM | 1 OCPU + 6GB ✅ |
| Boot Volume | 200 GB total | 47 GB ✅ |
| Outbound Data | 10 TB/month | ~negligible ✅ |
| **Total Cost** | | **$0/month forever** |
