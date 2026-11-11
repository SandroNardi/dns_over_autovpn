const $ = (id) => document.getElementById(id);

let rows = [];
let includeTunnels = false;
let sortKey = "network_name";
let sortDir = 1;
const openRows = new Set();

const FILTERS = [
  { id: "f-role", label: "All roles", value: (row) => row.vpn_role },
  { id: "f-hub", label: "Any hub", value: (row) => (row.hubs || []).map((hub) => hub.hub_name), multi: true },
  { id: "f-mx", label: "Any status", value: (row) => row.mx_status },
  { id: "f-l3", label: "Any", value: (row) => row.l3_routing },
  { id: "f-sw", label: "Any", value: (row) => switchState(row) },
];

function switchState(row) {
  const modes = (row.interfaces || [])
    .filter((item) => String(item.vlan_id) === "1" && item.dhcp)
    .map((item) => item.dhcp);
  if (modes.length) return modes;
  if (row.sw_dhcp && row.sw_dhcp !== "n/a") return row.sw_dhcp;
  if (row.sw_vlan1 && row.sw_vlan1 !== "n/a") return row.sw_vlan1;
  return row.l3_routing || "";
}

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.title) node.title = options.title;
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === "") continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function flash(kind, message) {
  const box = $("flash");
  box.className = `banner ${kind}`;
  box.textContent = message;
  if (!message) box.classList.add("hidden");
}

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let body = {};
  if (text) {
    try { body = JSON.parse(text); } catch (_err) { body = { error: text }; }
  }
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status}).`);
  return body;
}

function badgeClass(value) {
  const text = String(value || "").toLowerCase();
  if (text === "spoke") return "badge spoke";
  if (text === "hub") return "badge hub";
  if (text === "off" || text.startsWith("not checked") || text === "no switches") return "badge off";
  if (text === "error" || text.includes("error") || text === "unknown") return "badge error";
  if (text === "yes" || text === "dhcp server") return "badge good";
  return "badge warn";
}

const COLUMNS = [
  {
    key: "network_name", label: "Network", className: "name",
    render: (row) => [row.network_name, row.template ? el("small", { text: `Template: ${row.template}` }) : null],
  },
  { key: "vpn_role", label: "Auto VPN", render: (row) => el("span", { className: badgeClass(row.vpn_role), text: row.vpn_role }) },
  {
    key: "hub_count", label: "Hubs (priority order)",
    render: (row) => {
      if (!row.hubs || !row.hubs.length) return row.hubs_label || "—";
      return el("ol", { className: "hubs" }, row.hubs.map((hub) => el("li", {}, [
        hub.hub_name,
        hub.default_route ? el("span", { className: "tag", text: "default route" }) : null,
        hub.tunnel ? el("span", { className: "tag", text: hub.tunnel }) : null,
      ])));
    },
  },
  { key: "tunnels_label", label: "Tunnels", tunnelsOnly: true, render: (row) => row.tunnels_label || "—" },
  { key: "mx_status", label: "MX VLAN 1", render: (row) => el("span", { className: badgeClass(row.mx_status), text: row.mx_status }) },
  { key: "mx_dns", label: "MX VLAN 1 DNS", className: "dns", render: (row) => row.mx_dns || "—" },
  { key: "l3_routing", label: "Switch L3", render: (row) => el("span", { className: badgeClass(row.l3_routing), text: row.l3_routing }) },
  {
    key: "sw_vlan1", label: "Switch VLAN 1",
    render: (row) => [row.sw_vlan1 || "—", row.sw_dhcp && row.sw_dhcp !== "n/a" ? el("small", { className: "tag", text: row.sw_dhcp }) : null],
  },
  { key: "sw_dns", label: "Switch VLAN 1 DNS", className: "dns", render: (row) => row.sw_dns || "—" },
  {
    key: "notes_label", label: "Notes", className: "notes",
    render: (row) => (row.notes && row.notes.length ? `${row.notes.length} note${row.notes.length > 1 ? "s" : ""}` : ""),
  },
];

function visibleColumns() {
  return COLUMNS.filter((column) => !column.tunnelsOnly || includeTunnels);
}

function fillFilter(filter) {
  const select = $(filter.id);
  const current = select.value;
  const values = new Set();
  rows.forEach((row) => [].concat(filter.value(row)).forEach((value) => { if (value) values.add(value); }));
  select.replaceChildren(el("option", { text: filter.label }));
  select.firstChild.value = "";
  [...values].sort((a, b) => a.localeCompare(b)).forEach((value) => {
    const option = el("option", { text: value });
    option.value = value;
    select.appendChild(option);
  });
  select.value = values.has(current) ? current : "";
}

function filteredRows() {
  const query = $("search").value.trim().toLowerCase();
  const notesOnly = $("f-notes").checked;
  return rows.filter((row) => {
    for (const filter of FILTERS) {
      const wanted = $(filter.id).value;
      if (!wanted) continue;
      const values = [].concat(filter.value(row));
      if (!values.includes(wanted)) return false;
    }
    if (notesOnly && !(row.notes || []).length) return false;
    if (!query) return true;
    const hubs = (row.hubs || []).map((hub) => hub.hub_name).join(" ");
    const blob = [row.network_name, row.template, row.vpn_role, hubs, row.mx_status, row.mx_dns, row.mx_subnet,
      row.l3_routing, row.sw_vlan1, row.sw_dhcp, row.sw_dns, row.notes_label].join(" ").toLowerCase();
    return blob.includes(query);
  });
}

function sortRows(list) {
  return list.slice().sort((a, b) => {
    const left = a[sortKey];
    const right = b[sortKey];
    if (typeof left === "number" && typeof right === "number") return (left - right) * sortDir;
    return String(left ?? "").localeCompare(String(right ?? ""), undefined, { numeric: true, sensitivity: "base" }) * sortDir;
  });
}

function renderHead() {
  const head = $("grid-head");
  head.replaceChildren();
  visibleColumns().forEach((column) => {
    const th = el("th", { text: column.label, title: "Click to sort" });
    if (column.key === sortKey) th.appendChild(el("span", { className: "arrow", text: sortDir === 1 ? "▲" : "▼" }));
    th.addEventListener("click", () => {
      sortDir = sortKey === column.key ? -sortDir : 1;
      sortKey = column.key;
      renderTable();
    });
    head.appendChild(th);
  });
}

function miniTable(headers, records) {
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {}, headers.map((header) => el("th", { text: header })))));
  table.appendChild(el("tbody", {}, records.map((record) => el("tr", {}, record.map((value) => el("td", { text: String(value ?? "") }))))));
  return table;
}

function detailRow(row, span) {
  const grid = el("div", { className: "detail-grid" });

  const hubBlock = el("div", {}, el("h3", { text: "Hubs in priority order" }));
  if (row.hubs && row.hubs.length) {
    const headers = ["Priority", "Hub", "Default route"];
    if (includeTunnels) headers.push("Tunnel");
    hubBlock.appendChild(miniTable(headers, row.hubs.map((hub) => {
      const record = [hub.priority, hub.hub_name, hub.default_route ? "Yes" : "No"];
      if (includeTunnels) record.push(hub.tunnel || "—");
      return record;
    })));
  } else {
    hubBlock.appendChild(el("p", { className: "meta", text: row.vpn_role === "Spoke" ? "No hubs configured." : "Not a spoke." }));
  }
  grid.appendChild(hubBlock);

  const mxBlock = el("div", {}, el("h3", { text: "MX VLAN 1" }));
  mxBlock.appendChild(miniTable(["Field", "Value"], [
    ["Status", row.mx_status],
    ["Subnet", row.mx_subnet || "—"],
    ["DNS type", row.mx_dns_type || "—"],
    ["DNS", row.mx_dns || "—"],
  ]));
  grid.appendChild(mxBlock);

  const swBlock = el("div", {}, el("h3", { text: "Switch Layer 3 interfaces" }));
  swBlock.appendChild(el("p", { className: "meta", text: row.switch_summary || "Not checked." }));
  if (row.interfaces && row.interfaces.length) {
    swBlock.appendChild(miniTable(["Owner", "Interface", "VLAN", "Subnet", "IP", "DHCP", "DNS"],
      row.interfaces.map((item) => [item.owner, item.interface, item.vlan_id, item.subnet, item.ip, item.dhcp || "—", item.dns || "—"])));
  }
  grid.appendChild(swBlock);

  if (row.notes && row.notes.length) {
    grid.appendChild(el("div", {}, [el("h3", { text: "Notes" }), el("ul", {}, row.notes.map((note) => el("li", { text: note })))]));
  }
  const td = el("td", {}, grid);
  td.colSpan = span;
  return el("tr", { className: "detail" }, td);
}

function renderTable() {
  renderHead();
  const columns = visibleColumns();
  const list = sortRows(filteredRows());
  const body = $("grid-body");
  body.replaceChildren();
  if (!list.length) {
    const td = el("td", { className: "empty", text: "No networks match these filters." });
    td.colSpan = columns.length;
    body.appendChild(el("tr", {}, td));
  }
  list.forEach((row) => {
    const tr = el("tr", { className: `row${openRows.has(row.network_id) ? " open" : ""}` });
    columns.forEach((column) => {
      const td = el("td", { className: column.className || "" }, column.render(row));
      if (column.key === "notes_label" && row.notes_label) td.title = row.notes_label;
      tr.appendChild(td);
    });
    tr.addEventListener("click", () => {
      if (openRows.has(row.network_id)) openRows.delete(row.network_id); else openRows.add(row.network_id);
      renderTable();
    });
    body.appendChild(tr);
    if (openRows.has(row.network_id)) body.appendChild(detailRow(row, columns.length));
  });
  $("table-meta").textContent = `Showing ${list.length} of ${rows.length} networks. Click a row for details, click a header to sort.`;
  renderSummary();
}

const CHIPS = [
  { label: "Networks", count: (c) => c.networks, apply: () => { $("f-role").value = ""; } },
  { label: "Spokes", count: (c) => c.spokes, apply: () => { $("f-role").value = "Spoke"; }, active: () => $("f-role").value === "Spoke" },
  { label: "Hubs", count: (c) => c.hubs, apply: () => { $("f-role").value = "Hub"; }, active: () => $("f-role").value === "Hub" },
  { label: "Auto VPN off", count: (c) => c.off, apply: () => { $("f-role").value = "Off"; }, active: () => $("f-role").value === "Off" },
  { label: "Errors", count: (c) => c.errors, apply: () => { $("f-role").value = "Error"; }, active: () => $("f-role").value === "Error" },
  { label: "Switch L3 enabled", count: (c) => c.l3_yes, apply: () => { $("f-l3").value = "Yes"; }, active: () => $("f-l3").value === "Yes" },
  { label: "Switch VLAN 1 DHCP", count: (c) => c.sw_vlan1_dhcp, apply: () => { $("f-sw").value = "DHCP server"; }, active: () => $("f-sw").value === "DHCP server" },
  { label: "With notes", count: (c) => c.with_notes, apply: () => { $("f-notes").checked = !$("f-notes").checked; }, active: () => $("f-notes").checked },
];

let counts = {};

function renderSummary() {
  const box = $("summary");
  box.replaceChildren();
  CHIPS.forEach((chip) => {
    const button = el("button", { className: `chip${chip.active && chip.active() ? " active" : ""}` }, [
      el("strong", { text: String(chip.count(counts) ?? 0) }),
      el("small", { text: chip.label }),
    ]);
    button.type = "button";
    button.addEventListener("click", () => {
      const wasActive = chip.active && chip.active();
      if (wasActive && chip.label !== "With notes") {
        FILTERS.forEach((filter) => { if ($(filter.id).value) $(filter.id).value = ""; });
      } else {
        chip.apply();
      }
      renderTable();
    });
    box.appendChild(button);
  });
}

function setProgress(progress) {
  const bar = $("progress-bar");
  const total = progress.total || 0;
  if (total > 0) {
    bar.value = Math.round((progress.done / total) * 100);
    $("progress-count").textContent = `${progress.done}/${total} · ${bar.value}%`;
  } else {
    bar.removeAttribute("value");
    $("progress-count").textContent = "";
  }
  $("progress-label").textContent = progress.label || "Working…";
}

function showResult(result) {
  rows = result.rows || [];
  counts = result.counts || {};
  includeTunnels = !!result.include_tunnels;
  openRows.clear();
  FILTERS.forEach(fillFilter);
  $("progress-card").classList.remove("hidden");
  setProgress({
    done: rows.length,
    total: rows.length,
    label: `${result.org_name}: ${rows.length} networks, ${result.api_calls} API calls in ${result.elapsed}s (${result.scanned_at})`,
  });
  $("results").classList.remove("hidden");
  renderTable();
}

async function scan() {
  const orgId = $("org").value;
  if (!orgId) {
    flash("error", "Choose an organization first.");
    return;
  }
  flash("ok", "");
  $("scan").disabled = true;
  $("org").disabled = true;
  $("progress-card").classList.remove("hidden");
  setProgress({ done: 0, total: 0, label: "Starting…" });
  const timer = setInterval(async () => {
    try { setProgress(await api("/api/progress")); } catch (_err) { /* keep the last value */ }
  }, 500);
  try {
    const result = await api("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ org_id: orgId, include_tunnels: $("tunnels").checked }),
    });
    showResult(result);
  } catch (err) {
    flash("error", err.message);
    $("progress-bar").value = 0;
    $("progress-label").textContent = err.message;
  } finally {
    clearInterval(timer);
    $("scan").disabled = false;
    $("org").disabled = false;
  }
}

function resetFilters() {
  FILTERS.forEach((filter) => { $(filter.id).value = ""; });
  $("search").value = "";
  $("f-notes").checked = false;
  renderTable();
}

function bind() {
  $("scan").addEventListener("click", scan);
  $("use-key").addEventListener("click", submitKey);
  $("api-key").addEventListener("keydown", (event) => {
    if (event.key === "Enter") submitKey();
  });
  $("reset").addEventListener("click", resetFilters);
  ["search", "f-role", "f-hub", "f-mx", "f-l3", "f-sw", "f-notes"].forEach((id) => {
    $(id).addEventListener(id === "search" ? "input" : "change", renderTable);
  });
}

async function loadOrganizations() {
  const body = await api("/api/organizations");
  const select = $("org");
  const orgs = body.organizations || [];
  select.replaceChildren(el("option", { text: orgs.length ? "Choose an organization" : "No organizations available" }));
  select.firstChild.value = "";
  orgs.forEach((org) => {
    const option = el("option", { text: org.name });
    option.value = org.id;
    select.appendChild(option);
  });
  if (orgs.length === 1) select.value = orgs[0].id;
  select.disabled = false;
  $("scan").disabled = false;
  return orgs;
}

async function submitKey() {
  const input = $("api-key");
  const apiKey = input.value;
  input.value = "";
  if (!apiKey.trim()) {
    flash("error", "Paste the API key first.");
    return;
  }
  $("use-key").disabled = true;
  try {
    await api("/api/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    });
    $("key-card").classList.add("hidden");
    flash("ok", "Key accepted for this run. It was not saved.");
    await loadOrganizations();
  } catch (err) {
    flash("error", err.message);
    $("use-key").disabled = false;
  }
}

async function start() {
  bind();
  try {
    const sessionInfo = await api("/api/session");
    if (!sessionInfo.key_set) {
      $("org").replaceChildren(el("option", { text: "Paste an API key to continue" }));
      $("key-card").classList.remove("hidden");
      $("api-key").focus();
      return;
    }
    const orgs = await loadOrganizations();
    if (sessionInfo.scan_loaded) {
      const last = await api("/api/result");
      if (orgs.some((org) => org.id === last.org_id)) $("org").value = last.org_id;
      $("tunnels").checked = !!last.include_tunnels;
      showResult(last);
    }
  } catch (err) {
    flash("error", err.message);
    $("org").replaceChildren(el("option", { text: "Could not load organizations" }));
  }
}

start();
