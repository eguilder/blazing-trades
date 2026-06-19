// ==UserScript==
// @name         DeGiro Options Month Buttons
// @namespace    degiro
// @version      1.0
// @match        https://trader.degiro.nl/trader/*
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

    const MONTHS = [
        'JAN','FEB','MAR','APR','MAY','JUN',
        'JUL','AUG','SEP','OCT','NOV','DEC'
    ];

    let currentFilter = 'ALL';
    let currentTickerFilter = 'ALL';

        function extractMonth(text) {
        const m = text.match(/\d{1,2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}/i);
        return m ? m[1].toUpperCase() : null;
    }

    function extractTicker(text) {
        const m = text.trim().match(/^([A-Z]+)\s+[CP]/);
        return m ? m[1] : null;
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

            row.style.display =
                monthMatch && tickerMatch ? '' : 'none';
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
    }

    function applyFilter(month) {
        currentFilter = month;
        applyFilters();
    }

    function applyTickerFilter(ticker) {
        currentTickerFilter = ticker;
        applyFilters();
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
        const desiredKey =
            desiredMonths.join(',') + '|' + desiredTickers.join(',');

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

            btn.textContent = ticker;

            btn.style.padding = '4px 10px';
            btn.style.border = '1px solid #777';
            btn.style.borderRadius = '4px';
            btn.style.cursor = 'pointer';

            btn.onclick = () => applyTickerFilter(ticker);

            toolbar.appendChild(btn);
        });

        if (!desiredMonths.includes(currentFilter)) {
            currentFilter = 'ALL';
        }

        if (!desiredTickers.includes(currentTickerFilter)) {
            currentTickerFilter = 'ALL';
        }

        applyFilters();
    }

    const observer = new MutationObserver(() => {
        buildButtons();
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    setInterval(buildButtons, 2000);

})();
