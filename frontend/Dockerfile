ARG BASE_REGISTRY=public.ecr.aws/docker/library
FROM ${BASE_REGISTRY}/node:22-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM ${BASE_REGISTRY}/nginx:1.27-alpine

COPY nginx.conf /etc/nginx/knowledge.conf.template
COPY 40-knowledge-budget.sh /docker-entrypoint.d/40-knowledge-budget.sh
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
