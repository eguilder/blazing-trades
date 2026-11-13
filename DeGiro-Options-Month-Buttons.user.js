// ==UserScript==
// @name         DeGiro Options Month Buttons
// @namespace    https://github.com/eguilder/blazing-trades
// @version      1.1.7
// @description  Quick month selection buttons and option spread visuals for the DeGiro options chain
// @match        https://trader.degiro.nl/*
// @updateURL    https://raw.githubusercontent.com/eguilder/blazing-trades/main/DeGiro-Options-Month-Buttons.user.js
// @downloadURL  https://raw.githubusercontent.com/eguilder/blazing-trades/main/DeGiro-Options-Month-Buttons.user.js
// @homepageURL  https://github.com/eguilder/blazing-trades
// @supportURL   https://github.com/eguilder/blazing-trades/issues
// @grant        none
// ==/UserScript==

(function () {
    'use strict';

    if (
        location.pathname !== '/trader/' ||
        location.hash !== '#/portfolio/assets'
    ) {
        return;
    }

    // DeGiro is a SPA and can evaluate userscripts more than once while
    // navigating. Keep a single observer and interval alive.
    const INSTANCE_KEY = '__tmDeGiroOptionsMonthButtons';
    if (window[INSTANCE_KEY]) {
        return;
    }
    window[INSTANCE_KEY] = true;

    const MONTHS = [
        'JAN','FEB','MRT','APR','MEI','JUN',
        'JUL','AUG','SEP','OKT','NOV','DEC'
    ];

    let currentFilter = 'ALL';
    let currentTickerFilter = 'ALL';
    let currentPositionFilter = 'ALL';
    let marketData = window.__tmOptionMarketData || {};

        function extractMonth(text) {
        const m = text.match(/\d{1,2}(JAN|FEB|MRT|APR|MEI|JUN|JUL|AUG|SEP|OKT|NOV|DEC)\d{2}/i);
        return m ? m[1].toUpperCase() : null;
    }

    function extractTicker(text) {
        const m = text.trim().match(/^([A-Z]+)\s+[CP]/);
        return m ? m[1] : null;
    }

    function extractOption(text) {
        const m = text.trim().match(/^([A-Z]+)\s+([CP])(\d+(?:\.\d+)?)/);
        return m ? { ticker: m[1], right: m[2], strike: Number(m[3]) } : null;
    }

    function getPositionSize(row) {
        const sizeCell = row.querySelector('[data-field="size"]');
        if (!sizeCell) return null;
        const value = Number(sizeCell.textContent.replace(/[^\d,.-]/g, '').replace(',', '.'));
        return Number.isFinite(value) ? value : null;
    }


        function getOptionsSection() {
        return document.querySelector('[data-product-type-id="8"]');
    }

    function getOptionRows() {
        const section = getOptionsSection();
        if (!section) return [];
        return [...section.querySelectorAll('tbody tr')]
            .filter(row => {
                const product = row.querySelector('[data-name="productName"]');
                return product && extractMonth(product.textContent);
            });
    }

        function applyFilters() {

        getOptionRows().forEach(row => {
            const product = row.querySelector('[data-name="productName"]');
            const rowMonth = extractMonth(product.textContent);
            const rowTicker = extractTicker(product.textContent);

            const monthMatch =
                currentFilter === 'ALL' || rowMonth === currentFilter;

            const tickerMatch =
                currentTickerFilter === 'ALL' || rowTicker === currentTickerFilter;

            const size = getPositionSize(row);
            const positionMatch =
                currentPositionFilter === 'ALL' ||
                (currentPositionFilter === 'LONG' && size > 0) ||
                (currentPositionFilter === 'SHORT' && size < 0);

            row.style.display =
                monthMatch && tickerMatch && positionMatch ? '' : 'none';
        });

        document.querySelectorAll('.tm-month-btn').forEach(btn => {
            const active = btn.dataset.month === currentFilter;
            btn.style.background = active ? '#4caf50' : '';
            btn.style.color = active ? '#fff' : '';
            btn.style.fontWeight = active ? 'bold' : '';
        });

        document.querySelectorAll('.tm-ticker-btn').forEach(btn => {
            const active = btn.dataset.ticker === currentTickerFilter;
            btn.style.background = active ? '#3b82f6' : '';
            btn.style.color = active ? '#fff' : '';
            btn.style.fontWeight = active ? 'bold' : '';
        });

        document.querySelectorAll('.tm-position-btn').forEach(btn => {
            const active = btn.dataset.position === currentPositionFilter;
            btn.style.background = active ? '#a855f7' : '';
            btn.style.color = active ? '#fff' : '';
            btn.style.fontWeight = active ? 'bold' : '';
        });

        updateTickerSpreads();
    }

    function applyFilter(month) {
        currentFilter = month;
        applyFilters();
    }

    function applyTickerFilter(ticker) {
        currentTickerFilter = ticker;
        applyFilters();
    }

    function applyPositionFilter(position) {
        currentPositionFilter = position;
        applyFilters();
    }

    function updateTickerSpreads() {
        document.querySelectorAll('.tm-ticker-spread').forEach(bar => {
            const ticker = bar.dataset.ticker;
            const rows = getOptionRows().filter(row => {
                const product = row.querySelector('[data-name="productName"]');
                const option = product && extractOption(product.textContent);
                return option && option.ticker === ticker
                    && (currentFilter === 'ALL' || extractMonth(product.textContent) === currentFilter);
            });
            const strikes = [...new Set(
                rows.map(row => Number(extractOption(
                    row.querySelector('[data-name="productName"]').textContent
                ).strike)).filter(Number.isFinite)
            )].sort((a, b) => a - b);

            const legsByStrike = new Map();
            rows.forEach(row => {
                const option = extractOption(
                    row.querySelector('[data-name="productName"]').textContent
                );
                const size = getPositionSize(row);
                if (!option || !Number.isFinite(size) || size === 0) return;
                legsByStrike.set(
                    option.strike,
                    (legsByStrike.get(option.strike) || 0) + size
                );
            });

            const longStrikes = [...legsByStrike]
                .filter(([, size]) => size > 0)
                .map(([strike]) => strike)
                .sort((a, b) => a - b);
            const shortStrikes = [...legsByStrike]
                .filter(([, size]) => size < 0)
                .map(([strike]) => strike)
                .sort((a, b) => a - b);

            if (!strikes.length) {
                if (bar.style.display !== 'none') {
                    bar.style.display = 'none';
                }
                return;
            }

            const low = strikes[0];
            const high = strikes[strikes.length - 1];
            const spot = marketData[ticker] && Number(marketData[ticker].spot);
            const spotPosition = Number.isFinite(spot)
                ? high > low
                    ? Math.max(0, Math.min(100, ((spot - low) / (high - low)) * 100))
                    : 50
                : null;

            const renderKey = [
                currentFilter,
                low,
                high,
                Number.isFinite(spot) ? spot.toFixed(4) : '-',
                [...legsByStrike].map(([strike, size]) => `${strike}:${size}`).join(',')
            ].join('|');

            if (bar.dataset.renderKey === renderKey) {
                return;
            }

            bar.dataset.renderKey = renderKey;

            const relationStrikes = shortStrikes.length ? shortStrikes : strikes;
            let spotRelation = '';
            if (Number.isFinite(spot)) {
                if (spot < relationStrikes[0]) spotRelation = 'below';
                else if (spot > relationStrikes[relationStrikes.length - 1]) spotRelation = 'above';
                else spotRelation = shortStrikes.length > 1 ? 'inside short spread' : 'at/inside spread';
            }

            const formatStrikes = values => values.length ? values.join(', ') : '-';
            const legMarkers = [...legsByStrike].map(([strike, size]) => {
                const position = high > low
                    ? Math.max(0, Math.min(100, ((strike - low) / (high - low)) * 100))
                    : 50;
                const color = size < 0 ? '#f87171' : '#4ade80';
                return `<span style="position:absolute; left:${position}%; top:-3px; width:3px; height:14px; background:${color}; box-shadow:0 0 0 1px #0f172a; transform:translateX(-1px);"></span>`;
            }).join('');

            bar.style.display = 'block';
            bar.title = `${ticker} | long: ${formatStrikes(longStrikes)} | short: ${formatStrikes(shortStrikes)}`
                + `${spotPosition == null ? '' : ` | spot ${spot.toFixed(2)} (${spotRelation})`}`;
            bar.innerHTML = `<div style="position:relative; height:8px; margin-top:10px; border-radius:5px; overflow:visible; background:linear-gradient(90deg,#f87171 0 20%,#fbbf24 20% 80%,#60a5fa 80% 100%);">`
                + legMarkers
                + (spotPosition == null ? '' : `<span style="position:absolute; left:${spotPosition}%; top:-7px; width:2px; height:22px; background:#fff; box-shadow:0 0 0 1px #0f172a; transform:translateX(-1px);"><span style="position:absolute; left:50%; bottom:20px; transform:translateX(-50%); padding:1px 3px; border-radius:3px; background:#0f172a; color:#fff; font-size:9px; line-height:12px; white-space:nowrap;">${spot.toFixed(2)}</span></span>`)
                + `</div><div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8; line-height:12px;"><span>${low}</span><span>${high}</span></div>`;
        });
    }

    function buildButtons() {

        const rows = getOptionRows();
        if (!rows.length) {
            return;
        }

        const months = [...new Set(
            rows.map(r =>
                extractMonth(
                    r.querySelector('[data-name="productName"]').textContent
                )
            )
        )]
        .filter(Boolean)
        .sort((a,b)=>MONTHS.indexOf(a)-MONTHS.indexOf(b));

                const section = getOptionsSection();
        const table = section ? section.querySelector('table') : null;
        if (!table) {
            return;
        }

        let toolbar = section.querySelector('#tm-options-filter');

        if (!toolbar) {
            toolbar = document.createElement('div');
            toolbar.id = 'tm-options-filter';

            toolbar.style.display = 'flex';
            toolbar.style.flexWrap = 'wrap';
            toolbar.style.gap = '6px';
            toolbar.style.margin = '10px 0';

            table.parentElement.insertBefore(toolbar, table);
        }

                const tickers = [...new Set(
            rows.map(r =>
                extractTicker(
                    r.querySelector('[data-name="productName"]').textContent
                )
            )
        )]
        .filter(Boolean)
        .sort();

        const desiredMonths = ['ALL', ...months];
        const desiredTickers = ['ALL', ...tickers];
        const desiredPositions = ['ALL', 'LONG', 'SHORT'];
        const desiredKey =
            desiredMonths.join(',') + '|' + desiredTickers.join(',') + '|'
            + desiredPositions.join(',');

        if (toolbar.dataset.filterKey === desiredKey) {
            applyFilters();
            return;
        }

        toolbar.dataset.filterKey = desiredKey;
        toolbar.innerHTML = '';

        // -----------------------------------------------------------------
        // Month buttons
        // -----------------------------------------------------------------

        desiredMonths.forEach(month => {

            const btn = document.createElement('button');

            btn.className = 'tm-month-btn';
            btn.dataset.month = month;

            btn.textContent = month;

            btn.style.padding = '4px 10px';
            btn.style.border = '1px solid #777';
            btn.style.borderRadius = '4px';
            btn.style.cursor = 'pointer';

            btn.onclick = () => applyFilter(month);

            toolbar.appendChild(btn);
        });

        // -----------------------------------------------------------------
        // Divider
        // -----------------------------------------------------------------

        const divider = document.createElement('span');
        divider.style.borderLeft = '1px solid #555';
        divider.style.margin = '0 6px';
        toolbar.appendChild(divider);

        // -----------------------------------------------------------------
        // Ticker buttons
        // -----------------------------------------------------------------

        desiredTickers.forEach(ticker => {

            const btn = document.createElement('button');

            btn.className = 'tm-ticker-btn';
            btn.dataset.ticker = ticker;

            btn.style.padding = '4px 10px';
            btn.style.border = '1px solid #777';
            btn.style.borderRadius = '4px';
            btn.style.cursor = 'pointer';

            btn.textContent = ticker;
            btn.onclick = () => applyTickerFilter(ticker);

            if (ticker === 'ALL') {
                toolbar.appendChild(btn);
            } else {
                const group = document.createElement('div');
                group.className = 'tm-ticker-group';
                group.style.display = 'inline-flex';
                group.style.flexDirection = 'column';
                group.style.gap = '2px';
                group.style.minWidth = '180px';
                group.appendChild(btn);

                const spread = document.createElement('div');
                spread.className = 'tm-ticker-spread';
                spread.dataset.ticker = ticker;
                spread.style.width = '180px';
                spread.style.margin = '0 auto';
                group.appendChild(spread);
                toolbar.appendChild(group);
            }
        });

        const positionDivider = document.createElement('span');
        positionDivider.style.borderLeft = '1px solid #555';
        positionDivider.style.margin = '0 6px';
        toolbar.appendChild(positionDivider);

        desiredPositions.forEach(position => {
            const btn = document.createElement('button');
            btn.className = 'tm-position-btn';
            btn.dataset.position = position;
            btn.textContent = position === 'ALL' ? 'ALL POSITIONS' : position;
            btn.style.padding = '4px 10px';
            btn.style.border = '1px solid #777';
            btn.style.borderRadius = '4px';
            btn.style.cursor = 'pointer';
            btn.onclick = () => applyPositionFilter(position);
            toolbar.appendChild(btn);
        });

        if (!desiredMonths.includes(currentFilter)) {
            currentFilter = 'ALL';
        }

        if (!desiredTickers.includes(currentTickerFilter)) {
            currentTickerFilter = 'ALL';
        }

        if (!desiredPositions.includes(currentPositionFilter)) {
            currentPositionFilter = 'ALL';
        }

        applyFilters();
    }

    window.addEventListener('tm-option-market-data', event => {
        marketData = event.detail || {};
        updateTickerSpreads();
    });

    const observer = new MutationObserver(() => {
        buildButtons();
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    setInterval(buildButtons, 2000);

})();
