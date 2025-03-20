chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "extractSelection") {
        const selection = window.getSelection();
        if (selection.rangeCount === 0) {
            sendResponse({ text: "" });
            return;
        }

        const range = selection.getRangeAt(0);
        const container = document.createElement('div');
        container.appendChild(range.cloneContents());

        // Use innerText to preserve new lines and tabs
        const text = container.innerText;
        sendResponse({ text: text });
    }
});
