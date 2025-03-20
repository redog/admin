chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.create({
        id: "openInEditor",
        title: "Open in Editor",
        contexts: ["all"] // Changed from "selection" to "all"
    });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === "openInEditor") {
        // Inject content script if not already present
        chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files: ['content.js']
        }, () => {
            // After ensuring content script is injected, send a message to extract selection
            chrome.tabs.sendMessage(tab.id, { action: "extractSelection" }, (response) => {
                if (chrome.runtime.lastError) {
                    console.error("Error sending message:", chrome.runtime.lastError.message);
                    chrome.notifications.create({
                        type: 'basic',
                        iconUrl: 'icon.png',
                        title: 'Editor Interaction Error',
                        message: chrome.runtime.lastError.message
                    });
                    return;
                }

                const selectedText = response.text;
                console.log("Extracted Selected Text:", JSON.stringify(selectedText));
                
                // Send the extracted text to the native Python application
                chrome.runtime.sendNativeMessage(
                    "com.automationwise.openineditor",
                    { text: selectedText },
                    (nativeResponse) => {
                        if (chrome.runtime.lastError) {
                            console.error("Error sending message:", chrome.runtime.lastError.message);
                            chrome.notifications.create({
                                type: 'basic',
                                iconUrl: 'icon.png',
                                title: 'Editor Interaction Error',
                                message: chrome.runtime.lastError.message
                            });
                        } else {
                            console.log("Response from native app:", nativeResponse);
                            chrome.notifications.create({
                                type: 'basic',
                                iconUrl: 'icon.png',
                                title: 'Editor Interaction',
                                message: nativeResponse.result
                            });
                        }
                    }
                );
            });
        });
    }
});
