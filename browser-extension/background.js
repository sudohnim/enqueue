// The right-click menu: save a page, a link, the picked words or a picture.
if (typeof importScripts === "function") importScripts("enqueue.js");

const MENUS = [
  ["page", "Save page to Enqueue", ["page"]],
  ["link", "Save link to Enqueue", ["link"]],
  ["words", "Save selection to Enqueue", ["selection"]],
  ["picture", "Save picture to Enqueue", ["image"]],
];

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    for (const [id, title, contexts] of MENUS) chrome.contextMenus.create({ id, title, contexts });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if (info.menuItemId === "page") await saveLink(tab.url, tab.title);
    else if (info.menuItemId === "link") await saveLink(info.linkUrl, null);
    else if (info.menuItemId === "words") await saveWords(info.selectionText, tab.url, tab.title);
    else if (info.menuItemId === "picture") await savePicture(info.srcUrl, tab.url);
    badge(tab.id, "✓", "#2f7d4f");
  } catch (err) {
    badge(tab.id, "!", "#a3271f");
    console.warn("Enqueue:", err.message);
  }
});

function badge(tabId, text, color) {
  chrome.action.setBadgeBackgroundColor({ tabId, color });
  chrome.action.setBadgeText({ tabId, text });
  setTimeout(() => chrome.action.setBadgeText({ tabId, text: "" }), 2500);
}
