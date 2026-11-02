// Applies the stored/system theme before first paint (no flash). External file so the CSP can forbid inline scripts.
try {
  var t = localStorage.getItem("vand-theme");
  if (!t) t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = t;
} catch (e) { document.documentElement.dataset.theme = "light"; }
