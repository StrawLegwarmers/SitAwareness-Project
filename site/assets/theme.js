// Set light/dark before the page draws, so it doesn't flash the wrong colours.
// (Its own file rather than inline, so the page's security policy can forbid all inline scripts.)
try { const t = localStorage.getItem("sap-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
