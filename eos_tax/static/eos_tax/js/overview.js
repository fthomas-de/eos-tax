/* The overview table: copy buttons and DataTables.
 *
 * Loaded from index.html, which hands over the translated strings as
 * json_script "eos-tax-config" - a .js file cannot reach {% translate %}.
 */
document.addEventListener("DOMContentLoaded", function () {
    /* global ClipboardJS, DataTable */
    "use strict";

    const labels = JSON.parse(
        document.getElementById("eos-tax-config").textContent
    );

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
        console.error("eos_tax: copying the reason failed", event.action);
    });

    const table = document.querySelector("#table-eos-tax");

    if (!table) {
        return;  // the empty state renders no table at all
    }

    new DataTable(table, {
        // one entry per column - the search box hits Corporation only
        columns: [
            { searchable: true },   // Corporation
            { searchable: false },  // Ingame Corp Tax
            { searchable: false },  // Alliance Tax
            { searchable: false },  // Amount to pay in Isk
            { searchable: false },  // Month
            { searchable: false },  // Reason
            { searchable: false }   // Payed
        ],
        search: {
            caseInsensitive: true,  // "e" must also find "Ether Element"
            smart: true
        },
        // mirrors the server side order: the payable month's unpaid rows
        // first, then its paid rows, then the not yet payable follow-up
        // month - corporation name breaks every tie
        order: [[5, "asc"], [6, "asc"], [0, "asc"]],
        pageLength: 25,
        language: {
            search: labels.searchLabel,
            searchPlaceholder: labels.searchPlaceholder
        }
    });
});
