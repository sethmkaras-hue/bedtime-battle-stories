"use strict";
(() => {
  let csrf = null;
  const el = (id) => document.getElementById(id);
  const message = (text) => (el("parent-review-message").textContent = text);
  async function request(path, body) {
    const response = await fetch("/api/admin/" + path, {
      method: body ? "POST" : "GET",
      credentials: "same-origin",
      headers: body
        ? { "Content-Type": "application/json", "X-Parent-CSRF": csrf || "" }
        : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      const problems = Array.isArray(detail) ? detail : detail?.issues || [];
      const fields = problems
        .map((issue) => (issue.loc || []).join(".") + ": " + issue.msg)
        .join("; ");
      throw Error(
        (typeof detail === "string"
          ? detail
          : detail?.message || "Review action failed") +
          (detail?.creature ? " · " + detail.creature : "") +
          (fields ? " · " + fields : ""),
      );
    }
    return data;
  }
  function text(parent, value) {
    const p = document.createElement("p");
    p.textContent = value;
    parent.append(p);
  }
  function link(parent, label, url) {
    try {
      if (new URL(url).protocol !== "https:") return;
    } catch {
      return;
    }
    const a = document.createElement("a");
    a.textContent = label;
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    parent.append(a);
  }
  async function session() {
    const data = await request("session");
    csrf = data.csrf;
    el("parent-locked").hidden = data.unlocked;
    el("parent-unlocked").hidden = !data.unlocked;
    el("parent-config-status").textContent = data.configured
      ? "Use the passphrase configured on your server. Sessions lock after 15 minutes."
      : "Run .venv/bin/python scripts/configure_parent.py in the server terminal first. No account is required.";
    if (data.unlocked) await load();
  }
  async function load() {
    const data = await request("proposals");
    el("parent-coverage").textContent =
      data.pending.length +
      " pending proposals · " +
      data.coverage.licensed_images +
      " licensed images · " +
      data.coverage.verified_pronunciations +
      " verified pronunciations · " +
      data.coverage.ready_pronunciations +
      " prepared names";
    el("parent-proposals").replaceChildren();
    for (const row of data.pending) render(row);
    el("parent-missing").replaceChildren();
    for (const row of data.missing.filter((r) => r.issues.length)) {
      text(el("parent-missing"), row.name + ": " + row.issues.join(", "));
    }
  }
  function render(row) {
    const proposal = row.proposal,
      card = document.createElement("article");
    card.className = "parent-proposal";
    const h = document.createElement("h2");
    h.textContent = proposal.display_name;
    card.append(h);
    text(card, proposal.scientific_name + " · " + proposal.stage);
    const fields = document.createElement("pre");
    fields.textContent = JSON.stringify(proposal.science, null, 2);
    card.append(fields);
    for (const s of proposal.evidence || []) {
      text(card, s.title);
      link(card, "Inspect source", s.url);
    }
    for (const issue of proposal.issues || []) text(card, issue);
    for (const url of proposal.source_links || [])
      link(card, "Source attempted / manual research", url);
    const applied = new Set(row.applied_scopes || []);
    const scopes = [];
    function checkbox(label, value) {
      const wrapper = document.createElement("label");
      wrapper.className = "toggle";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.scope = value;
      wrapper.append(input, document.createTextNode(label));
      card.append(wrapper);
      scopes.push(input);
      return input;
    }
    if (Object.keys(proposal.science || {}).length && !applied.has("science"))
      checkbox(
        "I inspected these source-supported scientific fields",
        "science",
      );
    let phonetic, stress, tts;
    if (proposal.pronunciation && !applied.has("pronunciation")) {
      checkbox(
        "I checked the pronunciation guidance against its source",
        "pronunciation",
      );
      link(card, "Pronunciation source", proposal.pronunciation.source_url);
      if (proposal.pronunciation.acquisition === "supplied_reference") {
        const evidence = document.createElement("p");
        const reference = proposal.pronunciation;
        evidence.textContent =
          "Supplied reference · " +
          reference.publisher +
          " · retrieved " +
          reference.retrieved_on +
          " · original review: " +
          JSON.stringify(reference.source_verification) +
          (reference.alternatives?.length
            ? " · alternatives: " + reference.alternatives.join("; ")
            : "") +
          ". App approval is still required.";
        card.append(evidence);
      }
      for (const [key, label] of [
        ["phonetic", "Written pronunciation"],
        ["stress", "Syllable emphasis"],
        ["tts_text", "TTS-friendly text"],
      ]) {
        const wrapper = document.createElement("label");
        wrapper.textContent = label;
        const input = document.createElement("input");
        input.type = "text";
        input.value = proposal.pronunciation[key] || "";
        input.maxLength = key === "tts_text" ? 200 : 100;
        wrapper.append(input);
        card.append(wrapper);
        if (key === "phonetic") phonetic = input;
        if (key === "stress") stress = input;
        if (key === "tts_text") tts = input;
      }
    }
    const confirm = document.createElement("input");
    confirm.type = "checkbox";
    const label = document.createElement("label");
    label.className = "toggle";
    label.append(
      confirm,
      document.createTextNode("Confirm this parent review decision"),
    );
    card.append(label);
    const approve = document.createElement("button");
    approve.textContent = "Approve inspected updates";
    approve.disabled = true;
    const reject = document.createElement("button");
    reject.textContent = applied.size
      ? "Reject remaining updates"
      : "Reject proposal";
    reject.disabled = true;
    function updateButtons() {
      approve.disabled =
        !confirm.checked || !scopes.some((input) => input.checked);
      reject.disabled = !confirm.checked;
    }
    confirm.onchange = updateButtons;
    scopes.forEach((input) => (input.onchange = updateButtons));
    card.append(approve, reject);
    async function decide(decision) {
      approve.disabled = reject.disabled = true;
      try {
        const body = {
          decision,
          confirm: confirm.checked,
          scopes: scopes.filter((c) => c.checked).map((c) => c.dataset.scope),
        };
        if (
          decision === "approve" &&
          body.scopes.includes("pronunciation") &&
          phonetic
        ) {
          body.phonetic = phonetic.value;
          body.stress = stress.value;
          body.tts_text = tts.value;
        }
        const data = await request("proposals/" + row.id + "/decision", body);
        message(
          data.audio_note ||
            "Decision saved. No tournament progress was changed.",
        );
        await window.refreshCreatureLibrary?.();
        await load();
      } catch (error) {
        message(error.message);
        updateButtons();
      }
    }
    approve.onclick = () => decide("approve");
    reject.onclick = () => decide("reject");
    el("parent-proposals").append(card);
  }
  el("open-parent-review").onclick = async () => {
    show("parent-review");
    message("");
    try {
      await session();
    } catch (error) {
      message(error.message);
    }
  };
  el("parent-login").onsubmit = async (event) => {
    event.preventDefault();
    const password = el("parent-password").value;
    el("parent-password").value = "";
    try {
      const data = await request("login", { password });
      csrf = data.csrf;
      message("Parent review unlocked.");
      await session();
    } catch (error) {
      message(error.message);
    }
  };
  el("parent-refresh").onclick = () =>
    load().catch((error) => message(error.message));
  el("parent-logout").onclick = async () => {
    try {
      await request("logout", {});
      csrf = null;
      await session();
      message("Parent review is locked.");
    } catch (error) {
      message(error.message);
    }
  };
})();
