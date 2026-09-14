/* The sub tabs of the bots page, each fetched when it is first opened.
 *
 * Computing all four readings on every page load would make the page pay for
 * three nobody asked to see, so a pane stays empty until its tab is shown.
 */
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

    if (!wanted || typeof bootstrap === "undefined") {
        return;
    }

    const trigger = document.querySelector(
        '[data-bs-target="#eos-tax-tab-' + wanted + '"]'
    );

    if (trigger) {
        bootstrap.Tab.getOrCreateInstance(trigger).show();
    }
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

        trigger.addEventListener("shown.bs.tab", function () {
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
                })
                .catch(function (error) {
                    // let it be tried again rather than leaving a dead pane
                    delete pane.dataset.eosLoaded;
                    pane.textContent = config.error;
                    console.error("eos_tax: loading the tab failed", error);
                });
        });
    });

    const open = document.querySelector(
        ".tab-pane.active[id^='eos-tax-tab-']"
    );

    if (open) {
        eosTaxKeepTab(eosTaxTabName(open));
    }

    eosTaxOpenRequestedTab();
});
