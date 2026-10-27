/* GM Transactions: the sortable table, its counterparty filter, and the
 * wait for the job.
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

    const dataTable = new DataTable(table, {
        // one entry per column - the search box hits names, not numbers
        columns: [
            { searchable: true },   // Character
            { searchable: true },   // Corporation
            { searchable: true },   // Corporation at the time
            { searchable: true },   // Alliance
            { searchable: true },   // Corporations in the Alliance
            { searchable: true },   // Main
            { searchable: false },  // Age
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

    // one box per counterparty; the page leaves the boxes out when there
    // is only one to tick
    const boxes = Array.from(
        document.querySelectorAll("[data-eos-party-filter] input[type=checkbox]")
    );

    if (!boxes.length) {
        return;
    }

    // the ticked boxes, as the page sent them: GM X alone when it is there
    const ticked = function () {
        return new Set(
            boxes.filter(function (each) {
                return each.checked;
            }).map(function (each) {
                return each.value;
            })
        );
    };

    let shownParties = ticked();

    // ext.search is shared by every DataTable on the page, so it has to
    // leave the others alone
    DataTable.ext.search.push(function (settings, data, dataIndex) {
        if (settings.nTable !== table) {
            return true;
        }

        return shownParties.has(dataTable.row(dataIndex).node().dataset.eosParty);
    });

    // the table was drawn with every row before the filter existed
    dataTable.draw();

    boxes.forEach(function (box) {
        box.addEventListener("change", function () {
            shownParties = ticked();
            dataTable.draw();
        });
    });
});
