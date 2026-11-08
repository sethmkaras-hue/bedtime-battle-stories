"use strict";
window.BedtimeSettings = (() => {
  const defaults = {
    narrationProvider: "kokoro",
    pronunciationProvider: "piper",
    narrationVoice: "af_heart",
    pronunciationVoice: "en_US-lessac-medium",
    narrationRate: 0.95,
    nameRate: 0.8,
    autoNarration: false,
    pronunciationButtons: true,
    guidedNames: true,
    duration: "normal",
    realism: "balanced",
    shuffle: false,
    timeoutEnabled: true,
    idleMinutes: 5,
    reducedMotion: false,
  };
  const enums = {
    narrationProvider: ["kokoro", "piper", "openai", "browser"],
    pronunciationProvider: ["kokoro", "piper", "openai", "browser"],
    duration: ["short", "normal", "long"],
    realism: ["realistic", "balanced", "anything"],
    idleMinutes: [2, 5, 10, 15],
    narrationRate: [0.8, 0.95, 1, 1.15],
    nameRate: [0.65, 0.8, 1],
  };
  let value = { ...defaults };
  try {
    const saved = JSON.parse(localStorage.getItem("bedtimeSettings") || "{}");
    for (const k of Object.keys(defaults)) {
      const v = saved[k];
      if (
        enums[k]?.includes(v) ||
        (!enums[k] &&
          typeof v === typeof defaults[k] &&
          (typeof v !== "string" || v.length < 150))
      )
        value[k] = v;
    }
  } catch {}
  function save() {
    try {
      localStorage.setItem("bedtimeSettings", JSON.stringify(value));
    } catch {}
    document.body.classList.toggle("reduced-motion", value.reducedMotion);
    document.body.classList.toggle(
      "hide-pronunciation",
      !value.pronunciationButtons,
    );
  }
  function set(key, v) {
    if (!(key in defaults)) return;
    if (enums[key] && !enums[key].includes(v)) return;
    value[key] = v;
    save();
  }
  save();
  return { get: () => ({ ...value }), set, defaults };
})();
