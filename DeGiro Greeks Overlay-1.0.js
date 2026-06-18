// ==UserScript==
// @name         DeGiro Greeks Overlay
// @namespace    degiro-greeks
// @version      1.0
// @description  Show option Greeks from local IBKR service
// @match        https://trader.degiro.nl/*
// @grant        GM_xmlhttpRequest
// @connect      172.23.224.1
// ==/UserScript==

(function () {

    'use strict';

    const API_URL = 'http://172.23.224.1:5000/greeks';

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

    function ensureHeader() {

        const headerRow =
            document.querySelector('thead tr');

        if (!headerRow) {
            return;
        }

        if (
            headerRow.querySelector(
                '.tm-delta-header'
            )
        ) {
            return;
        }

        const delta =
            document.createElement('th');

        delta.className =
            'tm-delta-header';

        delta.textContent = 'Δ';

        delta.style.textAlign =
            'right';

        headerRow.appendChild(delta);

        const theta =
            document.createElement('th');

        theta.className =
            'tm-theta-header';

        theta.textContent = 'Θ';

        theta.style.textAlign =
            'right';

        headerRow.appendChild(theta);
    }

    function ensureCells(row) {

        console.log("Creating cells");

        let delta =
            row.querySelector('.tm-delta');

        let theta =
            row.querySelector('.tm-theta');

        if (!delta) {

            delta =
                document.createElement('td');

            delta.className =
                'tm-delta';

            delta.style.textAlign =
                'right';

            row.appendChild(delta);
        }

        if (!theta) {

            theta =
                document.createElement('td');

            theta.className =
                'tm-theta';

            theta.style.textAlign =
                'right';

            row.appendChild(theta);
        }

        return {
            delta,
            theta
        };
    }

    function showSummary(
        totalDelta,
        totalTheta
    ) {

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
                '10px';

            bar.style.right =
                '10px';

            bar.style.zIndex =
                '999999';

            bar.style.background =
                '#222';

            bar.style.color =
                '#fff';

            bar.style.padding =
                '8px 12px';

            bar.style.borderRadius =
                '6px';

            bar.style.fontWeight =
                'bold';

            document.body.appendChild(
                bar
            );
        }

        bar.textContent =
            `Δ ${totalDelta.toFixed(1)} | Θ ${totalTheta.toFixed(1)}`;
    }

    let refreshTimer;
    let isLoading = false;
    let cachedGreeks = null;

    function renderGreeks(greeks) {

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

        let totalDelta = 0;
        let totalTheta = 0;
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
                g.positionDelta != null
                    ? g.positionDelta
                        .toFixed(1)
                    : '-';

            cells.theta.textContent =
                g.positionTheta != null
                    ? g.positionTheta
                        .toFixed(1)
                    : '-';

            totalDelta +=
                g.positionDelta || 0;

            totalTheta +=
                g.positionTheta || 0;

            rendered += 1;
        });

        if (rendered > 0) {

            showSummary(
                totalDelta,
                totalTheta
            );
        }

        return rendered > 0;
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

        renderGreeks(
            cachedGreeks
        );

        return true;
    }

    function refresh() {

        if (isLoading) {
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
                        renderGreeks(
                            cachedGreeks
                        );

                        return;
                    }

                    isLoading = true;

                    try {

                        ensureHeader();

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
