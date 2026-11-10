"use strict";
(() => {
  const el = (id) => document.getElementById(id);
  async function refresh() {
    const [response, creatures] = await Promise.all([
      fetch("/api/creature-images/status"),
      fetch("/api/creatures"),
    ]);
    const data = await response.json();
    if (!response.ok) throw Error("Image status is unavailable");
    el("image-generation-status").textContent =
      `${data.generated} / ${data.total} generated · ${data.remaining} remaining · ${data.failed} failed attempts. Model: ${data.settings?.model || data.model_configuration?.model || "not installed"}. Storage: ${data.settings?.output_dir || data.output_dir}. ${data.setup_error || ""}`;
    const running = data.jobs.find((job) => job.status === "generating");
    const failure = data.jobs.find((job) => job.status === "failed");
    if (running)
      el("image-generation-status").textContent +=
        ` Generating ${running.name}, step ${running.step}.`;
    if (failure)
      el("image-generation-status").textContent +=
        ` Latest failure: ${failure.name}: ${failure.error}`;
    const selected = el("generated-image-creature").value;
    el("generated-image-creature").replaceChildren(
      ...(await creatures.json()).map((c) => new Option(c.name, c.id)),
    );
    if (selected) el("generated-image-creature").value = selected;
  }
  el("refresh-images").onclick = () =>
    refresh()
      .then(() => window.refreshCreatureLibrary?.())
      .catch(
        (error) => (el("image-generation-message").textContent = error.message),
      );
  el("view-image-metadata").onclick = async () => {
    try {
      const data = await (
        await fetch(
          "/api/creature-images/metadata/" +
            el("generated-image-creature").value,
        )
      ).json();
      el("image-generation-metadata").textContent = JSON.stringify(
        data,
        null,
        2,
      );
    } catch (error) {
      el("image-generation-message").textContent = error.message;
    }
  };
  el("regenerate-creature-image").onclick = async () => {
    const button = el("regenerate-creature-image");
    button.disabled = true;
    try {
      const session = await (await fetch("/api/admin/session")).json();
      if (!session.unlocked)
        throw Error(
          "Unlock parent controls using Parent content review, then return here. This does not approve individual images.",
        );
      const response = await fetch("/api/admin/creature-images/regenerate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Parent-CSRF": session.csrf,
        },
        body: JSON.stringify({
          creature_id: Number(el("generated-image-creature").value),
        }),
      });
      const data = await response.json();
      if (!response.ok)
        throw Error(
          typeof data.detail === "string"
            ? data.detail
            : "Generation could not be queued",
        );
      el("image-generation-message").textContent = data.message;
      await refresh();
    } catch (error) {
      el("image-generation-message").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
  el("image-management").addEventListener("toggle", () => {
    if (el("image-management").open)
      refresh().catch(
        (error) => (el("image-generation-message").textContent = error.message),
      );
  });
})();
