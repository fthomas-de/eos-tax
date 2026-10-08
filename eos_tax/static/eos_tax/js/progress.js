/* The progress bar of the recalculation runs, above every page of the app.
 *
 * Asks the server every two seconds while a run is going, once on load
 * otherwise, and again whenever the page says it started one (the
 * "eos-tax:progress-poll" event the settings page sends after the
 * recalculate button). A finished run stays with a reload button instead of
 * reloading by itself - the settings page may hold an unsaved form - and a
 * finished run is only shown at all if it started after the page was loaded,
 * or if a job of it failed: otherwise the page already shows its result.
 */
document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    const box = document.getElementById("eos-tax-progress");

    if (!box) {
        return;
    }

    const container = box.querySelector(".eos-tax-progress-runs");
    const label = function (name) {
        return box.getAttribute("data-eos-tax-" + name) || "";
    };
    const format = function (text, values) {
        return text.replace(/\{(\w+)\}/g, function (match, key) {
            return key in values ? String(values[key]) : match;
        });
    };

    // the server's clock at the first answer - runs from before it are old news
    let loadedAt = null;
    let timer = null;
    // the open state of each run's list survives the redraw every two seconds
    const openLists = new Set();

    const element = function (tag, className, text) {
        const node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        if (text !== undefined) {
            node.textContent = text;
        }
        return node;
    };

    const stateBadge = {
        queued: "text-bg-secondary",
        running: "text-bg-primary",
        done: "text-bg-success",
        skipped: "text-bg-warning",
        failed: "text-bg-danger",
    };

    const dismiss = function (run) {
        const csrfToken = box.querySelector("[name=csrfmiddlewaretoken]").value;

        fetch(label("progress-dismiss-url").replace("RUN_ID", run.id), {
            method: "POST",
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken, "X-Requested-With": "XMLHttpRequest" },
        })
            .catch(function (error) {
                console.error("eos_tax: dismissing the run failed", error);
            })
            .finally(poll);
    };

    const renderRun = function (run) {
        const failed = run.counts.failed;
        const wrapper = element("div", "mb-3");

        const head = element("div", "d-flex flex-wrap align-items-center gap-2 small mb-1");
        head.appendChild(element("span", "fw-semibold", label("label-" + run.kind)));
        head.appendChild(element("span", "text-body-secondary",
            format(label("label-count"), { finished: run.finished, total: run.total })));
        if (failed) {
            head.appendChild(element("span", "badge text-bg-danger",
                format(label("label-failed-count"), { count: failed })));
        }

        if (run.complete) {
            head.appendChild(element("span", "ms-auto", label("label-complete")));

            const reload = element("button", "btn btn-sm btn-primary", label("label-reload"));
            reload.type = "button";
            reload.addEventListener("click", function () {
                window.location.reload();
            });
            head.appendChild(reload);

            const close = element("button", "btn btn-sm btn-outline-secondary", label("label-dismiss"));
            close.type = "button";
            close.addEventListener("click", function () {
                close.disabled = true;
                dismiss(run);
            });
            head.appendChild(close);
        }
        wrapper.appendChild(head);

        const progress = element("div", "progress");
        progress.setAttribute("role", "progressbar");
        progress.setAttribute("aria-label", label("label-" + run.kind));
        progress.setAttribute("aria-valuemin", "0");
        progress.setAttribute("aria-valuemax", "100");
        progress.setAttribute("aria-valuenow", String(run.percent));

        let barClass = "progress-bar progress-bar-striped progress-bar-animated";
        if (run.complete) {
            barClass = failed ? "progress-bar bg-danger" : "progress-bar bg-success";
        }
        const bar = element("div", barClass, run.percent ? run.percent + " %" : "");
        bar.style.width = run.percent + "%";
        progress.appendChild(bar);
        wrapper.appendChild(progress);

        const details = element("details", "small mt-1");
        details.open = openLists.has(run.id);
        details.addEventListener("toggle", function () {
            if (details.open) {
                openLists.add(run.id);
            } else {
                openLists.delete(run.id);
            }
        });
        details.appendChild(element("summary", "text-body-secondary", label("label-details")));

        const table = element("table", "table table-sm mb-0");
        const body = element("tbody");
        run.jobs.forEach(function (job) {
            const row = element("tr");
            row.appendChild(element("td", "", job.corp_name));
            row.appendChild(element("td", "text-nowrap", job.month + "/" + job.year));

            const stateCell = element("td");
            stateCell.appendChild(element("span", "badge " + (stateBadge[job.state] || "text-bg-secondary"),
                label("state-" + job.state) || job.state));
            row.appendChild(stateCell);

            // a skip names its reason; a failure carries the exception text
            const detail = job.state === "skipped"
                ? (label("reason-" + job.detail) || job.detail)
                : job.detail;
            row.appendChild(element("td", "text-body-secondary", detail));

            body.appendChild(row);
        });
        table.appendChild(body);
        details.appendChild(table);
        wrapper.appendChild(details);

        return wrapper;
    };

    const poll = function () {
        window.clearTimeout(timer);

        fetch(label("progress-url"), { credentials: "same-origin" })
            .then(function (response) {
                return response.ok ? response.json() : null;
            })
            .then(function (data) {
                if (!data) {
                    return;
                }
                if (loadedAt === null) {
                    loadedAt = data.now;
                }

                const shown = data.runs.filter(function (run) {
                    return !run.complete || run.counts.failed > 0 || run.started_at >= loadedAt;
                });

                container.replaceChildren.apply(container, shown.map(renderRun));
                box.classList.toggle("d-none", shown.length === 0);

                if (shown.some(function (run) { return !run.complete; })) {
                    timer = window.setTimeout(poll, 2000);
                }
            })
            .catch(function () {
                timer = window.setTimeout(poll, 5000);
            });
    };

    document.addEventListener("eos-tax:progress-poll", poll);

    poll();
});
