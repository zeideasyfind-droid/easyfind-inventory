const publishForm = document.getElementById("publish-form");
const ownerMessageInput = document.getElementById("owner-message");
const dropzone = document.getElementById("dropzone");
const imageInput = document.getElementById("image-input");
const imageList = document.getElementById("image-list");
const mediaPreview = document.getElementById("media-preview");
const previewBtn = document.getElementById("preview-btn");
const sendBar = document.getElementById("send-bar");
const sendBtn = document.getElementById("send-btn");
const editBtn = document.getElementById("edit-btn");
const publishState = document.getElementById("publish-state");
const previewPanel = document.getElementById("preview-panel");
const previewText = document.getElementById("preview-text");
const previewMeta = document.getElementById("preview-meta");
const publishResult = document.getElementById("publish-result");
const statusBanner = document.getElementById("whatsapp-status-banner");

const DEFAULT_PREVIEW_TEXT = "Fill in the owner message and click Generate Preview to see the formatted listing here.";

let selectedFiles = [];

// ---------------------------------------------------------------------------
// Configuration status banner — fetched once on page load.
// Tells the operator immediately whether WhatsApp secrets are in place so
// 'WhatsApp Cloud API is not configured.' is never a surprise at send time.
// ---------------------------------------------------------------------------
async function loadWhatsAppStatus() {
  if (!statusBanner) return;
  try {
    const res = await fetch("/publish/status");
    if (!res.ok) { statusBanner.classList.add("hidden"); return; }
    const data = await res.json();

    if (data.configured) {
      statusBanner.textContent = "\u2705 WhatsApp configured";
      statusBanner.className = "wa-status-banner wa-status-ok";
    } else {
      const missing = [];
      if (!data.access_token.present)    missing.push("WHATSAPP_ACCESS_TOKEN");
      if (!data.phone_number_id.present) missing.push("WHATSAPP_PHONE_NUMBER_ID");
      if (!data.recipient_number.present) missing.push("WHATSAPP_RECIPIENT_NUMBER");
      statusBanner.textContent =
        "\u274c WhatsApp Cloud API is not configured \u2014 missing in Secrets: " + missing.join(", ");
      statusBanner.className = "wa-status-banner wa-status-error";
    }
  } catch (_) {
    statusBanner.classList.add("hidden");
  }
}

document.addEventListener("DOMContentLoaded", loadWhatsAppStatus);

// ---------------------------------------------------------------------------
// Media file handling
// ---------------------------------------------------------------------------
function renderImageList() {
  imageList.innerHTML = "";
  selectedFiles.forEach((file, index) => {
    const item = document.createElement("span");
    item.className = "image-chip";
    item.textContent = file.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "\u00d7";
    remove.addEventListener("click", () => {
      selectedFiles.splice(index, 1);
      renderImageList();
    });
    item.appendChild(remove);
    imageList.appendChild(item);
  });
  renderMediaPreview();
}

// Purely visual thumbnail strip in the live-preview column -- mirrors the
// upload order shown in the chip list above, but never touches what gets
// submitted (buildFormData still reads straight from selectedFiles).
function renderMediaPreview() {
  mediaPreview.querySelectorAll("img,video").forEach((el) => URL.revokeObjectURL(el.src));
  mediaPreview.innerHTML = "";
  selectedFiles.forEach((file) => {
    const url = URL.createObjectURL(file);
    const el = document.createElement(file.type.startsWith("video/") ? "video" : "img");
    el.src = url;
    el.className = "media-thumb";
    if (el.tagName === "VIDEO") {
      el.muted = true;
    }
    mediaPreview.appendChild(el);
  });
}

function addFiles(fileList) {
  // Preserve original order (11_WHATSAPP_DELIVERY_ENGINE.md).
  Array.from(fileList).forEach((file) => selectedFiles.push(file));
  renderImageList();
}

dropzone.addEventListener("click", () => imageInput.click());
imageInput.addEventListener("change", () => {
  addFiles(imageInput.files);
  imageInput.value = "";
});

["dragenter", "dragover"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
  });
});

dropzone.addEventListener("drop", (event) => {
  if (event.dataTransfer && event.dataTransfer.files) {
    addFiles(event.dataTransfer.files);
  }
});

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------
function showPublishState(message, kind) {
  publishState.textContent = message;
  publishState.className = `publish-state${kind ? " " + kind : ""}`;
  publishState.classList.toggle("hidden", !message);
}

function showResult(message, kind) {
  publishResult.textContent = message;
  publishResult.className = `publish-state${kind ? " " + kind : ""}`;
  publishResult.classList.toggle("hidden", !message);
}

function buildFormData() {
  const formData = new FormData();
  formData.append("owner_message", ownerMessageInput.value);
  selectedFiles.forEach((file) => formData.append("images", file));
  return formData;
}

// ---------------------------------------------------------------------------
// Preview
// ---------------------------------------------------------------------------
publishForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showResult("");

  if (!ownerMessageInput.value.trim()) {
    showPublishState("Please paste the owner message.", "error");
    return;
  }
  if (selectedFiles.length === 0) {
    showPublishState("Please add at least one photo.", "error");
    return;
  }

  previewBtn.disabled = true;
  showPublishState("Parsing message and enriching with Google Maps\u2026", "loading");
  sendBar.classList.add("hidden");

  try {
    const response = await fetch("/publish/preview", {
      method: "POST",
      body: buildFormData(),
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || "Could not generate a preview for this listing.");
    }

    previewText.textContent = data.preview;
    const locationLabel = data.society || data.landmark || "not identified";
    previewMeta.textContent = `Community: ${data.community} \u2014 ${locationLabel}`;
    sendBar.classList.remove("hidden");
    showPublishState("");
  } catch (err) {
    showPublishState(err.message, "error");
  } finally {
    previewBtn.disabled = false;
  }
});

editBtn.addEventListener("click", () => {
  sendBar.classList.add("hidden");
  previewText.textContent = DEFAULT_PREVIEW_TEXT;
  previewMeta.textContent = "";
  showResult("");
});

// ---------------------------------------------------------------------------
// Send
// ---------------------------------------------------------------------------
sendBtn.addEventListener("click", async () => {
  sendBtn.disabled = true;
  showResult("Sending media album to WhatsApp\u2026", "loading");

  try {
    const response = await fetch("/publish/send", {
      method: "POST",
      body: buildFormData(),
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || "Could not send this listing to WhatsApp.");
    }

    if (data.success) {
      showResult(
        `Sent ${data.image_count} file${data.image_count === 1 ? "" : "s"} to WhatsApp` +
        ` (message ${data.message_id}${data.request_id ? ", req " + data.request_id : ""}).`,
        "success"
      );
      selectedFiles = [];
      renderImageList();
      ownerMessageInput.value = "";
      sendBar.classList.add("hidden");
      previewText.textContent = DEFAULT_PREVIEW_TEXT;
      previewMeta.textContent = "";
    } else {
      showResult(
        `WhatsApp delivery failed: ${data.error || "unknown error"}` +
        `${data.request_id ? " [req " + data.request_id + "]" : ""}` +
        ". The listing text above is unchanged \u2014 you can copy it manually or retry.",
        "error"
      );
    }
  } catch (err) {
    showResult(err.message, "error");
  } finally {
    sendBtn.disabled = false;
  }
});
