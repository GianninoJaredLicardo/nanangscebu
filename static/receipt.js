// Receipt: download or share the sale as a JPEG image.
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const peso = (n) => "₱" + Number(n || 0).toLocaleString("en-PH", { maximumFractionDigits: 2 });
  const btn = $("#downloadReceipt");
  if (!btn) return;
  const R = JSON.parse($("#receipt-data").textContent);

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
      img.src = R.logo;
    });
  }

  // Split text into lines that fit maxWidth with the ctx's current font.
  function wrap(ctx, text, maxWidth) {
    const out = [];
    let line = "";
    for (const word of String(text).split(/\s+/)) {
      const test = line ? line + " " + word : word;
      if (line && ctx.measureText(test).width > maxWidth) { out.push(line); line = word; } else line = test;
    }
    if (line) out.push(line);
    return out.length ? out : [""];
  }

  // Shorten text with an ellipsis so it fits maxWidth.
  function fit(ctx, text, maxWidth) {
    if (ctx.measureText(text).width <= maxWidth) return text;
    while (text && ctx.measureText(text + "…").width > maxWidth) text = text.slice(0, -1);
    return text + "…";
  }

  // Draw the receipt on a canvas.
  async function drawReceipt() {
    const logo = await loadLogo();
    await loadFonts();
    const width = 1000, left = 54, right = 946, lineH = 38;
    const canvas = document.createElement("canvas");
    let ctx = canvas.getContext("2d");

    // Measure wrapped fields first so the canvas height fits everything.
    ctx.font = "18px 'Source Sans 3', Arial";
    const meta = [["Order No.", R.orderNo], ["Date and Time", R.date], ["Buyer", R.buyer]];
    if (R.contact) meta.push(["Contact", R.contact]);
    if (R.address) meta.push(["Address", R.address]);
    meta.push(["Price Level", R.tier]);
    const metaLines = meta.map(([k, v]) => [k, wrap(ctx, v, right - 240)]);
    const noteLines = R.note ? wrap(ctx, "Note: " + R.note, right - left) : [];
    const totals = [[`Subtotal (${R.packs} packs)`, peso(R.subtotal)]];
    if (R.discount) totals.push(["Discount", "-" + peso(R.discount)]);
    const after = [["Payment", R.payMethod]];
    if (R.amountPaid !== null && R.amountPaid !== undefined) after.push(["Amount Received", peso(R.amountPaid)], ["Change", peso(R.change)]);

    const metaRows = metaLines.reduce((n, [, ls]) => n + ls.length, 0);
    const height = 170 + (R.voided ? 50 : 0) + metaRows * 30 + 70 + R.items.length * lineH
      + 30 + totals.length * 34 + 60 + after.length * 34 + noteLines.length * 28 + 90;

    canvas.width = width * 2; canvas.height = height * 2;
    ctx = canvas.getContext("2d");
    ctx.scale(2, 2);
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, width, height);

    // Header
    let nameX = left;
    if (logo) { ctx.drawImage(logo, left, 26, 250, 96); nameX = 326; }
    ctx.fillStyle = "#5A0F36"; ctx.font = "700 19px 'Playfair Display', Georgia";
    wrap(ctx, R.shopName, right - nameX).forEach((l, i) => ctx.fillText(l, nameX, 60 + i * 24));
    ctx.fillStyle = "#8C6677"; ctx.font = "18px 'Source Sans 3', Arial";
    ctx.fillText("OFFICIAL RECEIPT" + (R.shopContact ? "  ·  " + R.shopContact : ""), nameX, 118);
    let y = 160;

    if (R.voided) {
      ctx.fillStyle = "#B42318"; ctx.font = "700 22px 'Source Sans 3', Arial";
      ctx.fillText("VOIDED — Stock Was Returned", left, y + 10);
      y += 50;
    }

    // Order details
    ctx.font = "18px 'Source Sans 3', Arial";
    metaLines.forEach(([k, ls]) => {
      ctx.fillStyle = "#8C6677"; ctx.fillText(k, left, y);
      ctx.fillStyle = "#3A1D2B"; ls.forEach((l, i) => ctx.fillText(l, 240, y + i * 30));
      y += ls.length * 30;
    });

    // Items table
    y += 6;
    ctx.strokeStyle = "#F7D6E6"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    y += 34;
    ctx.fillStyle = "#3A1D2B"; ctx.font = "700 18px 'Source Sans 3', Arial";
    ctx.fillText("Item", left, y);
    ctx.textAlign = "right"; ctx.fillText("Qty", 620, y); ctx.fillText("Price", 780, y); ctx.fillText("Amount", right, y); ctx.textAlign = "left";
    y += 30;
    ctx.font = "18px 'Source Sans 3', Arial";
    R.items.forEach((it) => {
      y += 8;
      ctx.fillText(fit(ctx, it.name, 500), left, y);
      ctx.textAlign = "right"; ctx.fillText(String(it.qty), 620, y); ctx.fillText(peso(it.price), 780, y); ctx.fillText(peso(it.subtotal), right, y); ctx.textAlign = "left";
      y += lineH - 8;
    });
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    y += 30;

    // Totals
    const row = ([k, v]) => { ctx.fillText(k, left, y); ctx.textAlign = "right"; ctx.fillText(v, right, y); ctx.textAlign = "left"; y += 34; };
    totals.forEach(row);
    ctx.fillStyle = "#D81B7A"; ctx.font = "700 30px 'Playfair Display', Georgia";
    y += 16; ctx.fillText("TOTAL", left, y); ctx.textAlign = "right"; ctx.fillText(peso(R.total), right, y); ctx.textAlign = "left";
    y += 44;
    ctx.fillStyle = "#3A1D2B"; ctx.font = "18px 'Source Sans 3', Arial";
    after.forEach(row);

    if (noteLines.length) {
      ctx.fillStyle = "#8C6677";
      noteLines.forEach((l) => { ctx.fillText(l, left, y); y += 28; });
    }
    ctx.fillStyle = "#8C6677"; ctx.textAlign = "center";
    ctx.fillText("Thank you for your order!", width / 2, height - 36);
    return canvas;
  }

  const fileName = `receipt-${String(R.orderNo).replace(/[^\w-]+/g, "_")}.jpg`;

  async function download() {
    const canvas = await drawReceipt();
    const link = document.createElement("a");
    link.download = fileName;
    link.href = canvas.toDataURL("image/jpeg", 0.92);
    link.click();
  }

  // Share straight to Messenger, Viber, etc. (phones that support sharing files)
  async function share() {
    const canvas = await drawReceipt();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    const file = new File([blob], fileName, { type: "image/jpeg" });
    try {
      await navigator.share({ files: [file], title: `Order ${R.orderNo}` });
    } catch (err) {
      if (err.name !== "AbortError") showToast("Couldn't share. Use Download JPEG instead.", true);
    }
  }

  btn.addEventListener("click", download);
  const shareBtn = $("#shareReceipt");
  const probe = new File([""], "x.jpg", { type: "image/jpeg" });
  if (shareBtn && navigator.canShare && navigator.canShare({ files: [probe] })) {
    shareBtn.hidden = false;
    shareBtn.addEventListener("click", share);
  }
})();
