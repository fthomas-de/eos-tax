/* GM Transactions: the sortable table, and the wait for the job.
 *
 * Loaded from gm-transactions.html, which hands over the translated strings
 * as json_script "eos-tax-config" - a .js file cannot reach {% translate %}.
 */
document.addEventListener("DOMContentLoaded", function () {
    /* global DataTable */
    "use strict";

    // the same pace as the bots page asks again for a list being computed
    const EOS_TAX_PENDING_RETRY_MS = 20000;

    if (document.querySelector("[data-eos-pending]")) {
        window.setTimeout(function () {
            window.location.reload();
        }, EOS_TAX_PENDING_RETRY_MS);
        return;
    }

    const labels = JSON.parse(
        document.getElementById("eos-tax-config").textContent
    );
    const table = document.querySelector("#table-eos-tax-gm");

    if (!table) {
        return;  // nothing found, nothing to sort
    }

    new DataTable(table, {
        // one entry per column - the search box hits names, not numbers
        columns: [
            { searchable: true },   // Character
            { searchable: true },   // Corporation
            { searchable: true },   // Alliance
            { searchable: true },   // Corporations in the Alliance
            { searchable: true },   // Main
            { searchable: false },  // Amount
            { searchable: false },  // Date
            { searchable: true },   // Transaction for
            { searchable: false },  // Wallet balance
            { searchable: true }    // Description
        ],
        search: {
            caseInsensitive: true,
            smart: true
        },
        // keep what the server sent: newest transaction first, then the
        // deepest wallets. Left alone DataTables would sort by Character
        order: [],
        pageLength: 25,
        language: {
            search: labels.searchLabel,
            searchPlaceholder: labels.searchPlaceholder
        }
    });
});
