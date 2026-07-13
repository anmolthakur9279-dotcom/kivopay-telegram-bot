import { Router, type Request, type Response, type NextFunction } from "express";
import { createServer } from "http";

const router = Router();

const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "admin1234";
const BOT_INTERNAL_API = "http://127.0.0.1:8001";

// ─── Auth middleware ──────────────────────────────────────────────────────────
function requireAuth(req: Request, res: Response, next: NextFunction) {
  if ((req.session as any)?.admin === true) return next();
  res.redirect("/login");
}

function requireAuthApi(req: Request, res: Response, next: NextFunction) {
  if ((req.session as any)?.admin === true) return next();
  res.status(401).json({ error: "Unauthorized" });
}

// ─── Helper: proxy to Python internal API ────────────────────────────────────
async function pyFetch(path: string, options: RequestInit = {}) {
  const res = await fetch(`${BOT_INTERNAL_API}${path}`, options);
  return res;
}

// ─── Login page ──────────────────────────────────────────────────────────────
router.get("/login", (req: Request, res: Response) => {
  const failed = req.query.failed === "1";
  res.type("text/html").send(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Admin Login</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { min-height: 100vh; display: flex; align-items: center; justify-content: center;
           background: #0f1117; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    .card { background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 12px;
            padding: 40px 36px; width: 100%; max-width: 380px; }
    .logo { text-align: center; margin-bottom: 28px; }
    .logo-icon { font-size: 36px; display: block; margin-bottom: 8px; }
    h1 { color: #e2e8f0; font-size: 1.4rem; font-weight: 600; text-align: center; margin-bottom: 6px; }
    .subtitle { color: #64748b; font-size: 0.85rem; text-align: center; margin-bottom: 28px; }
    label { display: block; color: #94a3b8; font-size: 0.8rem; font-weight: 500;
            text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
    input[type="password"] { width: 100%; padding: 10px 14px; background: #0f1117;
      border: 1px solid #2a2d3a; border-radius: 8px; color: #e2e8f0; font-size: 0.95rem;
      outline: none; transition: border-color 0.2s; margin-bottom: 20px; }
    input[type="password"]:focus { border-color: #3b82f6; }
    button { width: 100%; padding: 11px; background: #3b82f6; color: #fff; border: none;
             border-radius: 8px; font-size: 0.95rem; font-weight: 600; cursor: pointer;
             transition: background 0.2s; }
    button:hover { background: #2563eb; }
    .error { background: #2d1b1b; border: 1px solid #7f1d1d; color: #fca5a5;
             border-radius: 8px; padding: 10px 14px; font-size: 0.85rem;
             margin-bottom: 20px; display: ${failed ? "block" : "none"}; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">
      <span class="logo-icon">🤖</span>
      <h1>Bot Admin Panel</h1>
      <p class="subtitle">Primary admin access only</p>
    </div>
    <div class="error">❌ Incorrect password. Try again.</div>
    <form method="POST" action="/login">
      <label for="password">Password</label>
      <input type="password" id="password" name="password" autofocus autocomplete="current-password" placeholder="Enter admin password" />
      <button type="submit">Sign In</button>
    </form>
  </div>
</body>
</html>`);
});

router.post("/login", (req: Request, res: Response) => {
  const { password } = req.body as { password?: string };
  if (password === ADMIN_PASSWORD) {
    (req.session as any).admin = true;
    res.redirect("/admin");
  } else {
    res.redirect("/login?failed=1");
  }
});

router.get("/logout", (req: Request, res: Response) => {
  req.session.destroy(() => res.redirect("/login"));
});

// ─── Dashboard page ───────────────────────────────────────────────────────────
router.get("/admin", requireAuth, (_req: Request, res: Response) => {
  res.type("text/html").send(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Bot Admin Dashboard</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #0f1117; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; }
    header { background: #1a1d27; border-bottom: 1px solid #2a2d3a; padding: 14px 24px;
             display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 10; }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.05rem; }
    .brand-icon { font-size: 1.4rem; }
    .header-actions { display: flex; align-items: center; gap: 16px; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e;
                  box-shadow: 0 0 6px #22c55e; animation: pulse 2s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
    .btn { padding: 7px 14px; border-radius: 7px; font-size: 0.82rem; font-weight: 600;
           cursor: pointer; border: none; transition: all 0.15s; }
    .btn-ghost { background: transparent; color: #94a3b8; border: 1px solid #2a2d3a; }
    .btn-ghost:hover { background: #2a2d3a; color: #e2e8f0; }
    .btn-primary { background: #3b82f6; color: #fff; }
    .btn-primary:hover { background: #2563eb; }
    .btn-danger { background: #dc2626; color: #fff; }
    .btn-danger:hover { background: #b91c1c; }
    .btn-sm { padding: 4px 10px; font-size: 0.75rem; }
    main { max-width: 1100px; margin: 0 auto; padding: 28px 20px; }
    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin-bottom: 28px; }
    .stat-card { background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 10px; padding: 18px 20px; }
    .stat-label { color: #64748b; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
    .stat-value { font-size: 1.8rem; font-weight: 700; color: #e2e8f0; }
    .stat-value.green { color: #22c55e; }
    .stat-value.red { color: #f87171; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
    @media(max-width:700px){ .grid-2 { grid-template-columns: 1fr; } }
    .panel { background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 10px; overflow: hidden; }
    .panel-header { padding: 14px 18px; border-bottom: 1px solid #2a2d3a;
                    display: flex; align-items: center; justify-content: space-between; }
    .panel-title { font-weight: 600; font-size: 0.9rem; color: #cbd5e1; }
    .panel-body { padding: 16px 18px; }
    .group-item { display: flex; align-items: center; justify-content: space-between;
                  padding: 9px 0; border-bottom: 1px solid #1e2130; }
    .group-item:last-child { border-bottom: none; }
    .group-name { font-size: 0.88rem; font-weight: 500; color: #e2e8f0; }
    .group-id { font-size: 0.72rem; color: #64748b; font-family: monospace; margin-top: 2px; }
    .task-card { background: #0f1117; border: 1px solid #2a2d3a; border-radius: 8px; padding: 14px; margin-bottom: 12px; }
    .task-card:last-child { margin-bottom: 0; }
    .task-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
    .task-id { font-weight: 700; font-size: 0.85rem; }
    .task-type { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
                 border-radius: 20px; font-size: 0.72rem; font-weight: 600; }
    .task-type.repeat { background: #1e3a5f; color: #60a5fa; }
    .task-type.schedule { background: #1e3a2a; color: #4ade80; }
    .task-detail { color: #94a3b8; font-size: 0.8rem; margin-bottom: 10px; }
    .task-content { color: #cbd5e1; font-size: 0.82rem; background: #1a1d27;
                    border-radius: 6px; padding: 7px 10px; margin-bottom: 10px;
                    white-space: pre-wrap; word-break: break-word; max-height: 60px; overflow: hidden; }
    .group-checkboxes { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
    .group-check-label { display: flex; align-items: center; gap: 5px; padding: 4px 10px;
      background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 20px; cursor: pointer;
      font-size: 0.75rem; color: #94a3b8; transition: all 0.15s; user-select: none; }
    .group-check-label:has(input:checked) { background: #1e3a5f; border-color: #3b82f6; color: #60a5fa; }
    .group-check-label input { display: none; }
    .task-footer { display: flex; gap: 8px; }
    .empty-state { color: #4b5563; text-align: center; padding: 24px; font-size: 0.85rem; }
    .broadcast-panel { margin-bottom: 20px; }
    textarea { width: 100%; background: #0f1117; border: 1px solid #2a2d3a; border-radius: 8px;
               color: #e2e8f0; font-size: 0.88rem; padding: 10px 12px; resize: vertical;
               min-height: 80px; outline: none; transition: border-color 0.2s; font-family: inherit; }
    textarea:focus { border-color: #3b82f6; }
    .bc-groups { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
    .bc-actions { display: flex; align-items: center; gap: 10px; }
    .bc-select-all { font-size: 0.75rem; color: #3b82f6; cursor: pointer; background: none;
                     border: none; text-decoration: underline; }
    .toast { position: fixed; bottom: 24px; right: 24px; background: #1a1d27;
             border: 1px solid #2a2d3a; border-radius: 10px; padding: 12px 18px;
             font-size: 0.85rem; color: #e2e8f0; opacity: 0; transform: translateY(8px);
             transition: all 0.3s; pointer-events: none; z-index: 100; }
    .toast.show { opacity: 1; transform: translateY(0); }
    .toast.success { border-color: #22c55e; background: #0f2a1a; color: #86efac; }
    .toast.error { border-color: #dc2626; background: #2d1b1b; color: #fca5a5; }
    .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #3b82f6;
               border-top-color: transparent; border-radius: 50%; animation: spin 0.6s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <header>
    <div class="brand"><span class="brand-icon">🤖</span> Bot Admin Dashboard</div>
    <div class="header-actions">
      <span class="status-dot"></span>
      <span id="status-text" style="color:#94a3b8;font-size:0.8rem">Loading...</span>
      <a href="/logout"><button class="btn btn-ghost">Sign Out</button></a>
    </div>
  </header>
  <main>
    <div class="stats-grid" id="stats-grid">
      <div class="stat-card"><div class="stat-label">Tracked Groups</div><div class="stat-value" id="stat-groups">—</div></div>
      <div class="stat-card"><div class="stat-label">Active Tasks</div><div class="stat-value" id="stat-tasks">—</div></div>
      <div class="stat-card"><div class="stat-label">Public Access</div><div class="stat-value" id="stat-public">—</div></div>
      <div class="stat-card"><div class="stat-label">Broadcast</div><div class="stat-value" id="stat-broadcast">—</div></div>
      <div class="stat-card"><div class="stat-label">Translation</div><div class="stat-value" id="stat-trans">—</div></div>
    </div>

    <!-- Broadcast Panel -->
    <div class="panel broadcast-panel">
      <div class="panel-header">
        <span class="panel-title">📢 Manual Broadcast</span>
        <button class="btn btn-sm btn-ghost bc-select-all" onclick="toggleAllBcGroups()">Select All</button>
      </div>
      <div class="panel-body">
        <textarea id="bc-text" placeholder="Type your broadcast message here..."></textarea>
        <div class="bc-groups" id="bc-groups-list"><span style="color:#4b5563;font-size:0.8rem">Loading groups...</span></div>
        <div class="bc-actions">
          <button class="btn btn-primary" id="bc-send-btn" onclick="sendBroadcast()">Send Broadcast</button>
          <span style="color:#64748b;font-size:0.78rem" id="bc-hint">No groups selected — will send to all</span>
        </div>
      </div>
    </div>

    <div class="grid-2">
      <!-- Groups Panel -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">📋 Tracked Groups</span>
          <span id="groups-count" style="color:#64748b;font-size:0.78rem"></span>
        </div>
        <div class="panel-body" id="groups-list">
          <div class="empty-state">Loading...</div>
        </div>
      </div>

      <!-- Tasks Panel -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">⚙️ Active Tasks</span>
          <span id="tasks-count" style="color:#64748b;font-size:0.78rem"></span>
        </div>
        <div class="panel-body" id="tasks-list">
          <div class="empty-state">Loading...</div>
        </div>
      </div>
    </div>
  </main>
  <div class="toast" id="toast"></div>

  <script>
    let allGroups = [];
    let bcAllSelected = false;

    function showToast(msg, type = 'success') {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.className = 'toast show ' + type;
      setTimeout(() => t.className = 'toast', 3000);
    }

    async function loadStatus() {
      try {
        const r = await fetch('/api/admin/status');
        const d = await r.json();
        document.getElementById('stat-groups').textContent = d.tracked_groups;
        document.getElementById('stat-tasks').textContent = d.active_tasks;
        document.getElementById('stat-public').textContent = d.public_access ? '✅' : '🔒';
        document.getElementById('stat-public').className = 'stat-value ' + (d.public_access ? 'green' : 'red');
        document.getElementById('stat-broadcast').textContent = d.broadcast ? '✅' : '❌';
        document.getElementById('stat-broadcast').className = 'stat-value ' + (d.broadcast ? 'green' : 'red');
        document.getElementById('stat-trans').textContent = d.translation ? '✅' : '❌';
        document.getElementById('stat-trans').className = 'stat-value ' + (d.translation ? 'green' : 'red');
        document.getElementById('status-text').textContent = 'Bot Online';
      } catch(e) {
        document.getElementById('status-text').textContent = 'Bot Offline';
      }
    }

    async function loadGroups() {
      try {
        const r = await fetch('/api/admin/groups');
        allGroups = await r.json();
        document.getElementById('groups-count').textContent = allGroups.length + ' group(s)';
        const el = document.getElementById('groups-list');
        if (!allGroups.length) { el.innerHTML = '<div class="empty-state">No groups tracked yet</div>'; return; }
        el.innerHTML = allGroups.map(g => \`
          <div class="group-item">
            <div>
              <div class="group-name">\${escHtml(g.name)}</div>
              <div class="group-id">\${g.id}</div>
            </div>
          </div>\`).join('');
        renderBcGroups();
      } catch(e) {
        document.getElementById('groups-list').innerHTML = '<div class="empty-state">Failed to load groups</div>';
      }
    }

    function renderBcGroups() {
      const el = document.getElementById('bc-groups-list');
      if (!allGroups.length) { el.innerHTML = '<span style="color:#4b5563;font-size:0.8rem">No groups tracked</span>'; return; }
      el.innerHTML = allGroups.map(g => \`
        <label class="group-check-label">
          <input type="checkbox" name="bc-group" value="\${g.id}" onchange="updateBcHint()">
          \${escHtml(g.name)}
        </label>\`).join('');
    }

    function updateBcHint() {
      const checked = document.querySelectorAll('input[name="bc-group"]:checked');
      document.getElementById('bc-hint').textContent = checked.length
        ? \`Sending to \${checked.length} selected group(s)\`
        : 'No groups selected — will send to all';
    }

    function toggleAllBcGroups() {
      const boxes = document.querySelectorAll('input[name="bc-group"]');
      bcAllSelected = !bcAllSelected;
      boxes.forEach(b => b.checked = bcAllSelected);
      updateBcHint();
    }

    async function loadTasks() {
      try {
        const r = await fetch('/api/admin/tasks');
        const tasks = await r.json();
        document.getElementById('tasks-count').textContent = tasks.length + ' task(s)';
        const el = document.getElementById('tasks-list');
        if (!tasks.length) { el.innerHTML = '<div class="empty-state">No active tasks</div>'; return; }
        el.innerHTML = tasks.map(t => {
          const ttype = t.type || '?';
          const emoji = ttype === 'repeat' ? '🔁' : '⏰';
          const detail = ttype === 'repeat'
            ? \`Every \${t.interval_hours}h\`
            : \`Daily at \${t.scheduled_time}\`;
          const content = t.photo_file_id ? '📷 Photo' : (t.text || '').slice(0, 60);
          const tgMap = (t.targeted_groups || []).map(String);
          const groupChecks = allGroups.map(g => {
            const checked = tgMap.includes(String(g.id)) ? 'checked' : '';
            return \`<label class="group-check-label">
              <input type="checkbox" class="task-group-cb" data-tid="\${t.id}" value="\${g.id}" \${checked}>
              \${escHtml(g.name)}
            </label>\`;
          }).join('');
          return \`<div class="task-card" id="task-\${t.id}">
            <div class="task-header">
              <span class="task-id">#\${t.id}</span>
              <span class="task-type \${ttype}">\${emoji} \${ttype}</span>
            </div>
            <div class="task-detail">\${detail}</div>
            <div class="task-content">\${escHtml(content)}</div>
            <div class="group-checkboxes">\${groupChecks || '<span style="color:#4b5563;font-size:0.75rem">No groups tracked</span>'}</div>
            <div class="task-footer">
              <button class="btn btn-sm btn-primary" onclick="saveTaskGroups(\${t.id})">Save Groups</button>
              <button class="btn btn-sm btn-danger" onclick="deleteTask(\${t.id})">Stop Task</button>
            </div>
          </div>\`;
        }).join('');
      } catch(e) {
        document.getElementById('tasks-list').innerHTML = '<div class="empty-state">Failed to load tasks</div>';
      }
    }

    async function saveTaskGroups(tid) {
      const boxes = document.querySelectorAll(\`.task-group-cb[data-tid="\${tid}"]:checked\`);
      const groups = Array.from(boxes).map(b => String((b as HTMLInputElement).value));
      try {
        const r = await fetch(\`/api/admin/tasks/\${tid}\`, {
          method: 'PATCH',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ targeted_groups: groups })
        });
        if (r.ok) showToast(\`Task #\${tid} groups updated\`);
        else showToast('Failed to update task', 'error');
      } catch(e) { showToast('Network error', 'error'); }
    }

    async function deleteTask(tid) {
      if (!confirm(\`Stop task #\${tid}?\`)) return;
      try {
        const r = await fetch(\`/api/admin/tasks/\${tid}\`, { method: 'DELETE' });
        if (r.ok) { showToast(\`Task #\${tid} stopped\`); loadTasks(); loadStatus(); }
        else showToast('Failed to stop task', 'error');
      } catch(e) { showToast('Network error', 'error'); }
    }

    async function sendBroadcast() {
      const text = (document.getElementById('bc-text') as HTMLTextAreaElement).value.trim();
      if (!text) { showToast('Enter a message first', 'error'); return; }
      const checked = document.querySelectorAll('input[name="bc-group"]:checked');
      const tg = checked.length ? Array.from(checked).map(b => String((b as HTMLInputElement).value)) : null;
      const btn = document.getElementById('bc-send-btn') as HTMLButtonElement;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Sending...';
      try {
        const r = await fetch('/api/admin/broadcast', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ text, targeted_groups: tg })
        });
        const d = await r.json();
        if (r.ok) {
          showToast(\`Broadcast sent to \${d.targets} group(s)\`);
          (document.getElementById('bc-text') as HTMLTextAreaElement).value = '';
        } else { showToast(d.error || 'Broadcast failed', 'error'); }
      } catch(e) { showToast('Network error', 'error'); }
      btn.disabled = false;
      btn.textContent = 'Send Broadcast';
    }

    function escHtml(str) {
      return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    async function loadAll() {
      await loadStatus();
      await loadGroups();
      await loadTasks();
    }

    loadAll();
    setInterval(loadAll, 15000);
  </script>
</body>
</html>`);
});

// ─── API routes (protected) ───────────────────────────────────────────────────
router.get("/api/admin/status", requireAuthApi, async (_req, res) => {
  try {
    const r = await pyFetch("/status");
    const data = await r.json();
    res.json(data);
  } catch {
    res.status(503).json({ error: "Bot internal API unreachable" });
  }
});

router.get("/api/admin/groups", requireAuthApi, async (_req, res) => {
  try {
    const r = await pyFetch("/groups");
    const data = await r.json();
    res.json(data);
  } catch {
    res.status(503).json({ error: "Bot internal API unreachable" });
  }
});

router.get("/api/admin/tasks", requireAuthApi, async (_req, res) => {
  try {
    const r = await pyFetch("/tasks");
    const data = await r.json();
    res.json(data);
  } catch {
    res.status(503).json({ error: "Bot internal API unreachable" });
  }
});

router.patch("/api/admin/tasks/:id", requireAuthApi, async (req, res) => {
  try {
    const { id } = req.params;
    const r = await pyFetch(`/tasks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req.body),
    });
    const data = await r.json();
    res.status(r.status).json(data);
  } catch {
    res.status(503).json({ error: "Bot internal API unreachable" });
  }
});

router.delete("/api/admin/tasks/:id", requireAuthApi, async (req, res) => {
  try {
    const { id } = req.params;
    const r = await pyFetch(`/tasks/${id}`, { method: "DELETE" });
    const data = await r.json();
    res.status(r.status).json(data);
  } catch {
    res.status(503).json({ error: "Bot internal API unreachable" });
  }
});

router.post("/api/admin/broadcast", requireAuthApi, async (req, res) => {
  try {
    const r = await pyFetch("/broadcast", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req.body),
    });
    const data = await r.json();
    res.status(r.status).json(data);
  } catch {
    res.status(503).json({ error: "Bot internal API unreachable" });
  }
});

export default router;
