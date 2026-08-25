const toggle = document.getElementById("toggle");

chrome.storage.sync.get({ enabled: true }, (data) => {
  toggle.checked = data.enabled;
});

toggle.addEventListener("change", () => {
  chrome.storage.sync.set({ enabled: toggle.checked });
});
