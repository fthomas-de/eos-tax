/* GM Transactions: the sortable table, its counterparty filter, the note
 * popup of each row, and the wait for the job.
 *
 * Loaded from gm-transactions.html, which hands over the translated strings
 * as json_script "eos-tax-config" - a .js file cannot reach {% translate %}.
 */
/* The note of a row, edited in one popup the buttons share.
 *
 * A note is someone's free text, so it only ever travels as text: read from
 * value and dataset, written to value, textContent and attributes - never as
 * markup. The server cleans and limits it; the page shows what it answered,
 * not what was typed.
 */
function setUpNotes(dataTable) {
    /* global bootstrap */
    "use strict";

    const modal = document.getElementById("eos-tax-gm-note");

    if (!modal) {
        return;
    }

    const textarea = modal.querySelector("textarea");
    const count = modal.querySelector("[data-eos-note-count]");
    const error = modal.querySelector("[data-eos-note-error]");
    const save = modal.querySelector("[data-eos-note-save]");
    let button = null;

    const showCount = function () {
        count.textContent = String(textarea.value.length);
    };

    textarea.addEventListener("input", showCount);

    // Bootstrap names the button that opened the popup
    modal.addEventListener("show.bs.modal", function (event) {
        button = event.relatedTarget;
        modal.querySelector("[data-eos-note-name]").textContent = button.dataset.eosNoteName;
        textarea.value = button.dataset.eosNote;
        error.textContent = "";
        showCount();
    });

    modal.addEventListener("shown.bs.modal", function () {
        textarea.focus();
    });

    save.addEventListener("click", function () {
        const body = new URLSearchParams();
        body.set("character_id", button.dataset.eosNoteCharacter);
        body.set("entry_id", button.dataset.eosNoteEntry);
        body.set("text", textarea.value);

        save.disabled = true;
        error.textContent = "";

        fetch(modal.dataset.eosNoteUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": modal.querySelector("[name=csrfmiddlewaretoken]").value,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: body.toString(),
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(response.status);
                }

                return response.json();
            })
            .then(function (data) {
                const cell = button.closest("td");

                button.dataset.eosNote = data.text;
                button.title = data.text || modal.dataset.eosLabelEmpty;
                button.classList.toggle("btn-secondary", Boolean(data.text));
                button.classList.toggle("btn-outline-secondary", !data.text);
                cell.dataset.order = data.text;
                cell.dataset.search = data.text;
                // DataTables keeps what it read at the start; no draw, so
                // the row stays where the reader is looking
                dataTable.row(cell.closest("tr")).invalidate("dom");

                bootstrap.Modal.getInstance(modal).hide();
            })
            .catch(function (failure) {
                error.textContent = modal.dataset.eosLabelError;
                console.error("eos_tax: saving the note failed", failure);
            })
            .finally(function () {
                save.disabled = false;
            });
    });
}

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
            { searchable: false },  // In the Alliance
            { searchable: true },   // Note - its data-search, not the button
            { searchable: false },  // Date
            { searchable: true },   // Character
            { searchable: false },  // Age
            { searchable: true },   // Main
            { searchable: true },   // Corporation
            { searchable: true },   // Corporation at the time
            { searchable: true },   // Corporations in the Alliance
            { searchable: true },   // Alliance
            { searchable: false },  // Amount
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

    setUpNotes(dataTable);

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
