const form = document.getElementById("extract-form");
const urlInput = document.getElementById("url");
const extractBtn = document.getElementById("extract-btn");

const states = {
  loading: document.getElementById("loading"),
  success: document.getElementById("success"),
  duplicate: document.getElementById("duplicate"),
  error: document.getElementById("error"),
};

function showState(name) {
  Object.values(states).forEach((el) => el.classList.add("hidden"));
  if (name && states[name]) {
    states[name].classList.remove("hidden");
  }
  form.classList.toggle("hidden", Boolean(name));
}

function resetForm() {
  showState(null);
  urlInput.value = "";
  urlInput.focus();
}

document.getElementById("reset-success").addEventListener("click", resetForm);
document.getElementById("reset-duplicate").addEventListener("click", resetForm);
document.getElementById("reset-error").addEventListener("click", resetForm);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;

  extractBtn.disabled = true;
  showState("loading");

  try {
    const response = await fetch("/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || "Something went wrong while extracting this listing.");
    }

    if (data.status === "duplicate") {
      document.getElementById("duplicate-details").textContent =
        data.message || "This property already exists in the inventory.";
      showState("duplicate");
    } else if (data.status === "success") {
      document.getElementById("success-details").textContent =
        `Property ${data.property_id} saved to row ${data.sheet_row} in Google Sheets.`;
      showState("success");
    } else {
      throw new Error("Unexpected response from the server.");
    }
  } catch (err) {
    document.getElementById("error-details").textContent = err.message;
    showState("error");
  } finally {
    extractBtn.disabled = false;
  }
});
