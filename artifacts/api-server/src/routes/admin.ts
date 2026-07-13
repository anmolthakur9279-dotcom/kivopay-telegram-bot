import { Router, type Request, type Response, type NextFunction } from "express";
import multer from "multer";
import path from "path";
import fs from "fs";

const router = Router();

const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "admin1234";
const BOT_INTERNAL_API = "http://127.0.0.1:8001";
const UPLOADS_DIR = path.resolve(process.cwd(), "uploads");

// Ensure uploads directory exists
if (!fs.existsSync(UPLOADS_DIR)) fs.mkdirSync(UPLOADS_DIR, { recursive: true });

// Multer storage
const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, UPLOADS_DIR),
  filename: (_req, file, cb) => {
    const ext = path.extname(file.originalname);
    cb(null, `${Date.now()}_${Math.random().toString(36).slice(2)}${ext}`);
  },
});
const upload = multer({
  storage,
  limits: { fileSize: 20 * 1024 * 1024 }, // 20MB
  fileFilter: (_req, file, cb) => {
    if (file.mimetype.startsWith("image/")) cb(null, true);
    else cb(new Error("Only image files allowed"));
  },
});

// ─── Auth middleware ──────────────────────────────────────────────────────────
function requireAuth(req: Request, res: Response, next: NextFunction) {
  if ((req.session as any)?.admin === true) return next();
  res.redirect("/login");
}
function requireAuthApi(req: Request, res: Response, next: NextFunction) {
  if ((req.session as any)?.admin === true) return next();
  res.status(401).json({ error: "Unauthorized" });
}

// ─── Helper: call Python internal API ────────────────────────────────────────
async function pyFetch(path: string, options: RequestInit = {}, timeoutMs = 4000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BOT_INTERNAL_API}${path}`, { ...options, signal: ctrl.signal });
    return res;
  } finally {
    clearTimeout(timer);
  }
}

// ─── Fallback: read JSON files directly if bot is unreachable ────────────────
function readJsonFile(filePath: string, fallback: any) {
  try {
    const raw = fs.readFileSync(filePath, "utf8");
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function getGroupsFallback(): any[] {
  const raw = readJsonFile(path.resolve(process.cwd(), "tracked_groups.json"), {});
  if (Array.isArray(raw)) return raw.map((id: number) => ({ id, name: `Group ${id}` }));
  return Object.values(raw as Record<string, any>);
}

function getTasksFallback(): any[] {
  const raw = readJsonFile(path.resolve(process.cwd(), "active_tasks.json"), { tasks: {} });
  return Object.values((raw.tasks || raw) as Record<string, any>);
}

function getStatusFallback() {
  const groups = getGroupsFallback();
  const tasks = getTasksFallback();
  return { tracked_groups: groups.length, active_tasks: tasks.length, public_access: true, translation: true, broadcast: true, schedule: true, repeat: true };
}

// ─── Login page ──────────────────────────────────────────────────────────────
router.get("/login", (req: Request, res: Response) => {
  const failed = req.query.failed === "1";
  res.type("text/html").send(`<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Admin Login</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;
     background:#0f1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.card{background:#1a1d27;border:1px solid #2a2d3a;border-radius:12px;padding:40px 36px;width:100%;max-width:380px}
.logo{text-align:center;margin-bottom:28px}
.logo-icon{font-size:36px;display:block;margin-bottom:8px}
h1{color:#e2e8f0;font-size:1.4rem;font-weight:600;text-align:center;margin-bottom:6px}
.sub{color:#64748b;font-size:.85rem;text-align:center;margin-bottom:28px}
label{display:block;color:#94a3b8;font-size:.8rem;font-weight:500;text-transform:uppercase;
      letter-spacing:.05em;margin-bottom:6px}
input[type=password]{width:100%;padding:10px 14px;background:#0f1117;border:1px solid #2a2d3a;
  border-radius:8px;color:#e2e8f0;font-size:.95rem;outline:none;transition:border-color .2s;margin-bottom:20px}
input[type=password]:focus{border-color:#3b82f6}
button{width:100%;padding:11px;background:#3b82f6;color:#fff;border:none;border-radius:8px;
       font-size:.95rem;font-weight:600;cursor:pointer;transition:background .2s}
button:hover{background:#2563eb}
.err{background:#2d1b1b;border:1px solid #7f1d1d;color:#fca5a5;border-radius:8px;
     padding:10px 14px;font-size:.85rem;margin-bottom:20px;display:${failed?"block":"none"}}
</style></head><body>
<div class="card">
  <div class="logo"><span class="logo-icon">🤖</span><h1>Bot Admin Panel</h1><p class="sub">Primary admin access only</p></div>
  <div class="err">❌ Incorrect password. Try again.</div>
  <form method="POST" action="/login">
    <label for="pw">Password</label>
    <input type="password" id="pw" name="password" autofocus autocomplete="current-password" placeholder="Enter admin password"/>
    <button type="submit">Sign In →</button>
  </form>
</div></body></html>`);
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
<html lang="en"><head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Bot Admin Dashboard</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#0f1117;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}
header{background:#1a1d27;border-bottom:1px solid #2a2d3a;padding:14px 24px;
       display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.05rem}
.status-dot{width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 6px #22c55e}
.status-dot.offline{background:#f87171;box-shadow:0 0 6px #f87171}
.hdr-right{display:flex;align-items:center;gap:12px}
.btn{padding:7px 14px;border-radius:7px;font-size:.82rem;font-weight:600;cursor:pointer;border:none;transition:all .15s}
.btn-ghost{background:transparent;color:#94a3b8;border:1px solid #2a2d3a}
.btn-ghost:hover{background:#2a2d3a;color:#e2e8f0}
.btn-primary{background:#3b82f6;color:#fff}
.btn-primary:hover{background:#2563eb}
.btn-danger{background:#dc2626;color:#fff}
.btn-danger:hover{background:#b91c1c}
.btn-success{background:#16a34a;color:#fff}
.btn-success:hover{background:#15803d}
.btn-sm{padding:4px 10px;font-size:.75rem}
.btn:disabled{opacity:.5;cursor:not-allowed}
main{max-width:1140px;margin:0 auto;padding:24px 20px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}
.stat{background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:16px 18px}
.stat-label{color:#64748b;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}
.stat-value{font-size:1.7rem;font-weight:700}
.green{color:#22c55e}.red{color:#f87171}.blue{color:#60a5fa}
.panel{background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;overflow:hidden;margin-bottom:20px}
.ph{padding:13px 18px;border-bottom:1px solid #2a2d3a;display:flex;align-items:center;justify-content:space-between}
.pt{font-weight:600;font-size:.9rem;color:#cbd5e1}
.pb{padding:16px 18px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:720px){.grid2{grid-template-columns:1fr}}
label.field-label{display:block;color:#94a3b8;font-size:.75rem;font-weight:500;
                  text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px;margin-top:12px}
label.field-label:first-child{margin-top:0}
input[type=text],input[type=number],input[type=time],select,textarea{
  width:100%;background:#0f1117;border:1px solid #2a2d3a;border-radius:7px;color:#e2e8f0;
  font-size:.875rem;padding:9px 12px;outline:none;transition:border-color .2s;font-family:inherit}
input[type=text]:focus,input[type=number]:focus,input[type=time]:focus,select:focus,textarea:focus{border-color:#3b82f6}
select option{background:#1a1d27}
textarea{resize:vertical;min-height:72px}
.row{display:flex;gap:10px;align-items:flex-end}
.row>*{flex:1}
.file-input-wrap{position:relative}
.file-input-wrap input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.file-btn{display:flex;align-items:center;gap:6px;padding:8px 12px;background:#0f1117;
          border:1px dashed #3b82f6;border-radius:7px;color:#60a5fa;font-size:.8rem;cursor:pointer;transition:all .2s}
.file-btn:hover{background:#1e3a5f}
.preview-img{max-width:80px;max-height:60px;border-radius:5px;object-fit:cover;margin-left:8px;display:none}
.group-item{display:flex;align-items:center;justify-content:space-between;
            padding:9px 0;border-bottom:1px solid #1e2130}
.group-item:last-child{border-bottom:none}
.gname{font-size:.87rem;font-weight:500}
.gid{font-size:.7rem;color:#64748b;font-family:monospace;margin-top:2px}
.task-card{background:#0f1117;border:1px solid #2a2d3a;border-radius:8px;padding:13px;margin-bottom:10px}
.task-card:last-child{margin-bottom:0}
.task-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:7px}
.task-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;
            border-radius:20px;font-size:.7rem;font-weight:600}
.task-badge.repeat{background:#1e3a5f;color:#60a5fa}
.task-badge.schedule{background:#1e3a2a;color:#4ade80}
.task-detail{color:#94a3b8;font-size:.78rem;margin-bottom:8px}
.task-msg{color:#cbd5e1;font-size:.8rem;background:#1a1d27;border-radius:5px;padding:6px 9px;
          margin-bottom:9px;white-space:pre-wrap;word-break:break-word;max-height:52px;overflow:hidden}
.group-chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px}
.chip{display:flex;align-items:center;gap:4px;padding:3px 9px;background:#1a1d27;
      border:1px solid #2a2d3a;border-radius:20px;cursor:pointer;font-size:.72rem;
      color:#94a3b8;transition:all .15s;user-select:none}
.chip:has(input:checked){background:#1e3a5f;border-color:#3b82f6;color:#60a5fa}
.chip input{display:none}
.task-actions{display:flex;gap:7px}
.empty{color:#4b5563;text-align:center;padding:22px;font-size:.83rem}
.bc-groups{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0}
.bc-hint{color:#64748b;font-size:.75rem}
.toast{position:fixed;bottom:20px;right:20px;background:#1a1d27;border:1px solid #2a2d3a;
       border-radius:9px;padding:11px 16px;font-size:.83rem;color:#e2e8f0;opacity:0;
       transform:translateY(6px);transition:all .25s;pointer-events:none;z-index:999;max-width:300px}
.toast.show{opacity:1;transform:translateY(0)}
.toast.ok{border-color:#22c55e;background:#0a1f11;color:#86efac}
.toast.err{border-color:#dc2626;background:#2d1b1b;color:#fca5a5}
.spin{display:inline-block;width:12px;height:12px;border:2px solid currentColor;
      border-top-color:transparent;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
.type-fields{display:none}.type-fields.active{display:block}
.divider{border:none;border-top:1px solid #2a2d3a;margin:16px 0}
</style>
</head><body>
<header>
  <div class="brand">🤖 Bot Admin Dashboard</div>
  <div class="hdr-right">
    <span class="status-dot" id="sdot"></span>
    <span id="stext" style="color:#94a3b8;font-size:.8rem">Connecting...</span>
    <a href="/logout"><button class="btn btn-ghost">Sign Out</button></a>
  </div>
</header>

<main>
  <!-- Stats -->
  <div class="stats">
    <div class="stat"><div class="stat-label">Groups</div><div class="stat-value blue" id="s-groups">—</div></div>
    <div class="stat"><div class="stat-label">Active Tasks</div><div class="stat-value blue" id="s-tasks">—</div></div>
    <div class="stat"><div class="stat-label">Public Access</div><div class="stat-value" id="s-public">—</div></div>
    <div class="stat"><div class="stat-label">Broadcast</div><div class="stat-value" id="s-bc">—</div></div>
    <div class="stat"><div class="stat-label">Translation</div><div class="stat-value" id="s-trans">—</div></div>
  </div>

  <!-- Broadcast Panel -->
  <div class="panel">
    <div class="ph"><span class="pt">📢 Manual Broadcast</span>
      <button class="btn btn-sm btn-ghost" onclick="bcToggleAll()">Select All Groups</button></div>
    <div class="pb">
      <label class="field-label">Message</label>
      <textarea id="bc-text" placeholder="Type your broadcast message..."></textarea>
      <label class="field-label">Image (optional)</label>
      <div style="display:flex;align-items:center;gap:8px">
        <div class="file-input-wrap">
          <div class="file-btn" id="bc-file-btn">📎 Choose Image
            <input type="file" id="bc-file" accept="image/*" onchange="onBcFile(this)"/>
          </div>
        </div>
        <img id="bc-preview" class="preview-img"/>
        <span id="bc-file-name" style="color:#64748b;font-size:.75rem"></span>
      </div>
      <label class="field-label">Target Groups</label>
      <div class="bc-groups" id="bc-groups"></div>
      <div style="display:flex;align-items:center;gap:12px;margin-top:10px">
        <button class="btn btn-primary" id="bc-btn" onclick="sendBroadcast()">Send Broadcast</button>
        <span class="bc-hint" id="bc-hint">No groups selected — sends to all</span>
      </div>
    </div>
  </div>

  <!-- Create Task Panel -->
  <div class="panel">
    <div class="ph"><span class="pt">➕ Create Scheduled &amp; Repeat Tasks</span></div>
    <div class="pb">
      <div class="row">
        <div>
          <label class="field-label">Task Type</label>
          <select id="ct-type" onchange="onTypeChange()">
            <option value="repeat">🔁 Repeat Interval</option>
            <option value="schedule">⏰ Daily Schedule</option>
          </select>
        </div>
        <div id="ct-repeat-fields" class="type-fields active">
          <label class="field-label">Repeat every (hours)</label>
          <input type="number" id="ct-hours" placeholder="e.g. 2" min="0.1" step="0.5" value="1"/>
        </div>
        <div id="ct-schedule-fields" class="type-fields">
          <label class="field-label">Daily send time</label>
          <input type="time" id="ct-time" value="09:00"/>
        </div>
      </div>
      <label class="field-label">Message</label>
      <textarea id="ct-text" placeholder="Message text for this task..."></textarea>
      <label class="field-label">Image (optional)</label>
      <div style="display:flex;align-items:center;gap:8px">
        <div class="file-input-wrap">
          <div class="file-btn">📎 Choose Image
            <input type="file" id="ct-file" accept="image/*" onchange="onCtFile(this)"/>
          </div>
        </div>
        <img id="ct-preview" class="preview-img"/>
        <span id="ct-file-name" style="color:#64748b;font-size:.75rem"></span>
      </div>
      <div style="margin-top:14px">
        <button class="btn btn-success" id="ct-btn" onclick="createTask()">Create Task</button>
      </div>
    </div>
  </div>

  <!-- Groups + Tasks -->
  <div class="grid2">
    <div class="panel">
      <div class="ph">
        <span class="pt">📋 Tracked Groups</span>
        <span id="g-count" style="color:#64748b;font-size:.75rem"></span>
      </div>
      <div class="pb" id="groups-list"><div class="empty">Loading...</div></div>
    </div>
    <div class="panel">
      <div class="ph">
        <span class="pt">⚙️ Active Tasks</span>
        <span id="t-count" style="color:#64748b;font-size:.75rem"></span>
      </div>
      <div class="pb" id="tasks-list"><div class="empty">Loading...</div></div>
    </div>
  </div>
</main>
<div class="toast" id="toast"></div>

<!-- ── Edit Task Modal ─────────────────────────────────────────────────── -->
<div id="edit-overlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;overflow-y:auto;padding:24px 16px">
  <div style="background:#1a1d27;border:1px solid #2a2d3a;border-radius:12px;max-width:520px;margin:0 auto;overflow:hidden">
    <div style="padding:16px 20px;border-bottom:1px solid #2a2d3a;display:flex;align-items:center;justify-content:space-between">
      <span style="font-weight:700;font-size:1rem">✏️ Edit Task <span id="em-tid" style="color:#64748b;font-size:.85rem"></span></span>
      <button onclick="closeEditModal()" style="background:none;border:none;color:#94a3b8;font-size:1.3rem;cursor:pointer;line-height:1">×</button>
    </div>
    <div style="padding:20px">
      <input type="hidden" id="em-id"/>
      <input type="hidden" id="em-type"/>

      <!-- Type badge (read-only) -->
      <div style="margin-bottom:14px">
        <span class="field-label" style="display:block;color:#94a3b8;font-size:.75rem;font-weight:500;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px">Task Type</span>
        <span id="em-type-badge" style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:.75rem;font-weight:600;background:#1e3a5f;color:#60a5fa"></span>
      </div>

      <!-- Interval / Schedule time -->
      <div id="em-repeat-wrap" style="display:none;margin-bottom:14px">
        <label class="field-label" style="display:block;color:#94a3b8;font-size:.75rem;font-weight:500;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px">Repeat every (hours)</label>
        <input type="number" id="em-hours" min="0.1" step="0.5" style="width:100%;background:#0f1117;border:1px solid #2a2d3a;border-radius:7px;color:#e2e8f0;font-size:.875rem;padding:9px 12px;outline:none"/>
      </div>
      <div id="em-schedule-wrap" style="display:none;margin-bottom:14px">
        <label class="field-label" style="display:block;color:#94a3b8;font-size:.75rem;font-weight:500;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px">Daily send time</label>
        <input type="time" id="em-time" style="width:100%;background:#0f1117;border:1px solid #2a2d3a;border-radius:7px;color:#e2e8f0;font-size:.875rem;padding:9px 12px;outline:none"/>
      </div>

      <!-- Message -->
      <div style="margin-bottom:14px">
        <label class="field-label" style="display:block;color:#94a3b8;font-size:.75rem;font-weight:500;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px">Message</label>
        <textarea id="em-text" style="width:100%;background:#0f1117;border:1px solid #2a2d3a;border-radius:7px;color:#e2e8f0;font-size:.875rem;padding:9px 12px;outline:none;resize:vertical;min-height:72px;font-family:inherit"></textarea>
      </div>

      <!-- Image -->
      <div style="margin-bottom:14px">
        <label class="field-label" style="display:block;color:#94a3b8;font-size:.75rem;font-weight:500;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px">Replace Image (optional)</label>
        <div style="display:flex;align-items:center;gap:8px">
          <div class="file-input-wrap">
            <div class="file-btn">📎 Choose Image<input type="file" id="em-file" accept="image/*" onchange="onEmFile(this)"/></div>
          </div>
          <img id="em-preview" class="preview-img"/>
          <span id="em-file-name" style="color:#64748b;font-size:.75rem"></span>
        </div>
      </div>

      <!-- Target groups -->
      <div style="margin-bottom:18px">
        <label class="field-label" style="display:block;color:#94a3b8;font-size:.75rem;font-weight:500;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px">Target Groups</label>
        <div id="em-groups" style="display:flex;flex-wrap:wrap;gap:5px"></div>
        <p style="color:#4b5563;font-size:.72rem;margin-top:5px">No groups checked = send to all tracked groups</p>
      </div>

      <div style="display:flex;gap:10px">
        <button class="btn btn-primary" id="em-save-btn" onclick="submitEdit()">💾 Save &amp; Reload</button>
        <button class="btn btn-ghost" onclick="closeEditModal()">Cancel</button>
      </div>
    </div>
  </div>
</div>

<script>
let allGroups = [];
let bcAllSel = false;

// ── Helpers ──
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function toast(msg,type='ok'){
  const t=document.getElementById('toast');
  t.textContent=msg;t.className='toast show '+(type==='ok'?'ok':'err');
  setTimeout(()=>t.className='toast',3200);
}
function setBtn(id,loading,label){
  const b=document.getElementById(id);if(!b)return;
  b.disabled=loading;
  b.innerHTML=loading?'<span class="spin"></span> …':label;
}

// ── Status ──
async function loadStatus(){
  try{
    const r=await fetch('/api/admin/status');
    if(!r.ok)throw new Error();
    const d=await r.json();
    document.getElementById('s-groups').textContent=d.tracked_groups??'—';
    document.getElementById('s-tasks').textContent=d.active_tasks??'—';
    document.getElementById('s-public').textContent=d.public_access?'✅':'🔒';
    document.getElementById('s-public').className='stat-value '+(d.public_access?'green':'red');
    document.getElementById('s-bc').textContent=d.broadcast?'✅':'❌';
    document.getElementById('s-bc').className='stat-value '+(d.broadcast?'green':'red');
    document.getElementById('s-trans').textContent=d.translation?'✅':'❌';
    document.getElementById('s-trans').className='stat-value '+(d.translation?'green':'red');
    document.getElementById('sdot').className='status-dot';
    document.getElementById('stext').textContent='Bot Online';
  }catch{
    document.getElementById('sdot').className='status-dot offline';
    document.getElementById('stext').textContent='Bot Offline';
  }
}

// ── Groups ──
async function loadGroups(){
  try{
    const r=await fetch('/api/admin/groups');
    allGroups=await r.json();
    document.getElementById('g-count').textContent=allGroups.length+' group(s)';
    const el=document.getElementById('groups-list');
    if(!allGroups.length){el.innerHTML='<div class="empty">No groups tracked yet</div>';renderBcGroups();return;}
    el.innerHTML=allGroups.map(g=>\`<div class="group-item">
      <div><div class="gname">\${esc(g.name)}</div><div class="gid">\${g.id}</div></div>
    </div>\`).join('');
    renderBcGroups();
  }catch{document.getElementById('groups-list').innerHTML='<div class="empty">Failed to load</div>';}
}
function renderBcGroups(){
  const el=document.getElementById('bc-groups');
  if(!allGroups.length){el.innerHTML='<span style="color:#4b5563;font-size:.78rem">No groups tracked</span>';return;}
  el.innerHTML=allGroups.map(g=>\`<label class="chip">
    <input type="checkbox" name="bc-grp" value="\${g.id}" onchange="updateBcHint()">
    \${esc(g.name)}</label>\`).join('');
}
function bcToggleAll(){
  bcAllSel=!bcAllSel;
  document.querySelectorAll('input[name="bc-grp"]').forEach(b=>b.checked=bcAllSel);
  updateBcHint();
}
function updateBcHint(){
  const n=document.querySelectorAll('input[name="bc-grp"]:checked').length;
  document.getElementById('bc-hint').textContent=n?\`Sending to \${n} group(s)\`:'No groups selected — sends to all';
}

// ── Tasks ──
async function loadTasks(){
  try{
    const r=await fetch('/api/admin/tasks');
    const tasks=await r.json();
    document.getElementById('t-count').textContent=tasks.length+' task(s)';
    const el=document.getElementById('tasks-list');
    if(!tasks.length){el.innerHTML='<div class="empty">No active tasks</div>';return;}
    el.innerHTML=tasks.map(t=>{
      const tt=t.type||'?';
      const det=tt==='repeat'?\`Every \${t.interval_hours}h\`:\`Daily at \${t.scheduled_time}\`;
      const msg=t.photo_file_id||t.photo_path?'📷 Photo':(t.text||'').slice(0,60);
      const tgList=(t.targeted_groups||[]).map(String);
      const chips=allGroups.map(g=>{
        const chk=tgList.includes(String(g.id))?'checked':'';
        return \`<label class="chip"><input type="checkbox" class="tg-cb" data-tid="\${t.id}" value="\${g.id}" \${chk}>\${esc(g.name)}</label>\`;
      }).join('');
      return \`<div class="task-card" id="tc-\${t.id}">
        <div class="task-head">
          <span style="font-weight:700;font-size:.85rem">Task #\${t.id}</span>
          <span class="task-badge \${tt}">\${tt==='repeat'?'🔁':'⏰'} \${tt}</span>
        </div>
        <div class="task-detail">\${det}</div>
        \${msg?'<div class="task-msg">'+esc(msg)+'</div>':''}
        <div class="group-chips">\${chips||'<span style="color:#4b5563;font-size:.72rem">No groups tracked</span>'}</div>
        <div class="task-actions">
          <button class="btn btn-sm btn-primary" onclick="saveTaskGroups(\${t.id})">💾 Save Groups</button>
          <button class="btn btn-sm btn-ghost" onclick="openEditModal(\${JSON.stringify(t).replace(/"/g,'&quot;')})">✏️ Edit Task</button>
          <button class="btn btn-sm btn-danger" onclick="deleteTask(\${t.id})">🗑️ Delete / Stop</button>
        </div>
      </div>\`;
    }).join('');
  }catch{document.getElementById('tasks-list').innerHTML='<div class="empty">Failed to load</div>';}
}

async function saveTaskGroups(tid){
  const boxes=document.querySelectorAll(\`.tg-cb[data-tid="\${tid}"]:checked\`);
  const groups=Array.from(boxes).map(b=>b.value);
  try{
    const r=await fetch('/api/admin/tasks/'+tid,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({targeted_groups:groups})});
    if(r.ok)toast('Task #'+tid+' groups saved');else toast('Failed to save','err');
  }catch{toast('Network error','err');}
}

async function deleteTask(tid){
  if(!confirm('Stop and delete task #'+tid+'?'))return;
  try{
    const r=await fetch('/api/admin/tasks/'+tid,{method:'DELETE'});
    if(r.ok){toast('Task #'+tid+' deleted');loadTasks();loadStatus();}
    else toast('Failed to delete task','err');
  }catch{toast('Network error','err');}
}

// ── Edit Modal ──
function openEditModal(task){
  const t=typeof task==='string'?JSON.parse(task):task;
  document.getElementById('em-id').value=t.id;
  document.getElementById('em-type').value=t.type;
  document.getElementById('em-tid').textContent='#'+t.id;
  const badge=document.getElementById('em-type-badge');
  badge.textContent=t.type==='repeat'?'🔁 repeat':'⏰ schedule';
  badge.style.background=t.type==='repeat'?'#1e3a5f':'#2d1f3f';
  badge.style.color=t.type==='repeat'?'#60a5fa':'#a78bfa';

  // Timing fields
  document.getElementById('em-repeat-wrap').style.display=t.type==='repeat'?'block':'none';
  document.getElementById('em-schedule-wrap').style.display=t.type==='schedule'?'block':'none';
  if(t.type==='repeat')document.getElementById('em-hours').value=t.interval_hours||1;
  if(t.type==='schedule'){
    // Convert "09:30 AM" → "09:30" for <input type=time>
    let tv=t.scheduled_time||'';
    try{const d=new Date('1970-01-01 '+tv);if(!isNaN(d))tv=d.toTimeString().slice(0,5);}catch{}
    document.getElementById('em-time').value=tv;
  }

  document.getElementById('em-text').value=t.text||'';

  // Clear image fields
  document.getElementById('em-file').value='';
  document.getElementById('em-file-name').textContent='';
  const prev=document.getElementById('em-preview');prev.src='';prev.style.display='none';

  // Group checkboxes
  const tgList=(t.targeted_groups||[]).map(String);
  const el=document.getElementById('em-groups');
  if(!allGroups.length){el.innerHTML='<span style="color:#4b5563;font-size:.72rem">No groups tracked</span>';}
  else el.innerHTML=allGroups.map(g=>{
    const chk=tgList.includes(String(g.id))?'checked':'';
    return \`<label class="chip"><input type="checkbox" class="em-grp-cb" value="\${g.id}" \${chk}>\${esc(g.name)}</label>\`;
  }).join('');

  document.getElementById('edit-overlay').style.display='block';
  document.body.style.overflow='hidden';
}

function closeEditModal(){
  document.getElementById('edit-overlay').style.display='none';
  document.body.style.overflow='';
}

function onEmFile(inp){
  const f=inp.files[0];if(!f)return;
  document.getElementById('em-file-name').textContent=f.name;
  const prev=document.getElementById('em-preview');
  prev.src=URL.createObjectURL(f);prev.style.display='block';
}

async function submitEdit(){
  const tid=document.getElementById('em-id').value;
  const ttype=document.getElementById('em-type').value;
  const text=document.getElementById('em-text').value.trim();
  const file=document.getElementById('em-file').files[0];
  const checked=document.querySelectorAll('.em-grp-cb:checked');
  const tg=Array.from(checked).map(b=>b.value);

  const fd=new FormData();
  fd.append('text',text);
  fd.append('targeted_groups',JSON.stringify(tg));
  if(file)fd.append('image',file);
  if(ttype==='repeat'){
    const h=document.getElementById('em-hours').value;
    if(!h||isNaN(parseFloat(h))){toast('Enter a valid interval','err');return;}
    fd.append('interval_hours',h);
  }else{
    let tv=document.getElementById('em-time').value;
    if(!tv){toast('Enter a valid time','err');return;}
    // Convert HH:MM to "HH:MM AM/PM" for Python
    const [hh,mm]=tv.split(':').map(Number);
    const ampm=hh>=12?'PM':'AM';
    const h12=hh===0?12:hh>12?hh-12:hh;
    tv=String(h12).padStart(2,'0')+':'+String(mm).padStart(2,'0')+' '+ampm;
    fd.append('scheduled_time',tv);
  }

  setBtn('em-save-btn',true,'Save & Reload');
  try{
    const r=await fetch('/api/admin/tasks/'+tid,{method:'PUT',body:fd});
    const d=await r.json();
    if(r.ok){toast('Task #'+tid+' updated & reloaded');closeEditModal();loadTasks();loadStatus();}
    else toast(d.error||'Failed to update task','err');
  }catch{toast('Network error','err');}
  setBtn('em-save-btn',false,'Save & Reload');
}

// Close overlay when clicking backdrop
document.getElementById('edit-overlay').addEventListener('click',function(e){
  if(e.target===this)closeEditModal();
});

// ── Broadcast ──
function onBcFile(inp){
  const f=inp.files[0];if(!f)return;
  document.getElementById('bc-file-name').textContent=f.name;
  const prev=document.getElementById('bc-preview');
  prev.src=URL.createObjectURL(f);prev.style.display='block';
}
async function sendBroadcast(){
  const text=document.getElementById('bc-text').value.trim();
  const file=document.getElementById('bc-file').files[0];
  const checked=document.querySelectorAll('input[name="bc-grp"]:checked');
  const tg=checked.length?Array.from(checked).map(b=>b.value):null;
  if(!text&&!file){toast('Enter a message or choose an image','err');return;}
  setBtn('bc-btn',true,'Send Broadcast');
  try{
    const fd=new FormData();
    if(text)fd.append('text',text);
    if(file)fd.append('image',file);
    if(tg)fd.append('targeted_groups',JSON.stringify(tg));
    const r=await fetch('/api/admin/broadcast',{method:'POST',body:fd});
    const d=await r.json();
    if(r.ok){
      toast('Broadcast sent to '+d.targets+' group(s)');
      document.getElementById('bc-text').value='';
      document.getElementById('bc-file').value='';
      document.getElementById('bc-file-name').textContent='';
      document.getElementById('bc-preview').style.display='none';
    }else toast(d.error||'Broadcast failed','err');
  }catch{toast('Network error','err');}
  setBtn('bc-btn',false,'Send Broadcast');
}

// ── Create Task ──
function onTypeChange(){
  const v=document.getElementById('ct-type').value;
  document.getElementById('ct-repeat-fields').className='type-fields'+(v==='repeat'?' active':'');
  document.getElementById('ct-schedule-fields').className='type-fields'+(v==='schedule'?' active':'');
}
function onCtFile(inp){
  const f=inp.files[0];if(!f)return;
  document.getElementById('ct-file-name').textContent=f.name;
  const prev=document.getElementById('ct-preview');
  prev.src=URL.createObjectURL(f);prev.style.display='block';
}
async function createTask(){
  const type=document.getElementById('ct-type').value;
  const text=document.getElementById('ct-text').value.trim();
  const file=document.getElementById('ct-file').files[0];
  const hours=document.getElementById('ct-hours').value;
  const time=document.getElementById('ct-time').value;
  if(!text&&!file){toast('Enter a message or choose an image','err');return;}
  setBtn('ct-btn',true,'Create Task');
  try{
    const fd=new FormData();
    fd.append('type',type);
    if(text)fd.append('text',text);
    if(file)fd.append('image',file);
    if(type==='repeat')fd.append('interval_hours',hours);
    if(type==='schedule'){
      // Convert HH:MM to 12h format for Python bot
      const [h,m]=time.split(':').map(Number);
      const ampm=h>=12?'PM':'AM';
      const h12=h%12||12;
      fd.append('scheduled_time',h12+':'+String(m).padStart(2,'0')+' '+ampm);
    }
    const r=await fetch('/api/admin/tasks',{method:'POST',body:fd});
    const d=await r.json();
    if(r.ok){
      toast('Task #'+d.task_id+' created!');
      document.getElementById('ct-text').value='';
      document.getElementById('ct-file').value='';
      document.getElementById('ct-file-name').textContent='';
      document.getElementById('ct-preview').style.display='none';
      loadTasks();loadStatus();
    }else toast(d.error||'Failed to create task','err');
  }catch{toast('Network error','err');}
  setBtn('ct-btn',false,'Create Task');
}

async function loadAll(){await loadStatus();await loadGroups();await loadTasks();}
loadAll();
setInterval(loadAll,15000);
</script>
</body></html>`);
});

// ─── API: status ──────────────────────────────────────────────────────────────
router.get("/api/admin/status", requireAuthApi, async (_req, res) => {
  try {
    const r = await pyFetch("/status");
    res.json(await r.json());
  } catch {
    res.json(getStatusFallback());
  }
});

// ─── API: groups ──────────────────────────────────────────────────────────────
router.get("/api/admin/groups", requireAuthApi, async (_req, res) => {
  try {
    const r = await pyFetch("/groups");
    res.json(await r.json());
  } catch {
    res.json(getGroupsFallback());
  }
});

// ─── API: list tasks ──────────────────────────────────────────────────────────
router.get("/api/admin/tasks", requireAuthApi, async (_req, res) => {
  try {
    const r = await pyFetch("/tasks");
    res.json(await r.json());
  } catch {
    res.json(getTasksFallback());
  }
});

// ─── API: update task groups ──────────────────────────────────────────────────
router.patch("/api/admin/tasks/:id", requireAuthApi, async (req, res) => {
  try {
    const r = await pyFetch(`/tasks/${req.params.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req.body),
    });
    res.status(r.status).json(await r.json());
  } catch {
    res.status(503).json({ error: "Bot unreachable" });
  }
});

// ─── API: edit task (hot-reload) ──────────────────────────────────────────────
router.put(
  "/api/admin/tasks/:id",
  requireAuthApi,
  upload.single("image"),
  async (req: Request, res: Response) => {
    const { text, interval_hours, scheduled_time, targeted_groups: tgRaw } = req.body as Record<string, string>;
    const photoPath = (req.file as Express.Multer.File | undefined)?.path;
    const tg = tgRaw ? JSON.parse(tgRaw) : undefined;

    const payload: Record<string, any> = {};
    if (text !== undefined) payload.text = text || null;
    if (photoPath) payload.photo_path = photoPath;
    if (interval_hours) payload.interval_hours = parseFloat(interval_hours);
    if (scheduled_time) payload.scheduled_time = scheduled_time;
    if (tg !== undefined) payload.targeted_groups = tg;

    try {
      const r = await pyFetch(`/tasks/${req.params.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      res.status(r.status).json(await r.json());
    } catch {
      res.status(503).json({ error: "Bot unreachable" });
    }
  },
);

// ─── API: delete task ─────────────────────────────────────────────────────────
router.delete("/api/admin/tasks/:id", requireAuthApi, async (req, res) => {
  try {
    const r = await pyFetch(`/tasks/${req.params.id}`, { method: "DELETE" });
    res.status(r.status).json(await r.json());
  } catch {
    res.status(503).json({ error: "Bot unreachable" });
  }
});

// ─── API: broadcast (supports multipart with image) ───────────────────────────
router.post(
  "/api/admin/broadcast",
  requireAuthApi,
  upload.single("image"),
  async (req: Request, res: Response) => {
    const text = req.body.text as string | undefined;
    const tgRaw = req.body.targeted_groups as string | undefined;
    const tg = tgRaw ? JSON.parse(tgRaw) : null;
    const photoPath = (req.file as Express.Multer.File | undefined)?.path;

    if (!text && !photoPath) {
      res.status(400).json({ error: "text or image required" });
      return;
    }

    try {
      const payload: any = { text: text || null, targeted_groups: tg };
      if (photoPath) payload.photo_path = photoPath;
      const r = await pyFetch("/broadcast", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      res.status(r.status).json(await r.json());
    } catch {
      res.status(503).json({ error: "Bot unreachable" });
    }
  },
);

// ─── API: create task (supports multipart with image) ─────────────────────────
router.post(
  "/api/admin/tasks",
  requireAuthApi,
  upload.single("image"),
  async (req: Request, res: Response) => {
    const { type, text, interval_hours, scheduled_time } = req.body as Record<string, string>;
    const photoPath = (req.file as Express.Multer.File | undefined)?.path;

    if (!type) { res.status(400).json({ error: "type required" }); return; }
    if (!text && !photoPath) { res.status(400).json({ error: "text or image required" }); return; }

    try {
      const payload: any = { type, text: text || null };
      if (photoPath) payload.photo_path = photoPath;
      if (interval_hours) payload.interval_hours = parseFloat(interval_hours);
      if (scheduled_time) payload.scheduled_time = scheduled_time;

      const r = await pyFetch("/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      res.status(r.status).json(await r.json());
    } catch {
      res.status(503).json({ error: "Bot unreachable" });
    }
  },
);

export default router;
