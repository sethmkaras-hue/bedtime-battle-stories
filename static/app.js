"use strict";
const $ = (id) => document.getElementById(id),
  settings = window.BedtimeSettings;
let category = "",
  library = [],
  selected = [],
  current = null,
  screen = "welcome",
  returnScreen = "welcome",
  beforeQuiet = "welcome",
  lastAction = Date.now(),
  busy = false,
  providerInfo = {},
  loadId = 0,
  encyclopediaLibrary = [],
  activeProfile = null,
  profileReturn = "selection";
const screens = [
  "welcome",
  "encyclopedia",
  "profile",
  "attributions",
  "categories",
  "selection",
  "bracket",
  "player",
  "celebration",
  "settings",
  "quiet",
];
const audio = new BedtimeAudio($("story-audio"), $("audio-status"), () => {
  touch();
  if (screen === "player" && current?.chapter) guarded(finishChapter)();
});
function touch() {
  lastAction = Date.now();
}
function show(id) {
  if (screen === "player" && id !== "player") audio.stop();
  screen = id;
  screens.forEach((s) => ($(s).hidden = s !== id));
  $("back").hidden = ["welcome", "quiet"].includes(id);
  document.body.classList.toggle("sleeping", id === "quiet");
  $("message").textContent = "";
  touch();
  if (id === "bracket") requestAnimationFrame(drawConnectors);
  window.scrollTo({ top: 0, behavior: "instant" });
}
function stopAudio() {
  audio.stop();
}
function checkIdle() {
  const prefs = settings.get();
  if (!prefs.timeoutEnabled) return;
  if (audio.active() || (audio.generating && screen === "player")) {
    touch();
    return;
  }
  if (
    screen !== "quiet" &&
    Date.now() - lastAction >= prefs.idleMinutes * 60000
  ) {
    beforeQuiet = screen;
    audio.stop();
    show("quiet");
  }
}
document.addEventListener("pointerdown", touch);
document.addEventListener("keydown", touch);
document.addEventListener("visibilitychange", checkIdle);
setInterval(checkIdle, 1000);
function save() {
  try {
    sessionStorage.setItem("bedtimeTournament", JSON.stringify(current));
  } catch {}
  $("continue-adventure").hidden = !current;
}
async function api(path, options) {
  const r = await fetch(path, options);
  const data = await r.json();
  if (!r.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Please check your choices and try again.",
    );
  return data;
}
function guarded(fn) {
  return async (event) => {
    if (busy) return;
    busy = true;
    const b = event?.currentTarget;
    if (b?.tagName === "BUTTON") {
      b.disabled = true;
      b.classList.add("loading-button");
    }
    try {
      await fn();
    } catch (e) {
      $("message").textContent =
        e.message || "Something went wrong. Please try again.";
    } finally {
      busy = false;
      if (b) {
        b.disabled = false;
        b.classList.remove("loading-button");
      }
      if (screen === "selection") updateCount();
    }
  };
}
function illustration(c) {
  const ref = c.image_reference;
  return typeof ref === "string" &&
    (/^\/static\/[a-zA-Z0-9_./-]+$/.test(ref) || /^\/api\/library\/images\/\d+\/[a-f0-9]{64}$/.test(ref) || /^\/api\/creature-images\/files\/\d+\/[a-f0-9]{64}$/.test(ref)) &&
    !ref.includes("..")
    ? ref
    : "/static/assets/" +
        (c.category === "shark"
          ? "shark"
          : c.category === "marine_reptile"
            ? "marine_reptile"
            : "dinosaur") +
        ".svg";
}
function picture(c) {
  const img = document.createElement("img");
  img.src = illustration(c);
  img.alt = "";
  if (c.image_variants) {
    const entries = Object.entries(c.image_variants).filter(
      ([width, path]) =>
        /^\d+$/.test(width) &&
        /^\/static\/[A-Za-z0-9_./-]+$/.test(path) &&
        !path.includes(".."),
    );
    if (entries.length) {
      img.srcset = entries
        .map(([width, path]) => path + " " + width + "w")
        .join(", ");
      img.sizes = "(max-width:700px)45vw,240px";
    }
  }
  if (c.image_kind === "ai_generated") img.dataset.generatedImage = "true";
  else if (c.artwork_placeholder === false) img.dataset.realImage = "true";
  img.loading = "lazy";
  img.decoding = "async";
  img.onerror = () => {
    img.onerror = null;
    img.src = illustration({ ...c, image_reference: null });
  };
  return img;
}
function hear(c) {
  const b = document.createElement("button");
  b.className = "speaker";
  b.setAttribute("aria-pressed", "false");
  if (c.pronunciation_audio?.url)
    b.dataset.audioUrl = c.pronunciation_audio.url;
  else
    b.title =
      "Audio not prepared; written guide available in the creature profile";
  b.setAttribute("aria-label", "Pronounce " + c.name);
  b.innerHTML =
    '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M11 4 5 9H2v6h3l6 5V4Z"/><path d="M15 8c3 2 3 6 0 8m3-11c5 4 5 10 0 14" stroke-linecap="round"/></svg>';
  b.onclick = (e) => {
    e.stopPropagation();
    touch();
    audio.pronounce(c, settings.get(), b);
  };
  return b;
}
const popularNames = [
  "Tyrannosaurus",
  "Triceratops",
  "Stegosaurus",
  "Velociraptor",
  "Brachiosaurus",
  "Ankylosaurus",
  "Spinosaurus",
  "Diplodocus",
  "Parasaurolophus",
  "Allosaurus",
  "Great white shark",
  "Whale shark",
  "Tiger shark",
  "Great hammerhead",
  "Bull shark",
  "Blue shark",
  "Shortfin mako",
  "Nurse shark",
  "Mosasaurus",
  "Tylosaurus",
  "Plesiosaurus",
  "Ichthyosaurus",
  "Elasmosaurus",
  "Kronosaurus",
  "Liopleurodon",
  "Ophthalmosaurus",
];
function updateCount() {
  $("count").textContent = selected.length + " of 8 Selected";
  $("next").disabled = selected.length !== 8;
  $("random").disabled = library.length < 8;
}
function render() {
  updateCount();
  $("selection-slots").replaceChildren();
  for (let i = 0; i < 8; i++) {
    const c = library.find((c) => c.id === selected[i]);
    const slot = document.createElement("button");
    slot.className = "selection-slot" + (c ? " filled" : "");
    slot.setAttribute(
      "aria-label",
      c ? "Remove " + c.name : "Empty selection slot " + (i + 1),
    );
    if (c) {
      slot.append(picture(c));
      const label = document.createElement("span");
      label.textContent = c.name;
      slot.append(label);
      slot.onclick = () => {
        selected = selected.filter((id) => id !== c.id);
        render();
      };
    } else {
      slot.textContent = "+";
      slot.disabled = true;
    }
    $("selection-slots").append(slot);
  }
  const term = $("search").value.toLocaleLowerCase();
  let rows = library.filter((c) =>
    (c.name + " " + c.scientific_name).toLocaleLowerCase().includes(term),
  );
  if (!term && $("browse-group").value === "popular")
    rows = rows
      .filter((c) => popularNames.includes(c.name))
      .sort(
        (a, b) => popularNames.indexOf(a.name) - popularNames.indexOf(b.name),
      );
  $("library-heading").textContent = term
    ? "Your search"
    : $("browse-group").value === "popular"
      ? "Popular Creatures"
      : "All Creatures";
  $("library-status").textContent = rows.length
    ? rows.length + " creatures to explore. Tap a creature to join your adventure."
    : "No creatures found. Try another name.";
  $("creatures").replaceChildren(...rows.map((c) => creatureCard(c, true)));
}
function creatureCard(c, selectable) {
  const card = document.createElement("article");
  const pos = selected.indexOf(c.id);
  card.className = "creature" + (selectable && pos >= 0 ? " selected" : "");
  const pick = document.createElement("button");
  pick.className = "creature-pick";
  pick.setAttribute("aria-label", "Meet " + c.name);
  pick.append(picture(c));
  const name = document.createElement("strong");
  name.textContent = c.name;
  pick.append(name);
  pick.onclick = () => openProfile(c);
  card.append(pick, hear(c));
  if (c.artwork_placeholder !== false || c.image_kind === "ai_generated") {
    const note = document.createElement("p");
    note.className = "artwork-note";
    note.textContent = c.image_kind === "ai_generated" ? "AI-generated illustration" : "Illustration placeholder";
    card.append(note);
  }
  if (selectable) {
    const add = document.createElement("button");
    add.className = "creature-select";
    add.textContent = pos >= 0 ? "✓ Remove" : "＋ Add";
    add.setAttribute("aria-label", (pos >= 0 ? "Remove " : "Select ") + c.name);
    add.setAttribute("aria-pressed", String(pos >= 0));
    add.disabled =
      (selected.length === 8 && pos < 0) || c.eligible_for_tournament === false;
    add.onclick = () => {
      if (pos >= 0) selected = selected.filter((id) => id !== c.id);
      else if (selected.length < 8) selected.push(c.id);
      render();
    };
    card.append(add);
    if (pos >= 0) {
      const mark = document.createElement("span");
      mark.className = "selection-mark";
      mark.textContent = "✓ " + (pos + 1);
      card.append(mark);
    }
  }
  return card;
}

window.refreshCreatureLibrary = async () => {
  const rows = await api("/api/creatures");
  if (category && library.length) {
    library = rows.filter(c => category === "ocean" ? ["shark", "marine_reptile"].includes(c.category) : c.category === category);
    render();
  }
  if (encyclopediaLibrary.length) {
    encyclopediaLibrary = rows;
    renderEncyclopedia();
  }
};

async function choose(value) {
  const rows = await api(
    value === "ocean" ? "/api/creatures" : "/api/creatures?category=" + value,
  );
  category = value;
  library =
    value === "ocean"
      ? rows.filter((c) => ["shark", "marine_reptile"].includes(c.category))
      : rows;
  selected = [];
  $("search").value = "";
  $("browse-group").value = "all";
  render();
  show("selection");
}
document
  .querySelectorAll("[data-category]")
  .forEach((b) => (b.onclick = guarded(() => choose(b.dataset.category))));
$("start-adventure").onclick = () => show("categories");
$("search").oninput = render;
$("browse-group").onchange = render;
$("clear").onclick = () => {
  selected = [];
  render();
};
$("random").onclick = guarded(async () => {
  selected = (await api("/api/selection/random?category=" + category))
    .creature_ids;
  render();
});
async function createTournament(ids = selected) {
  audio.stop();
  const p = settings.get();
  const result = await api("/api/tournament", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      creature_ids: ids,
      shuffle: p.shuffle,
      realism: p.realism,
      duration: p.duration,
    }),
  });
  current = result;
  save();
  renderBracket();
  show("bracket");
  requestAnimationFrame(drawConnectors);
}
$("next").onclick = guarded(() => createTournament());
$("surprise").onclick = guarded(async () => {
  const all = await api("/api/creatures");
  const valid = ["dinosaur", "shark", "marine_reptile"].filter(
    (cat) => all.filter((c) => c.category === cat).length >= 8,
  );
  if (!valid.length)
    throw Error("Add at least eight compatible creatures to begin.");
  const cat = valid[Math.floor(Math.random() * valid.length)];
  const ids = (await api("/api/selection/random?category=" + cat)).creature_ids;
  await createTournament(ids);
});
function renderBracket() {
  $("rounds").replaceChildren();
  let activeId = current.chapter?.match_id;
  current.rounds.forEach((round, ri) => {
    const col = document.createElement("div");
    col.className = "round";
    const h = document.createElement("h2");
    h.textContent = round.name;
    col.append(h);
    const list = document.createElement("div");
    list.className = "round-matches";
    round.matches.forEach((m, i) => {
      const card = document.createElement("article");
      card.className =
        "match " +
        (m.status === "complete"
          ? "complete"
          : m.id === activeId
            ? "active"
            : "");
      card.dataset.match = m.id;
      const label = document.createElement("p");
      label.className = "match-label";
      label.textContent =
        "BATTLE " +
        (ri === 0 ? i + 1 : ri === 1 ? i + 5 : 7) +
        (m.id === activeId
          ? " · UP NEXT"
          : m.status === "complete"
            ? " · COMPLETE"
            : "");
      card.append(label);
      ["left", "right"].forEach((side, index) => {
        if (index) {
          const vs = document.createElement("div");
          vs.className = "match-vs";
          vs.textContent = "VS";
          card.append(vs);
        }
        const c = m[side];
        const row = document.createElement("div");
        row.className =
          "contender" +
          (m.winner && c ? (m.winner.id === c.id ? " winner" : " loser") : "");
        const name = document.createElement("span");
        name.textContent = c
          ? (m.winner?.id === c.id ? "✓ " : "") + c.name
          : "Waiting for Winner";
        if (c) row.append(picture(c));
        row.append(name);
        if (c) row.append(hear(c));
        card.append(row);
      });
      list.append(card);
    });
    col.append(list);
    $("rounds").append(col);
  });
  const winnerCol = document.createElement("div");
  winnerCol.className = "round";
  const title = document.createElement("h2");
  title.textContent = "Champion";
  const content = document.createElement("div");
  content.className = "round-matches";
  const winner = document.createElement("article");
  winner.className = "match";
  if (current.champion) {
    winner.append(picture(current.champion));
    const h = document.createElement("h3");
    h.textContent = current.champion.name;
    winner.append(h, hear(current.champion));
  } else winner.textContent = "✦ A champion is waiting to be discovered";
  content.append(winner);
  winnerCol.append(title, content);
  $("rounds").append(winnerCol);
  $("story").hidden = !current.chapter;
  requestAnimationFrame(drawConnectors);
}
$("focus-battle").onclick = () => {
  $("rounds")
    .querySelector(".active")
    ?.scrollIntoView({
      behavior: settings.get().reducedMotion ? "instant" : "smooth",
      block: "nearest",
      inline: "center",
    });
};
function overrides(participants) {
  const output = {};
  if (settings.get().guidedNames)
    for (const c of participants) {
      if (c.profile?.pronunciation?.status === "verified")
        output[c.name] = c.profile.pronunciation.tts_text;
      else if (c.pronunciation)
        output[c.name] = c.pronunciation.toLowerCase().replace(/sawr/g, "sore");
    }
  return output;
}

async function openStory() {
  if (!current?.chapter) return;
  const c = current.chapter;
  const ri = current.rounds.findIndex((r) =>
    r.matches.some((m) => m.id === c.match_id),
  );
  $("battle-label").textContent =
    current.rounds[ri].name.toUpperCase() +
    " · BATTLE " +
    (current.completed + 1) +
    " OF 7";
  $("chapter-title").textContent = c.title;
  $("chapter-text").replaceChildren();
  c.paragraphs.forEach((text) => {
    const p = document.createElement("p");
    p.textContent = text;
    $("chapter-text").append(p);
  });
  $("battle-creatures").replaceChildren();
  c.participants.forEach((creature, i) => {
    if (i) {
      const vs = document.createElement("span");
      vs.className = "versus";
      vs.textContent = "VS";
      $("battle-creatures").append(vs);
    }
    const card = document.createElement("div");
    card.className = "battle-portrait";
    const name = document.createElement("h2");
    name.textContent = creature.name;
    card.append(picture(creature), name, hear(creature));
    $("battle-creatures").append(card);
  });
  show("player");
  const id = ++loadId;
  audio.chunks = [];
  const prefs = settings.get();
  $("story-rate").value = String(prefs.narrationRate);
  const ready = await audio.prepare(
    [...c.paragraphs, c.ending].join("\n\n"),
    prefs,
    overrides(c.participants),
  );
  if (
    ready &&
    id === loadId &&
    screen === "player" &&
    prefs.autoNarration &&
    !audio.pronouncing &&
    !audio.active()
  )
    audio.play();
}
$("story").onclick = () => openStory();
function context(completed = current.completed) {
  return {
    creature_ids: current.entrant_ids,
    seed: current.seed,
    shuffle: current.shuffle,
    realism: current.realism,
    duration: current.duration,
    completed,
  };
}
async function finishChapter() {
  if (!current?.chapter) return;
  const ending = current.chapter.ending;
  const result = await api("/api/adventure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(context(current.completed + 1)),
  });
  audio.stop();
  current = result;
  save();
  renderBracket();
  if (current.champion) celebrate();
  else {
    show("bracket");
    requestAnimationFrame(drawConnectors);
    $("message").textContent = ending;
  }
}
$("finish").onclick = guarded(finishChapter);
$("play").onclick = () => audio.play();
$("pause").onclick = () => {
  audio.pause();
  touch();
};
$("replay").onclick = () => audio.replay();
$("story-rate").onchange = () => {
  settings.set("narrationRate", Number($("story-rate").value));
  if (audio.prefs) audio.prefs.narrationRate = settings.get().narrationRate;
  $("story-audio").playbackRate = settings.get().narrationRate;
};
function celebrate() {
  const c = current.champion;
  $("winner-card").replaceChildren(picture(c));
  const h = document.createElement("h2");
  h.textContent = c.name;
  $("winner-card").append(h, hear(c));
  show("celebration");
}
$("play-again").onclick = guarded(() => createTournament(current.entrant_ids));
$("new-adventure").onclick = () => {
  current = null;
  save();
  selected = [];
  show("categories");
};
$("view-bracket").onclick = () => {
  renderBracket();
  show("bracket");
  requestAnimationFrame(drawConnectors);
};
$("continue-adventure").onclick = () => {
  renderBracket();
  current.champion ? celebrate() : show("bracket");
  requestAnimationFrame(drawConnectors);
};
$("home").onclick = () => {
  loadId++;
  audio.stop();
  show("welcome");
};
$("back").onclick = () => {
  loadId++;
  audio.stop();
  if (screen === "settings") {
    const target = returnScreen;
    if (target === "player") openStory();
    else show(target);
    return;
  }
  show(
    {
      encyclopedia: "welcome",
      profile: profileReturn,
      attributions: "settings",
      categories: "welcome",
      selection: "categories",
      bracket: library.length ? "selection" : "welcome",
      player: "bracket",
      celebration: "bracket",
    }[screen] || "welcome",
  );
};
$("resume").onclick = () => show(beforeQuiet);
const fields = {
  "narration-provider": "narrationProvider",
  "pronunciation-provider": "pronunciationProvider",
  "narration-voice": "narrationVoice",
  "pronunciation-voice": "pronunciationVoice",
  "name-rate": "nameRate",
  "narration-rate": "narrationRate",
  "auto-narration": "autoNarration",
  "pronunciation-buttons": "pronunciationButtons",
  "guided-names": "guidedNames",
  duration: "duration",
  realism: "realism",
  shuffle: "shuffle",
  "timeout-enabled": "timeoutEnabled",
  "idle-minutes": "idleMinutes",
  "reduced-motion": "reducedMotion",
};
function voiceOptions(kind) {
  const provider = settings.get()[kind + "Provider"];
  const select = $(kind + "-voice"),
    saved = settings.get()[kind + "Voice"];
  select.replaceChildren();
  let voices =
    provider === "browser"
      ? (window.speechSynthesis?.getVoices?.() || [])
          .filter((v) => /^en[-_]/i.test(v.lang))
          .map((v) => ({ id: v.voiceURI, name: v.name }))
      : providerInfo[provider]?.voices || [];
  if (!voices.length)
    voices = [
      {
        id:
          provider === "kokoro"
            ? "af_heart"
            : provider === "piper"
              ? "en_US-lessac-medium"
              : provider === "openai"
                ? "coral"
                : "",
        name:
          provider === "browser"
            ? "Device default"
            : provider === "kokoro"
              ? "Heart · American English"
              : provider === "piper"
                ? "Lessac · US English"
                : "Coral",
      },
    ];
  voices.forEach((v) => select.add(new Option(v.name, v.id)));
  if (voices.some((v) => v.id === saved)) select.value = saved;
  else settings.set(kind + "Voice", voices[0].id);
}
function syncSettings() {
  const p = settings.get();
  for (const [id, key] of Object.entries(fields)) {
    if (id.endsWith("-voice")) continue;
    const el = $(id);
    if (el.type === "checkbox") el.checked = p[key];
    else el.value = String(p[key]);
  }
  voiceOptions("narration");
  voiceOptions("pronunciation");
}
for (const [id, key] of Object.entries(fields))
  $(id).addEventListener("change", () => {
    const el = $(id);
    settings.set(
      key,
      el.type === "checkbox"
        ? el.checked
        : ["nameRate", "narrationRate", "idleMinutes"].includes(key)
          ? Number(el.value)
          : el.value,
    );
    if (id.endsWith("-provider"))
      voiceOptions(id.startsWith("narration") ? "narration" : "pronunciation");
  });
$("preferences").onsubmit = (e) => e.preventDefault();
async function cacheStats() {
  try {
    const data = await api("/api/audio/cache");
    $("cache-stats").textContent =
      data.count +
      " saved audio files · " +
      (data.bytes / 1024 / 1024).toFixed(1) +
      " MB";
  } catch {
    $("cache-stats").textContent = "Audio cache status unavailable.";
  }
}
async function refreshProviders() {
  try {
    const data = await api("/api/audio/providers");
    providerInfo = data.providers;
    $("provider-status").replaceChildren();
    if (data.runtime) {
      const runtime = document.createElement("p");
      runtime.textContent =
        "Server: " +
        data.runtime.implementation +
        " " +
        data.runtime.python +
        " · CPU audio";
      $("provider-status").append(runtime);
    }
    Object.entries(providerInfo).forEach(([name, info]) => {
      const p = document.createElement("p");
      p.textContent =
        name +
        ": " +
        (info.available ? "Ready" : info.reason || "Setup needed") +
        (info.last_error ? " · " + info.last_error : "");
      $("provider-status").append(p);
    });
    const fallback = document.createElement("p");
    fallback.textContent =
      providerInfo.kokoro?.available && !providerInfo.piper?.available
        ? "Kokoro will handle both stories and names locally until Piper is ready."
        : providerInfo.piper?.available && !providerInfo.kokoro?.available
          ? "Piper will handle local audio until Kokoro is ready."
          : !providerInfo.kokoro?.available && !providerInfo.piper?.available
            ? "No local engine is ready. Device speech is the fallback until local setup is complete."
            : "";
    if (fallback.textContent) $("provider-status").append(fallback);
  } catch {
    $("provider-status").textContent =
      "Server audio unavailable. Device speech remains available.";
  }
  syncSettings();
}
$("settings-open").onclick = () => {
  if (screen === "settings") return;
  returnScreen = screen;
  audio.stop();
  show("settings");
  syncSettings();
  refreshProviders();
  cacheStats();
};
window.speechSynthesis?.addEventListener?.("voiceschanged", () => {
  if (screen === "settings") {
    voiceOptions("narration");
    voiceOptions("pronunciation");
  }
});
$("preview-name").onclick = () =>
  audio.previewPronunciation(
    {
      name: "Hello, little explorer.",
      pronunciation: "Hello, little explorer.",
    },
    settings.get(),
    $("preview-name"),
  );
$("preview-story").onclick = guarded(async () => {
  const p = settings.get();
  await audio.prepare(
    "The moon is shining. A wonderful little adventure is about to begin.",
    p,
  );
  await audio.play();
});
$("clear-cache").onclick = () => {
  $("cache-confirm").hidden = false;
};
$("cancel-clear").onclick = () => {
  $("cache-confirm").hidden = true;
};
$("confirm-clear").onclick = guarded(async () => {
  await api("/api/audio/cache", {
    method: "DELETE",
    headers: { "X-Bedtime-Confirm": "clear" },
  });
  $("cache-confirm").hidden = true;
  cacheStats();
});
$("benchmark").onclick = guarded(async () => {
  const p = settings.get();
  if (!["kokoro", "piper"].includes(p.narrationProvider))
    throw Error("Choose a local provider to benchmark.");
  $("benchmark-result").textContent = "Measuring local audio generation…";
  const data = await api("/api/audio/benchmark", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: p.narrationProvider,
      voice: p.narrationVoice,
    }),
  });
  let result = data;
  while (["queued", "generating"].includes(result.state)) {
    await new Promise((r) => setTimeout(r, 1000));
    result = await api("/api/audio/jobs/" + data.key);
  }
  if (result.state !== "ready")
    throw Error(result.error || "Benchmark unavailable");
  $("benchmark-result").textContent = result.cached
    ? "Cached result · " + JSON.stringify(result.metrics)
    : JSON.stringify(result.metrics);
});
async function restore() {
  try {
    const cfg = await api("/api/config");
    $("sample").hidden = !cfg.sample_data;
    const stored = JSON.parse(
      sessionStorage.getItem("bedtimeTournament") || "null",
    );
    if (stored) {
      const ids =
        stored.entrant_ids ||
        stored.rounds[0].matches.flatMap((m) => [m.left.id, m.right.id]);
      current = await api("/api/adventure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          creature_ids: ids,
          seed: stored.seed ?? 12345,
          shuffle: stored.shuffle ?? false,
          completed: stored.completed ?? 0,
          realism: stored.realism,
          duration: stored.duration,
        }),
      });
      save();
    }
    await refreshProviders();
  } catch {
    current = null;
    try {
      sessionStorage.removeItem("bedtimeTournament");
    } catch {}
  }
}
restore();

function drawConnectors() {
  const root = $("rounds");
  if (!current || !root.children.length) return;
  root.querySelector(".bracket-links")?.remove();
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("bracket-links");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("width", root.scrollWidth);
  svg.setAttribute("height", root.scrollHeight);
  const origin = root.getBoundingClientRect();
  function connect(source, target) {
    if (!source || !target) return;
    const a = source.getBoundingClientRect(),
      b = target.getBoundingClientRect(),
      sx = a.right - origin.left,
      sy = a.top + a.height / 2 - origin.top,
      dx = b.left - origin.left,
      dy = b.top + b.height / 2 - origin.top;
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", `M ${sx} ${sy} H ${(sx + dx) / 2} V ${dy} H ${dx}`);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "#596582");
    path.setAttribute("stroke-width", "2");
    svg.append(path);
  }
  current.rounds.forEach((r) =>
    r.matches.forEach((m) =>
      (m.sources || []).forEach((id) =>
        connect(
          root.querySelector(`[data-match="${id}"]`),
          root.querySelector(`[data-match="${m.id}"]`),
        ),
      ),
    ),
  );
  connect(
    root.querySelector('[data-match="r2m0"]'),
    root.querySelector(".round:last-child .match"),
  );
  root.prepend(svg);
}
window.addEventListener("resize", () => {
  if (screen === "bracket") drawConnectors();
});

$("browse-encyclopedia").onclick = guarded(async () => {
  encyclopediaLibrary = await api("/api/creatures");
  $("encyclopedia-search").value = "";
  $("discovery-filter").value = "all";
  renderEncyclopedia();
  show("encyclopedia");
});
function renderEncyclopedia() {
  const filter = $("discovery-filter").value,
    term = $("encyclopedia-search").value.toLowerCase();
  let rows = encyclopediaLibrary.filter((c) =>
    (c.name + " " + c.scientific_name).toLowerCase().includes(term),
  );
  if (filter === "featured")
    rows = rows.filter((c) => popularNames.includes(c.name));
  else if (["dinosaur", "shark", "marine_reptile"].includes(filter))
    rows = rows.filter((c) => c.category === filter);
  else if (filter !== "all")
    rows = rows.filter(
      (c) =>
        c.profile?.verification_status === "verified" &&
        (filter === "carnivores"
          ? ["meat", "carnivore"].includes(c.profile.diet)
          : filter === "herbivores"
            ? ["plants", "herbivore"].includes(c.profile.diet)
            : c.profile.discovery_tags.includes(filter)),
    );
  $("encyclopedia-cards").replaceChildren(
    ...rows.map((c) => creatureCard(c, false)),
  );
  $("encyclopedia-status").textContent = rows.length
    ? rows.length + " creatures to discover. Tap a picture to meet one."
    : "No reviewed profiles match this trail yet.";
}
$("discovery-filter").onchange = renderEncyclopedia;
$("encyclopedia-search").oninput = renderEncyclopedia;
function rangeText(value) {
  return value?.minimum == null
    ? "Unknown"
    : (value.minimum === value.maximum
        ? value.minimum
        : value.minimum + "–" + value.maximum) +
        " " +
        value.unit;
}
function profileParagraph(parent, text) {
  const p = document.createElement("p");
  p.textContent = text;
  parent.append(p);
}
function referenceLink(parent, text, url) {
  if (!/^https:\/\//.test(url || "")) return;
  const a = document.createElement("a");
  a.textContent = text;
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  parent.append(a);
}
function openProfile(c) {
  profileReturn = screen;
  activeProfile = c;
  const p = c.profile || {};
  const image = picture(c);
  image.sizes = "(max-width:700px)90vw,640px";
  $("profile-image").replaceChildren(image);
  $("profile-name").textContent = c.name;
  $("profile-speaker").replaceChildren(hear(c));
  $("profile-scientific").textContent = c.scientific_name;
  $("profile-description").textContent =
    p.description ||
    c.description ||
    "This creature’s story is being researched.";
  $("profile-review").textContent =
    (p.verification_status === "verified"
      ? "Reviewed profile."
      : p.import_stage === "source_supported" ? "Source-supported information." : p.import_stage === "manually_reviewed" ? "Some fields were reviewed; this profile is still incomplete." : "Unknown details are left unknown.") +
    (c.image_kind === "ai_generated" ? " AI-generated illustration; anatomical accuracy has not been verified." : c.artwork_placeholder !== false
      ? " The illustration is a decorative placeholder."
      : "");
  $("profile-facts").replaceChildren();
  const facts = {
    Length: rangeText(p.length),
    Weight: rangeText(p.weight),
    Time:
      p.time_period ||
      (p.modern_status === "living" ? "Living today" : "Unknown"),
    Habitat: p.habitat || c.habitat || "Unknown",
    Distribution: p.geographic_distribution?.join(", ") || "Unknown",
    Food: p.diet || c.diet || "Unknown",
    "Animal group": p.taxon_group || "Not yet reviewed",
    "Taxon rank": p.taxon_rank || "Unknown",
  };
  for (const [label, value] of Object.entries(facts)) {
    const dt = document.createElement("dt"),
      dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    $("profile-facts").append(dt, dd);
  }
  $("profile-fun-facts").replaceChildren();
  for (const fact of p.fun_facts?.length
    ? p.fun_facts
    : ["Three sourced discoveries are still being checked."]) {
    const li = document.createElement("li");
    li.textContent = fact;
    $("profile-fun-facts").append(li);
  }
  $("profile-adaptations").replaceChildren();
  const traits = [
    ...(p.physical_characteristics || []),
    ...(p.offensive_adaptations || []),
    ...(p.defensive_adaptations || []),
  ];
  if (!traits.length) traits.push("Adaptations are awaiting source review.");
  traits.forEach((t) => profileParagraph($("profile-adaptations"), t));
  $("profile-sources").replaceChildren();
  const art = c.internet_image || p.image || {};
  $("profile-image-attribution").replaceChildren();
  if (/CC[ -]BY/i.test(art.license || "")) {
    profileParagraph($("profile-image-attribution"),
      [art.creator || art.attribution, art.license, art.modifications].filter(Boolean).join(" · "));
    referenceLink($("profile-image-attribution"), "Image source", art.original_source_url);
    referenceLink($("profile-image-attribution"), "License", art.license_url);
  }
  $("profile-add").textContent = selected.includes(c.id)
    ? "Remove from Tournament"
    : "Add to Tournament";
  const otherWorld = selected.length > 0 && !library.some((r) => r.id === c.id);
  $("profile-add").disabled =
    (selected.length >= 8 && !selected.includes(c.id)) ||
    otherWorld ||
    c.eligible_for_tournament === false;
  if (c.eligible_for_tournament === false)
    $("profile-add").textContent = "Habitat review needed before competing";
  else if (otherWorld)
    $("profile-add").textContent = "Choose this creature’s adventure first";
  show("profile");
}
$("profile-add").onclick = guarded(async () => {
  const c = activeProfile;
  if (!library.some((r) => r.id === c.id)) await choose(c.category);
  if (selected.includes(c.id)) selected = selected.filter((id) => id !== c.id);
  else if (selected.length < 8) selected.push(c.id);
  render();
  show("selection");
});
$("open-attributions").onclick = guarded(async () => {
  const [records, coverage] = await Promise.all([
    api("/api/library/sources-credits"), api("/api/library/image-coverage"),
  ]);
  $("attribution-list").replaceChildren();
  for (const record of records) {
    const section = document.createElement("article");
    const image = record.image || {};
    profileParagraph(section, record.name + " · " + (record.scientific_name || ""));
    profileParagraph(section, "Artwork: " + record.image_kind);
    profileParagraph(section, "Creator: " + (image.creator || "Not provided"));
    profileParagraph(section, "License: " + (image.license || image.model_license || "Unknown; no permission asserted"));
    profileParagraph(section, image.attribution || "Attribution not provided");
    profileParagraph(section, image.modifications || "");
    profileParagraph(section, "Retrieved: " + (image.retrieved_on || image.generated_at || "Not recorded"));
    referenceLink(section, "Image source", image.original_source_url);
    referenceLink(section, "Direct image", image.download_url);
    referenceLink(section, "License", image.license_url);
    for (const source of record.sources || []) {
      profileParagraph(section, source.title);
      referenceLink(section, "Scientific reference", source.url);
    }
    const pron = record.pronunciation || {};
    profileParagraph(section, "Pronunciation: " + (pron.phonetic || "Not sourced") + " · " + (pron.status || "unverified"));
    referenceLink(section, "Pronunciation reference", pron.source_url);
    $("attribution-list").append(section);
  }
  $("library-audit-summary").textContent = JSON.stringify(coverage, null, 2);
  show("attributions");
});
