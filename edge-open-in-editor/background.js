chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.create({
        id: "openInEditor",
        title: "Open in Editor",
        contexts: ["all"]
    });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === "openInEditor") {
        chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files: ['content.js']
        }, () => {
            chrome.tabs.sendMessage(tab.id, { action: "extractSelection" }, (response) => {
                if (chrome.runtime.lastError) {
                    chrome.notifications.create({
                        type: 'basic',
                        iconUrl: 'icon.png',
                        title: 'Editor Interaction Error',
                        message: chrome.runtime.lastError.message
                    });
                    return;
                }

                const selectedText = response.text;
                chrome.runtime.sendNativeMessage(
                    "com.automationwise.openineditor",
                    { text: selectedText },
                    (nativeResponse) => {
                        if (chrome.runtime.lastError) {
                            chrome.notifications.create({
                                type: 'basic',
                                iconUrl: 'icon.png',
                                title: 'Editor Interaction Error',
                                message: chrome.runtime.lastError.message
                            });
                        } else {
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

