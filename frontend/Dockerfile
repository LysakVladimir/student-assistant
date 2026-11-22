FROM node:20.19-bookworm-slim

WORKDIR /app

COPY package*.json ./

RUN npm install -g npm@10.9.2 \
    && npm cache clean --force \
    && npm install --no-audit --no-fund

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
