const form = document.getElementById("render-form");
const submitBtn = document.getElementById("submit-btn");
const progressContainer = document.getElementById("progress-container");
const progressBarInner = document.getElementById("progress-bar-inner");
const progressMessage = document.getElementById("progress-message");
const resultContainer = document.getElementById("result-container");

function buildPayload() {
  const data = new FormData(form);
  return {
    lat: data.get("lat"),
    lon: data.get("lon"),
    label: data.get("label"),
    galton: form.galton.checked,
    cmap: data.get("cmap"),
    max_hours: data.get("max_hours"),
    dpi: data.get("dpi"),
    paper: data.get("paper"),
    title: form.title.checked,
  };
}

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/render`;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  resultContainer.innerHTML = "";
  progressContainer.hidden = false;
  progressBarInner.style.width = "0%";
  progressMessage.textContent = "Connecting to server ...";

  const socket = new WebSocket(wsUrl());

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify(buildPayload()));
  });

  socket.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "progress") {
      progressBarInner.style.width = `${msg.percent}%`;
      progressMessage.textContent = msg.message;
    } else if (msg.type === "done") {
      progressBarInner.style.width = "100%";
      progressMessage.textContent = "Done.";
      const img = document.createElement("img");
      img.src = `data:image/png;base64,${msg.image_base64}`;
      img.alt = msg.filename;
      resultContainer.appendChild(img);
      submitBtn.disabled = false;
    } else if (msg.type === "error") {
      const p = document.createElement("p");
      p.className = "error";
      p.textContent = `Error: ${msg.message}`;
      resultContainer.appendChild(p);
      submitBtn.disabled = false;
    }
  });

  socket.addEventListener("close", () => {
    submitBtn.disabled = false;
  });

  socket.addEventListener("error", () => {
    progressMessage.textContent = "Connection error.";
    submitBtn.disabled = false;
  });
});
