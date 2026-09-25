/* Corp Tax Changes: the sortable table and its quick filters.
 *
 * Loaded from tax-changes.html, which hands over the translated strings
 * as json_script "eos-tax-config" - a .js file cannot reach {% translate %}.
 */
document.addEventListener("DOMContentLoaded", function () {
    /* global DataTable */
    "use strict";

    const labels = JSON.parse(
        document.getElementById("eos-tax-config").textContent
    );
    const table = document.querySelector("#table-eos-tax-changes");

    if (!table) {
        return;  // nothing found, nothing to sort
    }

    const changes = new DataTable(table, {
        // one entry per column - the search box hits Corporation only
        columns: [
            { searchable: true },   // Corporation
            // searchable too, so "0" and "100" find the Corporations
            // that switched their tax off or all the way up
            { searchable: true },   // Change
            { searchable: false },  // On
            { searchable: false },  // Systems
            { searchable: false }   // Payouts
        ],
        search: {
            caseInsensitive: true,
            smart: true
        },
        // keep what the server sent: biggest move first. Left alone
        // DataTables would sort by the first column and lose that.
        order: [],
        pageLength: 25,
        language: {
            search: labels.searchLabel,
            searchPlaceholder: labels.searchPlaceholder
        }
    });

    // the buttons drive the same search box, so a filter and a typed
    // term cannot end up contradicting each other
    document.querySelectorAll("[data-eos-filter]").forEach(function (button) {
        button.addEventListener("click", function () {
            // the class is what Bootstrap draws and aria-pressed is
            // what gets announced, so both have to move together
            document.querySelectorAll("[data-eos-filter]").forEach(
                function (other) {
                    other.classList.remove("active");
                    other.setAttribute("aria-pressed", "false");
                }
            );
            button.classList.add("active");
            button.setAttribute("aria-pressed", "true");

            changes.search(button.dataset.eosFilter).draw();
        });
    });
});
