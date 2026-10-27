/* The sub tabs of the bots page, each fetched when it is first opened.
 *
 * Computing all four readings on every page load would make the page pay for
 * three nobody asked to see, so a pane stays empty until its tab is shown.
 */
/* How long a tab waits before asking again for a month the job is still
 * computing - a month takes the better part of a minute. */
const EOS_TAX_PENDING_RETRY_MS = 20000;

/* The tab the reader is on, as the url spells it: the pane id minus its
 * prefix, so "eos-tax-tab-rhythm" travels as "rhythm". */
function eosTaxTabName(pane) {
    return pane.id.replace("eos-tax-tab-", "");
}

/* Point every link that should survive a jump at the tab now open.
 *
 * Rewritten on each tab change rather than worked out when the link is
 * clicked: a middle click or "open in new tab" never fires a click handler,
 * and a link whose behaviour depends on one is a link that lies.
 */
function eosTaxKeepTab(name) {
    document.querySelectorAll("[data-eos-keep-tab]").forEach(function (link) {
        const url = new URL(link.href, window.location.href);

        url.searchParams.set("tab", name);
        link.href = url.pathname + url.search;
    });

    // the month form reloads the page too, and used to drop the reader back
    // on the first tab every time the month changed
    document.querySelectorAll("[data-eos-keep-tab-field]").forEach(function (field) {
        field.value = name;
    });
}

/* Reopen the tab the url asks for, once, on load.
 *
 * Bootstrap does the showing, which fires the same event a click fires - so
 * the pane fetches itself exactly the way it would have if the reader had
 * opened it by hand.
 */
function eosTaxOpenRequestedTab() {
    /* global bootstrap */
    const wanted = new URLSearchParams(window.location.search).get("tab");

    // the name goes into a selector below: anything but a plain word - a
    // quote from a hand edited url - would make querySelector throw and take
    // the rest of the page's script with it
    if (!wanted || !/^[a-z]+$/.test(wanted) || typeof bootstrap === "undefined") {
        return;
    }

    const trigger = document.querySelector(
        '[data-bs-target="#eos-tax-tab-' + wanted + '"]'
    );

    if (trigger) {
        bootstrap.Tab.getOrCreateInstance(trigger).show();
    }
}

/* Make the column headings of a grouped table sort it - the audit tab, one
 * tbody per main with its heading row on top.
 *
 * DataTables sorts rows and would scatter a main's characters over the whole
 * table, and Alliance Auth ships no RowGroup extension for it. So the column
 * marked "groups" orders the tbody elements by the main's name, and every
 * other column orders the rows inside each tbody, heading row left on top.
 */
function eosTaxSortGroups(root) {
    const ICONS = ["fa-sort", "fa-sort-up", "fa-sort-down"];

    // data-order where the words do not sort (ages, badges), else the text;
    // null for a cell with nothing to sort by, an age nobody knows
    function valueOf(cell) {
        if (cell.hasAttribute("data-order")) {
            const order = cell.dataset.order;

            if (order === "") {
                return null;
            }

            return isNaN(Number(order)) ? order : Number(order);
        }

        return cell.textContent.trim();
    }

    function compare(a, b, sign) {
        // the unknown stay at the bottom whichever way round
        if (a === null || b === null) {
            return (a === null) - (b === null);
        }

        if (typeof a === "number" && typeof b === "number") {
            return sign * (a - b);
        }

        return sign * String(a).localeCompare(String(b), undefined, {
            sensitivity: "base",
            numeric: true
        });
    }

    function show(heading, direction) {
        heading.setAttribute("aria-sort", direction);

        const icon = heading.querySelector("i");
        if (icon) {
            icon.classList.remove(...ICONS);
            icon.classList.add(
                direction === "ascending" ? "fa-sort-up"
                    : direction === "descending" ? "fa-sort-down" : "fa-sort"
            );
        }
    }

    root.querySelectorAll("table[data-eos-sortable-groups]").forEach(function (table) {
        const headings = Array.from(table.tHead.rows[0].cells);

        headings.forEach(function (heading, index) {
            const button = heading.querySelector("[data-eos-sort]");

            if (!button) {
                return;
            }

            button.addEventListener("click", function () {
                const direction = heading.getAttribute("aria-sort") === "ascending"
                    ? "descending" : "ascending";
                const sign = direction === "ascending" ? 1 : -1;

                if (button.dataset.eosSort === "groups") {
                    Array.from(table.tBodies)
                        .sort(function (a, b) {
                            return compare(a.dataset.eosGroup, b.dataset.eosGroup, sign);
                        })
                        .forEach(function (body) {
                            table.appendChild(body);
                        });
                } else {
                    Array.from(table.tBodies).forEach(function (body) {
                        Array.from(body.rows)
                            .filter(function (row) {
                                return !row.querySelector("[scope='rowgroup']");
                            })
                            // stable: rows equal here keep the order they had
                            .sort(function (a, b) {
                                return compare(
                                    valueOf(a.cells[index]), valueOf(b.cells[index]), sign
                                );
                            })
                            .forEach(function (row) {
                                body.appendChild(row);
                            });
                    });

                    // one row column at a time; the groups keep their own
                    headings.forEach(function (other) {
                        const sorter = other.querySelector("[data-eos-sort='rows']");

                        if (sorter && other !== heading) {
                            show(other, "none");
                        }
                    });
                }

                show(heading, direction);
            });
        });
    });
}

document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    const config = JSON.parse(
        document.getElementById("eos-tax-config").textContent
    );

    document.querySelectorAll('[data-bs-toggle="tab"]').forEach(function (trigger) {
        trigger.addEventListener("shown.bs.tab", function () {
            const pane = document.querySelector(trigger.dataset.bsTarget);

            if (pane) {
                eosTaxKeepTab(eosTaxTabName(pane));
            }
        });
    });

    document.querySelectorAll("[data-eos-signal]").forEach(function (pane) {
        const trigger = document.querySelector(
            '[data-bs-target="#' + pane.id + '"]'
        );

        if (!trigger) {
            return;
        }

        function load() {
            // once: the fragment is a snapshot of the month in the form
            // above, and that form reloads the page when it changes
            if (pane.dataset.eosLoaded) {
                return;
            }

            pane.dataset.eosLoaded = "1";
            pane.textContent = config.loading;

            fetch(config.signals[pane.dataset.eosSignal], {
                headers: { "X-Requested-With": "XMLHttpRequest" }
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error(response.status);
                    }

                    return response.text();
                })
                .then(function (html) {
                    pane.innerHTML = html;

                    // the rows arrived after the tab was shown, so the
                    // listener that keeps links pointed at it has already run
                    eosTaxKeepTab(eosTaxTabName(pane));

                    // a script tag inserted through innerHTML never runs, so
                    // the chart is drawn from here once the fragment lands
                    if (typeof eosTaxDrawChart === "function") {
                        eosTaxDrawChart(pane);
                    }

                    // the same for the sortable headings of the audit tab
                    eosTaxSortGroups(pane);

                    // the job is still computing the month: ask again while
                    // the tab stays open, and on the next visit to it
                    if (pane.querySelector("[data-eos-pending]")) {
                        delete pane.dataset.eosLoaded;
                        window.setTimeout(function () {
                            if (pane.classList.contains("active")) {
                                load();
                            }
                        }, EOS_TAX_PENDING_RETRY_MS);
                    }
                })
                .catch(function (error) {
                    // let it be tried again rather than leaving a dead pane
                    delete pane.dataset.eosLoaded;
                    pane.textContent = config.error;
                    console.error("eos_tax: loading the tab failed", error);
                });
        }

        trigger.addEventListener("shown.bs.tab", load);
    });

    // the first tab comes with the page, so a month still being computed
    // there is asked for again by reloading the page
    const hours = document.getElementById("eos-tax-tab-hours");

    if (hours && hours.querySelector("[data-eos-pending]")) {
        window.setTimeout(function () {
            if (hours.classList.contains("active")) {
                window.location.reload();
            }
        }, EOS_TAX_PENDING_RETRY_MS);
    }

    const open = document.querySelector(
        ".tab-pane.active[id^='eos-tax-tab-']"
    );

    if (open) {
        eosTaxKeepTab(eosTaxTabName(open));
    }

    eosTaxOpenRequestedTab();
});
