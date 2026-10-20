// Campo de hora en 24 h para el panel (spec 0004).
//
// Reemplaza al <input type="time"> del navegador, que en una Mac en inglés muestra un selector con
// a.m./p.m. incómodo de usar. Se escribe la hora como se dice ("1015", "9.30", "14") y queda
// "10:15", "09:30", "14:00". Los botones [data-time-chip] dentro de un [data-time-chips="id"] la
// completan con un toque.
(() => {
  const MESSAGE = "Escribí la hora en formato 24 h, por ejemplo 10:15.";
  const VALID = /^([01]?\d|2[0-3]):([0-5]\d)$/;

  const normalize = (raw) => {
    const value = (raw || "").trim().toLowerCase().replace(/\s*(hs?|h)\s*$/, "").replace(/[.,h ]/g, ":");
    if (/^\d{1,2}$/.test(value)) return `${value.padStart(2, "0")}:00`;
    if (/^\d{3,4}$/.test(value)) {
      const digits = value.padStart(4, "0");
      return `${digits.slice(0, 2)}:${digits.slice(2)}`;
    }
    const match = value.match(VALID);
    return match ? `${match[1].padStart(2, "0")}:${match[2]}` : (raw || "").trim();
  };
  const isValid = (value) => VALID.test(value);

  const syncChips = (input) => {
    document.querySelectorAll(`[data-time-chips="${input.id}"] [data-time-chip]`).forEach((chip) => {
      const selected = chip.dataset.timeChip === normalize(input.value);
      chip.classList.toggle("is-active", selected);
      chip.setAttribute("aria-pressed", String(selected));
    });
  };

  const commit = (input) => {
    if (input.value) input.value = normalize(input.value);
    input.setCustomValidity(!input.value || isValid(input.value) ? "" : MESSAGE);
    syncChips(input);
  };

  document.addEventListener("input", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || !input.matches("[data-time-24h]")) return;
    input.setCustomValidity("");
    syncChips(input);
  });
  document.addEventListener(
    "blur",
    (event) => {
      const input = event.target;
      if (input instanceof HTMLInputElement && input.matches("[data-time-24h]")) {
        commit(input);
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    },
    true
  );
  // Antes de enviar, "1015" pasa a "10:15" y una hora imposible frena el envío con el mensaje.
  document.addEventListener(
    "submit",
    (event) => {
      event.target.querySelectorAll?.("[data-time-24h]").forEach((input) => {
        commit(input);
        if (!input.checkValidity()) {
          event.preventDefault();
          input.reportValidity();
        }
      });
    },
    true
  );
  document.addEventListener("click", (event) => {
    const chip = event.target.closest?.("[data-time-chip]");
    if (!chip) return;
    const input = document.getElementById(chip.closest("[data-time-chips]")?.dataset.timeChips || "");
    if (!input) return;
    input.value = chip.dataset.timeChip;
    input.setCustomValidity("");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

  window.oralTime = { normalize, isValid, syncChips };
})();
