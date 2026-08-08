(function () {
  "use strict";

  var tokenInput = document.getElementById("bootstrap-token");
  var authBtn = document.getElementById("auth-btn");
  var sessionToken = localStorage.getItem("lab-session-token") || "";

  var QUICK = [
    { m: "GET", label: "目录 /api/ops", path: "" },
    { m: "GET", label: "engine/status", path: "engine/status" },
    { m: "GET", label: "engine/tasks", path: "engine/tasks", params: "limit=10" },
    { m: "GET", label: "engine/agents", path: "engine/agents" },
    { m: "GET", label: "engine/events", path: "engine/events", params: "limit=5" },
    { m: "GET", label: "ai/models", path: "ai/models" },
    { m: "GET", label: "ai/roles", path: "ai/roles" },
    { m: "GET", label: "ai/cost", path: "ai/cost" },
    { m: "GET", label: "memory/status", path: "memory/status" },
    { m: "GET", label: "memory/history", path: "memory/history" },
    { m: "GET", label: "memory/search", path: "memory/search", params: "query=你好" },
    { m: "GET", label: "config/snapshot", path: "config/snapshot" },
    { m: "GET", label: "agents/profiles", path: "agents/profiles" },
    { m: "GET", label: "messages（历史）", path: "messages", params: "limit=20" },
    { m: "GET", label: "activities（输出流）", path: "activities" },
    { m: "POST", label: "messages（发消息）", path: "messages", body: '{"text": "你好"}' },
    { m: "POST", label: "engine/pump", path: "engine/pump" },
    { m: "POST", label: "console/log（开日志）", path: "console/log", body: '{"enabled": true}' },
    { m: "POST", label: "console/clear", path: "console/clear" },
  ];

  var responsePre = document.getElementById("response");
  var responseHead = document.getElementById("response-head");

  function updateAuth() {
    var loggedIn = Boolean(sessionToken);
    authBtn.textContent = loggedIn ? "登出" : "登录";
    tokenInput.style.display = loggedIn ? "none" : "";
  }

  async function request(path, options) {
    var opts = Object.assign({}, options || {});
    opts.headers = Object.assign({}, opts.headers || {});
    if (sessionToken) opts.headers["Authorization"] = "Bearer " + sessionToken;
    var response = await fetch(path, opts);
    var body = await response.json().catch(function () {
      return null;
    });
    if (!response.ok) throw new Error("HTTP " + response.status + ": " + JSON.stringify(body));
    return body;
  }

  function flashAuth(message) {
    authBtn.disabled = true;
    authBtn.textContent = message;
    window.setTimeout(function () {
      authBtn.disabled = false;
      updateAuth();
    }, 2400);
  }

  async function login() {
    var token = tokenInput.value.trim();
    if (!token) {
      flashAuth("填 token 再登录");
      return;
    }
    try {
      var body = await request("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token_login: token }),
      });
      sessionToken = body.token;
      localStorage.setItem("lab-session-token", sessionToken);
      tokenInput.value = "";
      updateAuth();
    } catch (error) {
      flashAuth("登录失败");
    }
  }

  async function logout() {
    try {
      await request("/api/auth/logout", { method: "POST" });
    } catch (error) {
      /* 忽略登出错误 */
    }
    sessionToken = "";
    localStorage.removeItem("lab-session-token");
    updateAuth();
  }

  authBtn.addEventListener("click", function () {
    if (sessionToken) logout();
    else login();
  });

  function fillQuick(item) {
    document.getElementById("method").value = item.m;
    document.getElementById("path").value = item.path;
    document.getElementById("params").value = item.params || "";
    document.getElementById("body").value = item.body || "";
  }

  async function run() {
    var method = document.getElementById("method").value;
    var path = String(document.getElementById("path").value || "").trim();
    var params = String(document.getElementById("params").value || "").trim();
    var bodyRaw = document.getElementById("body").value.trim();
    var suffix = method === "GET" && params ? "?" + params.replace(/^\?/, "") : "";
    var url = "/api/ops/" + path + suffix;
    var runButton = document.getElementById("run-btn");
    runButton.disabled = true;
    responseHead.textContent = "请求中: " + method + " " + url;
    responseHead.className = "";
    try {
      var options = { method: method };
      if (method === "POST") {
        if (!bodyRaw) throw new Error("POST 需要请求体（JSON）");
        options.headers = { "Content-Type": "application/json" };
        options.body = bodyRaw;
      }
      var body = await request(url, options);
      var ok = body && body.ok;
      responseHead.textContent = method + " " + url + "  →  ok=" + ok + " code=" + (body ? body.code : "?");
      responseHead.className = ok ? "ok" : "err";
      responsePre.textContent = JSON.stringify(body, null, 2);
    } catch (error) {
      responseHead.textContent = method + " " + url + "  →  失败";
      responseHead.className = "err";
      responsePre.textContent = String(error.message);
    } finally {
      runButton.disabled = false;
    }
  }

  var list = document.getElementById("quick-list");
  var lastGroup = null;
  QUICK.forEach(function (item) {
    var groupName = item.m === "GET" ? "查询（GET）" : "命令（POST）";
    if (groupName !== lastGroup) {
      var heading = document.createElement("h3");
      heading.textContent = groupName;
      list.appendChild(heading);
      lastGroup = groupName;
    }
    var row = document.createElement("div");
    row.className = "quick";
    var tag = document.createElement("span");
    tag.className = "m" + (item.m === "POST" ? " post" : "");
    tag.textContent = item.m;
    var button = document.createElement("button");
    button.textContent = item.label;
    button.title = item.m + " /api/ops/" + item.path + (item.params ? "?" + item.params : "");
    button.addEventListener("click", function () {
      fillQuick(item);
    });
    row.appendChild(tag);
    row.appendChild(button);
    list.appendChild(row);
  });

  document.getElementById("run-btn").addEventListener("click", run);
  document.getElementById("path").addEventListener("keydown", function (event) {
    if (event.key === "Enter") run();
  });

  var root = document.documentElement;
  var storedTheme = localStorage.getItem("lab-theme");
  if (storedTheme === "dark" || storedTheme === "light") {
    root.setAttribute("data-theme", storedTheme);
  } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
    root.setAttribute("data-theme", "dark");
  }
  document.querySelector(".theme-toggle").addEventListener("click", function () {
    var nextTheme = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", nextTheme);
    localStorage.setItem("lab-theme", nextTheme);
  });

  updateAuth();
})();
