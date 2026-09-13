let selectedDb = null;
let selectedTable = null;
let databasesCache = [];
let tablesCache = [];
let backupsCache = [];
let schemaTemplates = [];
let recordFilterTimer = null;
let globalSearchTimer = null;
let toastTimer = null;

const SVG_NS = "http://www.w3.org/2000/svg";
const XLINK_NS = "http://www.w3.org/1999/xlink";

const authBox = document.getElementById("authBox");
const appBox = document.getElementById("appBox");
const logoutBtn = document.getElementById("logoutBtn");
const message = document.getElementById("message");
const userEmail = document.getElementById("userEmail");

const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const authModeButtons = [...document.querySelectorAll("[data-auth-mode]")];
const authTitle = document.getElementById("authTitle");
const authSubtitle = document.getElementById("authSubtitle");

const dbList = document.getElementById("dbList");
const tableList = document.getElementById("tableList");
const recordList = document.getElementById("recordList");
const tablesBox = document.getElementById("tablesBox");
const recordsBox = document.getElementById("recordsBox");
const currentDbName = document.getElementById("currentDbName");
const currentTableName = document.getElementById("currentTableName");
const columnsInfo = document.getElementById("columnsInfo");
const activityList = document.getElementById("activityList");
const functionList = document.getElementById("functionList");
const regionList = document.getElementById("regionList");
const backupList = document.getElementById("backupList");
const backupDatabaseSelect = document.getElementById("backupDatabaseSelect");
const backupName = document.getElementById("backupName");
const createBackupBtn = document.getElementById("createBackupBtn");
const downloadSnapshotBtn = document.getElementById("downloadSnapshotBtn");
const globalSearch = document.getElementById("globalSearch");
const searchResults = document.getElementById("searchResults");
const navLinks = [...document.querySelectorAll(".nav a")];

const confirmDialog = document.getElementById("confirmDialog");
const confirmTitle = document.getElementById("confirmTitle");
const confirmText = document.getElementById("confirmText");
const confirmOkBtn = document.getElementById("confirmOkBtn");
const confirmCancelBtn = document.getElementById("confirmCancelBtn");

const statDbs = document.getElementById("statDbs");
const statTables = document.getElementById("statTables");
const statRecords = document.getElementById("statRecords");
const statEvents = document.getElementById("statEvents");
const statStorage = document.getElementById("statStorage");
const statInvocations = document.getElementById("statInvocations");
const statBackups = document.getElementById("statBackups");
const scaleMode = document.getElementById("scaleMode");
const scaleConcurrency = document.getElementById("scaleConcurrency");
const scaleLatency = document.getElementById("scaleLatency");
const scaleColdStart = document.getElementById("scaleColdStart");
const backupPolicy = document.getElementById("backupPolicy");
const backupStatus = document.getElementById("backupStatus");
const backupLatest = document.getElementById("backupLatest");
const backupSize = document.getElementById("backupSize");

const dbForm = document.getElementById("dbForm");
const dbId = document.getElementById("dbId");
const dbSaveBtn = document.getElementById("dbSaveBtn");
const dbCancelBtn = document.getElementById("dbCancelBtn");

const tableForm = document.getElementById("tableForm");
const tableId = document.getElementById("tableId");
const tableSaveBtn = document.getElementById("tableSaveBtn");
const tableCancelBtn = document.getElementById("tableCancelBtn");
const schemaTemplateSelect = document.getElementById("schemaTemplateSelect");

const recordId = document.getElementById("recordId");
const recordData = document.getElementById("recordData");
const recordSaveBtn = document.getElementById("recordSaveBtn");
const recordFilter = document.getElementById("recordFilter");
const recordSortBy = document.getElementById("recordSortBy");
const recordSortOrder = document.getElementById("recordSortOrder");
const importData = document.getElementById("importData");

const actionLabels = {
  register: "Регистрация",
  login: "Вход",
  create_database: "Создана база",
  update_database: "Обновлена база",
  delete_database: "Удалена база",
  create_table: "Создана таблица",
  update_table: "Обновлена таблица",
  delete_table: "Удалена таблица",
  create_record: "Создана запись",
  update_record: "Обновлена запись",
  delete_record: "Удалена запись",
  import_records: "Импорт записей",
  create_backup: "Создан backup",
  restore_backup: "Восстановлен backup"
};

function svgIcon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  const use = document.createElementNS(SVG_NS, "use");
  svg.classList.add("icon");
  svg.setAttribute("aria-hidden", "true");
  use.setAttribute("href", `#icon-${name}`);
  use.setAttributeNS(XLINK_NS, "xlink:href", `#icon-${name}`);
  svg.append(use);
  return svg;
}

function setButtonContent(button, iconName, text) {
  button.textContent = "";
  if (iconName) button.append(svgIcon(iconName));
  button.append(document.createTextNode(text));
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function createButton(text, className, iconName) {
  const button = createElement("button", className);
  button.type = "button";
  setButtonContent(button, iconName, text);
  return button;
}

function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function normalizeErrorText(text, status) {
  const clean = (text || "").trim();
  if (!clean) return `Ошибка запроса (${status})`;
  if (clean.startsWith("<!doctype") || clean.startsWith("<html") || clean.includes("<title>404")) {
    return `API недоступен (${status}). Перезапустите актуальный CloudDB-сервер.`;
  }
  return clean.slice(0, 220);
}

function showMessage(text, type = "error") {
  clearTimeout(toastTimer);
  message.textContent = text || "";
  message.className = text ? `toast-message ${type}` : "toast-message";
  if (text) {
    toastTimer = setTimeout(() => showMessage(""), type === "error" ? 6500 : 3200);
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: normalizeErrorText(text, response.status) };
    }
  }
  if (!response.ok) {
    throw new Error(data.error || `Ошибка запроса (${response.status})`);
  }
  return data;
}

function setBusy(button, busy, iconName, idleText, busyText) {
  button.disabled = busy;
  setButtonContent(button, iconName, busy ? busyText : idleText);
}

function setAuthMode(mode) {
  const isLogin = mode === "login";
  loginForm.classList.toggle("hide", !isLogin);
  registerForm.classList.toggle("hide", isLogin);
  authModeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.authMode === mode);
  });
  authTitle.textContent = isLogin ? "Войдите в CloudDB" : "Создайте аккаунт CloudDB";
  authSubtitle.textContent = isLogin
    ? "Продолжите работу с вашими базами данных."
    : "Создайте рабочее пространство и начните моделировать данные.";
}

function updateActiveNav() {
  const activeHash = window.location.hash || "#dashboard";
  navLinks.forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === activeHash);
  });
}

function scrollToSection(hash) {
  const section = document.querySelector(hash);
  if (section) {
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function navigateToHash(hash) {
  if (window.location.hash !== hash) {
    window.location.hash = hash;
  }
  updateActiveNav();
  requestAnimationFrame(() => scrollToSection(hash));
}

function handleNavClick(event) {
  const hash = event.currentTarget.getAttribute("href");
  if (hash === "#tablesBox" && !selectedDb) {
    event.preventDefault();
    showMessage("Сначала откройте базу данных");
    navigateToHash("#databases");
    return;
  }

  if (hash === "#recordsBox" && !selectedTable) {
    event.preventDefault();
    if (selectedDb) {
      tablesBox.classList.remove("hide");
      showMessage("Сначала откройте таблицу");
      navigateToHash("#tablesBox");
      return;
    }
    showMessage("Сначала откройте базу данных и таблицу");
    navigateToHash("#databases");
    return;
  }

  if (hash === "#backupsBox") {
    syncBackupDatabaseOptions();
    loadBackups().catch((error) => showMessage(error.message));
  }
}

function confirmAction({ title, text, actionText = "Удалить", iconName = "trash", danger = true }) {
  if (
    !confirmDialog ||
    !confirmTitle ||
    !confirmText ||
    !confirmOkBtn ||
    !confirmCancelBtn ||
    typeof confirmDialog.showModal !== "function"
  ) {
    return Promise.resolve(window.confirm(`${title}\n\n${text}`));
  }

  if (confirmDialog.open) confirmDialog.close();
  confirmTitle.textContent = title;
  confirmText.textContent = text;
  confirmOkBtn.classList.toggle("danger", danger);
  setButtonContent(confirmOkBtn, iconName, actionText);

  return new Promise((resolve) => {
    const cleanup = () => {
      confirmOkBtn.removeEventListener("click", onConfirm);
      confirmCancelBtn.removeEventListener("click", onCancel);
      confirmDialog.removeEventListener("cancel", onCancel);
      confirmDialog.removeEventListener("click", onBackdrop);
    };
    const close = (answer) => {
      cleanup();
      confirmDialog.close();
      resolve(answer);
    };
    const onConfirm = () => close(true);
    const onCancel = (event) => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      close(false);
    };
    const onBackdrop = (event) => {
      if (event.target === confirmDialog) close(false);
    };

    confirmOkBtn.addEventListener("click", onConfirm);
    confirmCancelBtn.addEventListener("click", onCancel);
    confirmDialog.addEventListener("cancel", onCancel);
    confirmDialog.addEventListener("click", onBackdrop);
    confirmDialog.showModal();
  });
}

function renderEmpty(container, title, text, iconName = "database") {
  container.innerHTML = "";
  const empty = createElement("div", "empty-state");
  empty.append(svgIcon(iconName));
  empty.append(createElement("strong", "", title));
  empty.append(createElement("span", "", text));
  container.append(empty);
}

function renderListError(container, text) {
  container.innerHTML = "";
  const error = createElement("div", "empty-state error-state");
  error.append(createElement("strong", "", "Не удалось загрузить"));
  error.append(createElement("span", "", text));
  container.append(error);
}

async function checkLogin() {
  const me = await api("/api/me");
  if (me.logged_in) {
    authBox.classList.add("hide");
    appBox.classList.remove("hide");
    userEmail.textContent = me.email;
    try {
      await loadSchemaTemplates();
    } catch (error) {
      showMessage(error.message);
    }
    await refreshAll();
  } else {
    authBox.classList.remove("hide");
    appBox.classList.add("hide");
    userEmail.textContent = "Гость";
  }
}

async function refreshAll() {
  const results = await Promise.allSettled([loadOverview(), loadDatabases()]);
  results.forEach((result) => {
    if (result.status === "rejected") showMessage(result.reason.message);
  });
  syncBackupDatabaseOptions();
  await loadBackups().catch((error) => showMessage(error.message));
  if (selectedDb) await loadTables().catch((error) => showMessage(error.message));
  if (selectedTable) await loadRecords().catch((error) => showMessage(error.message));
}

async function loadOverview() {
  const overview = await api("/api/overview");
  const stats = overview.stats;

  statDbs.textContent = stats.databases;
  statTables.textContent = stats.tables;
  statRecords.textContent = stats.records;
  statEvents.textContent = stats.events;
  statStorage.textContent = formatBytes(stats.storage_bytes);
  statInvocations.textContent = overview.autoscaling.estimated_invocations;
  statBackups.textContent = stats.backups || 0;
  scaleMode.textContent = overview.autoscaling.mode;
  scaleConcurrency.textContent = overview.autoscaling.max_concurrency;
  scaleLatency.textContent = `${overview.autoscaling.p95_latency_ms} ms`;
  scaleColdStart.textContent = `${overview.autoscaling.cold_start_ms} ms`;
  backupPolicy.textContent = overview.backup_status?.policy || "manual snapshots";
  backupStatus.textContent = overview.backup_status?.status || "ready";
  backupLatest.textContent = overview.backup_status?.latest_at || "-";
  backupSize.textContent = formatBytes(overview.backup_status?.latest_size_bytes || 0);

  renderFunctions(overview.functions);
  renderRegions(overview.regions);
  renderActivity(overview.activity);
}

function renderFunctions(functions) {
  functionList.innerHTML = "";
  if (!functions.length) {
    renderEmpty(functionList, "Функций пока нет", "Создайте таблицы и записи, чтобы увидеть активность.", "function");
    return;
  }
  functions.forEach((fn) => {
    const row = createElement("div", "compact-row");
    row.append(createElement("strong", "", fn.name));
    row.append(createElement("span", "", fn.trigger));
    row.append(createElement("mark", "ok", fn.status));
    functionList.append(row);
  });
}

function renderRegions(regions) {
  regionList.innerHTML = "";
  regions.forEach((region) => {
    const row = createElement("div", "compact-row");
    row.append(createElement("strong", "", region.code));
    row.append(createElement("span", "", `${region.latency_ms} ms`));
    row.append(createElement("mark", region.status === "active" ? "ok" : "idle", region.status));
    regionList.append(row);
  });
}

function renderActivity(items) {
  activityList.innerHTML = "";
  if (!items.length) {
    renderEmpty(activityList, "Событий пока нет", "Действия пользователя появятся здесь.", "activity");
    return;
  }

  items.forEach((event) => {
    const row = createElement("div", "timeline-item");
    row.append(createElement("strong", "", actionLabels[event.action] || event.action));
    const details = event.details && (event.details.name || event.details.table || event.details.email || event.details.count);
    row.append(createElement("span", "", details ? String(details) : event.entity_type));
    row.append(createElement("small", "", event.created_at));
    activityList.append(row);
  });
}

async function loadSchemaTemplates() {
  if (schemaTemplates.length) return;
  schemaTemplates = await api("/api/schema/templates");
  schemaTemplates.forEach((template) => {
    const option = document.createElement("option");
    option.value = template.id;
    option.textContent = template.name;
    schemaTemplateSelect.append(option);
  });
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = event.submitter || loginForm.querySelector("button[type='submit']");
  try {
    setBusy(submitButton, true, null, "Продолжить", "Проверка...");
    await api("/api/login", {
      method: "POST",
      body: JSON.stringify(formData(event.target))
    });
    showMessage("");
    await checkLogin();
  } catch (error) {
    showMessage(error.message);
  } finally {
    setBusy(submitButton, false, null, "Продолжить", "Проверка...");
  }
});

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = event.submitter || registerForm.querySelector("button[type='submit']");
  try {
    setBusy(submitButton, true, null, "Создать аккаунт", "Создание...");
    await api("/api/register", {
      method: "POST",
      body: JSON.stringify(formData(event.target))
    });
    showMessage("");
    await checkLogin();
  } catch (error) {
    showMessage(error.message);
  } finally {
    setBusy(submitButton, false, null, "Создать аккаунт", "Создание...");
  }
});

authModeButtons.forEach((button) => {
  button.addEventListener("click", () => setAuthMode(button.dataset.authMode));
});

logoutBtn.addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  selectedDb = null;
  selectedTable = null;
  tablesBox.classList.add("hide");
  recordsBox.classList.add("hide");
  await checkLogin();
});

document.getElementById("refreshBtn").addEventListener("click", async (event) => {
  try {
    setBusy(event.currentTarget, true, "refresh", "", "");
    await refreshAll();
  } finally {
    setBusy(event.currentTarget, false, "refresh", "", "");
  }
});

dbForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = formData(event.target);
  const id = dbId.value;
  try {
    setBusy(dbSaveBtn, true, id ? "edit" : "plus", id ? "Сохранить" : "Добавить", id ? "Сохранение..." : "Создание...");
    await api(id ? `/api/databases/${id}` : "/api/databases", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(payload)
    });
    resetDatabaseForm();
    showMessage("База сохранена", "success");
    await refreshAll();
  } catch (error) {
    showMessage(error.message);
  } finally {
    setBusy(dbSaveBtn, false, dbId.value ? "edit" : "plus", dbId.value ? "Сохранить" : "Добавить", "");
  }
});

dbCancelBtn.addEventListener("click", resetDatabaseForm);

function resetDatabaseForm() {
  dbForm.reset();
  dbId.value = "";
  setButtonContent(dbSaveBtn, "plus", "Добавить");
}

async function loadDatabases() {
  dbList.innerHTML = "";
  databasesCache = await api("/api/databases");

  if (!databasesCache.length) {
    renderEmpty(dbList, "Нет баз данных", "Создайте первую базу в текущем рабочем пространстве.", "database");
    return databasesCache;
  }

  databasesCache.forEach((db) => {
    const item = createElement("article", "resource-card");
    if (selectedDb && selectedDb.id === db.id) item.classList.add("selected");
    const heading = createElement("div", "resource-heading");
    heading.append(svgIcon("database"));
    heading.append(createElement("h3", "", db.name));
    item.append(heading);
    item.append(createElement("p", "", db.description || "Без описания"));

    const counters = createElement("div", "card-counters");
    counters.append(createElement("span", "", `${db.table_count || 0} таблиц`));
    counters.append(createElement("span", "", `${db.record_count || 0} записей`));

    const actions = createElement("div", "card-actions");
    const openBtn = createButton("Открыть", "icon-button", "dashboard");
    const downloadBtn = createButton("Download DB", "secondary icon-button", "download");
    const backupBtn = createButton("Backup", "secondary icon-button", "backup");
    const editBtn = createButton("Изменить", "secondary icon-button", "edit");
    const deleteBtn = createButton("Удалить", "danger icon-button", "trash");
    openBtn.onclick = () => openDatabase(db);
    downloadBtn.onclick = () => downloadDatabaseSnapshot(db.id, downloadBtn, "Download DB").catch((error) => showMessage(error.message));
    backupBtn.onclick = async () => {
      syncBackupDatabaseOptions(db.id);
      navigateToHash("#backupsBox");
      await createBackup(db.id, backupBtn, "Backup").catch((error) => showMessage(error.message));
    };
    editBtn.onclick = () => editDatabase(db);
    deleteBtn.onclick = () => deleteDatabase(db.id);
    actions.append(openBtn, downloadBtn, backupBtn, editBtn, deleteBtn);

    item.append(counters, actions);
    dbList.append(item);
  });
  return databasesCache;
}

function editDatabase(db) {
  dbId.value = db.id;
  dbForm.elements.name.value = db.name;
  dbForm.elements.description.value = db.description || "";
  setButtonContent(dbSaveBtn, "edit", "Сохранить");
  dbForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function deleteDatabase(id) {
  const confirmed = await confirmAction({
    title: "Удалить базу?",
    text: "CloudDB удалит базу вместе со всеми таблицами и записями. Это действие нельзя отменить."
  });
  if (!confirmed) return;
  await api(`/api/databases/${id}`, { method: "DELETE" });
  if (selectedDb && selectedDb.id === id) {
    selectedDb = null;
    selectedTable = null;
    tablesBox.classList.add("hide");
    recordsBox.classList.add("hide");
  }
  await refreshAll();
}

async function openDatabase(db) {
  selectedDb = db;
  selectedTable = null;
  currentDbName.textContent = db.name;
  tablesBox.classList.remove("hide");
  recordsBox.classList.add("hide");
  resetTableForm();
  syncBackupDatabaseOptions(db.id);
  loadBackups(db.id).catch((error) => showMessage(error.message));
  await loadTables();
  await loadDatabases();
  navigateToHash("#tablesBox");
}

schemaTemplateSelect.addEventListener("change", () => {
  const template = schemaTemplates.find((item) => item.id === schemaTemplateSelect.value);
  if (!template) return;
  tableForm.elements.name.value = template.name.toLowerCase();
  tableForm.elements.columns.value = JSON.stringify(template.columns, null, 2);
});

tableForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedDb) {
    showMessage("Сначала выберите базу");
    return;
  }

  const payload = formData(event.target);
  const id = tableId.value;
  try {
    payload.database_id = selectedDb.id;
    payload.columns = JSON.parse(payload.columns);
    setBusy(tableSaveBtn, true, id ? "edit" : "plus", id ? "Сохранить таблицу" : "Создать таблицу", id ? "Сохранение..." : "Создание...");
    await api(id ? `/api/tables/${id}` : "/api/tables", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(payload)
    });
    resetTableForm();
    showMessage("Схема сохранена", "success");
    await refreshAll();
  } catch (error) {
    showMessage("Проверьте схему: " + error.message);
  } finally {
    setBusy(tableSaveBtn, false, tableId.value ? "edit" : "plus", tableId.value ? "Сохранить таблицу" : "Создать таблицу", "");
  }
});

tableCancelBtn.addEventListener("click", resetTableForm);

function resetTableForm() {
  tableForm.reset();
  tableId.value = "";
  schemaTemplateSelect.value = "";
  setButtonContent(tableSaveBtn, "plus", "Создать таблицу");
}

async function loadTables() {
  if (!selectedDb) return [];
  tableList.innerHTML = "";
  tablesCache = await api(`/api/tables?database_id=${selectedDb.id}`);

  if (!tablesCache.length) {
    renderEmpty(tableList, "Нет таблиц", "Создайте схему или выберите шаблон.", "schema");
    return tablesCache;
  }

  tablesCache.forEach((table) => {
    const item = createElement("article", "resource-card");
    if (selectedTable && selectedTable.id === table.id) item.classList.add("selected");
    const heading = createElement("div", "resource-heading");
    heading.append(svgIcon("schema"));
    heading.append(createElement("h3", "", table.name));
    item.append(heading);
    item.append(createElement("p", "", table.columns.map((column) => `${column.name}:${column.type || "text"}`).join(", ")));

    const counters = createElement("div", "card-counters");
    counters.append(createElement("span", "", `${table.record_count || 0} записей`));
    counters.append(createElement("span", "", `${table.columns.length} колонок`));

    const actions = createElement("div", "card-actions");
    const openBtn = createButton("Записи", "icon-button", "records");
    const editBtn = createButton("Схема", "secondary icon-button", "edit");
    const deleteBtn = createButton("Удалить", "danger icon-button", "trash");
    openBtn.onclick = () => openTable(table);
    editBtn.onclick = () => editTable(table);
    deleteBtn.onclick = () => deleteTable(table.id);
    actions.append(openBtn, editBtn, deleteBtn);

    item.append(counters, actions);
    tableList.append(item);
  });
  return tablesCache;
}

function editTable(table) {
  tableId.value = table.id;
  tableForm.elements.name.value = table.name;
  tableForm.elements.columns.value = JSON.stringify(table.columns, null, 2);
  setButtonContent(tableSaveBtn, "edit", "Сохранить таблицу");
  tableForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function deleteTable(id) {
  const confirmed = await confirmAction({
    title: "Удалить таблицу?",
    text: "Таблица и все связанные записи будут удалены из текущей базы."
  });
  if (!confirmed) return;
  await api(`/api/tables/${id}`, { method: "DELETE" });
  if (selectedTable && selectedTable.id === id) {
    selectedTable = null;
    recordsBox.classList.add("hide");
  }
  await refreshAll();
}

function openTable(table) {
  selectedTable = table;
  currentTableName.textContent = table.name;
  renderColumns(table.columns);
  resetRecordSortOptions(table.columns);
  clearRecordForm();
  recordsBox.classList.remove("hide");
  loadRecords().catch((error) => showMessage(error.message));
  loadTables().catch((error) => showMessage(error.message));
  navigateToHash("#recordsBox");
}

function renderColumns(columns) {
  columnsInfo.innerHTML = "";
  columns.forEach((column) => {
    const chip = createElement("span", "column-chip");
    chip.textContent = `${column.name} / ${column.type || "text"}${column.required ? " / required" : ""}`;
    columnsInfo.append(chip);
  });
}

function resetRecordSortOptions(columns) {
  recordSortBy.innerHTML = "";
  [
    { value: "id", label: "Сортировка: id" },
    { value: "created_at", label: "Создано" },
    { value: "updated_at", label: "Обновлено" },
    ...columns.map((column) => ({ value: column.name, label: column.name }))
  ].forEach((optionData) => {
    const option = document.createElement("option");
    option.value = optionData.value;
    option.textContent = optionData.label;
    recordSortBy.append(option);
  });
}

function defaultValueForColumn(column) {
  if (column.default !== undefined) return column.default;
  if (column.type === "number") return 0;
  if (column.type === "boolean") return false;
  if (column.type === "json") return {};
  return "";
}

function makeExampleRecord(columns) {
  const obj = {};
  columns.forEach((column) => {
    obj[column.name] = defaultValueForColumn(column);
  });
  return JSON.stringify(obj, null, 2);
}

document.getElementById("recordForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedTable) return;

  const id = recordId.value;
  try {
    const body = {
      table_id: selectedTable.id,
      data: JSON.parse(recordData.value)
    };
    setBusy(recordSaveBtn, true, id ? "edit" : "plus", id ? "Сохранить" : "Добавить запись", id ? "Сохранение..." : "Добавление...");
    await api(id ? `/api/records/${id}` : "/api/records", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(body)
    });
    clearRecordForm();
    showMessage("Запись сохранена", "success");
    await refreshAll();
  } catch (error) {
    showMessage("Проверьте JSON записи: " + error.message);
  } finally {
    setBusy(recordSaveBtn, false, recordId.value ? "edit" : "plus", recordId.value ? "Сохранить" : "Добавить запись", "");
  }
});

document.getElementById("recordCancelBtn").addEventListener("click", clearRecordForm);
document.getElementById("filterBtn").addEventListener("click", () => loadRecords().catch((error) => showMessage(error.message)));
recordFilter.addEventListener("input", () => {
  clearTimeout(recordFilterTimer);
  recordFilterTimer = setTimeout(() => loadRecords().catch((error) => showMessage(error.message)), 250);
});
recordSortBy.addEventListener("change", () => loadRecords().catch((error) => showMessage(error.message)));
recordSortOrder.addEventListener("change", () => loadRecords().catch((error) => showMessage(error.message)));

function clearRecordForm() {
  recordId.value = "";
  setButtonContent(recordSaveBtn, "plus", "Добавить запись");
  if (selectedTable) {
    recordData.value = makeExampleRecord(selectedTable.columns);
  }
}

async function loadRecords() {
  if (!selectedTable) return [];
  const params = new URLSearchParams({
    table_id: selectedTable.id,
    filter: recordFilter.value,
    sort_by: recordSortBy.value,
    sort_order: recordSortOrder.value
  });
  recordList.innerHTML = "";
  const records = await api(`/api/records?${params.toString()}`);

  if (!records.length) {
    renderEmpty(recordList, "Записей нет", "Добавьте запись или измените фильтр.", "records");
    return records;
  }

  records.forEach((record) => {
    const row = createElement("article", "record-row");
    const meta = createElement("div", "record-meta");
    meta.append(createElement("strong", "", `#${record.id}`));
    meta.append(createElement("span", "", `created ${record.created_at}`));
    meta.append(createElement("span", "", `updated ${record.updated_at}`));

    const actions = createElement("div", "card-actions");
    const editBtn = createButton("Изменить", "secondary icon-button", "edit");
    const deleteBtn = createButton("Удалить", "danger icon-button", "trash");
    editBtn.onclick = () => editRecord(record);
    deleteBtn.onclick = () => deleteRecord(record.id);
    actions.append(editBtn, deleteBtn);

    row.append(meta, actions);
    row.append(createElement("pre", "", JSON.stringify(record.data, null, 2)));
    recordList.append(row);
  });
  return records;
}

function editRecord(record) {
  recordId.value = record.id;
  setButtonContent(recordSaveBtn, "edit", "Сохранить");
  recordData.value = JSON.stringify(record.data, null, 2);
  recordData.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function deleteRecord(id) {
  const confirmed = await confirmAction({
    title: "Удалить запись?",
    text: "Запись исчезнет из таблицы и из будущих экспортов."
  });
  if (!confirmed) return;
  await api(`/api/records/${id}`, { method: "DELETE" });
  await refreshAll();
}

document.getElementById("importBtn").addEventListener("click", async () => {
  if (!selectedTable) return;
  try {
    const records = JSON.parse(importData.value);
    const result = await api(`/api/tables/${selectedTable.id}/import`, {
      method: "POST",
      body: JSON.stringify({ records })
    });
    showMessage(`Импортировано записей: ${result.imported}`, "success");
    importData.value = "[\n  {}\n]";
    await refreshAll();
  } catch (error) {
    showMessage("Импорт не выполнен: " + error.message);
  }
});

document.getElementById("exportBtn").addEventListener("click", async () => {
  try {
    await exportTableJson();
  } catch (error) {
    showMessage(error.message);
  }
});

document.getElementById("exportCsvBtn").addEventListener("click", async () => {
  try {
    await exportTableCsv();
  } catch (error) {
    showMessage(error.message);
  }
});

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.style.display = "none";
  document.body.append(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
    link.remove();
  }, 1000);
}

function filenameFromDisposition(header, fallback) {
  const value = header || "";
  const match = value.match(/filename="?([^"]+)"?/i);
  return match ? match[1] : fallback;
}

async function downloadFromApi(url, fallbackFileName) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    const text = await response.text();
    let error = `Download failed (${response.status})`;
    try {
      error = JSON.parse(text).error || error;
    } catch {
      error = normalizeErrorText(text, response.status);
    }
    throw new Error(error);
  }
  const blob = await response.blob();
  const filename = filenameFromDisposition(response.headers.get("Content-Disposition"), fallbackFileName);
  downloadBlob(blob, filename);
}

async function exportTableJson() {
  if (!selectedTable) return;
  const data = await api(`/api/tables/${selectedTable.id}/export`);
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  downloadBlob(blob, `${selectedTable.name}.json`);
}

async function exportTableCsv() {
  if (!selectedTable) return;
  const response = await fetch(`/api/tables/${selectedTable.id}/export?format=csv`);
  if (!response.ok) {
    const text = await response.text();
    let error = "CSV-экспорт не выполнен";
    try {
      error = JSON.parse(text).error || error;
    } catch {
      error = normalizeErrorText(text, response.status);
    }
    throw new Error(error);
  }
  const blob = await response.blob();
  downloadBlob(blob, `${selectedTable.name}.csv`);
}

function selectedBackupDatabaseId() {
  const value = backupDatabaseSelect.value;
  return value ? Number(value) : null;
}

function syncBackupDatabaseOptions(preferredId = null) {
  const currentValue = preferredId || selectedBackupDatabaseId() || selectedDb?.id || databasesCache[0]?.id || "";
  backupDatabaseSelect.innerHTML = "";
  if (!databasesCache.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Нет баз данных";
    backupDatabaseSelect.append(option);
    createBackupBtn.disabled = true;
    downloadSnapshotBtn.disabled = true;
    return;
  }

  databasesCache.forEach((db) => {
    const option = document.createElement("option");
    option.value = db.id;
    option.textContent = db.name;
    backupDatabaseSelect.append(option);
  });
  backupDatabaseSelect.value = String(currentValue || databasesCache[0].id);
  createBackupBtn.disabled = false;
  downloadSnapshotBtn.disabled = false;
}

async function loadBackups(databaseId = selectedBackupDatabaseId()) {
  backupList.innerHTML = "";
  if (!databaseId) {
    backupsCache = [];
    renderEmpty(backupList, "Backups недоступны", "Создайте базу данных, чтобы скачать SQLite snapshot или создать backup.", "backup");
    return backupsCache;
  }

  backupsCache = await api(`/api/databases/${databaseId}/backups`);
  renderBackups(backupsCache);
  return backupsCache;
}

function renderBackups(backups) {
  backupList.innerHTML = "";
  if (!backups.length) {
    renderEmpty(backupList, "Backup-история пустая", "Создайте первый snapshot выбранной базы данных.", "backup");
    return;
  }

  backups.forEach((backup) => {
    const item = createElement("article", "backup-card");
    const meta = createElement("div", "");
    meta.append(createElement("strong", "", backup.name));
    const details = createElement("div", "backup-meta");
    details.append(createElement("span", "", backup.created_at));
    details.append(createElement("span", "", formatBytes(backup.size_bytes)));
    details.append(createElement("span", "", `#${backup.id}`));
    meta.append(details);

    const actions = createElement("div", "card-actions");
    const downloadBtn = createButton("Download", "secondary icon-button", "download");
    const restoreBtn = createButton("Restore", "icon-button", "restore");
    downloadBtn.onclick = () => downloadBackup(backup.id, downloadBtn).catch((error) => showMessage(error.message));
    restoreBtn.onclick = () => restoreBackup(backup.id, restoreBtn).catch((error) => showMessage(error.message));
    actions.append(downloadBtn, restoreBtn);

    item.append(meta, actions);
    backupList.append(item);
  });
}

async function createBackup(databaseId = selectedBackupDatabaseId(), button = createBackupBtn, idleText = "Create backup") {
  if (!databaseId) {
    showMessage("Выберите базу данных");
    return;
  }
  const idleName = backupName.value.trim();
  try {
    setBusy(button, true, "backup", idleText, "Creating...");
    const backup = await api(`/api/databases/${databaseId}/backups`, {
      method: "POST",
      body: JSON.stringify({ name: idleName })
    });
    backupName.value = "";
    showMessage(`Backup создан: ${backup.name}`, "success");
    await Promise.allSettled([loadBackups(databaseId), loadOverview()]);
  } finally {
    setBusy(button, false, "backup", idleText, "Creating...");
  }
}

async function downloadDatabaseSnapshot(databaseId = selectedBackupDatabaseId(), button = downloadSnapshotBtn, idleText = "Download DB") {
  if (!databaseId) {
    showMessage("Выберите базу данных");
    return;
  }
  try {
    setBusy(button, true, "download", idleText, "Downloading...");
    await downloadFromApi(`/api/databases/${databaseId}/snapshot.sqlite`, "clouddb_snapshot.sqlite");
    showMessage("SQLite snapshot скачан", "success");
  } finally {
    setBusy(button, false, "download", idleText, "Downloading...");
  }
}

async function downloadBackup(backupId, button = null) {
  try {
    if (button) setBusy(button, true, "download", "Download", "Downloading...");
    await downloadFromApi(`/api/backups/${backupId}/download.sqlite`, "clouddb_backup.sqlite");
    showMessage("Backup скачан", "success");
  } finally {
    if (button) setBusy(button, false, "download", "Download", "Downloading...");
  }
}

async function restoreBackup(backupId, button = null) {
  const confirmed = await confirmAction({
    title: "Восстановить backup?",
    text: "CloudDB создаст новую базу с суффиксом Restored. Текущие базы и записи не будут перезаписаны.",
    actionText: "Restore",
    iconName: "restore",
    danger: false
  });
  if (!confirmed) return;

  try {
    if (button) setBusy(button, true, "restore", "Restore", "Restoring...");
    const restored = await api(`/api/backups/${backupId}/restore`, { method: "POST" });
    showMessage(`Восстановлена база: ${restored.name}`, "success");
    await refreshAll();
    const db = databasesCache.find((item) => item.id === restored.id);
    if (db) await openDatabase(db);
  } finally {
    if (button) setBusy(button, false, "restore", "Restore", "Restoring...");
  }
}

backupDatabaseSelect.addEventListener("change", () => {
  loadBackups().catch((error) => showMessage(error.message));
});

createBackupBtn.addEventListener("click", () => {
  createBackup().catch((error) => showMessage(error.message));
});

downloadSnapshotBtn.addEventListener("click", () => {
  downloadDatabaseSnapshot().catch((error) => showMessage(error.message));
});

globalSearch.addEventListener("input", () => {
  clearTimeout(globalSearchTimer);
  globalSearchTimer = setTimeout(runGlobalSearch, 250);
});

async function runGlobalSearch() {
  const query = globalSearch.value.trim();
  searchResults.innerHTML = "";
  if (query.length < 2) {
    searchResults.classList.add("hide");
    return;
  }

  try {
    const results = await api(`/api/search?q=${encodeURIComponent(query)}`);
    searchResults.classList.remove("hide");
    if (!results.length) {
      renderEmpty(searchResults, "Ничего не найдено", "Попробуйте другой запрос.", "search");
      return;
    }

    results.forEach((result) => {
      const item = createElement("button", "search-item");
      item.type = "button";
      item.append(createElement("strong", "", `${result.type}: ${result.title}`));
      item.append(createElement("span", "", result.subtitle || ""));
      item.onclick = () => jumpToSearchResult(result);
      searchResults.append(item);
    });
  } catch (error) {
    searchResults.classList.remove("hide");
    renderListError(searchResults, error.message);
  }
}

async function jumpToSearchResult(result) {
  searchResults.classList.add("hide");
  const db = databasesCache.find((item) => item.id === result.database_id);
  if (!db) return;
  await openDatabase(db);
  if (result.table_id) {
    const table = tablesCache.find((item) => item.id === result.table_id);
    if (table) openTable(table);
  }
}

window.addEventListener("hashchange", updateActiveNav);
navLinks.forEach((link) => link.addEventListener("click", handleNavClick));
setAuthMode("login");
updateActiveNav();
checkLogin().catch((error) => showMessage(error.message));
