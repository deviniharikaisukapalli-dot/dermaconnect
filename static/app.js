const appPage = document.body.dataset.page === "app";
const patientPage = document.body.dataset.page === "patient";

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : {};
  if (!response.ok) {
    throw new Error(data.detail || data.error || `Request failed (${response.status}).`);
  }
  return data;
}

function makeElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("is-error", isError);
  toast.classList.add("is-visible");
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => toast.classList.remove("is-visible"), 3600);
}

function formatDate(value, options = { dateStyle: "medium" }) {
  if (!value) return "—";
  const date = new Date(`${value.replace(" ", "T")}Z`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, options).format(date);
}

function fillSelect(select, records, placeholder, labelKey = "name") {
  if (!select) return;
  const current = select.value;
  select.replaceChildren(new Option(placeholder, ""));
  records.forEach((record) => select.add(new Option(record[labelKey], record.id)));
  if (records.some((record) => String(record.id) === current)) select.value = current;
}

function fillList(container, rows, emptyText, renderRow) {
  if (!container) return;
  container.replaceChildren();
  if (!rows.length) {
    container.append(makeElement("p", "empty-state", emptyText));
    return;
  }
  rows.forEach((row, index) => container.append(renderRow(row, index)));
}

if (appPage) initializeApp();
if (patientPage) initializePatientPage();

async function initializeApp() {
  const today = document.getElementById("today-label");
  today.textContent = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date());
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => openView(button.dataset.view));
  });
  document.querySelectorAll("[data-open-view]").forEach((button) => {
    button.addEventListener("click", () => openView(button.dataset.openView));
  });
  document.getElementById("refresh-overview").addEventListener("click", loadOverview);
  document.getElementById("refill-filter").addEventListener("change", loadRefills);
  document.getElementById("add-prescription-item").addEventListener("click", addPrescriptionItem);
  document.getElementById("shop-store").addEventListener("change", () => {
    loadInventory();
    updateFulfillmentAvailability();
  });
  document.getElementById("verify-form").addEventListener("submit", verifyToken);
  document.getElementById("inventory-form").addEventListener("submit", saveInventory);
  document.getElementById("store-form").addEventListener("submit", createStore);
  document.getElementById("start-scan").addEventListener("click", startScanner);
  document.getElementById("doctor-form").addEventListener("submit", (event) => createRecord(event, "/api/doctors", "Doctor added."));
  document.getElementById("patient-form").addEventListener("submit", (event) => createRecord(event, "/api/patients", "Patient added."));
  document.getElementById("product-form").addEventListener("submit", (event) => createRecord(event, "/api/products", "Product added."));
  document.getElementById("prescription-form").addEventListener("submit", createPrescription);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopScanner();
  });
  window.addEventListener("pagehide", stopScanner);

  addPrescriptionItem();
  await refreshDirectories();
  await loadOverview();
  await loadRefills();
}

function openView(viewName) {
  stopScanner();
  document.querySelectorAll(".page-view").forEach((section) => {
    section.classList.toggle("is-visible", section.id === `view-${viewName}`);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === viewName;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  const section = document.getElementById(`view-${viewName}`);
  if (!section) return;
  document.getElementById("section-label").textContent = section.dataset.pageTitle;
  if (viewName === "overview") loadOverview();
  if (viewName === "doctor") {
    refreshDirectories();
    loadPrescriptions("doctor-prescriptions");
  }
  if (viewName === "shopkeeper") {
    refreshDirectories();
    loadInventory();
  }
  if (viewName === "refills") loadRefills();
}

async function refreshDirectories() {
  try {
    const [doctors, patients, products, stores] = await Promise.all([
      requestJson("/api/doctors"), requestJson("/api/patients"),
      requestJson("/api/products"), requestJson("/api/stores"),
    ]);
    fillSelect(document.getElementById("prescription-doctor"), doctors.doctors, "Select doctor", "full_name");
    fillSelect(document.getElementById("prescription-patient"), patients.patients, "Select patient", "full_name");
    fillSelect(document.getElementById("shop-store"), stores.stores, "Select your store");
    fillSelect(document.getElementById("inventory-product"), products.products, "Select product");
    document.querySelectorAll(".item-product").forEach((select) => fillSelect(select, products.products, "Select product"));
    const status = document.getElementById("api-status");
    status.innerHTML = "<i></i>Connected";
    status.classList.add("is-online");
  } catch (error) {
    const status = document.getElementById("api-status");
    status.innerHTML = "<i></i>Offline";
    status.classList.remove("is-online");
    showToast(error.message, true);
  }
}

async function loadOverview() {
  try {
    const [dashboard, refills, prescriptions] = await Promise.all([
      requestJson("/api/dashboard"), requestJson("/api/refills"), requestJson("/api/prescriptions"),
    ]);
    document.getElementById("metric-total").textContent = dashboard.total_prescriptions;
    document.getElementById("metric-fulfilled").textContent = dashboard.fulfilled_prescriptions;
    document.getElementById("metric-rate").textContent = `${dashboard.fulfillment_rate}%`;
    document.getElementById("metric-refills").textContent = refills.refills.length;
    fillList(document.getElementById("top-products"), dashboard.top_products, "No prescriptions yet.", (product) => {
      const row = makeElement("li");
      row.append(makeElement("span", "rank-name", product.name));
      row.append(makeElement("span", "rank-count", `${product.units_prescribed} units`));
      return row;
    });
    fillList(document.getElementById("overview-refills"), refills.refills.slice(0, 4), "No scheduled refills.", (refill) => {
      const row = makeElement("div", "compact-row");
      const primary = makeElement("span", "compact-primary", refill.patient_name);
      primary.append(makeElement("span", "compact-secondary", refill.products || "Care plan"));
      row.append(primary, makeElement("span", "compact-value", formatDate(refill.due_at, { month: "short", day: "numeric" })));
      return row;
    });
    fillList(document.getElementById("shopkeeper-points"), dashboard.shopkeeper_points.slice(0, 5), "No partner activity yet.", (store) => {
      const row = makeElement("div", "compact-row");
      row.append(makeElement("span", "compact-primary", store.store_name));
      row.append(makeElement("span", "compact-value", `${store.points} pts`));
      return row;
    });
    renderPrescriptionRows(document.getElementById("recent-prescriptions"), prescriptions.prescriptions.slice(0, 5));
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderPrescriptionRows(container, prescriptions) {
  container.replaceChildren();
  if (!prescriptions.length) {
    const row = makeElement("tr");
    const cell = makeElement("td", "empty-state", "No prescriptions have been issued.");
    cell.colSpan = 4;
    row.append(cell);
    container.append(row);
    return;
  }
  prescriptions.forEach((prescription) => {
    const row = makeElement("tr");
    row.append(makeElement("td", "", prescription.patient_name));
    row.append(makeElement("td", "", prescription.doctor_name));
    row.append(makeElement("td", "", formatDate(prescription.issued_at)));
    const cell = makeElement("td");
    cell.append(makeElement("span", `status-pill status-${prescription.status}`, prescription.status));
    row.append(cell);
    container.append(row);
  });
}

async function loadPrescriptions(targetId) {
  try {
    const data = await requestJson("/api/prescriptions");
    renderPrescriptionRows(document.getElementById(targetId), data.prescriptions);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function loadRefills() {
  const target = document.getElementById("refill-list");
  if (!target) return;
  try {
    const status = document.getElementById("refill-filter")?.value || "scheduled";
    const data = await requestJson(`/api/refills?status=${encodeURIComponent(status)}`);
    fillList(target, data.refills, `No ${status} reminders.`, (refill) => {
      const card = makeElement("article", "refill-card");
      const date = makeElement("div", "refill-date");
      date.append(makeElement("strong", "", formatDate(refill.due_at, { month: "short", day: "numeric" })));
      date.append(makeElement("span", "", formatDate(refill.due_at, { year: "numeric" })));
      const detail = makeElement("div", "refill-detail");
      detail.append(makeElement("strong", "", refill.patient_name));
      detail.append(makeElement("span", "", refill.patient_phone || "No phone on record"));
      detail.append(makeElement("span", "refill-products", refill.products || "Care plan"));
      card.append(date, detail, makeElement("span", "status-pill refill-status", refill.status));
      return card;
    });
  } catch (error) {
    showToast(error.message, true);
  }
}

async function createRecord(event, endpoint, successMessage) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    await requestJson(endpoint, { method: "POST", body: JSON.stringify(data) });
    form.reset();
    await refreshDirectories();
    showToast(successMessage);
  } catch (error) {
    showToast(error.message, true);
  }
}

function addPrescriptionItem() {
  const row = makeElement("div", "prescription-item-row");
  const productLabel = makeElement("label", "", "Product");
  const productSelect = makeElement("select", "item-product");
  productSelect.required = true;
  productSelect.name = "product_id";
  productLabel.append(productSelect);
  const quantityLabel = makeElement("label", "", "Quantity");
  const quantity = makeElement("input");
  quantity.type = "number";
  quantity.min = "1";
  quantity.value = "1";
  quantity.required = true;
  quantity.name = "quantity";
  quantityLabel.append(quantity);
  const instructionLabel = makeElement("label", "", "Instructions");
  const instructions = makeElement("input");
  instructions.name = "instructions";
  instructions.placeholder = "e.g. Apply to affected area nightly";
  instructions.required = true;
  instructionLabel.append(instructions);
  const remove = makeElement("button", "remove-item", "×");
  remove.type = "button";
  remove.setAttribute("aria-label", "Remove product");
  remove.addEventListener("click", () => {
    if (document.querySelectorAll(".prescription-item-row").length > 1) row.remove();
  });
  row.append(productLabel, quantityLabel, instructionLabel, remove);
  document.getElementById("prescription-items").append(row);
  requestJson("/api/products").then((data) => fillSelect(productSelect, data.products, "Select product")).catch(() => {});
}

async function createPrescription(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const items = [...document.querySelectorAll(".prescription-item-row")].map((row) => ({
    product_id: Number(row.querySelector(".item-product").value),
    quantity: Number(row.querySelector('[name="quantity"]').value),
    instructions: row.querySelector('[name="instructions"]').value.trim(),
  }));
  const body = {
    doctor_id: Number(formData.get("doctor_id")),
    patient_id: Number(formData.get("patient_id")),
    refill_interval_days: Number(formData.get("refill_interval_days")),
    items,
  };
  try {
    const result = await requestJson("/api/prescriptions", { method: "POST", body: JSON.stringify(body) });
    const panel = document.getElementById("prescription-result");
    panel.replaceChildren();
    const image = makeElement("img");
    image.src = result.qr_image_url;
    image.alt = "Prescription QR code";
    const copy = makeElement("div", "result-copy");
    copy.append(makeElement("strong", "", "Prescription issued"));
    copy.append(makeElement("span", "", `Refill reminder: ${formatDate(result.refill_due_at)}`));
    const link = makeElement("a", "", result.patient_url);
    link.href = result.patient_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    copy.append(link);
    panel.append(image, copy);
    panel.hidden = false;
    form.reset();
    document.querySelector('[name="refill_interval_days"]').value = "30";
    document.getElementById("prescription-items").replaceChildren();
    addPrescriptionItem();
    await Promise.all([loadOverview(), loadPrescriptions("doctor-prescriptions"), loadRefills()]);
    showToast("Prescription issued and QR created.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function createStore(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  const data = { ...values };
  ["latitude", "longitude"].forEach((key) => {
    if (data[key] === "") delete data[key];
    else if (data[key] !== undefined) data[key] = Number(data[key]);
  });
  try {
    await requestJson("/api/stores", { method: "POST", body: JSON.stringify(data) });
    form.reset();
    await refreshDirectories();
    showToast("Partner store added.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function loadInventory() {
  const storeId = document.getElementById("shop-store").value;
  const target = document.getElementById("inventory-list");
  if (!storeId) {
    target.replaceChildren(makeElement("p", "empty-state", "Choose a store to view its stock."));
    return;
  }
  try {
    const data = await requestJson(`/api/stores/${storeId}/inventory`);
    fillList(target, data.inventory, "No stock recorded for this store.", (item) => {
      const row = makeElement("div", "inventory-row");
      row.append(makeElement("span", "", item.name));
      row.append(makeElement("span", "", `${item.stock_quantity} on hand`));
      return row;
    });
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveInventory(event) {
  event.preventDefault();
  const storeId = document.getElementById("shop-store").value;
  if (!storeId) return showToast("Choose a partner store first.", true);
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  data.product_id = Number(data.product_id);
  data.stock_quantity = Number(data.stock_quantity);
  try {
    await requestJson(`/api/stores/${storeId}/inventory`, { method: "PUT", body: JSON.stringify(data) });
    form.reset();
    await loadInventory();
    if (verifiedPrescription) renderVerification(verifiedPrescription);
    showToast("Store stock updated.");
  } catch (error) {
    showToast(error.message, true);
  }
}

let verifiedPrescription = null;

function extractToken(value) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    const url = new URL(trimmed, window.location.origin);
    const match = url.pathname.match(/\/(?:patient|api\/prescriptions)\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : trimmed;
  } catch {
    return trimmed;
  }
}

async function verifyToken(event) {
  event.preventDefault();
  const input = document.getElementById("qr-token");
  const token = extractToken(input.value);
  input.value = token;
  try {
    verifiedPrescription = await requestJson(`/api/verify/${encodeURIComponent(token)}`);
    renderVerification(verifiedPrescription);
  } catch (error) {
    verifiedPrescription = null;
    const result = document.getElementById("verification-result");
    result.replaceChildren(makeElement("p", "empty-state", error.message));
    result.hidden = false;
    showToast(error.message, true);
  }
}

function renderVerification(data) {
  const result = document.getElementById("verification-result");
  result.replaceChildren();
  const top = makeElement("div", "verify-top");
  top.append(makeElement("strong", "", `Prescription #${data.id}`));
  top.append(makeElement("span", `status-pill status-${data.status}`, data.status));
  result.append(top);
  const patient = makeElement("p", "compact-secondary", `Patient: ${data.patient_first_name} · Prescriber: ${data.doctor_name}`);
  patient.style.margin = "9px 0 0";
  result.append(patient);
  const items = makeElement("div", "verify-items");
  data.items.forEach((item) => {
    const row = makeElement("div", "verify-item");
    row.append(makeElement("span", "", `${item.name} · ${item.quantity}`));
    row.append(makeElement("span", "", item.instructions));
    items.append(row);
  });
  result.append(items);
  const footer = makeElement("div", "verify-footer");
  const storeId = document.getElementById("shop-store").value;
  const selectedStore = data.stores.find((store) => String(store.id) === storeId);
  const canFulfill = data.status === "issued" && selectedStore?.can_fulfill;
  footer.append(makeElement("p", "", !storeId ? "Select a store to check its stock." : selectedStore?.can_fulfill ? "All prescribed items are in stock at this store." : "This store does not have every prescribed item."));
  const fulfill = makeElement("button", "button button-accent", "Mark fulfilled");
  fulfill.type = "button";
  fulfill.disabled = !canFulfill;
  fulfill.addEventListener("click", fulfillCurrentPrescription);
  footer.append(fulfill);
  result.append(footer);
  result.hidden = false;
}

function updateFulfillmentAvailability() {
  if (verifiedPrescription) renderVerification(verifiedPrescription);
}

async function fulfillCurrentPrescription() {
  if (!verifiedPrescription) return;
  const storeId = document.getElementById("shop-store").value;
  const token = document.getElementById("qr-token").value;
  try {
    await requestJson(`/api/prescriptions/${verifiedPrescription.id}/fulfill`, {
      method: "POST",
      body: JSON.stringify({ qr_token: token, store_id: Number(storeId) }),
    });
    verifiedPrescription = await requestJson(`/api/verify/${encodeURIComponent(token)}`);
    renderVerification(verifiedPrescription);
    await Promise.all([loadInventory(), loadOverview()]);
    showToast("Order fulfilled. Loyalty points credited.");
  } catch (error) {
    showToast(error.message, true);
  }
}

let scannerStream = null;
let scannerFrame = 0;
let scannerActive = false;

async function startScanner() {
  if (!navigator.mediaDevices?.getUserMedia || !("BarcodeDetector" in window)) {
    showToast("QR camera scanning is unavailable here. Paste the QR token or patient link instead.", true);
    return;
  }
  try {
    const detector = new BarcodeDetector({ formats: ["qr_code"] });
    const video = document.getElementById("scan-video");
    scannerStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    video.srcObject = scannerStream;
    video.hidden = false;
    await video.play();
    scannerActive = true;
    const scanFrame = async () => {
      if (!scannerActive) return;
      if (video.readyState >= HTMLMediaElement.HAVE_ENOUGH_DATA) {
        try {
          const codes = await detector.detect(video);
          if (codes.length) {
            document.getElementById("qr-token").value = extractToken(codes[0].rawValue);
            stopScanner();
            document.getElementById("verify-form").requestSubmit();
            return;
          }
        } catch {
          stopScanner();
          showToast("Could not read that QR code. Enter its token manually.", true);
          return;
        }
      }
      scannerFrame = window.requestAnimationFrame(scanFrame);
    };
    scannerFrame = window.requestAnimationFrame(scanFrame);
  } catch (error) {
    stopScanner();
    showToast(error.name === "NotAllowedError" ? "Camera permission was denied." : "Could not open the camera. Enter the token manually.", true);
  }
}

function stopScanner() {
  scannerActive = false;
  if (scannerFrame) window.cancelAnimationFrame(scannerFrame);
  scannerFrame = 0;
  if (scannerStream) scannerStream.getTracks().forEach((track) => track.stop());
  scannerStream = null;
  const video = document.getElementById("scan-video");
  if (video) {
    video.pause();
    video.srcObject = null;
    video.hidden = true;
  }
}

async function initializePatientPage() {
  const token = document.body.dataset.token;
  let coordinates = "";
  document.getElementById("use-location").addEventListener("click", () => {
    if (!navigator.geolocation) return showPatientError("Location is unavailable in this browser. Showing partner stores without distance sorting.");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        coordinates = `?lat=${position.coords.latitude}&lng=${position.coords.longitude}`;
        loadPatientPrescription(token, coordinates);
      },
      () => showPatientError("Location permission was not granted. Showing partner stores without distance sorting."),
      { timeout: 8000, maximumAge: 300000 },
    );
  });
  await loadPatientPrescription(token, coordinates);
}

function showPatientError(message) {
  const error = document.getElementById("patient-error");
  error.textContent = message;
  error.hidden = false;
}

async function loadPatientPrescription(token, coordinates = "") {
  try {
    const data = await requestJson(`/api/prescriptions/${encodeURIComponent(token)}${coordinates}`);
    document.getElementById("patient-greeting").textContent = `${data.patient_first_name}'s care plan`;
    document.getElementById("patient-meta").textContent = `Prescribed by ${data.doctor_name} · Issued ${formatDate(data.issued_at)}`;
    const status = document.getElementById("patient-status");
    status.textContent = data.status;
    status.className = `status-pill status-${data.status}`;
    fillList(document.getElementById("patient-items"), data.items, "No products are listed for this prescription.", (item, index) => {
      const article = makeElement("article", "patient-item");
      article.append(makeElement("span", "item-number", String(index + 1).padStart(2, "0")));
      const detail = makeElement("div");
      detail.append(makeElement("h3", "", item.name));
      if (item.brand) detail.append(makeElement("p", "", item.brand));
      detail.append(makeElement("p", "", item.instructions));
      article.append(detail, makeElement("span", "item-quantity", `Qty ${item.quantity}`));
      return article;
    });
    fillList(document.getElementById("patient-stores"), data.stores, "No partner stores are registered yet.", (store) => {
      const article = makeElement("article", "patient-store");
      const top = makeElement("div", "patient-store-top");
      const details = makeElement("div");
      details.append(makeElement("h3", "", store.name));
      const address = makeElement("address", "", store.address);
      if (store.phone) address.append(document.createTextNode(` · ${store.phone}`));
      details.append(address);
      top.append(details);
      if (store.distance_km !== undefined) top.append(makeElement("span", "store-distance", `${store.distance_km} km`));
      article.append(top);
      const stock = makeElement("div", "store-stock");
      store.items.forEach((item) => stock.append(makeElement("span", `stock-chip${item.available ? "" : " is-short"}`, `${item.name}: ${item.stock_quantity} in stock`)));
      article.append(stock);
      return article;
    });
  } catch (error) {
    showPatientError(error.message);
    document.getElementById("patient-greeting").textContent = "Prescription unavailable";
    document.getElementById("patient-meta").textContent = "This care plan could not be loaded.";
    document.getElementById("patient-status").textContent = "Unavailable";
  }
}