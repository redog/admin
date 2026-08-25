const ASTERISM = "⁂";
const SLASH_S = /\/s(?=\s|[.,;:!?\-)\]}>'"’”]|$)/g;

let enabled = true;

chrome.storage.sync.get({ enabled: true }, (data) => {
  enabled = data.enabled;
  if (enabled) processPage();
});

chrome.storage.onChanged.addListener((changes) => {
  if (changes.enabled) {
    enabled = changes.enabled.newValue;
    if (enabled) processPage();
  }
});

function processPage() {
  if (!enabled) return;
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        const tag = node.parentElement?.tagName;
        if (tag === "SCRIPT" || tag === "STYLE" || tag === "TEXTAREA" || tag === "INPUT" || tag === "CODE" || tag === "PRE") {
          return NodeFilter.FILTER_REJECT;
        }
        if (node.parentElement?.isContentEditable) {
          return NodeFilter.FILTER_REJECT;
        }
        return SLASH_S.test(node.textContent)
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT;
      },
    }
  );

  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);

  for (const node of nodes) {
    SLASH_S.lastIndex = 0;
    node.textContent = node.textContent.replace(SLASH_S, ASTERISM);
  }
}

const observer = new MutationObserver((mutations) => {
  if (!enabled) return;
  for (const mutation of mutations) {
    for (const added of mutation.addedNodes) {
      if (added.nodeType === Node.TEXT_NODE) {
        SLASH_S.lastIndex = 0;
        if (SLASH_S.test(added.textContent)) {
          const tag = added.parentElement?.tagName;
          if (tag !== "SCRIPT" && tag !== "STYLE" && tag !== "TEXTAREA" && tag !== "INPUT" && tag !== "CODE" && tag !== "PRE" && !added.parentElement?.isContentEditable) {
            SLASH_S.lastIndex = 0;
            added.textContent = added.textContent.replace(SLASH_S, ASTERISM);
          }
        }
      } else if (added.nodeType === Node.ELEMENT_NODE) {
        processSubtree(added);
      }
    }
  }
});

function processSubtree(root) {
  if (!enabled) return;
  const tag = root.tagName;
  if (tag === "SCRIPT" || tag === "STYLE" || tag === "TEXTAREA" || tag === "INPUT" || tag === "CODE" || tag === "PRE") return;
  if (root.isContentEditable) return;

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const t = node.parentElement?.tagName;
      if (t === "SCRIPT" || t === "STYLE" || t === "TEXTAREA" || t === "INPUT" || t === "CODE" || t === "PRE") {
        return NodeFilter.FILTER_REJECT;
      }
      if (node.parentElement?.isContentEditable) return NodeFilter.FILTER_REJECT;
      return SLASH_S.test(node.textContent)
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT;
    },
  });

  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    SLASH_S.lastIndex = 0;
    node.textContent = node.textContent.replace(SLASH_S, ASTERISM);
  }
}

observer.observe(document.body, { childList: true, subtree: true });
