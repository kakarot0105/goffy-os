const views = {
  boot: document.getElementById("bootView"),
  lock: document.getElementById("lockView"),
  home: document.getElementById("homeView"),
  app: document.getElementById("appView"),
};

const statusTime = document.getElementById("statusTime");
const runtimeBadge = document.getElementById("runtimeBadge");
const lockTime = document.getElementById("lockTime");
const lockDate = document.getElementById("lockDate");
const heroGreeting = document.getElementById("heroGreeting");
const heroMessage = document.getElementById("heroMessage");
const runtimeStatus = document.getElementById("runtimeStatus");
const queueStatus = document.getElementById("queueStatus");
const queueWidgetValue = document.getElementById("queueWidgetValue");
const systemWidgetValue = document.getElementById("systemWidgetValue");
const bootProgress = document.getElementById("bootProgress");
const bootTip = document.getElementById("bootTip");
const unlockButton = document.getElementById("unlockButton");
const sheetToggle = document.getElementById("sheetToggle");
const appSheet = document.getElementById("appSheet");
const peekButton = document.getElementById("peekButton");
const notificationSheet = document.getElementById("notificationSheet");
const notificationList = document.getElementById("notificationList");
const sheetStatus = document.getElementById("sheetStatus");
const appBack = document.getElementById("appBack");
const appTitle = document.getElementById("appTitle");
const appEyebrow = document.getElementById("appEyebrow");
const appContent = document.getElementById("appContent");

const homeButtons = document.querySelectorAll("[data-app]");
const toggleButtons = document.querySelectorAll("[data-toggle]");
const homePromptButtons = document.querySelectorAll("[data-home-prompt]");

const bootTips = [
  "Syncing command surfaces...",
  "Verifying remote agent reachability...",
  "Loading memory and automation maps...",
  "Raising the kiosk shell...",
];

const defaultConsoleMessages = [
  {
    id: "m1",
    role: "assistant",
    body: "Boot complete. Remote agent core is linked and the shell is ready for commands.",
    stamp: "system",
  },
  {
    id: "m2",
    role: "assistant",
    body: "Queue health is good. Start with a daily brief, a room-state check, or a routine trigger.",
    stamp: "system",
  },
];

const defaultTasks = [
  {
    id: "t1",
    title: "Generate morning brief",
    detail: "Summarize agenda, battery, and routine state before 8:00.",
    status: "running",
  },
  {
    id: "t2",
    title: "Review room device state",
    detail: "Check lamp, speaker, and camera reachability.",
    status: "queued",
  },
  {
    id: "t3",
    title: "Capture one spoken note",
    detail: "Log a short memory before end-of-day routine.",
    status: "queued",
  },
  {
    id: "t4",
    title: "Archive resolved command threads",
    detail: "Keep the command surface short and useful.",
    status: "done",
  },
];

const defaultRoutines = [
  {
    id: "r1",
    name: "Arrival mode",
    detail: "Bring up dashboard, quiet speaker, and prep summary.",
    enabled: true,
  },
  {
    id: "r2",
    name: "Bedtime mode",
    detail: "Dim devices, arm quiet mode, and pin tomorrow's first task.",
    enabled: true,
  },
  {
    id: "r3",
    name: "Focus block",
    detail: "Mute non-critical nudges and surface only execution work.",
    enabled: false,
  },
];

const defaultDevices = [
  {
    id: "d1",
    name: "Desk lamp",
    zone: "Workspace",
    kind: "switch",
    active: true,
    detail: "Warm white",
  },
  {
    id: "d2",
    name: "Speaker",
    zone: "Bedroom",
    kind: "media",
    active: false,
    detail: "Idle",
  },
  {
    id: "d3",
    name: "Door sensor",
    zone: "Entry",
    kind: "guard",
    active: true,
    detail: "Closed",
  },
  {
    id: "d4",
    name: "Charging dock",
    zone: "Nightstand",
    kind: "power",
    active: true,
    detail: "Supplying power",
  },
];

const themes = {
  sunset: {
    label: "Sunset Grid",
    blurb: "Warm orange glass with deep navy contrast.",
  },
  lagoon: {
    label: "Lagoon Drift",
    blurb: "Teal motion for calmer operator mode.",
  },
  ember: {
    label: "Ember Spark",
    blurb: "Higher-contrast mode for late sessions.",
  },
};

function readJson(key, fallback) {
  const raw = localStorage.getItem(key);
  if (!raw) {
    return fallback;
  }

  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

const state = {
  currentView: "boot",
  currentApp: "console",
  activeTheme: localStorage.getItem("goffy-theme") || "sunset",
  runtimeMode: localStorage.getItem("goffy-runtime") || "remote",
  memoryNote: localStorage.getItem("goffy-memory") ||
    "Phone role: bedside agent shell.\nPrimary job: show tasks, run routines, collect voice notes, and stay simple.",
  consoleDraft: "",
  consoleMessages: readJson("goffy-console", defaultConsoleMessages),
  tasks: readJson("goffy-tasks", defaultTasks),
  routines: readJson("goffy-routines", defaultRoutines),
  devices: readJson("goffy-devices", defaultDevices),
  toggles: readJson("goffy-toggles", {
    mic: true,
    sync: true,
    guard: true,
    quiet: false,
  }),
};

function persistState() {
  localStorage.setItem("goffy-theme", state.activeTheme);
  localStorage.setItem("goffy-runtime", state.runtimeMode);
  localStorage.setItem("goffy-memory", state.memoryNote);
  writeJson("goffy-console", state.consoleMessages);
  writeJson("goffy-tasks", state.tasks);
  writeJson("goffy-routines", state.routines);
  writeJson("goffy-devices", state.devices);
  writeJson("goffy-toggles", state.toggles);
}

function showView(name) {
  Object.entries(views).forEach(([key, element]) => {
    element.classList.toggle("active", key === name);
  });
  state.currentView = name;
}

function getOpenTasks() {
  return state.tasks.filter((task) => task.status !== "done");
}

function getEnabledRoutines() {
  return state.routines.filter((routine) => routine.enabled);
}

function getActiveDevices() {
  return state.devices.filter((device) => device.active);
}

function updateClock() {
  const now = new Date();
  const time = new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
  }).format(now);

  const date = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(now);

  statusTime.textContent = time;
  lockTime.textContent = time;
  lockDate.textContent = date;

  const openTasks = getOpenTasks();
  const nextTask = openTasks[0];
  const hour = now.getHours();

  if (hour < 12) {
    heroGreeting.textContent = "Run the morning from one screen.";
  } else if (hour < 18) {
    heroGreeting.textContent = "Keep the queue tight and visible.";
  } else {
    heroGreeting.textContent = "Shift into a quieter control loop.";
  }

  heroMessage.textContent = nextTask
    ? `Next up: ${nextTask.title}. ${getEnabledRoutines().length} routines are armed and ${getActiveDevices().length} devices are active.`
    : `Queue is clear. ${getEnabledRoutines().length} routines are armed and ${getActiveDevices().length} devices are active.`;
}

function applyTheme(themeName) {
  state.activeTheme = themeName;
  document.body.dataset.theme = themeName;
  persistState();
}

function applyRuntimeMode(mode) {
  state.runtimeMode = mode;
  runtimeBadge.textContent = mode === "remote" ? "REM" : "LOC";
  persistState();
}

function toggleSheet(forceValue) {
  const shouldOpen =
    typeof forceValue === "boolean"
      ? forceValue
      : !notificationSheet.classList.contains("open");

  notificationSheet.classList.toggle("open", shouldOpen);
}

function refreshHomeState() {
  const openTasks = getOpenTasks();
  const activeDevices = getActiveDevices();

  runtimeStatus.textContent =
    state.runtimeMode === "remote" ? "Remote core linked" : "Local shell only";
  queueStatus.textContent = `${openTasks.length} active task${openTasks.length === 1 ? "" : "s"}`;
  queueWidgetValue.textContent = `${openTasks.length} active task${openTasks.length === 1 ? "" : "s"}`;
  systemWidgetValue.textContent = `${activeDevices.length}/${state.devices.length} devices active`;
}

function setSheetStatus() {
  const activeToggles = Object.entries(state.toggles)
    .filter(([, enabled]) => enabled)
    .map(([name]) => name);

  let status = "Remote core nominal.";

  if (!state.toggles.sync) {
    status = "Sync is offline. Shell running degraded.";
  } else if (state.toggles.quiet) {
    status = "Quiet mode armed. Only critical nudges allowed.";
  } else if (!state.toggles.guard) {
    status = "Guard layer relaxed. Device actions are less strict.";
  }

  sheetStatus.textContent = status;

  toggleButtons.forEach((button) => {
    const key = button.dataset.toggle;
    button.classList.toggle("active", Boolean(state.toggles[key]));
  });
}

function renderNotifications() {
  const openTasks = getOpenTasks();
  const firstTask = openTasks[0];
  const activeDevices = getActiveDevices();
  const notifications = [
    {
      app: "Queue",
      title: firstTask ? `${firstTask.title} is up next.` : "Queue is currently clear.",
      body: firstTask
        ? firstTask.detail
        : "Use the Tasks app or the Console to enqueue work.",
    },
    {
      app: "Devices",
      title: `${activeDevices.length}/${state.devices.length} device surfaces are active.`,
      body: activeDevices.length === state.devices.length
        ? "All configured devices are reachable from the shell."
        : "At least one device surface is idle or disconnected.",
    },
    {
      app: "Memory",
      title: "Pinned context is preserved.",
      body: state.memoryNote.split("\n")[0] || "Add one durable note in Memory.",
    },
  ];

  notificationList.innerHTML = notifications
    .map(
      (item) => `
        <article class="notification-card">
          <p class="notification-app">${item.app}</p>
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.body)}</span>
        </article>
      `
    )
    .join("");
}

function renderConsoleApp() {
  const promptButtons = [
    "Give me a daily brief",
    "Summarize connected devices",
    "Run bedtime routine",
    "What should this phone do next?",
  ]
    .map(
      (prompt) => `
        <button class="command-pill compact" data-prompt="${escapeHtml(prompt)}" type="button">
          ${escapeHtml(prompt)}
        </button>
      `
    )
    .join("");

  const messages = state.consoleMessages
    .slice(-8)
    .map((message) => {
      const outgoing = message.role === "user" ? "outgoing" : "";
      const label = message.role === "user" ? "You" : "Agent";

      return `
        <div class="bubble ${outgoing}">
          <strong class="bubble-role">${label}</strong>
          ${escapeHtml(message.body).replaceAll("\n", "<br>")}
          <small>${escapeHtml(message.stamp)}</small>
        </div>
      `;
    })
    .join("");

  return `
    <section class="stack">
      <article class="app-panel stack">
        <div class="console-toolbar">
          <span class="status-pill">${state.runtimeMode === "remote" ? "Remote core" : "Local shell"}</span>
          <span class="status-pill">${state.toggles.sync ? "Sync on" : "Sync off"}</span>
          <span class="status-pill">${state.toggles.mic ? "Mic armed" : "Mic muted"}</span>
        </div>
        <div class="conversation">${messages}</div>
      </article>

      <article class="app-panel stack">
        <p class="eyebrow">Dispatch</p>
        <div class="prompt-row">${promptButtons}</div>
        <textarea id="consoleInput" class="journal-area console-input" spellcheck="false" placeholder="Route a command, ask for state, or trigger a routine.">${escapeHtml(state.consoleDraft)}</textarea>
        <div class="task-footer">
          <span class="task-meta">Commands route to the ${state.runtimeMode === "remote" ? "remote agent backend" : "local shell"}.</span>
          <button class="ghost-button strong-button" data-action="send-prompt" type="button">Dispatch</button>
        </div>
      </article>
    </section>
  `;
}

function renderTasksApp() {
  const tasksMarkup = state.tasks
    .map((task) => {
      let actionLabel = "Complete";
      if (task.status === "queued") {
        actionLabel = "Start";
      } else if (task.status === "done") {
        actionLabel = "Reset";
      }

      return `
        <article class="task-card ${task.status}">
          <div class="task-head">
            <div>
              <p class="eyebrow">Task</p>
              <h3>${escapeHtml(task.title)}</h3>
            </div>
            <span class="task-state">${escapeHtml(task.status)}</span>
          </div>
          <p>${escapeHtml(task.detail)}</p>
          <div class="task-footer">
            <span class="task-meta">${task.status === "running" ? "Active now" : task.status === "queued" ? "Queued for execution" : "Archived result"}</span>
            <button class="ghost-button" data-task-action="${task.id}" type="button">${actionLabel}</button>
          </div>
        </article>
      `;
    })
    .join("");

  return `
    <section class="stack">
      <article class="app-panel">
        <p class="eyebrow">Execution Queue</p>
        <div class="stack">${tasksMarkup}</div>
      </article>
    </section>
  `;
}

function renderRoutinesApp() {
  const routinesMarkup = state.routines
    .map(
      (routine) => `
        <article class="task-card ${routine.enabled ? "running" : "queued"}">
          <div class="task-head">
            <div>
              <p class="eyebrow">Routine</p>
              <h3>${escapeHtml(routine.name)}</h3>
            </div>
            <span class="task-state">${routine.enabled ? "armed" : "idle"}</span>
          </div>
          <p>${escapeHtml(routine.detail)}</p>
          <div class="task-footer">
            <button class="ghost-button" data-routine-toggle="${routine.id}" type="button">
              ${routine.enabled ? "Disable" : "Enable"}
            </button>
            <button class="ghost-button strong-button" data-routine-run="${routine.id}" type="button">
              Run now
            </button>
          </div>
        </article>
      `
    )
    .join("");

  return `
    <section class="stack">
      <article class="app-panel">
        <p class="eyebrow">Automations</p>
        <div class="stack">${routinesMarkup}</div>
      </article>
    </section>
  `;
}

function renderMemoryApp() {
  const openTasks = getOpenTasks();
  const wordCount = state.memoryNote.trim() ? state.memoryNote.trim().split(/\s+/).length : 0;

  return `
    <section class="stack">
      <article class="app-panel">
        <p class="eyebrow">Persistent Context</p>
        <h3>Memory</h3>
        <textarea id="memoryArea" class="journal-area" spellcheck="false">${escapeHtml(state.memoryNote)}</textarea>
        <div class="journal-meta">
          <span>Stored locally in this shell</span>
          <span id="memoryCount">${wordCount} words</span>
        </div>
      </article>

      <article class="app-panel">
        <p class="eyebrow">Pinned Facts</p>
        <div class="snapshot-strip">
          <article class="snapshot-card">
            <strong>${state.runtimeMode === "remote" ? "Remote core" : "Local shell"}</strong>
            <span>Primary execution target</span>
          </article>
          <article class="snapshot-card">
            <strong>${openTasks.length}</strong>
            <span>Open tasks in the queue</span>
          </article>
          <article class="snapshot-card">
            <strong>${getEnabledRoutines().length}</strong>
            <span>Armed routines</span>
          </article>
        </div>
      </article>
    </section>
  `;
}

function renderDevicesApp() {
  const devicesMarkup = state.devices
    .map(
      (device) => `
        <article class="device-card">
          <div class="task-head">
            <div>
              <p class="eyebrow">${escapeHtml(device.zone)}</p>
              <h3>${escapeHtml(device.name)}</h3>
            </div>
            <span class="task-state">${device.active ? "active" : "idle"}</span>
          </div>
          <p>${escapeHtml(device.detail)}</p>
          <div class="task-footer">
            <span class="task-meta">${escapeHtml(device.kind)}</span>
            <button class="ghost-button" data-device-toggle="${device.id}" type="button">
              ${device.active ? "Deactivate" : "Activate"}
            </button>
          </div>
        </article>
      `
    )
    .join("");

  return `
    <section class="stack">
      <article class="app-panel">
        <p class="eyebrow">Connected Surfaces</p>
        <div class="device-grid">${devicesMarkup}</div>
      </article>
    </section>
  `;
}

function renderSettingsApp() {
  const themeButtons = Object.entries(themes)
    .map(
      ([key, value]) => `
        <button class="theme-chip ${key === state.activeTheme ? "active" : ""}" data-theme="${key}" type="button">
          <strong>${escapeHtml(value.label)}</strong>
          <span>${escapeHtml(value.blurb)}</span>
        </button>
      `
    )
    .join("");

  return `
    <section class="stack">
      <article class="app-panel">
        <p class="eyebrow">Runtime</p>
        <div class="toggle-list">
          <button class="settings-toggle ${state.runtimeMode === "remote" ? "active" : ""}" data-runtime="remote" type="button">
            <strong>Remote-first mode</strong>
            <span>Use the phone as the shell and route intelligence off-device.</span>
          </button>
          <button class="settings-toggle ${state.runtimeMode === "local" ? "active" : ""}" data-runtime="local" type="button">
            <strong>Local shell mode</strong>
            <span>Keep interactions on-device and reduce backend dependence.</span>
          </button>
        </div>
      </article>

      <article class="app-panel">
        <p class="eyebrow">Themes</p>
        <div class="theme-row">${themeButtons}</div>
      </article>

      <article class="app-panel">
        <p class="eyebrow">Shell Toggles</p>
        <div class="toggle-list">
          <button class="settings-toggle ${state.toggles.mic ? "active" : ""}" data-toggle-setting="mic" type="button">
            <strong>Microphone</strong>
            <span>${state.toggles.mic ? "Ready for voice capture" : "Muted at the shell level"}</span>
          </button>
          <button class="settings-toggle ${state.toggles.sync ? "active" : ""}" data-toggle-setting="sync" type="button">
            <strong>Sync</strong>
            <span>${state.toggles.sync ? "Cloud and backend sync enabled" : "Shell operating in offline mode"}</span>
          </button>
          <button class="settings-toggle ${state.toggles.guard ? "active" : ""}" data-toggle-setting="guard" type="button">
            <strong>Guard</strong>
            <span>${state.toggles.guard ? "Sensitive actions require explicit routing" : "Guard layer relaxed for prototyping"}</span>
          </button>
          <button class="settings-toggle ${state.toggles.quiet ? "active" : ""}" data-toggle-setting="quiet" type="button">
            <strong>Quiet mode</strong>
            <span>${state.toggles.quiet ? "Suppressing non-critical nudges" : "Normal notification posture"}</span>
          </button>
        </div>
      </article>
    </section>
  `;
}

const appDefinitions = {
  console: {
    eyebrow: "Command",
    title: "Console",
    render: renderConsoleApp,
  },
  tasks: {
    eyebrow: "Queue",
    title: "Tasks",
    render: renderTasksApp,
  },
  routines: {
    eyebrow: "Automation",
    title: "Routines",
    render: renderRoutinesApp,
  },
  memory: {
    eyebrow: "Context",
    title: "Memory",
    render: renderMemoryApp,
  },
  devices: {
    eyebrow: "Hardware",
    title: "Devices",
    render: renderDevicesApp,
  },
  settings: {
    eyebrow: "System",
    title: "Settings",
    render: renderSettingsApp,
  },
};

function renderCurrentApp() {
  const app = appDefinitions[state.currentApp];
  if (!app) {
    return;
  }

  appEyebrow.textContent = app.eyebrow;
  appTitle.textContent = app.title;
  appContent.innerHTML = app.render();
}

function refreshUi(rerenderApp = true) {
  applyRuntimeMode(state.runtimeMode);
  refreshHomeState();
  setSheetStatus();
  renderNotifications();
  updateClock();

  if (rerenderApp && state.currentView === "app") {
    renderCurrentApp();
  }
}

function openApp(appId) {
  state.currentApp = appId;
  renderCurrentApp();
  toggleSheet(false);
  showView("app");
}

function cycleTask(taskId) {
  state.tasks = state.tasks.map((task) => {
    if (task.id !== taskId) {
      return task;
    }

    if (task.status === "queued") {
      return { ...task, status: "running" };
    }

    if (task.status === "running") {
      return { ...task, status: "done" };
    }

    return { ...task, status: "queued" };
  });

  persistState();
  refreshUi();
}

function toggleRoutine(routineId) {
  state.routines = state.routines.map((routine) =>
    routine.id === routineId ? { ...routine, enabled: !routine.enabled } : routine
  );

  persistState();
  refreshUi();
}

function runRoutine(routineId) {
  const routine = state.routines.find((entry) => entry.id === routineId);
  if (!routine) {
    return;
  }

  if (routine.id === "r2") {
    state.toggles.quiet = true;
  }

  state.consoleMessages.push({
    id: `m${Date.now()}`,
    role: "assistant",
    body: `Routine executed: ${routine.name}. ${routine.detail}`,
    stamp: "routine",
  });

  persistState();
  refreshUi();
}

function toggleDevice(deviceId) {
  state.devices = state.devices.map((device) => {
    if (device.id !== deviceId) {
      return device;
    }

    const active = !device.active;
    let detail = device.detail;

    if (device.kind === "switch") {
      detail = active ? "Warm white" : "Off";
    } else if (device.kind === "media") {
      detail = active ? "Playing ambient loop" : "Idle";
    } else if (device.kind === "guard") {
      detail = active ? "Closed" : "Bypassed";
    } else if (device.kind === "power") {
      detail = active ? "Supplying power" : "Standby";
    }

    return { ...device, active, detail };
  });

  persistState();
  refreshUi();
}

function updateMemory(value) {
  state.memoryNote = value;
  persistState();

  const memoryCount = document.getElementById("memoryCount");
  if (memoryCount) {
    const wordCount = value.trim() ? value.trim().split(/\s+/).length : 0;
    memoryCount.textContent = `${wordCount} words`;
  }
}

function toggleSetting(key) {
  state.toggles[key] = !state.toggles[key];
  persistState();
  refreshUi();
}

function summarizeState() {
  const openTasks = getOpenTasks();
  const activeDevices = getActiveDevices();

  return `${openTasks.length} active tasks, ${getEnabledRoutines().length} armed routines, and ${activeDevices.length} active devices.`;
}

function addConsoleMessage(role, body, stamp) {
  state.consoleMessages.push({
    id: `m${Date.now()}${Math.random().toString(16).slice(2, 6)}`,
    role,
    body,
    stamp,
  });
}

function applyPromptSideEffects(prompt) {
  const normalized = prompt.toLowerCase();

  if (normalized.includes("bedtime")) {
    state.toggles.quiet = true;
    const bedtimeRoutine = state.routines.find((routine) => routine.id === "r2");
    if (bedtimeRoutine) {
      bedtimeRoutine.enabled = true;
    }
  }

  if (normalized.includes("lamp")) {
    const lamp = state.devices.find((device) => device.id === "d1");
    if (lamp) {
      lamp.active = !lamp.active;
      lamp.detail = lamp.active ? "Warm white" : "Off";
    }
  }
}

function generateAgentReply(prompt) {
  const normalized = prompt.toLowerCase();
  const openTasks = getOpenTasks();

  if (normalized.includes("daily brief") || normalized.includes("brief")) {
    return `Daily brief: ${summarizeState()} Next task is ${openTasks[0] ? openTasks[0].title : "not set"}.`;
  }

  if (normalized.includes("device") || normalized.includes("room")) {
    return state.devices
      .map((device) => `${device.name}: ${device.active ? "active" : "idle"} (${device.detail})`)
      .join("\n");
  }

  if (normalized.includes("memory") || normalized.includes("note")) {
    return `Pinned memory says: ${state.memoryNote.split("\n")[0] || "no pinned context yet"}.`;
  }

  if (normalized.includes("what should this phone do next")) {
    return openTasks[0]
      ? `Use this phone as the operator shell. Next concrete action: ${openTasks[0].title}. Keep heavy reasoning off-device and let the phone handle capture, display, and dispatch.`
      : "Queue is clear. Next step is to define one narrow job for this phone: dashboard, voice intake, or device control.";
  }

  if (normalized.includes("bedtime")) {
    return "Bedtime routine triggered. Quiet mode is armed and the shell is shifting to a lower-noise state.";
  }

  return `Command received. Current state: ${summarizeState()}`;
}

function sendPrompt(prompt) {
  const trimmed = prompt.trim();
  if (!trimmed) {
    return;
  }

  addConsoleMessage("user", trimmed, "manual");
  applyPromptSideEffects(trimmed);
  addConsoleMessage("assistant", generateAgentReply(trimmed), state.runtimeMode);
  state.consoleDraft = "";
  persistState();
  openApp("console");
  refreshUi();
}

function startBootSequence() {
  let step = 0;
  showView("boot");

  const interval = window.setInterval(() => {
    step += 1;
    bootProgress.style.width = `${step * 25}%`;
    bootTip.textContent = bootTips[(step - 1) % bootTips.length];

    if (step >= 4) {
      window.clearInterval(interval);
      window.setTimeout(() => {
        showView("lock");
      }, 260);
    }
  }, 380);
}

homeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    openApp(button.dataset.app);
  });
});

homePromptButtons.forEach((button) => {
  button.addEventListener("click", () => {
    sendPrompt(button.dataset.homePrompt);
  });
});

unlockButton.addEventListener("click", () => {
  showView("home");
});

sheetToggle.addEventListener("click", () => {
  toggleSheet();
});

appSheet.addEventListener("click", () => {
  toggleSheet();
});

peekButton.addEventListener("click", () => {
  toggleSheet(true);
});

appBack.addEventListener("click", () => {
  toggleSheet(false);
  showView("home");
});

toggleButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.dataset.toggle;
    state.toggles[key] = !state.toggles[key];
    persistState();
    refreshUi(false);
  });
});

appContent.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const taskAction = target.closest("[data-task-action]");
  if (taskAction instanceof HTMLElement) {
    cycleTask(taskAction.dataset.taskAction);
    return;
  }

  const routineToggle = target.closest("[data-routine-toggle]");
  if (routineToggle instanceof HTMLElement) {
    toggleRoutine(routineToggle.dataset.routineToggle);
    return;
  }

  const routineRun = target.closest("[data-routine-run]");
  if (routineRun instanceof HTMLElement) {
    runRoutine(routineRun.dataset.routineRun);
    return;
  }

  const deviceToggle = target.closest("[data-device-toggle]");
  if (deviceToggle instanceof HTMLElement) {
    toggleDevice(deviceToggle.dataset.deviceToggle);
    return;
  }

  const themeTrigger = target.closest(".theme-chip[data-theme]");
  if (themeTrigger instanceof HTMLElement) {
    applyTheme(themeTrigger.dataset.theme);
    refreshUi();
    return;
  }

  const runtimeTrigger = target.closest("[data-runtime]");
  if (runtimeTrigger instanceof HTMLElement) {
    applyRuntimeMode(runtimeTrigger.dataset.runtime);
    persistState();
    refreshUi();
    return;
  }

  const toggleTrigger = target.closest("[data-toggle-setting]");
  if (toggleTrigger instanceof HTMLElement) {
    toggleSetting(toggleTrigger.dataset.toggleSetting);
    return;
  }

  const sendTrigger = target.closest("[data-action='send-prompt']");
  if (sendTrigger instanceof HTMLElement) {
    sendPrompt(state.consoleDraft);
    return;
  }

  const promptTrigger = target.closest("[data-prompt]");
  if (promptTrigger instanceof HTMLElement) {
    sendPrompt(promptTrigger.dataset.prompt);
  }
});

appContent.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  if (target.id === "memoryArea" && target instanceof HTMLTextAreaElement) {
    updateMemory(target.value);
    return;
  }

  if (target.id === "consoleInput" && target instanceof HTMLTextAreaElement) {
    state.consoleDraft = target.value;
  }
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const clickedInsideSheet = target.closest("#notificationSheet");
  const clickedToggle =
    target.closest("#sheetToggle") ||
    target.closest("#appSheet") ||
    target.closest("#peekButton");

  if (!clickedInsideSheet && !clickedToggle && notificationSheet.classList.contains("open")) {
    toggleSheet(false);
  }
});

applyTheme(state.activeTheme);
applyRuntimeMode(state.runtimeMode);
refreshUi(false);
startBootSequence();
window.setInterval(updateClock, 1000);
