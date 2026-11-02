/* The overview table: DataTables. Its copy buttons are copy-buttons.js.
 *
 * Loaded from index.html, which hands over the translated strings as
 * json_script "eos-tax-config" - a .js file cannot reach {% translate %}.
 */
document.addEventListener("DOMContentLoaded", function () {
    /* global DataTable */
    "use strict";

    const labels = JSON.parse(
        document.getElementById("eos-tax-config").textContent
    );

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
            { searchable: false },  // Amount paid in Isk
            { searchable: false },  // Month
            { searchable: false },  // Reason
            { searchable: false },  // Payed
            { searchable: false },  // Characters without wallet audit
            { searchable: false }   // Calculation time
        ],
        search: {
            caseInsensitive: true,  // "e" must also find "Ether Element"
            smart: true
        },
        // month, then corporation name, and nothing else - Reason and Paid
        // stay sortable by click, but do not reorder the rows on their own
        order: [[5, "asc"], [0, "asc"]],
        pageLength: 25,
        language: {
            search: labels.searchLabel,
            searchPlaceholder: labels.searchPlaceholder
        }
    });
});
