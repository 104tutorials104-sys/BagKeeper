# Deploy on Oracle Cloud Always Free

1. **Create the VM** (Oracle console -> Compute -> Instances -> Create)
   - Image: Ubuntu 22.04 (or 24.04). Shape: Ampere `VM.Standard.A1.Flex` (1-2 OCPU, 6-12 GB), or `E2.1.Micro`.
   - Networking: assign a public IPv4. Download the SSH private key when prompted.
   - Reserve the IP (Networking -> Reserved public IPs) so it never changes.
2. **Open ports** in Networking -> VCN -> Security Lists -> Default -> Add Ingress Rules:
   source `0.0.0.0/0`, TCP, destination ports `80` and `443`.
3. **SSH in:** `ssh -i <key> ubuntu@<public-ip>`
4. **Get the code** (repo is private): create a read-only deploy key.
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/bagkeeper_deploy -N ""
   cat ~/.ssh/bagkeeper_deploy.pub     # add under GitHub repo -> Settings -> Deploy keys (read-only)
   GIT_SSH_COMMAND="ssh -i ~/.ssh/bagkeeper_deploy -o IdentitiesOnly=yes" \
     git clone git@github.com:gufranmohammed48-git/BagKeeper.git
   ```
5. **Install and start:** `cd BagKeeper && bash deploy/setup.sh`
   (log out/in once if it just installed Docker, then re-run if needed).
6. **DNS (Cloudflare):** A record `bagkeeper` -> VM public IP, **DNS only** (grey cloud).
   Caddy then gets the HTTPS certificate automatically.
7. **Update later:** `cd BagKeeper && git pull && cd deploy && sudo docker compose up -d --build`
8. **Backups:** nightly in `deploy/data/backups`. Copy them off the server regularly.
