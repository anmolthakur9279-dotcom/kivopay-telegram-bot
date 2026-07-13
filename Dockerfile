FROM node:22-bookworm

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN corepack enable

RUN corepack prepare pnpm@latest --activate

RUN pnpm install

RUN pnpm build

RUN pip3 install --no-cache-dir -r <(printf "pytelegrambotapi\ngoogle-genai\ngoogle-generativeai\npillow")

EXPOSE 8080

CMD ["bash", "start_production.sh"]
