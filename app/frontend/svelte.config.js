import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  kit: {
    adapter: adapter({
      fallback: 'index.html',
      pages: '../backend/ledger_flow_frontend/static',
      assets: '../backend/ledger_flow_frontend/static'
    })
  }
};

export default config;
