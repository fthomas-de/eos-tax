/* global Chart */
"use strict";

/**
 * Wires up the tax/income chart on the statistics page.
 *
 * `config.dataUrl` and `config.text` come from the template via json_script -
 * a plain .js file cannot read Django template variables, so the page hands
 * them in instead of this file reaching for them itself.
 */
function initEosTaxStatistics(config) {
    const DATA_URL = config.dataUrl;
    const TEXT = config.text;

    const yearSelect = document.querySelector("#eos-tax-year");
    const allianceSelect = document.querySelector("#eos-tax-alliance");
    const typeSelect = document.querySelector("#eos-tax-chart-type");
    const monthSelect = document.querySelector("#eos-tax-month");
    const monthField = document.querySelector("#eos-tax-month-field");
    const minShareInput = document.querySelector("#eos-tax-min-share");
    // Bootstrap's md, the width at which the legend stops sitting
    // beside the chart and the axis stops having room for every label
    const narrow = window.matchMedia("(max-width: 767.98px)");

    const canvas = document.querySelector("#eos-tax-chart");
    const legendBody = document.querySelector("#eos-tax-legend");
    const figures = document.querySelector("#eos-tax-figures");
    const status = document.querySelector("#eos-tax-status");

    if (!canvas) {
        return;  // no data at all, the template rendered the empty state
    }

    // the overview formats ISK server side with dots as the thousands
    // separator; Intl would follow the viewer's locale and print commas
    const isk = {
        format: function (value) {
            return Math.round(value)
                .toString()
                .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
        }
    };

    // A figure in billions or millions, with as many decimals as it takes to
    // tell neighbours apart. Whole billions printed 480 M as "0 B", and put
    // "2 B" on the axis twice for the ticks at 1.5 B and 2 B. The decimal
    // comma goes with the dots the overview groups thousands with.
    function scaled(value, divisor, unit) {
        const number = value / divisor;
        const absolute = Math.abs(number);
        const digits = absolute < 10 ? 2 : (absolute < 100 ? 1 : 0);
        const parts = number.toFixed(digits).split(".");
        const whole = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
        const fraction = (parts[1] || "").replace(/0+$/, "");

        return (fraction ? whole + "," + fraction : whole) + " " + unit;
    }

    // B and M untranslated on purpose - the same letter in every language
    // beats a locale specific abbreviation nobody recognises
    function compact(value) {
        const absolute = Math.abs(value);

        if (absolute >= 1e9) {
            return scaled(value, 1e9, "B");
        }

        if (absolute >= 1e6) {
            return scaled(value, 1e6, "M");
        }

        return isk.format(value);
    }

    // AA themes are named (flatly, darkly, ...), so prefers-color-scheme says
    // nothing useful here - derive the mode from the rendered surface instead.
    function prefersDarkSurface() {
        const background = getComputedStyle(document.body).backgroundColor;
        const parts = background.match(/\d+(\.\d+)?/g);

        if (!parts || parts.length < 3) {
            return false;
        }

        const [red, green, blue] = parts.slice(0, 3).map(Number);
        return (0.2126 * red + 0.7152 * green + 0.0722 * blue) < 128;
    }

    const dark = prefersDarkSurface();
    const bodyStyle = getComputedStyle(document.body);
    Chart.defaults.color = bodyStyle.color;
    Chart.defaults.font.family = bodyStyle.fontFamily;

    function dashStyle(dash) {
        if (!dash || dash.length === 0) {
            return "solid";
        }

        return dash[0] > 3 ? "dashed" : "dotted";
    }

    function neutralColour() {
        // a fold is not an entity, so it must not take a categorical hue
        return dark ? "#8a8a85" : "#9a9a94";
    }

    let payload = null;
    let chart = null;

    function isPie() {
        return typeSelect.value === "pie";
    }

    function selectedMonth() {
        return Number(monthSelect.value || 1) - 1;
    }

    function minShare() {
        return Math.min(100, Math.max(0, Number(minShareInput.value) || 0));
    }

    function entries() {
        const month = selectedMonth();

        return payload.series.map(function (corp, index) {
            return {
                key: corp.corp_id,
                name: corp.name,
                tax: corp.tax.slice(),
                income: corp.income.slice(),
                taxTotal: corp.tax_total,
                incomeTotal: corp.income_total,
                monthTax: corp.tax[month],
                monthIncome: corp.income[month],
                members: corp.members || 0,
                colour: corp.color,
                dash: corp.dash,
                parts: []
            };
        });
    }

    function sumArrays(list, field) {
        return list.reduce(function (acc, entry) {
            return acc.map(function (value, index) {
                return value + entry[field][index];
            });
        }, new Array(12).fill(0));
    }

    function fold(all, valueOf) {
        const total = all.reduce(function (sum, entry) {
            return sum + valueOf(entry);
        }, 0);

        if (total <= 0 || minShare() <= 0) {
            return all;
        }

        const limit = total * minShare() / 100;
        const kept = all.filter(function (entry) { return valueOf(entry) >= limit; });
        const small = all.filter(function (entry) { return valueOf(entry) < limit; });

        // folding a single corporation only renames it
        if (small.length < 2) {
            return all;
        }

        const sum = function (field) {
            return small.reduce(function (acc, entry) { return acc + entry[field]; }, 0);
        };

        kept.push({
            key: "__other__",
            name: TEXT.other + " (" + small.length + ")",
            tax: sumArrays(small, "tax"),
            income: sumArrays(small, "income"),
            taxTotal: sum("taxTotal"),
            incomeTotal: sum("incomeTotal"),
            monthTax: sum("monthTax"),
            monthIncome: sum("monthIncome"),
            members: sum("members"),
            colour: neutralColour(),
            dash: [],
            parts: small
        });

        return kept;
    }

    function visible() {
        const all = entries();

        return isPie()
            ? fold(all, function (entry) { return entry.monthTax; })
            : fold(all, function (entry) { return entry.taxTotal; });
    }

    function fillMonths() {
        if (monthSelect.options.length === payload.labels.length) {
            return;  // labels do not change between requests
        }

        monthSelect.replaceChildren();
        payload.labels.forEach(function (label, index) {
            const option = document.createElement("option");
            option.value = String(index + 1);
            option.textContent = label;
            monthSelect.append(option);
        });
        monthSelect.value = String(new Date().getMonth() + 1);
    }

    function legendRow(entry, index, toggle) {
        const row = document.createElement("tr");
        const nameCell = document.createElement("td");

        if (toggle) {
            const check = document.createElement("div");
            check.className = "form-check mb-0";

            const input = document.createElement("input");
            input.className = "form-check-input";
            input.type = "checkbox";
            input.checked = true;
            input.id = "eos-tax-entry-" + index;
            input.addEventListener("change", function () {
                toggle(index, input.checked);
            });

            const label = document.createElement("label");
            label.className = "form-check-label";
            label.htmlFor = input.id;

            const swatch = document.createElement("span");
            swatch.className = "eos-tax-swatch me-2";
            swatch.style.setProperty("--eos-tax-swatch-color", entry.colour);
            swatch.style.setProperty("--eos-tax-swatch-style", dashStyle(entry.dash));

            label.append(swatch, document.createTextNode(entry.name));
            check.append(input, label);
            nameCell.append(check);
        } else {
            // a folded member: shown for its figures, not selectable
            row.className = "text-body-secondary";
            nameCell.className = "ps-4 small";
            nameCell.textContent = entry.name;
        }

        const incomeCell = document.createElement("td");
        incomeCell.className = "text-end d-none d-md-table-cell";
        incomeCell.textContent = isk.format(
            isPie() ? entry.monthIncome : entry.incomeTotal
        );

        const taxCell = document.createElement("td");
        taxCell.className = "text-end";
        taxCell.textContent = isk.format(
            isPie() ? entry.monthTax : entry.taxTotal
        );

        row.append(nameCell, incomeCell, taxCell);

        return row;
    }

    function renderLegend(shown, toggle) {
        legendBody.replaceChildren();

        shown.forEach(function (entry, index) {
            legendBody.append(legendRow(entry, index, toggle));

            // keep the numbers of everything that went into the fold
            entry.parts.forEach(function (part) {
                legendBody.append(legendRow(part, null, null));
            });
        });
    }

    function renderFigures(all, shown) {
        const pie = isPie();
        const taxOf = function (entry) { return pie ? entry.monthTax : entry.taxTotal; };
        const incomeOf = function (entry) { return pie ? entry.monthIncome : entry.incomeTotal; };

        const totalTax = all.reduce(function (s, e) { return s + taxOf(e); }, 0);
        const totalIncome = all.reduce(function (s, e) { return s + incomeOf(e); }, 0);
        const drawn = shown.filter(function (e) { return e.key !== "__other__"; });
        const drawnTax = drawn.reduce(function (s, e) { return s + taxOf(e); }, 0);
        const covered = totalTax ? Math.round(drawnTax / totalTax * 1000) / 10 : 0;

        const parts = [
            TEXT.shown.replace("{shown}", drawn.length).replace("{total}", all.length),
            TEXT.covered.replace("{value}", covered + " %"),
            TEXT.income.replace("{value}", compact(totalIncome)),
            TEXT.tax.replace("{value}", compact(totalTax))
        ];

        figures.replaceChildren();
        parts.forEach(function (text, index) {
            const span = document.createElement("span");
            span.textContent = text;
            if (index === parts.length - 1) {
                span.className = "ms-auto";
            }
            figures.append(span);
        });
    }

    function lineConfig(shown) {
        return {
            type: "line",
            data: {
                labels: payload.labels,
                datasets: shown.map(function (entry) {
                    return {
                        label: entry.name,
                        data: entry.tax,
                        borderColor: entry.colour,
                        backgroundColor: entry.colour,
                        borderDash: entry.dash,
                        borderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        tension: 0
                    };
                })
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "nearest", intersect: false },
                plugins: {
                    legend: { display: false },  // the checkbox table is the legend
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return context.dataset.label + ": " + isk.format(context.parsed.y);
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            // never turn the months on their side - a
                            // rotated label is what made this unreadable.
                            // Dropping every other one keeps the rest level.
                            maxRotation: 0,
                            autoSkip: true,
                            autoSkipPadding: narrow.matches ? 12 : 4
                        }
                    },
                    y: {
                        beginAtZero: true,
                        ticks: {
                            maxTicksLimit: narrow.matches ? 5 : 8,
                            callback: function (value) {
                                return compact(value);
                            }
                        }
                    }
                }
            }
        };
    }

    function pieConfig(shown) {
        const total = shown.reduce(function (sum, entry) {
            return sum + entry.monthTax;
        }, 0);

        return {
            type: "pie",
            data: {
                labels: shown.map(function (entry) { return entry.name; }),
                datasets: [{
                    data: shown.map(function (entry) { return entry.monthTax; }),
                    backgroundColor: shown.map(function (entry) { return entry.colour; }),
                    // a thin gap keeps neighbouring slices apart even when
                    // their hues sit close together
                    borderColor: bodyStyle.backgroundColor,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                const share = total
                                    ? Math.round((context.parsed / total) * 1000) / 10
                                    : 0;

                                return context.label + ": " + isk.format(context.parsed)
                                    + " (" + share + "%)";
                            }
                        }
                    }
                }
            }
        };
    }

    function render() {
        if (!payload) {
            return;
        }

        monthField.hidden = !isPie();

        const all = entries();
        const shown = visible();

        if (chart) {
            chart.destroy();
        }

        if (isPie()) {
            // Biggest share first, so the pie reads round from the
            // largest slice. Other stays last whatever its size - it
            // is a remainder, not a corporation. The colour travels
            // with the entry, so reordering repaints nothing.
            const ordered = shown.slice().sort(function (first, second) {
                if (first.key === "__other__") {
                    return 1;
                }
                if (second.key === "__other__") {
                    return -1;
                }

                return second.monthTax - first.monthTax;
            });

            chart = new Chart(canvas, pieConfig(ordered));
            renderLegend(ordered, function (index) {
                chart.toggleDataVisibility(index);
                chart.update();
            });
        } else {
            chart = new Chart(canvas, lineConfig(shown));
            renderLegend(shown, function (index, on) {
                chart.setDatasetVisibility(index, on);
                chart.update();
            });
        }

        renderFigures(all, shown);
    }

    function load() {
        const params = new URLSearchParams({ year: yearSelect.value });

        if (allianceSelect.value) {
            params.set("alliance", allianceSelect.value);
        }

        status.textContent = TEXT.loading;

        fetch(DATA_URL + "?" + params.toString(), {
            headers: { "X-Requested-With": "XMLHttpRequest" }
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(response.status);
                }

                return response.json();
            })
            .then(function (fetched) {
                payload = fetched;
                fillMonths();
                render();
                status.textContent = payload.series.length
                    ? payload.series.length + " " + TEXT.corporations
                    : TEXT.empty;
            })
            .catch(function () {
                status.textContent = TEXT.error;
            });
    }

    // year and alliance need fresh data; the rest only redraws
    yearSelect.addEventListener("change", load);
    allianceSelect.addEventListener("change", load);
    typeSelect.addEventListener("change", render);
    monthSelect.addEventListener("change", render);
    minShareInput.addEventListener("change", render);
    load();
}


// the page hands the strings over as data; nothing else starts this file
document.addEventListener("DOMContentLoaded", function () {
    const element = document.getElementById("eos-tax-config");

    if (element) {
        initEosTaxStatistics(JSON.parse(element.textContent));
    }
});
