import type { Plugin } from 'vite';

import { fileURLToPath } from 'node:url';

import { loadEnv } from 'vite';

const loopbackHosts = new Set(['127.0.0.1', '[::1]', 'localhost']);
const loopbackAddresses = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1']);

/** 仅向本机同源页面提供运行期凭证，不参与静态构建或预览。 */
export function panelConnection(envDir = fileURLToPath(new URL('../../../', import.meta.url))): Plugin {
  return {
    name: 'aurora-panel-connection',
    apply: 'serve',
    configureServer(server) {
      const env = loadEnv(server.config.mode, envDir, 'AURORA_');
      server.middlewares.use((request, response, next) => {
        if (request.url?.split('?')[0] !== '/__aurora/connection') return next();
        response.removeHeader('Access-Control-Allow-Origin');
        response.removeHeader('Access-Control-Allow-Credentials');
        response.setHeader('Cache-Control', 'no-store');
        response.setHeader('X-Content-Type-Options', 'nosniff');
        response.setHeader('Content-Type', 'application/json');
        const deny = (status: number) => {
          response.statusCode = status;
          response.end();
        };
        let origin: URL;
        try {
          origin = new URL(`${server.config.server.https ? 'https' : 'http'}://${request.headers.host}`);
        } catch {
          return deny(403);
        }
        if (
          !loopbackHosts.has(origin.hostname) ||
          !loopbackAddresses.has(request.socket.remoteAddress ?? '') ||
          request.headers.origin !== origin.origin ||
          request.headers['x-aurora-panel'] !== '1' ||
          (request.headers['sec-fetch-site'] && request.headers['sec-fetch-site'] !== 'same-origin')
        ) {
          return deny(403);
        }
        if (request.method !== 'POST') return deny(405);
        const token = env.AURORA_API_TOKEN;
        if (!token) return deny(204);
        let url: URL;
        try {
          url = new URL(env.AURORA_API_URL || 'http://127.0.0.1:10270');
          if (
            !['http:', 'https:'].includes(url.protocol) ||
            url.username ||
            url.password ||
            url.search ||
            url.hash ||
            url.pathname !== '/' ||
            !/^[A-Za-z0-9_-]{32,256}$/u.test(token)
          )
            throw new Error('invalid');
        } catch {
          return deny(503);
        }
        response.end(JSON.stringify({ url: url.origin, token }));
      });
    },
  };
}
