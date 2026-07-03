const o={$:"USD","€":"EUR","£":"GBP","¥":"JPY"};function i(t,e="USD"){const r=String(t||"").trim();if(!r)return e;const n=r.toUpperCase();return/^[A-Z]{3}$/.test(n)?n:o[r]??e}export{i as n};
