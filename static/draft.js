(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const peso = (n) => "₱" + Number(n || 0).toLocaleString("en-PH", { maximumFractionDigits: 2 });
  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
  const capWords = (s) => String(s || "").replace(/(^|[^\p{L}\p{N}'’])(\p{Ll})/gu, (m, a, b) => a + b.toUpperCase());
  const capFirst = (s) => String(s || "").replace(/^\s*\p{Ll}/u, (c) => c.toUpperCase());
  const products = JSON.parse($("#draft-products-data").textContent);
  const shopName = $("#draftSheet").dataset.shopName;
  const byId = new Map(products.map((p) => [p.id, p]));
  const cart = new Map();
  let tierMode = "srp";
  let draftId = null; // set once the draft is saved or opened from History
  const customerByName = new Map(JSON.parse($("#draft-customers-data").textContent)
    .map((c) => [c.name.trim().toLowerCase().replace(/\s+/g, " "), c]));

  function selectedLines() {
    return [...cart].map(([id, qty]) => {
      const p = byId.get(id);
      const price = Number(p[tierMode] || 0);
      return { id, name: p.name, qty, price, subtotal: price * qty };
    });
  }

  function renderProducts() {
    const category = $("#draftCategory").value;
    const search = $("#draftProductSearch").value.trim().toLowerCase();
    const current = $("#draftProduct").value;
    const list = products.filter((p) => (category === "All" || p.category === category) && (!search || p.name.toLowerCase().includes(search)));
    $("#draftProduct").innerHTML = list.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
    if (list.some((p) => p.id === current)) $("#draftProduct").value = current;
  }

  function render() {
    $$("#draftTier button").forEach((b) => b.classList.toggle("on", b.dataset.tier === tierMode));
    const lines = selectedLines();
    $("#draftLines").innerHTML = lines.length ? lines.map((l) => `
      <div class="draft-line" data-id="${esc(l.id)}">
        <div><b>${esc(l.name)}</b><span class="muted small">${peso(l.price)} each</span></div>
        <label class="draft-qty">Qty<select data-act="qty">${Array.from({ length: 100 }, (_, i) => `<option value="${i + 1}" ${i + 1 === l.qty ? "selected" : ""}>${i + 1}</option>`).join("")}</select></label>
        <b class="num">${peso(l.subtotal)}</b>
        <button class="x" type="button" data-act="remove" aria-label="Remove ${esc(l.name)}">×</button>
      </div>`).join("") : `<p class="empty">Add products to calculate an estimate.</p>`;
    const subtotal = lines.reduce((sum, l) => sum + l.subtotal, 0);
    const packs = lines.reduce((sum, l) => sum + l.qty, 0);
    const discount = Math.min(Math.max(num($("#draftDiscount").value), 0), subtotal);
    $("#draftPacks").textContent = packs;
    $("#draftSubtotal").textContent = peso(subtotal);
    $("#draftTotal").textContent = peso(subtotal - discount);
  }

  // Use the same fonts as the pages (they must be loaded before drawing on the canvas).
  function loadFonts() {
    if (!document.fonts) return Promise.resolve();
    return Promise.all(["700 30px 'Playfair Display'", "18px 'Source Sans 3'", "700 18px 'Source Sans 3'"]
      .map((f) => document.fonts.load(f).catch(() => null)));
  }

  function loadLogo() {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = $("#draftSheet").dataset.logo;
    });
  }

  async function downloadImage(type) {
    const logo = await loadLogo();
    await loadFonts();
    const lines = selectedLines();
    const subtotal = lines.reduce((sum, l) => sum + l.subtotal, 0);
    const discount = Math.min(Math.max(num($("#draftDiscount").value), 0), subtotal);
    const total = subtotal - discount;
    const customer = capWords($("#draftCustomer").value.trim()) || "Walk-in customer";
    const contact = $("#draftContact").value.trim();
    const address = capWords($("#draftAddress").value.trim());
    const note = capFirst($("#draftNote").value.trim());
    const canvas = document.createElement("canvas");
    const width = 1000;
    const lineHeight = 38;
    const extra = (contact ? 1 : 0) + (address ? 1 : 0);
    const headShift = 70 + extra * 32;
    const height = Math.max(630, 520 + lines.length * lineHeight) + extra * 32;
    canvas.width = width * 2; canvas.height = height * 2;
    const ctx = canvas.getContext("2d");
    ctx.scale(2, 2);
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, width, height);
    let nameX = 54;
    if (logo) { ctx.drawImage(logo, 54, 26, 250, 96); nameX = 326; }
    ctx.fillStyle = "#5A0F36"; ctx.font = "700 19px 'Playfair Display', Georgia"; ctx.fillText(shopName, nameX, 66);
    ctx.fillStyle = "#8C6677"; ctx.font = "18px 'Source Sans 3', Arial"; ctx.fillText("DRAFT QUOTE", nameX, 96);
    let infoY = 174;
    ctx.fillText(customer, 54, infoY);
    if (contact) { infoY += 32; ctx.fillText("Contact: " + contact.slice(0, 60), 54, infoY); }
    if (address) { infoY += 32; ctx.fillText("Address: " + address.slice(0, 75), 54, infoY); }
    ctx.translate(0, headShift);
    ctx.fillText(`Price Level: ${tierMode.toUpperCase()}`, 54, 136);
    ctx.strokeStyle = "#F7D6E6"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(54, 164); ctx.lineTo(946, 164); ctx.stroke();
    ctx.fillStyle = "#3A1D2B"; ctx.font = "700 18px 'Source Sans 3', Arial";
    ctx.fillText("Product", 54, 198); ctx.textAlign = "right"; ctx.fillText("Qty", 750, 198); ctx.fillText("Amount", 946, 198);
    ctx.font = "18px 'Source Sans 3', Arial";
    ctx.textAlign = "left";
    lines.forEach((l, i) => { const y = 238 + i * lineHeight; ctx.fillText(l.name.slice(0, 42), 54, y); ctx.textAlign = "right"; ctx.fillText(String(l.qty), 750, y); ctx.fillText(peso(l.subtotal), 946, y); ctx.textAlign = "left"; });
    const y = 260 + lines.length * lineHeight;
    ctx.strokeStyle = "#F7D6E6"; ctx.beginPath(); ctx.moveTo(54, y); ctx.lineTo(946, y); ctx.stroke();
    ctx.fillText(`Subtotal (${lines.reduce((sum, l) => sum + l.qty, 0)} packs)`, 54, y + 42); ctx.textAlign = "right"; ctx.fillText(peso(subtotal), 946, y + 42); ctx.textAlign = "left";
    if (discount) { ctx.fillText("Discount", 54, y + 76); ctx.textAlign = "right"; ctx.fillText("-" + peso(discount), 946, y + 76); ctx.textAlign = "left"; }
    ctx.fillStyle = "#D81B7A"; ctx.font = "700 30px 'Playfair Display', Georgia"; ctx.fillText("TOTAL", 54, y + 124); ctx.textAlign = "right"; ctx.fillText(peso(total), 946, y + 124); ctx.textAlign = "left";
    if (note) { ctx.fillStyle = "#8C6677"; ctx.font = "18px 'Source Sans 3', Arial"; ctx.fillText(("Note: " + note).slice(0, 80), 54, y + 166); }
    const link = document.createElement("a");
    link.download = `draft-quote.${type === "image/jpeg" ? "jpg" : "png"}`;
    link.href = canvas.toDataURL(type, 0.92);
    link.click();
  }

  $("#draftCategory").addEventListener("change", renderProducts);
  $("#draftProductSearch").addEventListener("input", renderProducts);
  $("#addDraftProduct").addEventListener("click", () => {
    const id = $("#draftProduct").value;
    if (id) cart.set(id, (cart.get(id) || 0) + num($("#draftQty").value));
    render();
  });
  $("#draftTier").addEventListener("click", (e) => { const b = e.target.closest("[data-tier]"); if (b) { tierMode = b.dataset.tier; render(); } });
  $("#draftLines").addEventListener("click", (e) => { const b = e.target.closest("[data-act=remove]"); if (b) { cart.delete(b.closest("[data-id]").dataset.id); render(); } });
  $("#draftLines").addEventListener("change", (e) => { if (e.target.dataset.act === "qty") { cart.set(e.target.closest("[data-id]").dataset.id, num(e.target.value)); render(); } });
  $("#draftDiscount").addEventListener("input", render);
  $("#printDraft").addEventListener("click", () => window.print());
  $("#downloadJpeg").addEventListener("click", () => downloadImage("image/jpeg"));
  // Hand the draft to New order (same tab), where stock is checked when the sale is completed.
  $("#draftToOrder").addEventListener("click", (e) => {
    if (!cart.size) { showToast("Add products to the draft first.", true); return; }
    const draft = {
      items: [...cart], tierMode, customer: capWords($("#draftCustomer").value.trim()),
      contact: $("#draftContact").value.trim(), address: capWords($("#draftAddress").value.trim()),
      note: capFirst($("#draftNote").value.trim()), discount: $("#draftDiscount").value,
    };
    try { sessionStorage.setItem("draftToOrder", JSON.stringify(draft)); } catch (err) {
      showToast("Couldn't move the draft. Your browser is blocking storage.", true); return;
    }
    location.href = e.currentTarget.dataset.orderUrl;
  });

  // Returning buyer: fill in their contact number and address (only into empty or auto-filled boxes).
  const autoFilled = { draftContact: "", draftAddress: "" };
  $("#draftCustomer").addEventListener("input", (e) => {
    const c = customerByName.get(e.target.value.trim().toLowerCase().replace(/\s+/g, " "));
    if (!c) return;
    [["draftContact", c.contact], ["draftAddress", c.address]].forEach(([id, value]) => {
      const input = $("#" + id);
      if (value && (!input.value || input.value === autoFilled[id])) { input.value = value; autoFilled[id] = value; }
    });
  });

  // Save to Draft History. Saving a draft opened from History updates that same draft.
  $("#saveDraft").addEventListener("click", async (e) => {
    if (!cart.size) { showToast("Add products to the draft first.", true); return; }
    const btn = e.currentTarget;
    btn.disabled = true; btn.textContent = "Saving…";
    try {
      const res = await fetch(btn.dataset.saveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content },
        body: JSON.stringify({
          id: draftId, items: [...cart].map(([id, qty]) => ({ id, qty })), tierMode,
          customer: $("#draftCustomer").value, contact: $("#draftContact").value, address: $("#draftAddress").value,
          note: $("#draftNote").value, discount: $("#draftDiscount").value,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Couldn't save the draft. Check your internet and try again.");
      draftId = data.id;
      history.replaceState(null, "", data.url);
      showToast("Draft saved. Find it anytime in History.");
    } catch (err) {
      showToast(err.message || "Couldn't save the draft. Check your internet and try again.", true);
    } finally {
      btn.disabled = false; btn.textContent = "Save Draft";
    }
  });

  // Opened from Draft History: load its products and details.
  const saved = JSON.parse($("#draft-saved-data").textContent);
  if (saved) {
    draftId = saved.id;
    let missing = 0;
    saved.items.forEach(([id, qty]) => { if (byId.has(id) && qty > 0) cart.set(id, qty); else missing++; });
    if (["srp", "reseller", "dealer"].includes(saved.tierMode)) tierMode = saved.tierMode;
    $("#draftCustomer").value = saved.customer || "";
    $("#draftContact").value = saved.contact || "";
    $("#draftAddress").value = saved.address || "";
    $("#draftNote").value = saved.note || "";
    $("#draftDiscount").value = num(saved.discount);
    if (missing) showToast(`${missing} product(s) in this draft no longer exist and were skipped.`, true);
  }

  renderProducts(); render();
})();
