/* The daily curve behind one Corporation's ingame tax rate.
 *
 * Loaded from tax-change-detail.html, which hands over the translated strings
 * as json_script "eos-tax-config" - a .js file cannot reach {% translate %}.
 */
document.addEventListener("DOMContentLoaded", function () {
    /* global Chart */
    "use strict";

    const labels = JSON.parse(
        document.getElementById("eos-tax-config").textContent
    );
    const canvas = document.querySelector("#eos-tax-rate-chart");

    if (!canvas) {
        return;
    }

    const series = JSON.parse(document.querySelector("#eos-tax-series").textContent);
    const narrow = window.matchMedia("(max-width: 767.98px)");
    const style = window.getComputedStyle(document.body);
    // trimmed, with a fallback, the way bot-charts.js reads it: the raw
    // custom property carries a leading space and is empty on a theme that
    // does not set it, and Chart.js then draws the line in its default grey,
    // which on Darkly all but vanishes against the card
    const accent = style.getPropertyValue("--bs-primary").trim() || "#375a7f";

    new Chart(canvas, {
        type: "line",
        data: {
            labels: series.map(function (point) { return point.day; }),
            datasets: [{
                // one series, so no legend box - the card title names it
                label: labels.axis,
                data: series.map(function (point) { return point.rate; }),
                borderColor: accent,
                backgroundColor: accent,
                borderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 8,
                tension: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "nearest", intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            const point = series[context.dataIndex];

                            // the words used to be English here while the
                            // columns above them were translated
                            return point.rate + " % \u00b7 " + point.payouts
                                + " " + labels.payouts + " \u00b7 "
                                + point.systems + " " + labels.systems;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: {
                        maxRotation: 0,
                        autoSkip: true,
                        autoSkipPadding: narrow.matches ? 12 : 4
                    }
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        maxTicksLimit: narrow.matches ? 5 : 8,
                        callback: function (value) { return value + " %"; }
                    }
                }
            }
        }
    });
});
