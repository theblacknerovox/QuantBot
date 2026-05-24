#!/bin/bash
# QuantBot AI — Script de Deploy para VPS Ubuntu 22.04
# Uso: bash deploy.sh

set -e  # Parar em caso de erro

echo "
╔═══════════════════════════════════════╗
║       QuantBot AI — Deploy Script     ║
╚═══════════════════════════════════════╝
"

# ─── VARIÁVEIS ────────────────────────────────────────────────────────────────
PROJECT_DIR="/opt/quantbot"
REPO_URL="https://github.com/seuusuario/quantbot-ai.git"  # Altere aqui
DOMAIN="seudominio.com"  # Altere aqui

# ─── 1. ATUALIZAR SISTEMA ─────────────────────────────────────────────────────
echo "📦 [1/8] Atualizando sistema..."
apt-get update -qq && apt-get upgrade -y -qq

# ─── 2. INSTALAR DEPENDÊNCIAS ─────────────────────────────────────────────────
echo "🔧 [2/8] Instalando dependências..."
apt-get install -y -qq \
    docker.io docker-compose-v2 \
    nginx certbot python3-certbot-nginx \
    git curl wget ufw fail2ban

# Iniciar Docker
systemctl enable docker
systemctl start docker

# ─── 3. CONFIGURAR FIREWALL ───────────────────────────────────────────────────
echo "🔒 [3/8] Configurando firewall..."
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ─── 4. CLONAR PROJETO ────────────────────────────────────────────────────────
echo "📂 [4/8] Clonando projeto..."
if [ -d "$PROJECT_DIR" ]; then
    cd "$PROJECT_DIR" && git pull origin main
else
    git clone "$REPO_URL" "$PROJECT_DIR"
fi
cd "$PROJECT_DIR"

# ─── 5. CONFIGURAR .ENV ───────────────────────────────────────────────────────
echo "⚙️  [5/8] Configurando variáveis de ambiente..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    # Gerar secrets aleatórios
    SECRET_KEY=$(openssl rand -hex 32)
    ENCRYPTION_KEY=$(openssl rand -hex 16)
    JWT_SECRET=$(openssl rand -hex 32)
    POSTGRES_PASS=$(openssl rand -base64 24)
    
    sed -i "s/TROQUE_POR_UMA_CHAVE_SECRETA_DE_64_CHARS_MINIMO/$SECRET_KEY/" .env
    sed -i "s/CHAVE_AES256_PARA_CREDENCIAIS_BINANCE_32BYTES/$ENCRYPTION_KEY/" .env
    sed -i "s/OUTRO_SECRET_PARA_JWT_DIFERENTE_DO_APP_SECRET/$JWT_SECRET/" .env
    sed -i "s/senha_forte/$POSTGRES_PASS/g" .env
    
    echo ""
    echo "⚠️  IMPORTANTE: Edite o arquivo .env e adicione:"
    echo "   - OPENAI_API_KEY ou GEMINI_API_KEY"
    echo "   - Demais configurações personalizadas"
    echo ""
    read -p "Pressione ENTER após editar o .env para continuar..."
fi

# ─── 6. BUILD E START ─────────────────────────────────────────────────────────
echo "🐳 [6/8] Build Docker..."
docker compose build --no-cache

echo "🚀 [7/8] Iniciando serviços..."
docker compose up -d

# Aguardar banco inicializar
echo "⏳ Aguardando banco de dados..."
sleep 15

# Verificar saúde dos containers
docker compose ps

# ─── 7. SSL COM CERTBOT ───────────────────────────────────────────────────────
echo "🔐 [8/8] Configurando SSL..."
if [ ! -z "$DOMAIN" ] && [ "$DOMAIN" != "seudominio.com" ]; then
    certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --non-interactive --agree-tos \
        --email "admin@$DOMAIN" --redirect
    
    # Renovação automática
    (crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet") | crontab -
fi

# ─── DONE ─────────────────────────────────────────────────────────────────────
echo "
╔═══════════════════════════════════════╗
║          ✅ Deploy concluído!          ║
╚═══════════════════════════════════════╝

🌐 Frontend:  http://$DOMAIN (ou http://IP_DO_SERVIDOR)
🔌 Backend:   http://$DOMAIN/api
📊 API Docs:  http://$DOMAIN/api/docs

📋 Comandos úteis:
  Ver logs:    docker compose logs -f
  Reiniciar:   docker compose restart
  Parar:       docker compose down
  Status:      docker compose ps
"
