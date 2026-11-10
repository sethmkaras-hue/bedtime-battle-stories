"use strict";
(() => {
  document.getElementById("refresh-import-coverage").onclick = async () => {
    const target = document.getElementById("image-import-coverage");
    try {
      const response = await fetch("/api/library/image-coverage");
      if (!response.ok) throw Error("Image coverage is unavailable");
      const data = await response.json();
      target.textContent = `${data.internet_images} Internet images · ${data.images_retained} preserved images · ${data.placeholders_remaining} placeholders · ${data.total} creatures`;
      await window.refreshCreatureLibrary?.();
    } catch (error) { target.textContent = error.message; }
  };
})();
