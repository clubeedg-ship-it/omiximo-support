# syntax=docker/dockerfile:1
#
# Production image for the Omiximo Support frontend.
#
# Previously this image ran `npm run dev` (the Vite dev server) in the cluster.
# A dev server keeps the whole module graph + file watcher resident in memory,
# which is why the frontend pod was repeatedly OOMKilled. This builds the static
# bundle once and serves it with nginx — a few MB of RAM instead of hundreds.
#
# Vite inlines `import.meta.env.VITE_*` at BUILD time, so the API URL and Clerk
# config must be passed as build args (see k8s/README.md for the build command).

FROM node:22-alpine AS build

WORKDIR /app
ENV CI=true

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Baked into the bundle at build time.
ARG VITE_API_URL
ARG VITE_CLERK_PUBLISHABLE_KEY
ARG VITE_CLERK_JWT_TEMPLATE
ARG VITE_ALLOW_INSECURE_DEV_AUTH_BYPASS
ENV VITE_API_URL=$VITE_API_URL \
    VITE_CLERK_PUBLISHABLE_KEY=$VITE_CLERK_PUBLISHABLE_KEY \
    VITE_CLERK_JWT_TEMPLATE=$VITE_CLERK_JWT_TEMPLATE \
    VITE_ALLOW_INSECURE_DEV_AUTH_BYPASS=$VITE_ALLOW_INSECURE_DEV_AUTH_BYPASS

RUN npm run build


FROM nginx:1.27-alpine AS runtime

# Listen on 5173 so the Kubernetes Service targetPort / NodePort (30173) and the
# host-nginx upstream stay unchanged across the cutover.
COPY nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 5173

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:5173/healthz >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
