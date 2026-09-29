// Small helpers used on every page.
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  // Toast: hide after a few seconds
  const toast = $("#toast");
  window.showToast = (msg, isError = false) => {
    toast.textContent = msg;
    toast.classList.toggle("error", isError);
    toast.classList.add("show");
    clearTimeout(window.showToast.t);
    window.showToast.t = setTimeout(() => toast.classList.remove("show"), isError ? 6000 : 3000);
  };
  if (toast && toast.classList.contains("show")) {
    window.showToast.t = setTimeout(() => toast.classList.remove("show"), toast.classList.contains("error") ? 6000 : 3000);
  }

  // Ask before dangerous actions; stop double submits
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) { e.preventDefault(); return; }
    if (f.dataset.sent) { e.preventDefault(); return; }
    f.dataset.sent = "1";
    $$("button[type=submit]", f).forEach((b) => (b.disabled = true));
  });

  // Products: filter rows instantly
  const table = $("#prodTable");
  if (table) {
    const run = () => {
      const q = $("#prodSearch").value.trim().toLowerCase();
      const cat = $("#prodCat").value;
      const st = $("#prodStock").value;
      let shown = 0;
      $$("tbody tr", table).forEach((tr) => {
        const ok = (!q || tr.dataset.name.includes(q)) &&
          (cat === "all" || tr.dataset.cat === cat) &&
          (st === "all" || (st === "low" && tr.dataset.stock !== "ok") || (st === "out" && tr.dataset.stock === "out"));
        tr.hidden = !ok;
        if (ok) shown++;
      });
      $("#prodEmpty").hidden = shown > 0;
    };
    ["#prodSearch", "#prodCat", "#prodStock"].forEach((s) => $(s).addEventListener("input", run));
    run();
  }

  // Stock in: show current stock of the chosen product
  const rs = $("#rsProduct");
  if (rs) {
    const show = () => {
      const o = rs.selectedOptions[0];
      $("#rsCurrent").innerHTML = o && o.value ? `Current stock: <b>${o.dataset.stock}</b>` : "";
    };
    rs.addEventListener("change", show);
    show();

    // Search: keep only matching products in the list (rebuilt, since hidden options don't work on every phone)
    const groups = $$("optgroup", rs).map((g) => ({ label: g.label, options: $$("option", g) }));
    const placeholder = rs.options[0];
    $("#rsSearch").addEventListener("input", (e) => {
      const q = e.target.value.trim().toLowerCase();
      const current = rs.value;
      rs.replaceChildren(placeholder);
      let matches = [];
      groups.forEach((g) => {
        const opts = g.options.filter((o) => !q || o.textContent.toLowerCase().includes(q));
        if (!opts.length) return;
        const og = document.createElement("optgroup");
        og.label = g.label;
        og.append(...opts);
        rs.append(og);
        matches = matches.concat(opts);
      });
      if (matches.some((o) => o.value === current)) rs.value = current;
      else rs.value = q && matches.length === 1 ? matches[0].value : "";
      $("#rsEmpty").hidden = matches.length > 0;
      show();
    });
  }

  // Sales: reload when a date changes
  const rf = $("#rangeForm");
  if (rf) $$("input[type=date]", rf).forEach((i) => i.addEventListener("change", () => rf.submit()));
})();
