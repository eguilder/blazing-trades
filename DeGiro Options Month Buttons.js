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

    function extractMonth(text) {
        const m = text.match(/\d{1,2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}/i);
        return m ? m[1].toUpperCase() : null;
    }

    function getOptionRows() {
        return [...document.querySelectorAll('tbody tr')]
            .filter(row => {
                const product = row.querySelector('[data-name="productName"]');
                return product && extractMonth(product.textContent);
            });
    }

    function applyFilter(month) {
        currentFilter = month;

        getOptionRows().forEach(row => {
            const product = row.querySelector('[data-name="productName"]');
            const rowMonth = extractMonth(product.textContent);

            row.style.display =
                month === 'ALL' || rowMonth === month
                    ? ''
                    : 'none';
        });

        document.querySelectorAll('.tm-month-btn').forEach(btn => {
            if (btn.dataset.month === month) {
                btn.style.background = '#4caf50';
                btn.style.color = '#fff';
                btn.style.fontWeight = 'bold';
            } else {
                btn.style.background = '';
                btn.style.color = '';
                btn.style.fontWeight = '';
            }
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

        const table = rows[0].closest('table');
        if (!table) {
            return;
        }

        let toolbar = document.getElementById('tm-options-filter');

        if (!toolbar) {
            toolbar = document.createElement('div');
            toolbar.id = 'tm-options-filter';

            toolbar.style.display = 'flex';
            toolbar.style.flexWrap = 'wrap';
            toolbar.style.gap = '6px';
            toolbar.style.margin = '10px 0';

            table.parentElement.insertBefore(toolbar, table);
        }

        const desired = ['ALL', ...months];

        if (toolbar.dataset.months === desired.join(',')) {
            applyFilter(currentFilter);
            return;
        }

        toolbar.dataset.months = desired.join(',');
        toolbar.innerHTML = '';

        desired.forEach(month => {

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

        if (!desired.includes(currentFilter)) {
            currentFilter = 'ALL';
        }

        applyFilter(currentFilter);
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
