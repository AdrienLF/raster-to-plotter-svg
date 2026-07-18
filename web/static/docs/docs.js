(function () {
  "use strict";

  const pages = [
    { href: "index.html", title: "Start here", section: "Start", summary: "Orientation, first plot, projects and exporting.", keywords: "home onboarding install first plot" },
    { href: "tutorials.html", title: "Flagship tutorials", section: "Start", summary: "Three complete workflows with exact settings and checkpoints.", keywords: "tutorial walkthrough sample recipe" },
    { href: "choose-a-style.html", title: "Choose a style", section: "Create", summary: "Pick a PFM by subject, pen, time and visual goal.", keywords: "compare recommend portrait marker tsp" },
    { href: "create.html", title: "Creating strokes", section: "Create", summary: "Path finding, regions, Shape Dither and generators.", keywords: "pfm algorithms image generate region" },
    { href: "reference.html", title: "PFM reference", section: "Create", summary: "All built-in styles and their complete parameter schemas.", keywords: "parameters defaults ranges catalog" },
    { href: "compose.html", title: "Composing the page", section: "Compose", summary: "Raster and vector layers, transforms, masks and occlusion.", keywords: "layers rotate fit fill crop mask" },
    { href: "fields.html", title: "Painting with Fields", section: "Compose", summary: "Drive parameters with tone, gradients, noise and painted masks.", keywords: "bindings engraving direction paint" },
    { href: "plot.html", title: "Pens, paper & plotting", section: "Plot", summary: "Drawing sets, machine setup, estimates and resumable jobs.", keywords: "plotter pen paper serial speed resume" },
    { href: "troubleshooting.html", title: "Troubleshooting", section: "Plot", summary: "Symptom-led recovery, calibration and safe diagnostics.", keywords: "error slow empty sam gpu serial jam" },
    { href: "tessellations.html", title: "Cavalry tessellations", section: "Extend", summary: "Bake reusable tone-responsive patterns in Cavalry.", keywords: "bridge bake lattice custom" },
    { href: "whats-new.html", title: "What’s new", section: "Extend", summary: "Recent workflow changes and compatibility notes.", keywords: "release changes migration exif raster shape dither" },
  ];
  window.PLOTTER_DOCS_PAGES = pages;

  function node(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text) item.textContent = text;
    return item;
  }

  function currentFile() {
    const file = window.location.pathname.split("/").pop();
    return file || "index.html";
  }

  function slug(text) {
    return text.toLowerCase().trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "section";
  }

  function buildSidebar(activeFile) {
    const main = document.querySelector("main");
    const aside = node("aside", "docs-sidebar");
    aside.id = "docs-navigation";
    const nav = node("nav", "docs-nav");
    nav.setAttribute("aria-label", "Manual");
    let section = "";
    for (const page of pages) {
      if (page.section !== section) {
        section = page.section;
        nav.appendChild(node("div", "docs-nav-section", section));
      }
      const link = node("a", "docs-nav-link");
      link.href = page.href;
      link.textContent = page.title;
      if (page.href === activeFile) link.setAttribute("aria-current", "page");
      nav.appendChild(link);
    }
    aside.appendChild(nav);

    // The generated reference has 50 entry headings; keep its local navigation
    // useful by listing families rather than turning the sidebar into a catalog.
    const tocSelector = main.classList.contains("reference-page") ? "main h2" : "main h2, main h3";
    const headings = Array.from(document.querySelectorAll(tocSelector));
    if (headings.length) {
      const toc = node("nav", "docs-toc");
      toc.setAttribute("aria-label", "On this page");
      toc.appendChild(node("div", "docs-nav-section", "On this page"));
      for (const heading of headings) {
        if (!heading.id) heading.id = slug(heading.textContent || "section");
        const link = node("a", heading.tagName === "H3" ? "toc-h3" : "toc-h2");
        link.href = `#${heading.id}`;
        link.textContent = heading.textContent;
        toc.appendChild(link);
      }
      aside.appendChild(toc);
    }
    return aside;
  }

  function buildSearch() {
    const dialog = node("dialog", "docs-search-dialog");
    dialog.setAttribute("aria-label", "Search the manual");
    const form = node("form", "docs-search-box");
    form.method = "dialog";
    const input = node("input", "docs-search-input");
    input.type = "search";
    input.placeholder = "Search workflows, tools, errors…";
    input.setAttribute("aria-label", "Search documentation");
    const close = node("button", "docs-search-close", "Close");
    close.value = "cancel";
    const results = node("div", "docs-search-results");
    results.setAttribute("aria-live", "polite");
    form.append(input, close, results);
    dialog.appendChild(form);

    function render(query) {
      const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
      const matches = pages.filter((page) => {
        const haystack = `${page.title} ${page.summary} ${page.keywords}`.toLowerCase();
        return terms.every((term) => haystack.includes(term));
      });
      results.replaceChildren();
      if (!matches.length) {
        results.appendChild(node("p", "docs-search-empty", "No matching page. Try a tool name or symptom."));
        return;
      }
      for (const page of matches) {
        const link = node("a", "docs-search-result");
        link.href = page.href;
        link.append(node("strong", "", page.title), node("span", "", page.summary));
        results.appendChild(link);
      }
    }
    input.addEventListener("input", () => render(input.value));
    render("");
    return { dialog, input };
  }

  function addPager(main, activeFile) {
    const index = pages.findIndex((page) => page.href === activeFile);
    if (index < 0) return;
    const pager = node("nav", "docs-pager");
    pager.setAttribute("aria-label", "Manual pages");
    if (index > 0) {
      const previous = node("a", "docs-pager-link");
      previous.href = pages[index - 1].href;
      previous.innerHTML = `<span>Previous</span><strong>← ${pages[index - 1].title}</strong>`;
      pager.appendChild(previous);
    }
    if (index < pages.length - 1) {
      const next = node("a", "docs-pager-link docs-pager-next");
      next.href = pages[index + 1].href;
      next.innerHTML = `<span>Next</span><strong>${pages[index + 1].title} →</strong>`;
      pager.appendChild(next);
    }
    main.appendChild(pager);
  }

  document.addEventListener("DOMContentLoaded", () => {
    const main = document.querySelector("main");
    if (!main) return;
    document.body.classList.add("docs-enhanced");
    main.id = main.id || "main-content";

    const skip = node("a", "skip-link", "Skip to content");
    skip.href = `#${main.id}`;
    document.body.prepend(skip);

    const activeFile = currentFile();
    const topbar = node("header", "docs-topbar");
    const menu = node("button", "docs-menu-button", "Contents");
    menu.type = "button";
    menu.setAttribute("aria-controls", "docs-navigation");
    menu.setAttribute("aria-expanded", "false");
    const brand = node("a", "docs-brand", "✦ PlotterForge Manual");
    brand.href = "index.html";
    const actions = node("div", "docs-topbar-actions");
    const version = node("span", "docs-version", "July 2026");
    const searchOpen = node("button", "docs-search-open");
    searchOpen.type = "button";
    searchOpen.innerHTML = "Search <kbd>/</kbd>";
    actions.append(version, searchOpen);
    topbar.append(menu, brand, actions);

    const shell = node("div", "docs-shell");
    main.parentNode.insertBefore(topbar, main);
    main.parentNode.insertBefore(shell, main);
    const sidebar = buildSidebar(activeFile);
    shell.append(sidebar, main);
    addPager(main, activeFile);

    const { dialog, input } = buildSearch();
    document.body.appendChild(dialog);
    function openSearch() {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      input.focus();
    }
    searchOpen.addEventListener("click", openSearch);
    menu.addEventListener("click", () => {
      const open = document.body.classList.toggle("docs-nav-open");
      menu.setAttribute("aria-expanded", String(open));
      if (open) sidebar.querySelector("a").focus();
    });
    document.addEventListener("keydown", (event) => {
      const editing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "");
      if (event.key === "/" && !editing) {
        event.preventDefault();
        openSearch();
      }
      if (event.key === "Escape") {
        document.body.classList.remove("docs-nav-open");
        menu.setAttribute("aria-expanded", "false");
      }
    });
  });
})();
