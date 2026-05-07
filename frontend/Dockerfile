FROM node:22-alpine

WORKDIR /app

# Install dependencies before copying full source for better layer caching
COPY package.json package-lock.json ./
RUN npm install

# Copy application source
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
