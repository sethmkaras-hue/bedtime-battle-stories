"use strict";
let category = "",
  library = [],
  selected = [],
  current = null,
  lastAction = Date.now(),
  screen = "categories",
  beforeQuiet = "categories",
  narrationToken = 0,
  busy = false;
const $ = (id) => document.getElementById(id);
const screens = [
  "categories",
  "selection",
  "settings",
  "bracket",
  "player",
  "quiet",
];
function touch() {
  lastAction = Date.now();
}
function show(id) {
  screen = id;
  screens.forEach((s) => ($(s).hidden = s !== id));
  $("back").hidden = ["categories", "quiet"].includes(id);
  $("message").textContent = "";
  touch();
}
function save() {
  try {
    sessionStorage.setItem("bedtimeTournament", JSON.stringify(current));
  } catch {
    /* Optional browser storage. */
  }
}
function stopAudio() {
  narrationToken++;
  window.speechSynthesis?.cancel();
  document.querySelectorAll("audio").forEach((a) => a.pause());
  $("pause").textContent = "Pause";
}
function narrationActive() {
  return (
    Boolean(
      window.speechSynthesis?.speaking && !window.speechSynthesis?.paused,
    ) ||
    Array.from(document.querySelectorAll("audio")).some(
      (a) => !a.paused && !a.ended,
    )
  );
}
function checkIdle() {
  if (narrationActive()) {
    touch();
    return;
  }
  if (screen !== "quiet" && Date.now() - lastAction >= 300000) {
    beforeQuiet = screen;
    stopAudio();
    show("quiet");
  }
}
document.addEventListener("pointerdown", touch);
document.addEventListener("keydown", touch);
document.addEventListener("visibilitychange", checkIdle);
setInterval(checkIdle, 1000);
function voices() {
  return (
    window.speechSynthesis
      ?.getVoices?.()
      .filter((v) => /^en[-_]/i.test(v.lang)) || []
  );
}
function loadVoices() {
  const saved = $("voice").value;
  $("voice").replaceChildren(new Option("Device default", ""));
  voices().forEach((v) =>
    $("voice").add(new Option(v.name + " (" + v.lang + ")", v.voiceURI)),
  );
  if (saved) $("voice").value = saved;
  else {
    const preferred = voices().find((v) =>
      /Google US English|Samantha|Natural/i.test(v.name),
    );
    if (preferred) $("voice").value = preferred.voiceURI;
  }
}
window.speechSynthesis?.addEventListener?.("voiceschanged", loadVoices);
loadVoices();
try {
  const pref = JSON.parse(localStorage.getItem("bedtimeVoice") || "null");
  if (pref) {
    $("name-rate").value = pref.rate || "0.8";
    $("guided-names").checked = pref.guided !== false;
    const restoreVoice = () => {
      if (voices().some((v) => v.voiceURI === pref.voice))
        $("voice").value = pref.voice;
    };
    restoreVoice();
    window.speechSynthesis?.addEventListener?.("voiceschanged", restoreVoice);
  }
} catch {
  /* Optional preferences. */
}
["voice", "name-rate", "guided-names"].forEach((id) =>
  $(id).addEventListener("change", () => {
    try {
      localStorage.setItem(
        "bedtimeVoice",
        JSON.stringify({
          voice: $("voice").value,
          rate: $("name-rate").value,
          guided: $("guided-names").checked,
        }),
      );
    } catch {}
  }),
);
function spokenName(c) {
  return $("guided-names").checked && c.pronunciation
    ? c.pronunciation
        .toLowerCase()
        .replace(/sawr/g, "sore")
        .replace(/\buh\b/g, "ah")
    : c.name;
}
// One adapter for pronunciation and narration; a future audio service can replace it.
function utterance(text, rate) {
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-US";
  u.rate = rate;
  const v = voices().find((v) => v.voiceURI === $("voice").value);
  if (v) {
    u.voice = v;
    u.lang = v.lang;
  }
  return u;
}
function say(c) {
  if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
    $("message").textContent =
      "Speech is unavailable. Try the written pronunciation guide.";
    return;
  }
  stopAudio();
  touch();
  const u = utterance(spokenName(c), Number($("name-rate").value));
  u.onend = touch;
  u.onerror = () => {
    $("message").textContent =
      "The device voice could not play. Try another voice.";
    touch();
  };
  speechSynthesis.speak(u);
}
function hear(c) {
  const b = document.createElement("button");
  b.textContent = "Hear";
  b.setAttribute("aria-label", "Pronounce " + c.name);
  b.onclick = () => say(c);
  return b;
}
async function api(path, options) {
  const r = await fetch(path, options);
  const data = await r.json();
  if (!r.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Please check your selection and settings.",
    );
  return data;
}
function guarded(action) {
  return async () => {
    if (busy) return;
    busy = true;
    try {
      await action();
    } catch (e) {
      $("message").textContent = e.message || "Please try again.";
    } finally {
      busy = false;
    }
  };
}
function render() {
  const term = $("search").value.toLocaleLowerCase();
  $("creatures").replaceChildren();
  const visible = library.filter((c) =>
    (c.name + " " + c.scientific_name).toLocaleLowerCase().includes(term),
  );
  $("library-status").textContent = visible.length + " creatures to explore";
  visible.forEach((c) => {
    const el = document.createElement("div");
    el.className = "creature";
    const row = document.createElement("div");
    row.className = "creature-actions";
    const b = document.createElement("button");
    const pos = selected.indexOf(c.id);
    b.textContent = (pos >= 0 ? pos + 1 + ". " : "") + c.name;
    b.setAttribute("aria-pressed", String(pos >= 0));
    b.disabled = selected.length === 8 && pos < 0;
    b.onclick = () => {
      if (pos >= 0) selected = selected.filter((x) => x !== c.id);
      else if (selected.length < 8) selected.push(c.id);
      render();
    };
    row.append(b, hear(c));
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Meet " + c.name;
    details.append(summary);
    [
      c.scientific_name,
      c.description,
      "Food: " + (c.diet || "Not yet reviewed"),
      "Say it: " + (c.pronunciation || c.name),
      "Measurements: not yet verified",
    ].forEach((text) => {
      const p = document.createElement("p");
      p.textContent = text;
      details.append(p);
    });
    if (c.review_status) {
      const p = document.createElement("p");
      p.textContent = "Scientific reference review pending.";
      details.append(p);
    }
    if (c.source_url) {
      const link = document.createElement("a");
      link.href = c.source_url;
      link.textContent = "Parent reference";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      details.append(link);
    }
    el.append(row, details);
    $("creatures").append(el);
  });
  $("count").textContent = selected.length + " of 8 selected";
  $("next").disabled = selected.length !== 8;
  $("random").disabled = library.length < 8;
}
async function categoryLibrary(value) {
  if (value === "ocean") {
    const rows = await api("/api/creatures");
    return rows.filter((c) => ["shark", "marine_reptile"].includes(c.category));
  }
  return api("/api/creatures?category=" + encodeURIComponent(value));
}
document.querySelectorAll("[data-category]").forEach(
  (b) =>
    (b.onclick = guarded(async () => {
      category = b.dataset.category;
      library = await categoryLibrary(category);
      selected = [];
      $("search").value = "";
      render();
      show("selection");
      if (library.length < 8)
        $("message").textContent =
          "This library needs at least eight creatures.";
    })),
);
$("search").oninput = render;
$("random").onclick = guarded(async () => {
  const data = await api(
    "/api/selection/random?category=" + encodeURIComponent(category),
  );
  selected = data.creature_ids;
  render();
});
$("next").onclick = () => show("settings");
function renderBracket() {
  $("rounds").replaceChildren();
  current.rounds.forEach((round) => {
    const h = document.createElement("h3");
    h.textContent = round.name;
    $("rounds").append(h);
    round.matches.forEach((m, i) => {
      const a = document.createElement("article");
      const label = document.createElement("p");
      label.textContent =
        "Match " + (i + 1) + (m.status === "complete" ? " · complete" : "");
      a.append(label);
      ["left", "right"].forEach((side, n) => {
        if (n) a.append(document.createTextNode(" versus "));
        const c = m[side];
        const span = document.createElement("span");
        span.textContent = c ? c.name : "Winner of earlier match";
        a.append(span);
        if (c) a.append(hear(c));
      });
      if (m.winner) {
        const p = document.createElement("p");
        p.textContent = "Winner: " + m.winner.name;
        a.append(p);
      }
      $("rounds").append(a);
    });
  });
  $("champion").textContent = current.champion
    ? "Our champion is " + current.champion.name + "! Everyone can rest now."
    : "";
  $("story").hidden = !current.chapter;
}
$("start").onclick = guarded(async () => {
  stopAudio();
  current = await api("/api/tournament", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      creature_ids: selected,
      shuffle: $("shuffle").checked,
      realism: $("realism").value,
      duration: $("duration").value,
    }),
  });
  save();
  renderBracket();
  show("bracket");
});
function openStory() {
  const c = current.chapter;
  if (!c) return;
  $("chapter-title").textContent = c.title;
  $("chapter-text").replaceChildren();
  c.paragraphs.forEach((text) => {
    const p = document.createElement("p");
    p.textContent = text;
    $("chapter-text").append(p);
  });
  $("speak").textContent = "Hear the names";
  show("player");
}
$("story").onclick = openStory;
$("speak").onclick = () => {
  if (current?.chapter)
    say({
      name: current.chapter.participants.map((c) => c.name).join(" and "),
      pronunciation: current.chapter.participants.map(spokenName).join(" and "),
    });
};
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
  stopAudio();
  current = result;
  save();
  renderBracket();
  show("bracket");
  $("message").textContent = ending;
}
$("finish").onclick = guarded(finishChapter);
function playStory() {
  if (!current?.chapter) return;
  if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
    $("message").textContent =
      "Read the story below, then reveal the ending. Speech is unavailable on this device.";
    return;
  }
  stopAudio();
  const token = narrationToken;
  let chunks = [...current.chapter.paragraphs, current.chapter.ending];
  const participants = current.chapter.participants
    .slice()
    .sort((a, b) => b.name.length - a.name.length);
  chunks = chunks.map((t) => {
    for (const c of participants) t = t.split(c.name).join(spokenName(c));
    return t;
  });
  let index = 0;
  function next() {
    if (token !== narrationToken) return;
    if (index === chunks.length) {
      touch();
      guarded(finishChapter)();
      return;
    }
    const u = utterance(chunks[index++], Number($("story-rate").value));
    u.onend = () => {
      touch();
      next();
    };
    u.onerror = (e) => {
      if (
        token === narrationToken &&
        !["canceled", "interrupted"].includes(e.error)
      )
        $("message").textContent =
          "Playback stopped. Try another voice or read along.";
    };
    speechSynthesis.speak(u);
  }
  next();
}
$("play").onclick = () => {
  if (window.speechSynthesis?.paused) {
    speechSynthesis.resume();
    $("pause").textContent = "Pause";
  } else playStory();
};
$("replay").onclick = playStory;
$("pause").onclick = () => {
  if (!window.speechSynthesis) return;
  if (speechSynthesis.paused) {
    speechSynthesis.resume();
    $("pause").textContent = "Pause";
  } else {
    speechSynthesis.pause();
    $("pause").textContent = "Resume";
  }
  touch();
};
$("stop").onclick = () => {
  stopAudio();
  touch();
};
$("home").onclick = () => {
  stopAudio();
  show("categories");
};
$("back").onclick = () => {
  stopAudio();
  show(
    {
      selection: "categories",
      settings: "selection",
      bracket: library.length ? "settings" : "categories",
      player: "bracket",
    }[screen] || "categories",
  );
};
$("resume").onclick = () => show(beforeQuiet);
async function restore() {
  try {
    const config = await api("/api/config");
    $("sample").hidden = !config.sample_data;
    const stored = JSON.parse(
      sessionStorage.getItem("bedtimeTournament") || "null",
    );
    if (stored) {
      current = stored;
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
      renderBracket();
      show("bracket");
    }
  } catch {
    current = null;
    try {
      sessionStorage.removeItem("bedtimeTournament");
    } catch {}
  }
}
restore();
