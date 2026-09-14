/* The three charts behind the character page tabs.
 *
 * Each fragment carries its numbers in a json_script and a canvas naming the
 * chart to draw; a script tag inside an innerHTML never runs, so the drawing
 * is done from here after the fragment lands.
 */
"use strict";

function eosTaxThemeColours() {
    // the theme is the reader's choice in Alliance Auth and has nothing to do
    // with the system light/dark setting, so ask the page and not the browser
    const style = window.getComputedStyle(document.body);

    return {
        accent: style.getPropertyValue("--bs-primary").trim() || "#375a7f",
        // Darkly's --bs-secondary (#444) sits almost exactly on the card
        // background behind a chart, and its own --bs-primary (#375a7f) is
        // nearly as dark against the grid - a "muted" point or a thin accent
        // line there is not dim, it is gone. --bs-success reads on both a
        // light and a dark canvas, so the low contrast pairs use it instead.
        success: style.getPropertyValue("--bs-success").trim() || "#00bc8c",
        danger: style.getPropertyValue("--bs-danger").trim() || "#e74c3c",
        text: style.color,
        grid: style.getPropertyValue("--bs-border-color").trim() || "#ccc",
        // resolved here, not written as var(--bs-primary-rgb) in a fillStyle:
        // a canvas takes colour strings, not CSS, and would ignore a custom
        // property without saying so
        accentBand: "rgba("
            + (style.getPropertyValue("--bs-primary-rgb").trim() || "55, 90, 127")
            + ", 0.12)",
    };
}

/* Whether the fragment handed over a Corporation to compare against.
 *
 * A Corporation that is one person leaves nothing behind once that person is
 * taken out, and the reading then sends null for every hour rather than a
 * copy of the Character - two identical lines read as perfect agreement,
 * which is the opposite of having no yardstick.
 */
function eosTaxHasCorporation(series) {
    return series.some(function (point) {
        return point.corporation !== null && point.corporation !== undefined;
    });
}

function eosTaxReadJson(pane, id) {
    const element = pane.querySelector("#" + id);

    return element ? JSON.parse(element.textContent) : null;
}

function eosTaxRunChart(canvas, points, colours) {
    /* global Chart */
    const inRun = points.filter(function (point) { return point.in_run; });
    const rest = points.filter(function (point) { return !point.in_run; });

    return new Chart(canvas, {
        type: "scatter",
        data: {
            datasets: [
                {
                    label: canvas.dataset.eosLabelRest,
                    data: rest.map(function (point) {
                        return { x: point.day, y: point.hour };
                    }),
                    backgroundColor: colours.success,
                    pointRadius: 3
                },
                {
                    label: canvas.dataset.eosLabelRun,
                    data: inRun.map(function (point) {
                        return { x: point.day, y: point.hour };
                    }),
                    backgroundColor: colours.danger,
                    pointRadius: 5
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: colours.text } },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            const hour = Math.floor(context.parsed.y);
                            const minute = Math.round(
                                (context.parsed.y - hour) * 60
                            );

                            return String(hour).padStart(2, "0") + ":"
                                + String(minute).padStart(2, "0");
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: canvas.dataset.eosAxisDay,
                        color: colours.text
                    },
                    min: 1,
                    max: 31,
                    ticks: { stepSize: 2, color: colours.text },
                    grid: { color: colours.grid }
                },
                y: {
                    // a clock runs down the page the way a calendar does
                    reverse: true,
                    min: 0,
                    max: 24,
                    ticks: {
                        stepSize: 3,
                        color: colours.text,
                        callback: function (value) {
                            return String(value).padStart(2, "0") + ":00";
                        }
                    },
                    grid: { color: colours.grid }
                }
            }
        }
    });
}

/* Shades the Corporation's busy hours behind the bars.
 *
 * Not by colouring the bars themselves: colour already says which series a bar
 * belongs to, and Chart.js builds a legend swatch from the first entry of a
 * colour array - so a Character whose first hour fell outside the window got a
 * legend in the outside colour while most of its bars wore the inside one.
 */
const eosTaxWindowBand = {
    id: "eosTaxWindowBand",
    beforeDatasetsDraw: function (chart, args, options) {
        const hours = options.hours;

        if (!hours || !hours.length) {
            return;
        }

        const area = chart.chartArea;
        const scale = chart.scales.x;
        const width = area.width / chart.data.labels.length;
        const context = chart.ctx;

        context.save();
        context.fillStyle = options.fill;

        hours.forEach(function (hour) {
            const index = chart.data.labels.indexOf(
                String(hour).padStart(2, "0")
            );

            if (index < 0) {
                return;
            }

            context.fillRect(
                scale.getPixelForValue(index) - width / 2,
                area.top,
                width,
                area.height
            );
        });

        context.restore();
    }
};

function eosTaxRhythmChart(canvas, series, window_, colours) {
    /* global Chart */
    const datasets = [
        {
            label: canvas.dataset.eosLabelCharacter,
            data: series.map(function (point) { return point.character; }),
            backgroundColor: colours.accent
        }
    ];

    if (eosTaxHasCorporation(series)) {
        datasets.push({
            label: canvas.dataset.eosLabelCorporation,
            data: series.map(function (point) { return point.corporation; }),
            type: "line",
            borderColor: colours.danger,
            backgroundColor: colours.danger,
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3
        });
    }

    return new Chart(canvas, {
        type: "bar",
        plugins: [eosTaxWindowBand],
        data: {
            labels: series.map(function (point) {
                return String(point.hour).padStart(2, "0");
            }),
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: colours.text } },
                eosTaxWindowBand: {
                    hours: window_ || [],
                    // the theme's own accent at a tenth, the way the bot
                    // matrix tints its cells. Resolved here rather than
                    // written as var(): a canvas fillStyle is not CSS and
                    // would silently ignore a custom property.
                    fill: colours.accentBand
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: canvas.dataset.eosAxisHour,
                        color: colours.text
                    },
                    ticks: { color: colours.text },
                    grid: { display: false }
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        color: colours.text,
                        callback: function (value) { return value + " %"; }
                    },
                    grid: { color: colours.grid }
                }
            }
        }
    });
}

function eosTaxClockChart(canvas, series, colours) {
    /* global Chart */
    const datasets = [
        {
            label: canvas.dataset.eosLabelCharacter,
            data: series.map(function (point) { return point.character; }),
            // not colours.accent: Darkly's --bs-primary is a dark navy that
            // all but disappears behind this chart's grid lines
            borderColor: colours.success,
            backgroundColor: "transparent",
            borderWidth: 2,
            pointRadius: 2
        }
    ];

    if (eosTaxHasCorporation(series)) {
        datasets.push({
            label: canvas.dataset.eosLabelCorporation,
            data: series.map(function (point) { return point.corporation; }),
            borderColor: colours.danger,
            backgroundColor: "transparent",
            borderWidth: 2,
            pointRadius: 0
        });
    }

    return new Chart(canvas, {
        type: "radar",
        data: {
            labels: series.map(function (point) {
                return String(point.hour).padStart(2, "0");
            }),
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: colours.text } } },
            scales: {
                r: {
                    beginAtZero: true,
                    angleLines: { color: colours.grid },
                    grid: { color: colours.grid },
                    pointLabels: { color: colours.text },
                    ticks: {
                        backdropColor: "transparent",
                        color: colours.text,
                        callback: function (value) { return value + " %"; }
                    }
                }
            }
        }
    });
}

function eosTaxDrawChart(pane) {
    const canvas = pane.querySelector("[data-eos-chart]");

    if (!canvas || typeof Chart === "undefined") {
        return;
    }

    const colours = eosTaxThemeColours();
    const data = eosTaxReadJson(pane, "eos-tax-chart-data");

    if (!data) {
        return;
    }

    if (canvas.dataset.eosChart === "runs") {
        eosTaxRunChart(canvas, data, colours);
    } else if (canvas.dataset.eosChart === "rhythm") {
        eosTaxRhythmChart(
            canvas, data, eosTaxReadJson(pane, "eos-tax-chart-window"), colours
        );
    } else if (canvas.dataset.eosChart === "clock") {
        eosTaxClockChart(canvas, data, colours);
    }
}
