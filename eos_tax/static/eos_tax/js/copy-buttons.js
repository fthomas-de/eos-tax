/* The copy buttons (.eos-tax-copy) of every page that has them.
 *
 * Loaded after bundles/clipboard-js.html. One file rather than a copy per
 * page: the icon swap below once had to be fixed, and a second copy would
 * have kept the fault.
 */
document.addEventListener("DOMContentLoaded", function () {
    /* global ClipboardJS */
    "use strict";

    // a selector makes Clipboard.js delegate from the document, so the
    // buttons DataTables renders on later pages are covered too
    const clipboard = new ClipboardJS(".eos-tax-copy");

    clipboard.on("success", function (event) {
        event.clearSelection();

        // the icon is the only acknowledgement that fits without
        // pushing the row around
        const icon = event.trigger.querySelector("i");

        // Font Awesome Free has no regular check, only a solid one, so
        // the style swaps with the glyph - fa-regular fa-check has no
        // drawing behind it and the browser puts a placeholder there
        icon.classList.replace("fa-regular", "fa-solid");
        icon.classList.replace("fa-copy", "fa-check");
        icon.classList.add("text-success");

        window.setTimeout(function () {
            icon.classList.replace("fa-solid", "fa-regular");
            icon.classList.replace("fa-check", "fa-copy");
            icon.classList.remove("text-success");
        }, 1500);
    });

    clipboard.on("error", function (event) {
        console.error("eos_tax: copying to the clipboard failed", event.action);
    });
});
