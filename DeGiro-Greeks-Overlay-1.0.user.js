// ==UserScript==
// @name         DeGiro Greeks Overlay
// @namespace    https://github.com/eguilder/blazing-trades
// @version      1.0.3
// @description  Show option Greeks from local IBKR service
// @match        https://trader.degiro.nl/trader/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @updateURL    https://raw.githubusercontent.com/eguilder/blazing-trades/main/DeGiro-Greeks-Overlay-1.0.user.js
// @downloadURL  https://raw.githubusercontent.com/eguilder/blazing-trades/main/DeGiro-Greeks-Overlay-1.0.user.js
// @homepageURL  https://github.com/eguilder/blazing-trades
// @supportURL   https://github.com/eguilder/blazing-trades/issues

// ==/UserScript==

(function () {

    'use strict';

    if (
        location.pathname !== '/trader/' ||
        location.hash !== '#/portfolio/assets'
    ) {
        return;
    }

    const API_URL = 'http://127.0.0.1:5000/greeks';

    const MONTHS = {
        JAN:'01',
        FEB:'02',
        MAR:'03',
        APR:'04',
        MAY:'05',
        JUN:'06',
        JUL:'07',
        AUG:'08',
        SEP:'09',
        OCT:'10',
        NOV:'11',
        DEC:'12'
    };

    function parseOption(text) {

        const m = text.trim().match(
            /^([A-Z]+)\s+([CP])(\d+(?:\.\d+)?)\s+(\d{2})([A-Z]{3})(\d{2})$/
        );

        if (!m) {
            return null;
        }

        return {
            underlying: m[1],
            right: m[2],
            strike: parseFloat(m[3]),
            expiry: `20${m[6]}${MONTHS[m[5]]}${m[4]}`
        };
    }

    function requestGreeks(payload) {

        return new Promise((resolve, reject) => {

            GM_xmlhttpRequest({

                method: 'POST',

                url: API_URL,

                headers: {
                    'Content-Type': 'application/json'
                },

                data: JSON.stringify(payload),

                onload: response => {

                    try {

                        resolve(
                            JSON.parse(
                                response.responseText
                            )
                        );

                    } catch (e) {

                        reject(e);
                    }
                },

                onerror: reject
            });
        });
    }

    function getRows() {

        return [...document.querySelectorAll('tbody tr')]
            .filter(row =>
                row.querySelector(
                    '[data-name="productName"]'
                )
            );
    }

    function getPositions() {

        const positions = [];

        getRows().forEach((row, idx) => {

            const product =
                row.querySelector(
                    '[data-name="productName"]'
                );

            const qty =
                row.querySelector(
                    '[data-field="size"]'
                );

            if (!product || !qty) {
                return;
            }

            const option =
                parseOption(
                    product.textContent
                );

            if (!option) {
                return;
            }

            positions.push({

                rowId:
                    String(idx),

                qty:
                    parseInt(
                        qty.textContent
                            .replace(
                                /[^\d-]/g,
                                ''
                            ),
                        10
                    ),

                row,

                ...option
            });
        });

        return positions;
    }

    function getOptionsTable() {

        const optionRow =
            getPositions()
                .find(position =>
                    position.row.isConnected
                );

        return optionRow
            ? optionRow.row.closest('table')
            : null;
    }

    function isOverlayElement(node) {

        if (node.nodeType !== Node.ELEMENT_NODE) {
            return false;
        }

        return node.id === 'tm-greeks-summary' ||
            node.classList.contains('tm-delta-header') ||
            node.classList.contains('tm-theta-header') ||
            node.classList.contains('tm-delta') ||
            node.classList.contains('tm-theta');
    }

    function isOverlayMutation(mutation) {

        if (
            mutation.target.nodeType === Node.ELEMENT_NODE &&
            isOverlayElement(mutation.target)
        ) {
            return true;
        }

        const changedNodes = [
            ...mutation.addedNodes,
            ...mutation.removedNodes
        ];

        return changedNodes.length > 0 &&
            changedNodes.every(isOverlayElement);
    }

    function getTotalPlColumnIndex(table) {

        const headerRow =
            table
                ? table.querySelector('thead tr')
                : null;

        if (!headerRow) {
            return -1;
        }

        return [...headerRow.children]
            .findIndex(cell =>
                cell.textContent
                    .replace(/\s+/g, ' ')
                    .trim()
                    .toLowerCase()
                    .includes('total p/l')
            );
    }

    function insertAfter(anchor, node) {

        if (!anchor || !anchor.parentNode) {
            return;
        }

        anchor.parentNode.insertBefore(
            node,
            anchor.nextSibling
        );
    }

    function formatGreek(value) {

        return value != null
            ? Number(value).toFixed(3)
            : '-';
    }

    function removeOverlayColumnsOutside(table) {

        document
            .querySelectorAll(
                '.tm-delta-header, .tm-theta-header, .tm-delta, .tm-theta'
            )
            .forEach(cell => {

                if (cell.closest('table') !== table) {
                    cell.remove();
                }
            });
    }

    function ensureHeader() {

        const table =
            getOptionsTable();

        const headerRow =
            table
                ? table.querySelector('thead tr')
                : null;

        if (!headerRow) {
            return;
        }

        removeOverlayColumnsOutside(
            table
        );

        const totalPlColumnIndex =
            getTotalPlColumnIndex(
                table
            );

        const anchor =
            totalPlColumnIndex >= 0
                ? headerRow.children[totalPlColumnIndex] ||
                    headerRow.lastElementChild
                : headerRow.lastElementChild;

        let delta =
            headerRow.querySelector(
                '.tm-delta-header'
            );

        let theta =
            headerRow.querySelector(
                '.tm-theta-header'
            );

        if (!delta) {

            delta =
                document.createElement('th');

            delta.className =
                'tm-delta-header';

            delta.textContent = 'Δ';
        }

        if (!theta) {

            theta =
                document.createElement('th');

            theta.className =
                'tm-theta-header';

            theta.textContent = 'Θ';
        }

        delta.style.textAlign =
            'right';

        theta.style.textAlign =
            'right';

        insertAfter(anchor, theta);
        insertAfter(anchor, delta);
    }

    function ensureCells(row) {

        console.log("Creating cells");

        let delta =
            row.querySelector('.tm-delta');

        let theta =
            row.querySelector('.tm-theta');

        const totalPlColumnIndex =
            getTotalPlColumnIndex(
                row.closest('table')
            );

        const anchor =
            totalPlColumnIndex >= 0
                ? row.children[totalPlColumnIndex] ||
                    row.lastElementChild
                : row.lastElementChild;

        if (!delta) {

            delta =
                document.createElement('td');

            delta.className =
                'tm-delta';

            delta.style.textAlign =
                'right';

        }

        if (!theta) {

            theta =
                document.createElement('td');

            theta.className =
                'tm-theta';

            theta.style.textAlign =
                'right';

        }

        insertAfter(anchor, theta);
        insertAfter(anchor, delta);

        return {
            delta,
            theta
        };
    }

    function ensurePanel() {

        let bar =
            document.getElementById(
                'tm-greeks-summary'
            );

        if (!bar) {

            bar =
                document.createElement('div');

            bar.id =
                'tm-greeks-summary';

            bar.style.position =
                'fixed';

            bar.style.top =
                'calc(10px + 3cm)';

            bar.style.right =
                '10px';

            bar.style.zIndex =
                '999999';

            bar.style.background =
                '#1e293b';

            bar.style.color =
                '#e2e8f0';

            bar.style.padding =
                '12px 16px';

            bar.style.borderRadius =
                '8px';

            bar.style.fontFamily =
                'Arial, sans-serif';

            bar.style.fontSize =
                '13px';

            bar.style.lineHeight =
                '1.6';

            bar.style.boxShadow =
                '0 4px 12px rgba(0,0,0,0.4)';

            bar.style.minWidth =
                '180px';

            document.body.appendChild(
                bar
            );
        }

        return bar;
    }

    function showLoading() {

        const bar = ensurePanel();

        bar.innerHTML =
            `<div style="margin-bottom:8px; font-weight:bold; color:#94a3b8;`
            + ` text-transform:uppercase; font-size:11px; letter-spacing:0.05em;">`
            + `Greeks Summary`
            + `</div>`
            + `<div style="color:#94a3b8; font-size:12px;">`
            + `&#9696; Loading&hellip;`
            + `</div>`;
    }

    function showSummary(
        totalTheta,
        deltaByTicker,
        thetaByTicker
    ) {

        const bar = ensurePanel();

        const thetaColor =
            totalTheta < 0
                ? '#f87171'
                : '#4ade80';

        const thetaLines =
            Object.entries(thetaByTicker)
                .sort(([left], [right]) =>
                    left.localeCompare(right)
                )
                .map(([ticker, theta]) => {

                    const color =
                        theta >= 0
                            ? '#4ade80'
                            : '#f87171';

                    return `<div style="display:flex; justify-content:space-between; gap:16px;">`
                        + `<span style="color:#94a3b8;">${ticker}</span>`
                        + `<span style="color:${color}; font-weight:bold;">`
                        + `${theta.toFixed(2)}`
                        + `</span>`
                        + `</div>`;
                })
                .join('');

        const deltaLines =
            Object.entries(deltaByTicker)
                .sort(([left], [right]) =>
                    left.localeCompare(right)
                )
                .map(([ticker, syntheticShares]) => {

                    const color =
                        syntheticShares >= 0
                            ? '#4ade80'
                            : '#f87171';

                    return `<div style="display:flex; justify-content:space-between; gap:16px;">`
                        + `<span style="color:#94a3b8;">${ticker}</span>`
                        + `<span style="color:${color}; font-weight:bold;">`
                        + `${syntheticShares.toFixed(1)} shares`
                        + `</span>`
                        + `</div>`;
                })
                .join('');

        const timestamp =
            fetchedAt
                ? fetchedAt.toLocaleTimeString(
                    [],
                    {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit'
                    }
                )
                : '-';

        bar.innerHTML =
            `<div style="margin-bottom:8px; font-weight:bold; color:#94a3b8;`
            + ` text-transform:uppercase; font-size:11px; letter-spacing:0.05em;">`
            + `Greeks Summary`
            + `</div>`
            + `<div style="display:flex; justify-content:space-between; gap:16px; margin-bottom:8px;">`
            + `<span style="color:#94a3b8;">Portfolio Θ</span>`
            + `<span style="color:${thetaColor}; font-weight:bold;">`
            + `${totalTheta.toFixed(2)}</span>`
            + `</div>`
            + `<div style="margin-bottom:4px; color:#94a3b8; font-size:11px;`
            + ` text-transform:uppercase; letter-spacing:0.05em;">Theta by Ticker</div>`
            + thetaLines
            + `<div style="border-top:1px solid #334155; margin-bottom:8px;"></div>`
            + `<div style="margin-bottom:4px; color:#94a3b8; font-size:11px;`
            + ` text-transform:uppercase; letter-spacing:0.05em;">Synthetic Shares</div>`
            + deltaLines
            + `<div style="border-top:1px solid #334155; margin-top:8px; padding-top:6px;`
            + ` color:#475569; font-size:11px; text-align:right;">`
            + `Updated ${timestamp}`
            + `</div>`;
    }

    let refreshTimer;
    let renderFrame;
    let isLoading = false;
    let isRendering = false;
    let cachedGreeks = null;
    let fetchedAt = null;

    function renderGreeks(greeks) {

        isRendering = true;

        ensureHeader();

        const currentPositions =
            getPositions();

        const currentPositionsByRowId =
            new Map(
                currentPositions.map(position => [
                    position.rowId,
                    position
                ])
            );

        let totalTheta = 0;
        const thetaByTicker = {};
        const deltaByTicker = {};
        let rendered = 0;

        greeks.forEach((g, idx) => {

            const position =
                currentPositionsByRowId.get(
                    String(g.rowId)
                ) ||
                currentPositions[idx];

            if (!position || !position.row.isConnected) {
                console.warn(
                    'Skipping detached Greeks row:',
                    g
                );

                return;
            }

            const cells =
                ensureCells(
                    position.row
                );

            cells.delta.textContent =
                formatGreek(
                    g.delta
                );

            cells.theta.textContent =
                formatGreek(
                    g.theta
                );

            if (g.positionTheta != null) {

                const ticker =
                    g.underlying ||
                    position.underlying;

                totalTheta +=
                    g.positionTheta;

                thetaByTicker[ticker] =
                    (thetaByTicker[ticker] || 0)
                    + g.positionTheta;
            }

            if (g.positionDelta != null) {

                const ticker =
                    g.underlying ||
                    position.underlying;

                deltaByTicker[ticker] =
                    (deltaByTicker[ticker] || 0)
                    + g.positionDelta;
            }

            rendered += 1;
        });

        if (rendered > 0) {

            showSummary(
                totalTheta,
                deltaByTicker,
                thetaByTicker
            );
        }

        isRendering = false;

        return rendered > 0;
    }

    function scheduleRenderGreeks(greeks) {

        if (renderFrame) {
            return;
        }

        renderFrame =
            requestAnimationFrame(
                () => {

                    renderFrame = null;

                    try {

                        renderGreeks(
                            greeks
                        );

                    } finally {

                        isRendering = false;
                    }
                }
            );
    }

    async function loadGreeks() {

        const positions = getPositions();

        if (!positions.length) {

            console.log(
                'No option positions found'
            );

            return false;
        }

        console.log(
            'Sending positions:',
            positions
        );

        const payload =
            positions.map(p => ({

                rowId:
                    p.rowId,

                underlying:
                    p.underlying,

                expiry:
                    p.expiry,

                strike:
                    p.strike,

                right:
                    p.right,

                qty:
                    p.qty
            }));

        const greeks =
            await requestGreeks(
                payload
            );

        console.log(
            'Greeks received:',
            greeks
        );

        cachedGreeks = greeks;
        fetchedAt = new Date();

        scheduleRenderGreeks(
            cachedGreeks
        );

        return true;
    }

    function refresh() {

        if (isLoading) {
            return;
        }

        if (cachedGreeks) {
            scheduleRenderGreeks(
                cachedGreeks
            );

            return;
        }

        clearTimeout(
            refreshTimer
        );

        refreshTimer =
            setTimeout(
                async () => {

                    if (isLoading) {
                        return;
                    }

                    if (cachedGreeks) {
                        scheduleRenderGreeks(
                            cachedGreeks
                        );

                        return;
                    }

                    isLoading = true;

                    try {

                        ensureHeader();

                        showLoading();

                        await loadGreeks();

                    } catch (e) {

                        console.error(
                            'Greeks error:',
                            e
                        );
                    } finally {

                        isLoading = false;
                    }

                },
                1500
            );
    }

    const observer =
        new MutationObserver(
            mutations => {

                if (isRendering) {
                    return;
                }

                if (
                    mutations.every(
                        isOverlayMutation
                    )
                ) {
                    return;
                }

                refresh();
            }
        );

    observer.observe(
        document.body,
        {
            childList: true,
            subtree: true
        }
    );

    console.log(
        'DeGiro Greeks script loaded'
    );

    refresh();

})();
