const http = require("http");
const httpProxy = require("http-proxy");

const proxy = httpProxy.createProxyServer({
  ws: true,
  changeOrigin: true,
});

const server = http.createServer((req, res) => {
  const url = req.url || "";

  if (url === "/health" || url === "/health/") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, service: "cspe-vr-proxy", port: 8080 }));
    return;
  }

  if (url.startsWith("/api")) {
    proxy.web(req, res, { target: "http://127.0.0.1:8787" });
    return;
  }

  if (url.startsWith("/viewer") || url.startsWith("/_next")) {
    proxy.web(req, res, { target: "http://127.0.0.1:3000" });
    return;
  }

  proxy.web(req, res, { target: "http://127.0.0.1:5173" });
});

server.on("upgrade", (req, socket, head) => {
  const url = req.url || "";

  if (url.startsWith("/viewer") || url.startsWith("/_next")) {
    proxy.ws(req, socket, head, { target: "http://127.0.0.1:3000" });
    return;
  }

  proxy.ws(req, socket, head, { target: "http://127.0.0.1:5173" });
});

server.listen(8080, "0.0.0.0", () => {
  console.log("VR proxy running on http://0.0.0.0:8080");
  console.log("Frontend -> /");
  console.log("GraphXR  -> /viewer and /_next");
  console.log("API      -> /api");
});