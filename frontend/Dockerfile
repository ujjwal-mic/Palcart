# Dockerfile for the PalCart FRONTEND (the React page)
# ====================================================
# Two stages:
#   1. "build": use Node to turn our React code into plain web files.
#   2. "serve": a tiny web server (nginx) hands those files out, and also
#      passes every /api/... request on to the backend container.

# ---- Stage 1: build the web files ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
# Leave empty to use the same address as the page (nginx forwards /api to the backend).
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---- Stage 2: serve them ----
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
