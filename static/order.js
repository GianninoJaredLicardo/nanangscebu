// New order screen: pick products, compute totals, send to the server.
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const peso = (n) => "₱" + Number(n || 0).toLocaleString("en-PH", { maximumFractionDigits: 2 });
  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
  const TIER_LABEL = { srp: "SRP", reseller: "Reseller", dealer: "Dealer" };

  const products = JSON.parse($("#products-data").textContent);
  const S = JSON.parse($("#settings-data").textContent);
  const byId = new Map(products.map((p) => [p.id, p]));
  const cart = new Map(); // id -> qty
  let tierMode = "auto";
  let cat = "All";

  function tierTotals() {
    const t = { srp: 0, reseller: 0, dealer: 0 };
    for (const [id, q] of cart) { const p = byId.get(id); t.srp += p.srp * q; t.reseller += p.reseller * q; t.dealer += p.dealer * q; }
    return t;
  }
  function tier() {
    if (tierMode !== "auto") return tierMode;
    const t = tierTotals();
    return t.dealer >= S.dealerMin ? "dealer" : t.reseller >= S.resellerMin ? "reseller" : "srp";
  }
  function lines() {
    const tr = tier();
    return [...cart].map(([id, qty]) => { const p = byId.get(id); return { id, name: p.name, qty, price: p[tr], subtotal: p[tr] * qty, stock: p.stock, short: qty > p.stock }; });
  }

  function renderPicker() {
    const q = $("#pickSearch").value.trim().toLowerCase();
    const inStock = $("#pickInStock").checked;
    const tr = tier();
    const list = products.filter((p) => (cat === "All" || p.category === cat) && (!q || p.name.toLowerCase().includes(q)) && (!inStock || p.stock > 0 || cart.has(p.id)));
    $("#pickList").innerHTML = list.length ? list.map((p) => {
      const inCart = cart.get(p.id) || 0;
      return `<button type="button" class="pick" data-id="${esc(p.id)}" ${p.stock - inCart <= 0 ? "disabled" : ""}>
        <span class="pick-name">${esc(p.name)}</span>
        <span class="pick-meta"><span class="stock-${p.state}">${p.stock <= 0 ? "Out of stock" : `${p.stock} in stock`}</span>${inCart ? `<span class="in-cart">${inCart} in order</span>` : ""}</span>
        <span class="pick-price">${peso(p[tr])}</span></button>`;
    }).join("") : `<p class="empty">${q ? `No products match “${esc(q)}”.` : inStock ? "Nothing in stock here. Untick “in-stock only” to see all, or add stock in Stock in." : "No products here."}</p>`;
  }

  function renderCart() {
    const tr = tier();
    $$("#tierSeg button").forEach((b) => b.classList.toggle("on", b.dataset.tier === tierMode));
    const t = tierTotals();
    let note;
    if (!cart.size) note = `Auto picks the price: Reseller from ${peso(S.resellerMin)}, Dealer from ${peso(S.dealerMin)}.`;
    else if (tierMode !== "auto") note = `Using <b>${TIER_LABEL[tr]}</b> price (set by you).`;
    else if (tr === "dealer") note = `Using <b>Dealer</b> price. Order is ${peso(S.dealerMin)} or more.`;
    else if (tr === "reseller") note = `Using <b>Reseller</b> price. Add ${peso(S.dealerMin - t.dealer)} more for Dealer price.`;
    else note = `Using <b>SRP</b>. Add ${peso(S.resellerMin - t.reseller)} more for Reseller price.`;
    $("#tierNote").innerHTML = note;

    const ls = lines();
    $("#cartList").innerHTML = ls.length ? ls.map((l) => `
      <div class="line ${l.short ? "short" : ""}" data-id="${esc(l.id)}">
        <div class="line-main"><span class="line-name">${esc(l.name)}</span>
          <span class="muted small">${peso(l.price)} each${l.short ? `, only ${l.stock} in stock` : ""}</span></div>
        <button type="button" class="x" data-act="rm" aria-label="Remove ${esc(l.name)}">×</button>
        <div class="qty">
          <button type="button" data-act="dec" aria-label="One less">−</button>
          <input type="number" min="1" step="1" value="${l.qty}" data-act="qty" aria-label="Quantity" inputmode="numeric">
          <button type="button" data-act="inc" aria-label="One more">+</button>
        </div>
        <span class="line-sub">${peso(l.subtotal)}</span>
      </div>`).join("") : `<p class="empty">Tap a product to add it to this order.</p>`;

    const subtotal = ls.reduce((a, l) => a + l.subtotal, 0);
    const packs = ls.reduce((a, l) => a + l.qty, 0);
    const discount = Math.min(Math.max(num($("#discount").value), 0), subtotal);
    const total = subtotal - discount;
    $("#tPacks").textContent = packs;
    $("#tSub").textContent = peso(subtotal);
    $("#tTotal").textContent = peso(total);
    const paid = $("#payAmount").value;
    const cl = $("#changeLine");
    cl.className = "change";
    if (paid !== "" && ls.length) {
      const d = num(paid) - total;
      cl.textContent = d >= 0 ? `Change: ${peso(d)}` : `Short by ${peso(-d)}`;
      cl.classList.add(d >= 0 ? "ok" : "bad");
    } else cl.textContent = "";
    $("#completeSale").disabled = !ls.length;
    const jump = $("#jumpTicket");
    jump.hidden = !ls.length;
    jump.innerHTML = `<span>View order (${packs} packs)</span><span>${peso(total)}</span>`;
  }
  const render = () => { renderCart(); renderPicker(); };

  $("#pickSearch").addEventListener("input", renderPicker);
  $("#pickInStock").addEventListener("change", renderPicker);
  $("#pickCats").addEventListener("click", (e) => {
    const c = e.target.closest("[data-cat]"); if (!c) return;
    cat = c.dataset.cat;
    $$("#pickCats .chip").forEach((x) => x.classList.toggle("on", x === c));
    renderPicker();
  });
  $("#pickList").addEventListener("click", (e) => {
    const b = e.target.closest(".pick"); if (!b || b.disabled) return;
    cart.set(b.dataset.id, (cart.get(b.dataset.id) || 0) + 1);
    render();
  });
  $("#tierSeg").addEventListener("click", (e) => { const b = e.target.closest("[data-tier]"); if (b) { tierMode = b.dataset.tier; render(); } });
  $("#cartList").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]"); if (!b || b.dataset.act === "qty") return;
    const id = b.closest(".line").dataset.id; const q = cart.get(id) || 0;
    if (b.dataset.act === "inc") cart.set(id, q + 1);
    if (b.dataset.act === "dec") q > 1 ? cart.set(id, q - 1) : cart.delete(id);
    if (b.dataset.act === "rm") cart.delete(id);
    render();
  });
  $("#cartList").addEventListener("change", (e) => {
    if (e.target.dataset.act !== "qty") return;
    const id = e.target.closest(".line").dataset.id; const q = parseInt(e.target.value, 10);
    q > 0 ? cart.set(id, q) : cart.delete(id);
    render();
  });
  ["#discount", "#payAmount"].forEach((s) => $(s).addEventListener("input", renderCart));
  $("#clearCart").addEventListener("click", () => { if (!cart.size || confirm("Clear this order?")) { cart.clear(); tierMode = "auto"; render(); } });
  $("#jumpTicket").addEventListener("click", () => $(".ticket").scrollIntoView({ behavior: "smooth", block: "start" }));
  new IntersectionObserver(([e]) => document.body.classList.toggle("ticket-visible", e.isIntersecting), { threshold: 0.1 }).observe($(".ticket"));
  window.addEventListener("beforeunload", (e) => { if (cart.size && !window.__saving) { e.preventDefault(); e.returnValue = ""; } });

  $("#completeSale").addEventListener("click", async () => {
    const ls = lines();
    if (!ls.length) return;
    const short = ls.filter((l) => l.short);
    if (short.length) { showToast("Not enough stock: " + short.map((l) => `${l.name} (${l.stock} left)`).join(", "), true); return; }
    const btn = $("#completeSale");
    btn.disabled = true; btn.textContent = "Saving…";
    try {
      const res = await fetch(S.saleUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content },
        body: JSON.stringify({
          items: ls.map((l) => ({ id: l.id, qty: l.qty })),
          tierMode, buyer: $("#buyerName").value, contact: $("#buyerContact").value, note: $("#orderNote").value,
          discount: $("#discount").value, payMethod: $("#payMethod").value, amountPaid: $("#payAmount").value,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Couldn't save the sale. Check your internet and try again.");
      window.__saving = true;
      location.href = data.url;
    } catch (err) {
      showToast(err.message || "Couldn't save the sale. Check your internet and try again.", true);
      btn.disabled = false; btn.textContent = "Complete sale";
    }
  });

  render();
})();
