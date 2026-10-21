// Buscador de pacientes para los formularios de turno (spec 0009).
//
// Cada [data-patient-picker] tiene un campo de búsqueda, un input oculto patient_id y, si permite
// pacientes nuevos, un panel [data-new-patient] con sus propios campos. Marca data-ready="1" cuando hay
// un paciente elegido (o los datos mínimos del nuevo) y avisa con el evento "patientchange".
(() => {
  const SEARCH_URL = "/api/v1/patients/search";

  document.querySelectorAll("[data-patient-picker]").forEach((picker) => {
    const search = picker.querySelector("[data-picker-search]");
    const hidden = picker.querySelector("input[name=patient_id]");
    const results = picker.querySelector("[data-picker-results]");
    const chosen = picker.querySelector("[data-picker-chosen]");
    const chosenName = picker.querySelector("[data-picker-chosen-name]");
    const searchBox = picker.querySelector("[data-picker-searchbox]");
    const newPanel = picker.querySelector("[data-new-patient]");
    const newToggle = picker.querySelector("[data-new-patient-toggle]");
    const message = picker.querySelector("[data-picker-message]");
    if (!search || !hidden || !results || !chosen || !searchBox) return;

    let timer = null;
    let latest = 0;

    const newFields = () => (newPanel ? [...newPanel.querySelectorAll("input")] : []);
    // DNI, nombre y apellido son obligatorios; celular y email no (se toman por nombre, no por orden).
    const requiredNew = () => ["new_dni", "new_first_name", "new_last_name"].map((name) => newPanel.querySelector(`[name=${name}]`));
    const newOpen = () => Boolean(newPanel && !newPanel.hidden);
    const isReady = () => {
      if (hidden.value) return true;
      if (!newOpen()) return false;
      return requiredNew().every((input) => input.value.trim());
    };
    const notify = () => {
      picker.dataset.ready = isReady() ? "1" : "0";
      picker.dispatchEvent(new CustomEvent("patientchange", { bubbles: true }));
    };
    const say = (text) => {
      if (message) {
        message.textContent = text || "";
        message.hidden = !text;
      }
    };
    const clearResults = () => {
      results.innerHTML = "";
      results.hidden = true;
    };

    const choose = (patient) => {
      hidden.value = patient.id;
      chosenName.textContent = `${patient.label} · DNI ${patient.dni}`;
      chosen.hidden = false;
      searchBox.hidden = true;
      clearResults();
      say("");
      notify();
    };
    const change = () => {
      hidden.value = "";
      chosen.hidden = true;
      searchBox.hidden = false;
      search.value = "";
      search.focus();
      notify();
    };

    const render = (patients, typed) => {
      results.innerHTML = "";
      if (!patients.length) {
        const empty = document.createElement("p");
        empty.className = "picker-empty";
        empty.textContent = newPanel ? `No encontramos a "${typed}". Podés cargarlo como paciente nuevo.` : `No encontramos a "${typed}".`;
        results.appendChild(empty);
      }
      patients.forEach((patient) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "picker-option";
        option.setAttribute("role", "option");
        const name = document.createElement("strong");
        name.textContent = patient.label;
        const detail = document.createElement("span");
        detail.textContent = `DNI ${patient.dni}${patient.contact ? ` · ${patient.contact}` : ""}`;
        option.append(name, detail);
        option.addEventListener("click", () => choose(patient));
        results.appendChild(option);
      });
      results.hidden = false;
    };

    search.addEventListener("input", () => {
      clearTimeout(timer);
      const typed = search.value.trim();
      if (typed.length < 2) {
        clearResults();
        return;
      }
      timer = setTimeout(async () => {
        const ticket = ++latest;
        try {
          const response = await fetch(`${SEARCH_URL}?q=${encodeURIComponent(typed)}`, { headers: { Accept: "application/json" } });
          if (!response.ok) throw new Error("search");
          const patients = await response.json();
          if (ticket === latest) render(patients, typed);
        } catch (error) {
          say("No pudimos buscar. Reintentá en unos segundos.");
        }
      }, 200);
    });
    chosen.querySelector("[data-picker-change]")?.addEventListener("click", change);

    if (newPanel && newToggle) {
      newToggle.addEventListener("click", () => {
        const open = newPanel.hidden;
        newPanel.hidden = !open;
        newToggle.textContent = open ? "Volver a buscar" : "+ Paciente nuevo";
        searchBox.hidden = open || Boolean(hidden.value);
        if (open) {
          hidden.value = "";
          chosen.hidden = true;
          clearResults();
        }
        requiredNew().forEach((input) => (input.required = open));
        if (open) newFields()[0].focus();
        notify();
      });
      newFields().forEach((input) => input.addEventListener("input", notify));
    }

    // El formulario no sale sin paciente: lo dice acá en lugar de dejar que el servidor lo rechace.
    picker.closest("form")?.addEventListener("submit", (event) => {
      if (!isReady()) {
        event.preventDefault();
        say("Elegí un paciente o cargá uno nuevo.");
        (newOpen() ? newFields()[0] : search).focus();
      }
    });
    notify();
  });
})();
