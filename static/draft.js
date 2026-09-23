(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const peso = (n) => "₱" + Number(n || 0).toLocaleString("en-PH", { maximumFractionDigits: 2 });
  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
  const products = JSON.parse($("#draft-products-data").textContent);
  const shopName = $("#draftSheet").dataset.shopName;
  const byId = new Map(products.map((p) => [p.id, p]));
  const cart = new Map();
  let tierMode = "srp";

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

  function downloadImage(type) {
    const lines = selectedLines();
    const subtotal = lines.reduce((sum, l) => sum + l.subtotal, 0);
    const discount = Math.min(Math.max(num($("#draftDiscount").value), 0), subtotal);
    const total = subtotal - discount;
    const customer = $("#draftCustomer").value.trim() || "Walk-in customer";
    const note = $("#draftNote").value.trim();
    const canvas = document.createElement("canvas");
    const width = 1000;
    const lineHeight = 38;
    const height = Math.max(560, 330 + lines.length * lineHeight);
    canvas.width = width * 2; canvas.height = height * 2;
    const ctx = canvas.getContext("2d");
    ctx.scale(2, 2);
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = "#5A0F36"; ctx.font = "700 34px Georgia"; ctx.fillText(shopName, 54, 62);
    ctx.fillStyle = "#8C6677"; ctx.font = "18px Arial"; ctx.fillText("DRAFT QUOTE", 750, 62);
    ctx.fillText(customer, 54, 104);
    ctx.fillText(`Price level: ${tierMode.toUpperCase()}`, 54, 136);
    ctx.strokeStyle = "#F7D6E6"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(54, 164); ctx.lineTo(946, 164); ctx.stroke();
    ctx.fillStyle = "#3A1D2B"; ctx.font = "700 18px Arial";
    ctx.fillText("Product", 54, 198); ctx.textAlign = "right"; ctx.fillText("Qty", 750, 198); ctx.fillText("Amount", 946, 198);
    ctx.font = "18px Arial";
    ctx.textAlign = "left";
    lines.forEach((l, i) => { const y = 238 + i * lineHeight; ctx.fillText(l.name.slice(0, 42), 54, y); ctx.textAlign = "right"; ctx.fillText(String(l.qty), 750, y); ctx.fillText(peso(l.subtotal), 946, y); ctx.textAlign = "left"; });
    const y = 260 + lines.length * lineHeight;
    ctx.strokeStyle = "#F7D6E6"; ctx.beginPath(); ctx.moveTo(54, y); ctx.lineTo(946, y); ctx.stroke();
    ctx.fillText(`Subtotal (${lines.reduce((sum, l) => sum + l.qty, 0)} packs)`, 54, y + 42); ctx.textAlign = "right"; ctx.fillText(peso(subtotal), 946, y + 42); ctx.textAlign = "left";
    if (discount) { ctx.fillText("Discount", 54, y + 76); ctx.textAlign = "right"; ctx.fillText("-" + peso(discount), 946, y + 76); ctx.textAlign = "left"; }
    ctx.fillStyle = "#D81B7A"; ctx.font = "700 30px Georgia"; ctx.fillText("TOTAL", 54, y + 124); ctx.textAlign = "right"; ctx.fillText(peso(total), 946, y + 124); ctx.textAlign = "left";
    if (note) { ctx.fillStyle = "#8C6677"; ctx.font = "18px Arial"; ctx.fillText(("Note: " + note).slice(0, 80), 54, y + 166); }
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
  renderProducts(); render();
})();
